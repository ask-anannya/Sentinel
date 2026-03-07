"""
Violation detection engine.
Loads HR source-of-truth data, calls Nova 2 Lite via nova_client,
saves violations to the database, and calculates compliance score.
"""

import csv
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any

import database
import nova_client

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
EMPLOYEES_CSV = os.path.join(DATA_DIR, "employees.csv")
ROLE_POLICIES_JSON = os.path.join(DATA_DIR, "role_policies.json")


def _load_employees() -> list[dict[str, str]]:
    """Load the HR source-of-truth employees CSV."""
    employees = []
    with open(EMPLOYEES_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            employees.append(dict(row))
    return employees


def _load_role_policies() -> dict[str, Any]:
    """Load role policy rules from JSON."""
    with open(ROLE_POLICIES_JSON, encoding="utf-8") as f:
        return json.load(f)


def analyze_violations(
    scan_results: list[dict[str, Any]],
    scan_id: str,
) -> list[dict[str, Any]]:
    """
    For each tool's extracted users, call Nova 2 Lite to detect violations.
    Saves all violations to the database.
    Returns the combined list of violations found.
    """
    hr_employees = _load_employees()
    role_policies = _load_role_policies()
    today = datetime.now().strftime("%Y-%m-%d")

    all_violations: list[dict[str, Any]] = []

    for tool_result in scan_results:
        tool_name = tool_result["tool"]
        extracted_users = tool_result.get("users", [])
        screenshot_path = tool_result.get("screenshot_path")

        if not extracted_users:
            logger.warning(
                "No users extracted from %s — skipping violation analysis", tool_name
            )
            continue

        logger.info(
            "Analyzing %d users from %s for violations", len(extracted_users), tool_name
        )

        raw_violations = nova_client.detect_violations(
            extracted_users=extracted_users,
            hr_employees=hr_employees,
            role_policies=role_policies,
            tool_name=tool_name,
            today=today,
        )

        for v in raw_violations:
            violation = {
                "violation_id": str(uuid.uuid4()),
                "scan_id": scan_id,
                "tool_name": tool_name,
                "username": v.get("username", "unknown"),
                "full_name": v.get("full_name", ""),
                "department": v.get("department", ""),
                "role": v.get("role", ""),
                "violation_type": v.get("violation_type", "UNKNOWN"),
                "severity": v.get("severity", "MEDIUM"),
                "severity_score": v.get("severity_score", 50),
                "evidence": v.get("evidence", ""),
                "soc2_control": v.get("soc2_control", ""),
                "screenshot_path": screenshot_path,
                "status": "open",
                "detected_at": datetime.now().isoformat(),
            }
            all_violations.append(violation)

    if all_violations:
        database.insert_violations(all_violations)
        logger.info("Saved %d violations to database", len(all_violations))

    return all_violations


def calculate_compliance_score() -> dict[str, Any]:
    """
    Calculate compliance score based on open violations.
    Deductions: CRITICAL=-15, HIGH=-8, MEDIUM=-4.
    Returns score dict.
    """
    open_violations = database.get_open_violations()

    role_policies = _load_role_policies()
    deductions = role_policies.get("compliance_score", {}).get(
        "deductions", {"CRITICAL": 15, "HIGH": 8, "MEDIUM": 4}
    )

    score = 100
    by_severity: dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0}

    for v in open_violations:
        severity = v.get("severity", "MEDIUM")
        by_severity[severity] = by_severity.get(severity, 0) + 1
        score -= deductions.get(severity, 4)

    score = max(0, score)

    return {
        "score": score,
        "total_violations": len(open_violations),
        "by_severity": by_severity,
        "deductions_applied": {
            sev: count * deductions.get(sev, 0)
            for sev, count in by_severity.items()
        },
    }
