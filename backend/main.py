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


@app.on_event("startup")
async def startup() -> None:
    database.init_db()
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

        loop = asyncio.get_event_loop()
        scan_results = await loop.run_in_executor(
            None,
            functools.partial(agent_pool.scan_all_tools, event_callback=event_callback),
        )
        violations = ve.analyze_violations(scan_results, scan_id)

        completed_at = datetime.now().isoformat()
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
    """Return full audit history."""
    return database.get_audit_trail()


# ---------------------------------------------------------------------------
# Compliance score
# ---------------------------------------------------------------------------


@app.get("/api/compliance-score")
async def get_compliance_score() -> dict[str, Any]:
    """Return current compliance score and breakdown."""
    return violation_engine.calculate_compliance_score()


# ---------------------------------------------------------------------------
# PDF / text report export
# ---------------------------------------------------------------------------


def _build_pdf(report_text: str) -> bytes:
    """Convert the Nova 2 Lite plain-text report into a formatted PDF."""
    from fpdf import FPDF

    LH = 5.5  # standard line height

    def _write_inline(pdf: FPDF, text: str) -> None:
        """Write a string, switching to bold for **…** spans."""
        for part in re.split(r"(\*\*[^*]+\*\*)", text):
            if part.startswith("**") and part.endswith("**"):
                pdf.set_font("Helvetica", "B", 9)
                pdf.write(LH, part[2:-2])
            else:
                pdf.set_font("Helvetica", "", 9)
                pdf.write(LH, part)

    pdf = FPDF()
    pdf.set_margins(20, 20, 20)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # ── Header banner ────────────────────────────────────────────────────────
    pdf.set_fill_color(15, 23, 42)          # slate-900
    pdf.rect(0, 0, pdf.w, 38, style="F")
    pdf.set_y(8)
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(pdf.w, 12, "SENTINEL", align="C", ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(148, 163, 184)       # slate-400
    pdf.cell(pdf.w, 6, "Compliance Audit Report  \u00b7  SOC2 / HIPAA / GDPR", align="C", ln=True)
    pdf.set_text_color(100, 116, 139)       # slate-500
    pdf.cell(pdf.w, 5, f"Generated {datetime.now().strftime('%B %d, %Y  at  %H:%M')}", align="C", ln=True)
    pdf.set_y(48)
    pdf.set_text_color(30, 41, 59)          # slate-800 (default body colour)

    # ── Body ─────────────────────────────────────────────────────────────────
    for raw_line in report_text.splitlines():
        stripped = raw_line.strip()

        # blank line → small gap
        if not stripped:
            pdf.ln(2)
            continue

        # Screenshot filename → embed actual image
        img_match = re.search(r"([\w\-]+\.png)", stripped)
        if img_match:
            img_name = img_match.group(1)
            img_path = Path(__file__).parent / "screenshots" / img_name
            if img_path.exists():
                # Print any surrounding label text first
                label = re.sub(r"\[?[\w\-]+\.png\]?", "", stripped).strip(" :-")
                if label:
                    pdf.set_x(pdf.l_margin)
                    pdf.set_font("Helvetica", "I", 8)
                    pdf.set_text_color(100, 116, 139)
                    pdf.cell(pdf.epw, 5, label, ln=True)
                pdf.set_x(pdf.l_margin)
                pdf.image(str(img_path), x=pdf.l_margin, w=pdf.epw)
                pdf.ln(4)
                continue

        # === Section header ===
        if stripped.startswith("==="):
            title = stripped.strip("= ").strip()
            pdf.ln(5)
            pdf.set_fill_color(37, 99, 235)     # blue-600
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_x(pdf.l_margin)
            pdf.cell(pdf.epw, 9, f"  {title}", fill=True, ln=True)
            pdf.set_text_color(30, 41, 59)
            pdf.ln(2)
            continue

        # --- horizontal rule
        if stripped.startswith("---"):
            pdf.set_x(pdf.l_margin)
            y = pdf.get_y() + 2
            pdf.set_draw_color(148, 163, 184)
            pdf.line(pdf.l_margin, y, pdf.l_margin + pdf.epw, y)
            pdf.ln(6)
            continue

        # - bullet point  (supports one level of indentation)
        if stripped.startswith("- ") or stripped.startswith("* "):
            indent = len(raw_line) - len(raw_line.lstrip(" "))
            x_off = pdf.l_margin + 4 + max(0, indent - 1) * 4
            pdf.set_x(x_off)
            pdf.set_text_color(30, 41, 59)
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(5, LH, "\xb7", ln=False)
            _write_inline(pdf, stripped[2:])
            pdf.ln(LH)
            continue

        # 1. Numbered list item
        num_match = re.match(r"^(\d+)\.\s+(.*)", stripped)
        if num_match:
            num, content = num_match.group(1), num_match.group(2)
            pdf.set_x(pdf.l_margin + 4)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(37, 99, 235)
            pdf.cell(7, LH, f"{num}.", ln=False)
            pdf.set_text_color(30, 41, 59)
            _write_inline(pdf, content)
            pdf.ln(LH)
            continue

        # regular paragraph text
        pdf.set_x(pdf.l_margin)
        pdf.set_text_color(71, 85, 105)     # slate-600
        _write_inline(pdf, stripped)
        pdf.ln(LH)

    return bytes(pdf.output())


@app.get("/api/reports/export")
async def export_report() -> Response:
    """Generate a formatted PDF audit report via Nova 2 Lite and return it as a download."""
    audit_data = {
        "generated_at": datetime.now().isoformat(),
        "violations": database.get_violations(),
        "audit_trail": database.get_audit_trail()[:50],
        "compliance_score": violation_engine.calculate_compliance_score(),
        "latest_scan": database.get_latest_scan(),
    }

    try:
        report_text = nova_client.generate_audit_report(audit_data)
    except Exception as exc:
        logger.error("Report generation failed: %s", exc)
        raise HTTPException(
            status_code=500, detail=f"Report generation failed: {exc}"
        )

    pdf_bytes = _build_pdf(report_text)
    filename = f"sentinel_audit_{datetime.now().strftime('%Y%m%d')}.pdf"
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
