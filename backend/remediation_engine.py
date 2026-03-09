"""
Remediation engine.
Uses Nova Act to log into legacy tools and execute approved remediations.
Every remediation is fully audited with screenshot evidence.
"""

import logging
import os
import uuid
from datetime import datetime
from typing import Any

from nova_act import NovaAct
from nova_act.types.workflow import Workflow

import database
import agent_pool

logger = logging.getLogger(__name__)

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Remediation instruction templates (keyed by violation_type)
# ---------------------------------------------------------------------------

REMEDIATION_INSTRUCTIONS: dict[str, str] = {
    "ACCESS_VIOLATION": (
        "Navigate to the user management page. "
        "Find the user with username '{username}'. "
        "Click their Edit or Disable link. "
        "Click the 'Disable Account' or 'Deactivate' button to revoke their access. "
        "Confirm any confirmation dialog. "
        "Verify the account shows as Disabled or Inactive."
    ),
    "INACTIVE_ADMIN": (
        "Navigate to the user management page. "
        "Find the user with username '{username}'. "
        "Click their Edit link. "
        "Click the 'Deactivate Account' button or remove their admin privileges. "
        "Confirm any confirmation dialog. "
        "Verify the change is reflected in the user table."
    ),
    "PERMISSION_CREEP": (
        "Navigate to the user management page. "
        "Find the user with username '{username}'. "
        "Click their Edit link. "
        "Revoke admin or elevated access — click 'Revoke Admin', "
        "'Revoke Approval Rights', or change Access Level to 'Standard User'. "
        "Save the changes. "
        "Verify the user no longer has admin/elevated access."
    ),
    "SHARED_ACCOUNT": None,  # Manual review only — no autonomous action
}

SHARED_ACCOUNT_MSG = (
    "Shared account violations require manual review and organizational decision. "
    "Autonomous remediation is not performed for shared accounts (SOC2 CC6.3). "
    "Please review this account manually and determine the appropriate action."
)


def _get_tool_config(tool_name: str) -> dict[str, str] | None:
    """Look up tool configuration by name."""
    configs = agent_pool._get_tool_configs()
    return next((c for c in configs if c["name"] == tool_name), None)


def _take_screenshot(nova: NovaAct, prefix: str) -> str | None:
    """Take a confirmation screenshot and return the filename."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"remediation_{prefix}_{timestamp}.png"
        filepath = os.path.join(SCREENSHOTS_DIR, filename)
        nova.page.screenshot(path=filepath)
        return filename
    except Exception as exc:
        logger.warning("Remediation screenshot failed: %s", exc)
        return None


def execute_remediation(
    violation: dict[str, Any],
    approved_by: str,
    event_callback=None,
) -> dict[str, Any]:
    """
    Execute an approved remediation for a violation.

    Returns a result dict with success/failure and evidence.
    Updates violation status and creates audit trail entry.
    """
    violation_id = violation["violation_id"]
    violation_type = violation["violation_type"]
    tool_name = violation["tool_name"]
    username = violation["username"]

    logger.info(
        "Executing remediation for violation %s (%s) on %s user %s",
        violation_id,
        violation_type,
        tool_name,
        username,
    )

    def _emit(step: int, message: str, status: str, screenshot: str | None = None) -> None:
        if event_callback:
            event_callback(step, message, status, screenshot=screenshot)

    # Violation-type-specific action messages
    _ACTION_RUNNING = {
        "ACCESS_VIOLATION": "Disabling account...",
        "INACTIVE_ADMIN": "Deactivating account...",
        "PERMISSION_CREEP": "Revoking admin access...",
    }
    _ACTION_DONE = {
        "ACCESS_VIOLATION": "Account disabled",
        "INACTIVE_ADMIN": "Account deactivated",
        "PERMISSION_CREEP": "Admin access revoked",
    }

    # --- Shared accounts: manual review only ---
    if violation_type == "SHARED_ACCOUNT":
        resolved_at = datetime.now().isoformat()
        database.update_violation_status(
            violation_id,
            status="resolved",
            resolved_by=approved_by,
            resolved_at=resolved_at,
            dismiss_reason="Flagged for manual review (shared account policy)",
        )
        database.insert_audit_entry(
            {
                "entry_id": str(uuid.uuid4()),
                "event_type": "remediation_approved",
                "violation_id": violation_id,
                "scan_id": violation.get("scan_id"),
                "actor": approved_by,
                "action": f"SHARED_ACCOUNT flagged for manual review: {username} on {tool_name}",
                "result": "manual_review",
                "screenshot_path": None,
                "timestamp": resolved_at,
                "details": SHARED_ACCOUNT_MSG,
            }
        )
        return {
            "success": True,
            "manual_review": True,
            "message": SHARED_ACCOUNT_MSG,
            "screenshot_path": None,
        }

    # --- Look up tool config ---
    tool_config = _get_tool_config(tool_name)
    if not tool_config:
        error_msg = f"Tool configuration not found for: {tool_name}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}

    # --- Get remediation instructions ---
    instructions_template = REMEDIATION_INSTRUCTIONS.get(violation_type)
    if not instructions_template:
        error_msg = f"No remediation instructions for violation type: {violation_type}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}

    instructions = instructions_template.format(username=username)

    # --- Execute via Nova Act ---
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    workflow_name = os.environ.get("NOVA_ACT_WORKFLOW_NAME", "sentinel-scan")

    screenshot_path: str | None = None
    try:
        _emit(0, f"Navigating to {tool_name} login...", "running")
        with Workflow(
            model_id="nova-act-latest",
            workflow_definition_name=workflow_name,
            boto_session_kwargs={"region_name": region},
        ) as workflow:
            with NovaAct(
                starting_page=tool_config["url"] + "/login",
                headless=True,
                ignore_https_errors=True,
                workflow=workflow,
            ) as nova:
                # Login
                nova.act("Click on the username input field")
                nova.page.keyboard.type(tool_config["username"])
                nova.act("Click on the password input field")
                nova.page.keyboard.type(tool_config["password"])
                nova.act("Click the submit button inside the login form to log in (it may say 'Sign In', 'Login', or 'Authenticate')")

                # Screenshot: post-login state
                shot_login = _take_screenshot(nova, f"{tool_name}_{username}_login")
                _emit(1, f"Logged into {tool_name}", "success", screenshot=shot_login)

                # Auto-accept native browser confirm() dialogs.
                # All three legacy portals use onclick="return confirm(...)" on
                # their disable/deactivate/revoke buttons. Nova Act cannot see
                # or interact with native JS dialogs, so we accept them via the
                # Playwright dialog event before the agent clicks the button.
                nova.page.on("dialog", lambda dialog: dialog.accept())

                # Navigate to user
                nova.act(
                    "Navigate to the user management page or click on Users in the navigation menu"
                )

                # Screenshot: user row visible
                shot_user = _take_screenshot(nova, f"{tool_name}_{username}_user")
                _emit(2, f"Located user: {username}", "success", screenshot=shot_user)

                # Execute remediation
                _emit(3, _ACTION_RUNNING.get(violation_type, "Executing action..."), "running")
                nova.act(instructions)

                # Screenshot: confirmation state after action
                shot_done = _take_screenshot(nova, f"{tool_name}_{username}_done")
                _emit(3, _ACTION_DONE.get(violation_type, "Action complete"), "success", screenshot=shot_done)

                # Final audit screenshot (stored in DB)
                screenshot_path = _take_screenshot(
                    nova, f"{tool_name}_{username}_{violation_type.lower()}"
                )
                _emit(4, "Confirmation screenshot captured", "success", screenshot=screenshot_path)

        resolved_at = datetime.now().isoformat()
        database.update_violation_status(
            violation_id,
            status="resolved",
            resolved_by=approved_by,
            resolved_at=resolved_at,
        )
        database.insert_audit_entry(
            {
                "entry_id": str(uuid.uuid4()),
                "event_type": "remediation_approved",
                "violation_id": violation_id,
                "scan_id": violation.get("scan_id"),
                "actor": approved_by,
                "action": (
                    f"Remediated {violation_type} for {username} on {tool_name}"
                ),
                "result": "success",
                "screenshot_path": screenshot_path,
                "timestamp": resolved_at,
                "details": instructions,
            }
        )
        _emit(5, "Audit trail updated", "success")

        logger.info(
            "Remediation successful for violation %s. Screenshot: %s",
            violation_id,
            screenshot_path,
        )
        return {
            "success": True,
            "manual_review": False,
            "message": f"Remediation executed for {username} on {tool_name}.",
            "screenshot_path": screenshot_path,
        }

    except Exception as exc:
        logger.error(
            "Remediation failed for violation %s: %s", violation_id, exc, exc_info=True
        )
        _emit(-1, f"Error: {exc}", "error")
        failed_at = datetime.now().isoformat()
        database.insert_audit_entry(
            {
                "entry_id": str(uuid.uuid4()),
                "event_type": "remediation_approved",
                "violation_id": violation_id,
                "scan_id": violation.get("scan_id"),
                "actor": approved_by,
                "action": f"Remediation FAILED for {username} on {tool_name}",
                "result": "failed",
                "screenshot_path": None,
                "timestamp": failed_at,
                "details": str(exc),
            }
        )
        return {"success": False, "error": str(exc)}
