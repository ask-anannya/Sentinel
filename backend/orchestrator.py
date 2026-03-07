"""
Scan orchestrator.
Coordinates Nova Act agent pool → violation engine → database updates.
Designed to run as a FastAPI BackgroundTask so the API endpoint returns immediately.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

import database
import agent_pool
import violation_engine

logger = logging.getLogger(__name__)


def run_scan() -> str:
    """
    Execute a full compliance scan:
    1. Create scan record (status: running)
    2. Scan all tools via Nova Act agent pool (parallel)
    3. Analyze violations via Nova 2 Lite
    4. Update scan record (status: completed)

    Returns the scan_id so callers can poll status.
    """
    scan_id = str(uuid.uuid4())
    started_at = datetime.now().isoformat()

    database.create_scan(scan_id, "running", "Scan in progress", started_at)

    # Audit entry: scan started
    database.insert_audit_entry(
        {
            "entry_id": str(uuid.uuid4()),
            "event_type": "scan_started",
            "violation_id": None,
            "scan_id": scan_id,
            "actor": "system",
            "action": "Compliance scan started",
            "result": "started",
            "screenshot_path": None,
            "timestamp": started_at,
            "details": "Automated compliance scan triggered",
        }
    )

    try:
        logger.info("Scan %s: starting agent pool scan", scan_id)
        scan_results = agent_pool.scan_all_tools()

        logger.info("Scan %s: analyzing violations", scan_id)
        violations = violation_engine.analyze_violations(scan_results, scan_id)

        completed_at = datetime.now().isoformat()
        database.update_scan(
            scan_id,
            status="completed",
            message=f"Scan completed. {len(violations)} violation(s) detected.",
            violations_found=len(violations),
            completed_at=completed_at,
        )

        # Audit entry: scan completed
        database.insert_audit_entry(
            {
                "entry_id": str(uuid.uuid4()),
                "event_type": "scan_completed",
                "violation_id": None,
                "scan_id": scan_id,
                "actor": "system",
                "action": f"Compliance scan completed with {len(violations)} violation(s)",
                "result": "success",
                "screenshot_path": None,
                "timestamp": completed_at,
                "details": f"Tools scanned: {len(scan_results)}. "
                           f"Successful: {sum(1 for r in scan_results if r['success'])}.",
            }
        )

        logger.info(
            "Scan %s completed: %d violations found", scan_id, len(violations)
        )

    except Exception as exc:
        logger.error("Scan %s failed: %s", scan_id, exc, exc_info=True)
        failed_at = datetime.now().isoformat()
        database.update_scan(
            scan_id,
            status="failed",
            message=f"Scan failed: {exc}",
            completed_at=failed_at,
        )
        database.insert_audit_entry(
            {
                "entry_id": str(uuid.uuid4()),
                "event_type": "scan_completed",
                "violation_id": None,
                "scan_id": scan_id,
                "actor": "system",
                "action": "Compliance scan failed",
                "result": "failed",
                "screenshot_path": None,
                "timestamp": failed_at,
                "details": str(exc),
            }
        )

    return scan_id
