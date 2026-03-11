"""
Sentinel Compliance Monitoring Platform — FastAPI backend.
All API routes for scans, violations, audit trail, compliance score, and PDF export.
"""

import asyncio
import functools
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# Playwright's sync API uses asyncio.new_event_loop() internally. On Windows
# the default policy produces a SelectorEventLoop which cannot spawn subprocesses.
# Setting ProactorEventLoop policy here (process-wide) fixes it for all threads.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

import database
import orchestrator
import remediation_engine
import scheduler
import violation_engine
import nova_client
import briefing_generator
import nova_sonic_tts
import voice_assistant as va_module
from event_bus import event_bus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Sentinel Compliance Platform",
    description="Autonomous SOC2/HIPAA/GDPR compliance monitoring via Amazon Nova Act",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# CORS — allow React dev server + deployed frontend
# ---------------------------------------------------------------------------

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Static files — serve screenshots
# ---------------------------------------------------------------------------

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)
app.mount("/api/screenshots", StaticFiles(directory=str(SCREENSHOTS_DIR)), name="screenshots")

# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------


SESSION_START = datetime.now().isoformat()


@app.on_event("startup")
async def startup() -> None:
    database.init_db()
    database.clear_score_history()
    scheduler.start_scheduler()
    event_bus.set_loop(asyncio.get_running_loop())
    logger.info("Sentinel backend started")


@app.on_event("shutdown")
async def shutdown() -> None:
    scheduler.stop_scheduler()
    logger.info("Sentinel backend stopped")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ScanTriggerResponse(BaseModel):
    scan_id: str
    message: str


class ApproveRemediationRequest(BaseModel):
    approved_by: str


class DismissViolationRequest(BaseModel):
    dismissed_by: str
    reason: str


# ---------------------------------------------------------------------------
# Scan endpoints
# ---------------------------------------------------------------------------


@app.post("/api/scan/trigger", response_model=ScanTriggerResponse)
async def trigger_scan(background_tasks: BackgroundTasks) -> ScanTriggerResponse:
    """Trigger a compliance scan. Returns scan_id immediately; scan runs in background."""
    scan_id = str(uuid.uuid4())
    started_at = datetime.now().isoformat()

    database.create_scan(scan_id, "running", "Scan started", started_at)
    database.insert_audit_entry(
        {
            "entry_id": str(uuid.uuid4()),
            "event_type": "scan_started",
            "violation_id": None,
            "scan_id": scan_id,
            "actor": "user",
            "action": "Manual compliance scan triggered via API",
            "result": "started",
            "screenshot_path": None,
            "timestamp": started_at,
            "details": None,
        }
    )

    background_tasks.add_task(_run_scan_background, scan_id)

    return ScanTriggerResponse(
        scan_id=scan_id,
        message="Scan started. Poll /api/scan/{scan_id}/status for progress.",
    )


async def _run_scan_background(scan_id: str) -> None:
    """Background task wrapper for the synchronous orchestrator."""
    try:
        import agent_pool
        import violation_engine as ve

        def event_callback(tool: str, message: str, status: str, screenshot: str | None = None) -> None:
            event_bus.emit(scan_id, tool, message, status, screenshot=screenshot)

        # Snapshot: score at scan start (always 100 — no violations yet for this scan)
        database.insert_score_snapshot(100, "Scan started")

        loop = asyncio.get_event_loop()
        scan_results = await loop.run_in_executor(
            None,
            functools.partial(agent_pool.scan_all_tools, event_callback=event_callback),
        )
        violations = ve.analyze_violations(scan_results, scan_id)

        completed_at = datetime.now().isoformat()
        # Snapshot: score after violations detected
        post_scan_score = ve.calculate_compliance_score(scan_id=scan_id)["score"]
        database.insert_score_snapshot(post_scan_score, f"Scan complete — {len(violations)} violation(s)", completed_at)
        database.update_scan(
            scan_id,
            status="completed",
            message=f"Scan completed. {len(violations)} violation(s) detected.",
            violations_found=len(violations),
            completed_at=completed_at,
        )
        database.insert_audit_entry(
            {
                "entry_id": str(uuid.uuid4()),
                "event_type": "scan_completed",
                "violation_id": None,
                "scan_id": scan_id,
                "actor": "system",
                "action": f"Scan completed — {len(violations)} violation(s) found",
                "result": "success",
                "screenshot_path": None,
                "timestamp": completed_at,
                "details": f"Tools scanned: {len(scan_results)}",
            }
        )
        event_bus.emit(scan_id, "system", "scan_complete", "success")
        event_bus.close(scan_id)
    except Exception as exc:
        logger.error("Background scan %s failed: %s", scan_id, exc, exc_info=True)
        database.update_scan(
            scan_id,
            status="failed",
            message=f"Scan failed: {exc}",
            completed_at=datetime.now().isoformat(),
        )
        event_bus.emit(scan_id, "system", "scan_complete", "error")
        event_bus.close(scan_id)


@app.get("/api/scan/{scan_id}/status")
async def get_scan_status(scan_id: str) -> dict[str, Any]:
    """Return current status of a scan."""
    scan = database.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan


@app.get("/api/scan/{scan_id}/events")
async def scan_events(scan_id: str) -> EventSourceResponse:
    """Stream real-time scan progress events via SSE."""
    import json

    async def generator():
        async for event in event_bus.subscribe(scan_id):
            yield {"data": json.dumps(event)}

    return EventSourceResponse(generator())


# ---------------------------------------------------------------------------
# Violations endpoints
# ---------------------------------------------------------------------------


@app.get("/api/violations")
async def list_violations(
    severity: str | None = Query(default=None),
    tool: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    """List violations with optional filters."""
    filters: dict[str, str] = {}
    if severity:
        filters["severity"] = severity
    if tool:
        filters["tool"] = tool
    if status:
        filters["status"] = status
    return database.get_violations(filters if filters else None)


@app.get("/api/violations/{violation_id}")
async def get_violation(violation_id: str) -> dict[str, Any]:
    """Get a single violation by ID."""
    violation = database.get_violation(violation_id)
    if not violation:
        raise HTTPException(status_code=404, detail="Violation not found")
    return violation


@app.post("/api/violations/{violation_id}/approve")
async def approve_remediation(
    violation_id: str,
    body: ApproveRemediationRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Approve remediation for a violation. Executes via Nova Act in background."""
    violation = database.get_violation(violation_id)
    if not violation:
        raise HTTPException(status_code=404, detail="Violation not found")
    if violation["status"] != "open":
        raise HTTPException(
            status_code=400,
            detail=f"Violation is already {violation['status']}",
        )

    background_tasks.add_task(
        _execute_remediation_background, violation, body.approved_by
    )

    return {
        "message": "Remediation approved and queued for execution.",
        "violation_id": violation_id,
    }


@app.get("/api/violations/{violation_id}/remediation-events")
async def remediation_events(violation_id: str) -> EventSourceResponse:
    """Stream real-time remediation progress events via SSE."""
    import json

    async def generator():
        async for event in event_bus.subscribe(violation_id):
            yield {"data": json.dumps(event)}

    return EventSourceResponse(generator())


async def _execute_remediation_background(
    violation: dict[str, Any], approved_by: str
) -> None:
    """Background wrapper for synchronous remediation engine.

    execute_remediation uses Playwright's sync API which cannot run inside a
    live asyncio event loop. Offload it to a thread via run_in_executor so
    Playwright sees no running loop.
    """
    violation_id = violation["violation_id"]

    def event_callback(step_index: int, message: str, status: str, screenshot: str | None = None) -> None:
        event_bus.emit(violation_id, "remediation", message, status, step_index=step_index, screenshot=screenshot)

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            functools.partial(
                remediation_engine.execute_remediation, violation, approved_by, event_callback
            ),
        )
        outcome = "remediation_complete" if result.get("success") else "remediation_failed"
        if result.get("success"):
            # Snapshot: score after this remediation
            scan_id_for_score = violation.get("scan_id")
            remediated_score = violation_engine.calculate_compliance_score(scan_id=scan_id_for_score)["score"]
            database.insert_score_snapshot(
                remediated_score,
                f"Remediated: {violation.get('username', '')} ({violation.get('violation_type', '')})",
            )
        event_bus.emit(violation_id, "system", outcome, "success" if result.get("success") else "error")
        event_bus.close(violation_id)
    except Exception as exc:
        logger.error(
            "Remediation background task failed for %s: %s",
            violation_id,
            exc,
            exc_info=True,
        )
        event_bus.emit(violation_id, "system", "remediation_failed", "error")
        event_bus.close(violation_id)


@app.post("/api/violations/{violation_id}/dismiss")
async def dismiss_violation(
    violation_id: str,
    body: DismissViolationRequest,
) -> dict[str, Any]:
    """Dismiss a violation with a reason."""
    violation = database.get_violation(violation_id)
    if not violation:
        raise HTTPException(status_code=404, detail="Violation not found")
    if violation["status"] != "open":
        raise HTTPException(
            status_code=400,
            detail=f"Violation is already {violation['status']}",
        )

    dismissed_at = datetime.now().isoformat()
    database.update_violation_status(
        violation_id,
        status="dismissed",
        resolved_by=body.dismissed_by,
        resolved_at=dismissed_at,
        dismiss_reason=body.reason,
    )
    database.insert_audit_entry(
        {
            "entry_id": str(uuid.uuid4()),
            "event_type": "violation_dismissed",
            "violation_id": violation_id,
            "scan_id": violation.get("scan_id"),
            "actor": body.dismissed_by,
            "action": f"Violation dismissed: {violation['username']} — {violation['violation_type']}",
            "result": "dismissed",
            "screenshot_path": None,
            "timestamp": dismissed_at,
            "details": body.reason,
        }
    )
    return {"message": "Violation dismissed.", "violation_id": violation_id}


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


@app.get("/api/audit-trail")
async def get_audit_trail() -> list[dict[str, Any]]:
    """Return audit history for the current server session only."""
    return database.get_audit_trail(since=SESSION_START)


# ---------------------------------------------------------------------------
# Compliance score
# ---------------------------------------------------------------------------


@app.get("/api/compliance-score")
async def get_compliance_score() -> dict[str, Any]:
    """Return current compliance score and breakdown."""
    return violation_engine.calculate_compliance_score()


@app.get("/api/compliance-score/history")
async def get_score_history() -> list[dict[str, Any]]:
    """Return score snapshots for trend chart."""
    return database.get_score_history()


# ---------------------------------------------------------------------------
# PDF / text report export
# ---------------------------------------------------------------------------


SOC2_CONTROLS: dict[str, Any] = {
    "CC6.1": {
        "name": "Logical and Physical Access Controls",
        "description": (
            "The entity implements logical access security measures to protect against "
            "unauthorized access."
        ),
        "violation_types": ["INACTIVE_ADMIN"],
    },
    "CC6.2": {
        "name": "User Access Provisioning and Deprovisioning",
        "description": (
            "The entity manages access credentials for personnel and removes access "
            "upon termination."
        ),
        "violation_types": ["ACCESS_VIOLATION"],
    },
    "CC6.3": {
        "name": "Access Role Management",
        "description": (
            "The entity authorizes and manages role-based access and restricts "
            "privileged access."
        ),
        "violation_types": ["SHARED_ACCOUNT", "PERMISSION_CREEP"],
    },
}

VIOLATION_TEMPLATES: dict[str, str] = {
    "ACCESS_VIOLATION": (
        "Terminated employee '{username}' retained {role} privileges in {tool} "
        "post-termination. This constitutes a violation of SOC2 CC6.2."
    ),
    "INACTIVE_ADMIN": (
        "Account '{username}' ({role}) has not authenticated in {days}+ days while "
        "retaining administrative privileges in {tool}. This constitutes a violation "
        "of SOC2 CC6.1."
    ),
    "SHARED_ACCOUNT": (
        "Shared account '{username}' was identified with {role} access in {tool}. "
        "Shared privileged accounts violate SOC2 CC6.3."
    ),
    "PERMISSION_CREEP": (
        "User '{username}' ({department}, {role_title}) holds elevated {role} privileges "
        "in {tool} inconsistent with their designated role. This constitutes a violation "
        "of SOC2 CC6.3."
    ),
}


def _format_detection_method(v: dict[str, Any]) -> str:
    """Return a short 'how Sentinel found this' narrative for a violation."""
    vtype = v.get("violation_type", "")
    tool  = v.get("tool_name") or v.get("tool", "the tool")
    uname = v.get("username", "the account")
    role  = v.get("role", "administrative")
    dept  = v.get("department", "unknown department")
    evidence = v.get("evidence", "")
    days_match = re.search(r"(\d+)\s*days?", evidence, re.IGNORECASE)
    days = days_match.group(1) if days_match else "90"

    if vtype == "ACCESS_VIOLATION":
        return (
            f"Sentinel's Nova Act agent logged into {tool} and extracted the full active "
            f"user list via browser automation. The account '{uname}' was cross-referenced "
            f"against the HR system of record and flagged because the employee is marked "
            f"TERMINATED in HR records but retains active {role} access in the tool."
        )
    if vtype == "INACTIVE_ADMIN":
        return (
            f"Sentinel's Nova Act agent logged into {tool} and scraped last-login timestamps "
            f"for all privileged accounts. '{uname}' was flagged for holding {role} privileges "
            f"with no recorded authentication activity in over {days} days, exceeding the "
            f"90-day inactivity threshold defined in SOC2 CC6.1 policy."
        )
    if vtype == "SHARED_ACCOUNT":
        return (
            f"Sentinel's Nova Act agent logged into {tool} and scanned all user accounts. "
            f"'{uname}' was identified as a shared account by username pattern analysis and "
            f"flagged for holding {role} access. Shared privileged accounts cannot be "
            f"individually attributed and violate SOC2 CC6.3 non-repudiation requirements."
        )
    if vtype == "PERMISSION_CREEP":
        return (
            f"Sentinel's Nova Act agent logged into {tool} and extracted user roles. "
            f"'{uname}' ({dept}) was cross-referenced against the role policy ruleset. "
            f"Their designated job classification is on the restricted list for {role} "
            f"access, indicating privilege accumulation beyond their authorised scope "
            f"in violation of SOC2 CC6.3."
        )
    return (
        f"Sentinel's Nova Act agent detected this violation during an automated scan of {tool}."
    )


def _format_violation_description(v: dict[str, Any]) -> str:
    vtype = v.get("violation_type", "")
    tmpl = VIOLATION_TEMPLATES.get(vtype, "{evidence}")
    evidence = v.get("evidence", "")
    days_match = re.search(r"(\d+)\s*days?", evidence, re.IGNORECASE)
    days = days_match.group(1) if days_match else "90"
    try:
        return tmpl.format(
            username=v.get("username", "unknown"),
            role=v.get("role", "unknown"),
            tool=v.get("tool_name") or v.get("tool", "unknown"),
            days=days,
            department=v.get("department", "unknown"),
            role_title=v.get("role", "unknown"),
            evidence=evidence,
        )
    except KeyError:
        return evidence


def _sanitize(text: str) -> str:
    """Replace Unicode characters outside latin-1 with ASCII equivalents."""
    return (
        text
        .replace("\u2014", "--")   # em dash
        .replace("\u2013", "-")    # en dash
        .replace("\u2018", "'")    # left single quote
        .replace("\u2019", "'")    # right single quote
        .replace("\u201c", '"')    # left double quote
        .replace("\u201d", '"')    # right double quote
        .replace("\u2022", "-")    # bullet
        .replace("\u00b7", ".")    # middle dot
        .replace("\u2026", "...")  # ellipsis
        .encode("latin-1", errors="replace").decode("latin-1")
    )


def _build_soc2_pdf(
    audit_data: dict[str, Any],
    executive_summary: str,
    recommendations: list[str],
) -> bytes:
    """Build a structured SOC2 compliance PDF directly from audit data."""
    from fpdf import FPDF

    violations: list[dict[str, Any]] = audit_data.get("violations", [])
    latest_scan = audit_data.get("latest_scan")

    if latest_scan and latest_scan.get("started_at"):
        scan_date = latest_scan["started_at"][:10]
    else:
        scan_date = datetime.now().strftime("%Y-%m-%d")

    open_v = [v for v in violations if v.get("status") == "open"]
    crit = sum(1 for v in open_v if v.get("severity") == "CRITICAL")
    high = sum(1 for v in open_v if v.get("severity") == "HIGH")
    med  = sum(1 for v in open_v if v.get("severity") == "MEDIUM")
    score_obj = audit_data.get("compliance_score", {})
    final_score = score_obj.get("score", max(0, 100 - crit * 15 - high * 8 - med * 4))
    remediated = [v for v in violations if v.get("status") == "resolved"]

    LH = 5.5
    BLUE       = (37, 99, 235)
    SLATE_900  = (15, 23, 42)
    SLATE_800  = (30, 41, 59)
    SLATE_600  = (71, 85, 105)
    SLATE_400  = (148, 163, 184)
    WHITE      = (255, 255, 255)

    class _SOC2PDF(FPDF):
        def __init__(self_inner):
            super().__init__("P", "mm", "A4")
            self_inner._is_cover = True
            self_inner.set_margins(20, 22, 20)
            self_inner.set_auto_page_break(auto=True, margin=20)

        def header(self_inner):
            if self_inner._is_cover:
                return
            self_inner.set_fill_color(*SLATE_900)
            self_inner.rect(0, 0, self_inner.w, 12, style="F")
            self_inner.set_y(3.5)
            self_inner.set_x(self_inner.l_margin)
            self_inner.set_font("Helvetica", "B", 8)
            self_inner.set_text_color(*SLATE_400)
            self_inner.cell(self_inner.epw - 20, 5.5, "SENTINEL -- SOC2 Compliance Report", align="L")
            self_inner.cell(20, 5.5, f"Page {self_inner.page_no()}", align="R")
            # Position cursor below the header bar so content never overlaps it
            self_inner.set_y(self_inner.t_margin)
            self_inner.set_text_color(*SLATE_800)

        def footer(self_inner):
            if self_inner._is_cover:
                return
            self_inner.set_y(-12)
            self_inner.set_x(self_inner.l_margin)
            self_inner.set_font("Helvetica", "I", 7)
            self_inner.set_text_color(*SLATE_400)
            self_inner.cell(self_inner.epw - 20, 5, "CONFIDENTIAL -- For Internal and Auditor Use Only", align="C")
            self_inner.cell(20, 5, f"Page {self_inner.page_no()}", align="R")

    pdf = _SOC2PDF()

    # ── Cover page ────────────────────────────────────────────────────────────
    pdf._is_cover = True
    pdf.add_page()

    pdf.set_fill_color(*SLATE_900)
    pdf.rect(0, 0, pdf.w, pdf.h, style="F")

    # CONFIDENTIAL watermark — rotated 45°, dark-on-dark
    cx, cy = pdf.w / 2, pdf.h / 2
    with pdf.rotation(angle=45, x=cx, y=cy):
        pdf.set_font("Helvetica", "B", 60)
        pdf.set_text_color(30, 41, 59)
        tw = pdf.get_string_width("CONFIDENTIAL")
        pdf.text(x=cx - tw / 2, y=cy + 12, txt="CONFIDENTIAL")

    pdf.set_y(78)
    pdf.set_x(0)
    pdf.set_font("Helvetica", "B", 48)
    pdf.set_text_color(*WHITE)
    pdf.cell(pdf.w, 22, "SENTINEL", align="C", ln=True)

    pdf.set_x(0)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(*SLATE_400)
    pdf.cell(pdf.w, 8, "AcmeCorp", align="C", ln=True)

    pdf.ln(8)
    pdf.set_x(0)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*WHITE)
    pdf.cell(pdf.w, 10, "SOC2 Type II Compliance Audit Report", align="C", ln=True)

    pdf.ln(4)
    pdf.set_x(0)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(pdf.w, 7, f"Audit Period:  {scan_date}", align="C", ln=True)

    pdf.set_y(pdf.h - 22)
    pdf.set_x(0)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(pdf.w, 5, f"Generated {datetime.now().strftime('%B %d, %Y  at  %H:%M UTC')}", align="C", ln=True)

    # ── Content pages ─────────────────────────────────────────────────────────
    pdf._is_cover = False

    def section_header(title: str) -> None:
        pdf.ln(4)
        pdf.set_fill_color(*BLUE)
        pdf.set_text_color(*WHITE)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_x(pdf.l_margin)
        pdf.cell(pdf.epw, 9, f"  {title}", fill=True, ln=True)
        pdf.set_text_color(*SLATE_800)
        pdf.ln(3)

    def subsection_header(title: str) -> None:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*SLATE_800)
        pdf.set_x(pdf.l_margin)
        pdf.cell(pdf.epw, 7, title, ln=True)
        y = pdf.get_y()
        pdf.set_draw_color(*SLATE_400)
        pdf.line(pdf.l_margin, y, pdf.l_margin + pdf.epw, y)
        pdf.ln(3)

    def body_text(text: str) -> None:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*SLATE_600)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, LH, text)
        pdf.ln(2)

    def embed_image(img_path_str: str, indent: float = 0, img_w: float = 130) -> None:
        """Embed an image, inserting a page break first if it won't fit."""
        img_h_est = img_w * 0.6  # conservative ratio to prevent overflow
        if pdf.get_y() + img_h_est > pdf.h - 25:
            pdf.add_page()
            pdf.set_y(pdf.t_margin)  # header() leaves cursor inside the bar; reset below it
        try:
            pdf.set_x(pdf.l_margin + indent)
            pdf.image(img_path_str, x=pdf.l_margin + indent, w=img_w)
            pdf.ln(3)
        except Exception:
            pass

    # Section 1 — Executive Summary
    pdf.add_page()
    section_header("Section 1 -- Executive Summary")
    body_text(_sanitize(executive_summary))

    # Section 2 — Audit Scope & Methodology
    section_header("Section 2 -- Audit Scope & Methodology")
    body_text(
        "This audit was conducted by the Sentinel Compliance Platform across three enterprise "
        "internal tools: HR Portal (port 5001), IT Admin (port 5002), and Procurement Portal "
        "(port 5003). The audit employed Amazon Nova Act for browser automation-driven data "
        "extraction and Amazon Nova 2 Lite (via AWS Bedrock) for AI-driven violation detection "
        "and analysis.\n\n"
        "Each tool was accessed programmatically to extract user account data including "
        "usernames, roles, departments, and last-login timestamps. This data was "
        "cross-referenced against the HR system of record to identify access control violations "
        "across SOC2 Trust Service Criteria CC6.1, CC6.2, and CC6.3."
    )

    # Section 3 — Findings by SOC2 Control
    pdf.add_page()
    section_header("Section 3 -- Findings by SOC2 Control")

    finding_num = 1
    sev_colors = {
        "CRITICAL": (239, 68, 68),
        "HIGH":     (249, 115, 22),
        "MEDIUM":   (234, 179, 8),
        "LOW":      (34, 197, 94),
    }
    for idx, (control_id, control_info) in enumerate(SOC2_CONTROLS.items()):
        control_violations = [v for v in violations if v.get("soc2_control") == control_id]
        if idx > 0:
            pdf.add_page()
        subsection_header(f"{control_id} -- {control_info['name']}")
        body_text(control_info["description"])

        if not control_violations:
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(*SLATE_400)
            pdf.set_x(pdf.l_margin)
            pdf.cell(pdf.epw, LH, "No violations found for this control.", ln=True)
            pdf.ln(2)
        else:
            for v in control_violations:
                severity = v.get("severity", "")
                badge_rgb = sev_colors.get(severity, (100, 116, 139))

                pdf.set_fill_color(*badge_rgb)
                pdf.set_x(pdf.l_margin)
                pdf.cell(2, LH, "", fill=True, ln=False)
                pdf.set_font("Helvetica", "B", 9)
                pdf.set_text_color(*SLATE_800)
                pdf.cell(pdf.epw - 2, LH, f"  Finding #{finding_num} -- {control_id} Violation [{severity}]", ln=True)

                # Violation description
                desc = _sanitize(_format_violation_description(v))
                pdf.set_font("Helvetica", "B", 8)
                pdf.set_text_color(*SLATE_800)
                pdf.set_x(pdf.l_margin + 4)
                pdf.cell(pdf.epw - 4, LH, "Finding:", ln=True)
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(*SLATE_600)
                pdf.set_x(pdf.l_margin + 4)
                pdf.multi_cell(pdf.epw - 4, LH, desc)
                pdf.ln(1)

                # How Sentinel detected this
                detection = _sanitize(_format_detection_method(v))
                pdf.set_font("Helvetica", "B", 8)
                pdf.set_text_color(*SLATE_800)
                pdf.set_x(pdf.l_margin + 4)
                pdf.cell(pdf.epw - 4, LH, "How Sentinel detected this:", ln=True)
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(*SLATE_600)
                pdf.set_x(pdf.l_margin + 4)
                pdf.multi_cell(pdf.epw - 4, LH, detection)
                pdf.ln(1)

                status_label = v.get("status", "open").title()
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(*SLATE_400)
                pdf.set_x(pdf.l_margin + 4)
                pdf.cell(pdf.epw - 4, LH, f"Status: {status_label}", ln=True)

                screenshot_path = v.get("screenshot_path")
                if screenshot_path:
                    img_path = SCREENSHOTS_DIR / Path(screenshot_path).name
                    if img_path.exists():
                        embed_image(str(img_path), indent=0, img_w=pdf.epw)
                pdf.ln(4)
                finding_num += 1

    # Section 4 — Compliance Score
    pdf.add_page()
    section_header("Section 4 -- Compliance Score")

    # Scoring methodology explanation
    body_text(
        "Sentinel uses a 100-point baseline scoring model to quantify the organisation's "
        "SOC2 compliance posture. Each open violation detected during the scan incurs a "
        "point deduction scaled to its severity:"
    )

    bullet_items = [
        "CRITICAL (-15 pts):  Immediate, severe risk -- e.g. terminated employees retaining active system access (CC6.2).",
        "HIGH (-8 pts):       Significant risk requiring prompt action -- e.g. inactive administrator accounts (CC6.1).",
        "MEDIUM (-4 pts):     Elevated risk requiring remediation -- e.g. permission creep or shared privileged accounts (CC6.3).",
    ]
    for item in bullet_items:
        pdf.set_x(pdf.l_margin + 4)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*SLATE_600)
        pdf.cell(5, LH, "-", ln=False)
        pdf.multi_cell(pdf.epw - 9, LH, _sanitize(item))

    pdf.ln(2)
    body_text(
        "Only open (un-remediated) violations contribute to deductions. Resolved or "
        "dismissed violations are excluded from the calculation."
    )

    # Score narrative
    total_open = crit + high + med
    if total_open == 0:
        narrative = (
            "No open violations were detected during this scan. The organisation achieved "
            "a perfect compliance score of 100, indicating full adherence to the audited "
            "SOC2 Trust Service Criteria for this assessment period."
        )
    else:
        parts = []
        if crit:
            parts.append(f"{crit} CRITICAL violation{'s' if crit > 1 else ''} (-{crit * 15} pts)")
        if high:
            parts.append(f"{high} HIGH violation{'s' if high > 1 else ''} (-{high * 8} pts)")
        if med:
            parts.append(f"{med} MEDIUM violation{'s' if med > 1 else ''} (-{med * 4} pts)")
        deducted = 100 - final_score
        narrative = (
            f"This scan identified {total_open} open violation{'s' if total_open > 1 else ''}: "
            f"{', '.join(parts)}. A total of {deducted} points were deducted from the 100-point "
            f"baseline, yielding a final compliance score of {final_score}/100. "
        )
        if final_score >= 80:
            narrative += "The score reflects a generally compliant posture with isolated findings requiring attention."
        elif final_score >= 50:
            narrative += "The score indicates a moderate compliance risk; the identified violations require prompt remediation."
        else:
            narrative += "The score reflects significant compliance risk. Immediate remediation of all open violations is strongly recommended."
    body_text(narrative)

    col_label = pdf.epw - 25

    def score_row(label: str, value: str, bold: bool = False, separator: bool = False) -> None:
        if separator:
            y = pdf.get_y()
            pdf.set_draw_color(*SLATE_400)
            pdf.line(pdf.l_margin, y, pdf.l_margin + pdf.epw, y)
            pdf.ln(1)
        style = "B" if bold else ""
        pdf.set_font("Courier", style, 9)
        pdf.set_text_color(*SLATE_800 if bold else SLATE_600)
        pdf.set_x(pdf.l_margin)
        pdf.cell(col_label, LH, label, ln=False)
        pdf.cell(25, LH, value, align="R", ln=True)

    score_row("Baseline Score:", "100")
    score_row(f"CRITICAL deductions:  {crit} x -15  =", f"-{crit * 15}")
    score_row(f"HIGH deductions:      {high} x -8   =", f"-{high * 8}")
    score_row(f"MEDIUM deductions:    {med} x -4   =", f"-{med * 4}")
    score_row("Final Score:", str(final_score), bold=True, separator=True)
    pdf.ln(4)

    # Section 5 — Remediation Summary
    pdf.add_page()
    section_header("Section 5 -- Remediation Summary")

    if not remediated:
        body_text("No remediations have been executed during this audit period.")
    else:
        # Build lookup: violation_id -> audit trail entry for remediations
        audit_trail = audit_data.get("audit_trail", [])
        remediation_audit: dict[str, dict[str, Any]] = {
            e["violation_id"]: e
            for e in audit_trail
            if e.get("event_type") == "remediation_approved" and e.get("violation_id")
        }

        for rem_num, v in enumerate(remediated, 1):
            vid = v.get("violation_id", "")
            audit_entry = remediation_audit.get(vid, {})
            severity = v.get("severity", "")
            badge_rgb = {
                "CRITICAL": (239, 68, 68),
                "HIGH":     (249, 115, 22),
                "MEDIUM":   (234, 179, 8),
            }.get(severity, (100, 116, 139))

            # Heading row with severity badge
            pdf.set_fill_color(*badge_rgb)
            pdf.set_x(pdf.l_margin)
            pdf.cell(2, LH, "", fill=True, ln=False)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(*SLATE_800)
            vtype = v.get("violation_type", "")
            pdf.cell(
                pdf.epw - 2, LH,
                f"  Remediation #{rem_num} -- {vtype} [{severity}] -- {v.get('username', '')} on {v.get('tool_name', v.get('tool', ''))}",
                ln=True,
            )
            pdf.ln(1)

            # Finding
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(*SLATE_800)
            pdf.set_x(pdf.l_margin + 4)
            pdf.cell(pdf.epw - 4, LH, "Finding:", ln=True)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*SLATE_600)
            pdf.set_x(pdf.l_margin + 4)
            pdf.multi_cell(pdf.epw - 4, LH, _sanitize(v.get("evidence", _format_violation_description(v))))
            pdf.ln(1)

            # Actions Taken (Nova Act instructions from audit trail details)
            steps = audit_entry.get("details", "")
            if steps:
                pdf.set_font("Helvetica", "B", 8)
                pdf.set_text_color(*SLATE_800)
                pdf.set_x(pdf.l_margin + 4)
                pdf.cell(pdf.epw - 4, LH, "Actions Taken by Sentinel:", ln=True)
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(*SLATE_600)
                pdf.set_x(pdf.l_margin + 4)
                pdf.multi_cell(pdf.epw - 4, LH, _sanitize(steps))
                pdf.ln(1)

            # Result
            resolved_at = (audit_entry.get("timestamp") or v.get("resolved_at") or "")[:16]
            resolved_by = audit_entry.get("actor") or v.get("resolved_by") or "system"
            result_line = f"Successfully remediated by {resolved_by} at {resolved_at}."
            if audit_entry.get("result") == "manual_review":
                result_line = f"Flagged for manual review by {resolved_by} at {resolved_at}."
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(*SLATE_800)
            pdf.set_x(pdf.l_margin + 4)
            pdf.cell(pdf.epw - 4, LH, "Result:", ln=True)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*SLATE_600)
            pdf.set_x(pdf.l_margin + 4)
            pdf.cell(pdf.epw - 4, LH, _sanitize(result_line), ln=True)
            pdf.ln(1)

            # Screenshot evidence (prefer audit entry screenshot, fall back to violation screenshot)
            shot = audit_entry.get("screenshot_path") or v.get("screenshot_path")
            if shot:
                img_path = SCREENSHOTS_DIR / Path(shot).name
                if img_path.exists():
                    pdf.set_font("Helvetica", "I", 8)
                    pdf.set_text_color(*SLATE_400)
                    pdf.set_x(pdf.l_margin + 4)
                    pdf.cell(pdf.epw - 4, LH, "Evidence screenshot:", ln=True)
                    embed_image(str(img_path), indent=0, img_w=pdf.epw)

            pdf.ln(5)

    # Section 6 — Recommendations
    pdf.add_page()
    section_header("Section 6 -- Recommendations")

    for i, rec in enumerate(recommendations, 1):
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*BLUE)
        pdf.cell(8, LH, f"{i}.", ln=False)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*SLATE_600)
        pdf.multi_cell(pdf.epw - 8, LH, _sanitize(rec))
        pdf.ln(2)

    # Attestation block
    pdf.ln(8)
    y = pdf.get_y()
    pdf.set_draw_color(*SLATE_400)
    pdf.line(pdf.l_margin, y, pdf.l_margin + pdf.epw, y)
    pdf.ln(5)

    generated_at = datetime.now().strftime("%B %d, %Y at %H:%M UTC")
    attestation = (
        f"This report was generated by Sentinel Compliance Platform v1.0\n"
        f"on {generated_at}.\n\n"
        "Automated analysis powered by Amazon Nova Act (browser automation)\n"
        "and Amazon Nova 2 Lite (AI-driven violation detection).\n\n"
        "This document is intended for internal use and qualified auditors only."
    )
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*SLATE_600)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pdf.epw, LH, attestation, align="C")

    y2 = pdf.get_y() + 3
    pdf.set_draw_color(*SLATE_400)
    pdf.line(pdf.l_margin, y2, pdf.l_margin + pdf.epw, y2)

    return bytes(pdf.output())


@app.get("/api/reports/export")
async def export_report() -> Response:
    """Generate a structured SOC2 PDF audit report and return it as a download."""
    latest_scan = database.get_latest_scan()
    scan_id = latest_scan["scan_id"] if latest_scan else None
    audit_data = {
        "generated_at": datetime.now().isoformat(),
        "violations": database.get_violations(scan_id=scan_id),
        "audit_trail": database.get_audit_trail(since=SESSION_START)[:50],
        "compliance_score": violation_engine.calculate_compliance_score(scan_id=scan_id),
        "latest_scan": latest_scan,
    }

    try:
        executive_summary = nova_client.generate_executive_summary(audit_data)
    except Exception as exc:
        logger.error("Executive summary generation failed: %s", exc)
        executive_summary = (
            "This automated compliance audit was conducted by the Sentinel platform across "
            "enterprise internal tools. The audit identified access control violations "
            "requiring remediation. Please review the findings in this report for details."
        )

    try:
        recommendations = nova_client.generate_recommendations(audit_data)
    except Exception as exc:
        logger.error("Recommendations generation failed: %s", exc)
        recommendations = [
            "Implement quarterly access reviews for all administrative accounts.",
            "Enforce immediate access revocation upon employee termination.",
            "Prohibit shared administrative accounts across all systems.",
        ]

    pdf_bytes = _build_soc2_pdf(audit_data, executive_summary, recommendations)
    filename = f"sentinel_soc2_audit_{datetime.now().strftime('%Y%m%d')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# Voice assistant — status
# ---------------------------------------------------------------------------


@app.get("/api/voice-assistant/status")
async def voice_assistant_status() -> dict[str, Any]:
    enabled = os.environ.get("NOVA_SONIC_ENABLED", "true").lower() != "false"
    voice_id = os.environ.get("NOVA_SONIC_VOICE_ID", "tiffany")
    return {"enabled": enabled, "voice_id": voice_id}


# ---------------------------------------------------------------------------
# Voice assistant — WebSocket (primary interactive path)
# ---------------------------------------------------------------------------


@app.websocket("/api/voice-session")
async def voice_session_ws(websocket: WebSocket) -> None:
    """Bidirectional PCM audio stream for Nova Sonic voice assistant."""
    await websocket.accept()
    logger.info("Voice session WebSocket connected")

    async def on_action(action: str, params: dict[str, Any]) -> None:
        """Handle intents detected from Nova Sonic text output."""
        if action == "scan_started":
            # Trigger a real scan and tell the frontend about it
            scan_id = str(uuid.uuid4())
            started_at = datetime.now().isoformat()
            database.create_scan(scan_id, "running", "Scan started via voice", started_at)
            database.insert_audit_entry({
                "entry_id": str(uuid.uuid4()),
                "event_type": "scan_started",
                "violation_id": None,
                "scan_id": scan_id,
                "actor": "voice-assistant",
                "action": "Compliance scan triggered via voice command",
                "result": "started",
                "screenshot_path": None,
                "timestamp": started_at,
                "details": None,
            })
            asyncio.create_task(_run_scan_background(scan_id))
            await websocket.send_text(
                json.dumps({"type": "action", "action": "scan_started", "scan_id": scan_id})
            )

        elif action == "generate_report":
            await websocket.send_text(
                json.dumps({"type": "action", "action": "generate_report", "url": "/api/reports/export"})
            )


    try:
        session = va_module.VoiceSession()
        await session.run(websocket, on_action=on_action)
    except WebSocketDisconnect:
        logger.info("Voice session WebSocket disconnected")
    except Exception as exc:
        logger.error("Voice session error: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Audio briefing — fallback (no mic / voice disabled)
# ---------------------------------------------------------------------------


@app.get("/api/scan/{scan_id}/briefing-text")
async def get_scan_briefing_text(scan_id: str) -> dict[str, str]:
    """Return the spoken briefing text for a completed scan (cached)."""
    scan = database.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan["status"] != "completed":
        raise HTTPException(status_code=409, detail="Scan not yet completed")

    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(
        None, briefing_generator.generate_briefing_text, scan_id
    )
    return {"text": text, "scan_id": scan_id}


@app.get("/api/scan/{scan_id}/briefing-audio")
async def get_scan_briefing_audio(scan_id: str) -> StreamingResponse:
    """
    Generate and stream a WAV audio briefing for a completed scan.
    Uses cached briefing text to avoid a double Nova 2 Lite call.
    """
    scan = database.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan["status"] != "completed":
        raise HTTPException(status_code=409, detail="Scan not yet completed")

    voice_id = os.environ.get("NOVA_SONIC_VOICE_ID", "tiffany")
    loop = asyncio.get_event_loop()

    # generate_briefing_text is cached — safe to call here even if briefing-text
    # was already fetched in parallel; second call returns instantly from cache
    text = await loop.run_in_executor(
        None, briefing_generator.generate_briefing_text, scan_id
    )
    wav_bytes = await loop.run_in_executor(
        None, nova_sonic_tts.synthesize_speech, text, voice_id
    )

    return StreamingResponse(
        iter([wav_bytes]),
        media_type="audio/wav",
        headers={"Content-Disposition": f"inline; filename=briefing_{scan_id[:8]}.wav"},
    )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "sentinel-backend"}


# ---------------------------------------------------------------------------
# Serve React frontend (production build)
# Must be registered last so all /api/* routes take priority.
# ---------------------------------------------------------------------------

FRONTEND_DIST = Path(__file__).parent / "dist"

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        file = FRONTEND_DIST / full_path
        if file.is_file():
            return FileResponse(str(file))
        return FileResponse(str(FRONTEND_DIST / "index.html"))
