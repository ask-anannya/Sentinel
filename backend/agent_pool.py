"""
Nova Act agent pool for parallel scanning of legacy enterprise tools.
Each tool is scanned in its own browser session. All sessions share a single
Workflow context (SDK multi-threading pattern).
"""

import os
import logging
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from nova_act import NovaAct
from nova_act.types.workflow import Workflow

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool configurations — populated from environment variables at runtime
# ---------------------------------------------------------------------------

def _get_tool_configs() -> list[dict[str, str]]:
    return [
        {
            "name": "hr-portal",
            "url": os.environ.get("HRMS_URL", "http://localhost:5001"),
            "username": os.environ.get("HRMS_USERNAME", "admin"),
            "password": os.environ.get("HRMS_PASSWORD", "admin123"),
            "user_page": "/users",
            "description": "AcmeCorp HRMS v3.1 (PeopleSoft-style HR portal)",
        },
        {
            "name": "it-admin",
            "url": os.environ.get("ITADMIN_URL", "http://localhost:5002"),
            "username": os.environ.get("ITADMIN_USERNAME", "admin"),
            "password": os.environ.get("ITADMIN_PASSWORD", "admin123"),
            "user_page": "/users",
            "description": "IT Administration Console v2.4 (ServiceNow-style)",
        },
        {
            "name": "procurement",
            "url": os.environ.get("PROCUREMENT_URL", "http://localhost:5003"),
            "username": os.environ.get("PROCUREMENT_USERNAME", "admin"),
            "password": os.environ.get("PROCUREMENT_PASSWORD", "admin123"),
            "user_page": "/users",
            "description": "AcmeCorp Procurement Portal v1.8.2 (SAP SRM-style)",
        },
    ]


TOOL_CONFIGS = _get_tool_configs()


# ---------------------------------------------------------------------------
# Pydantic models for structured extraction
# ---------------------------------------------------------------------------

class ExtractedUser(BaseModel):
    username: str
    full_name: str
    role: str
    last_login_date: str
    account_status: str
    department: str


class UserList(BaseModel):
    users: list[ExtractedUser]


# ---------------------------------------------------------------------------
# Scan instructions passed to Nova Act for structured extraction
# ---------------------------------------------------------------------------

SCAN_INSTRUCTIONS = """
Look at the user table on this page. For every row in the table, extract:
- username: the username or login ID
- full_name: the person's full name
- role: their job role or title
- last_login_date: the date they last logged in (as shown, e.g. 2024-01-15)
- account_status: their account status (Active, Inactive, Disabled, etc.)
- department: their department or team

Return ALL users visible in the table. Do not skip any rows.
"""


# ---------------------------------------------------------------------------
# Screenshots directory
# ---------------------------------------------------------------------------

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


def _save_screenshot(nova: NovaAct, tool_name: str) -> str | None:
    """Take a screenshot via Playwright and save it. Returns relative path."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{tool_name}_{timestamp}.png"
        filepath = os.path.join(SCREENSHOTS_DIR, filename)
        nova.page.screenshot(path=filepath)
        return filename
    except Exception as exc:
        logger.warning("Screenshot failed for %s: %s", tool_name, exc)
        return None


def scan_tool(tool_config: dict[str, str], workflow: Workflow) -> dict[str, Any]:
    """
    Scan a single legacy tool using Nova Act.
    Returns extracted user data and screenshot path.
    """
    tool_name = tool_config["name"]
    logger.info("Starting scan for tool: %s", tool_name)

    try:
        with NovaAct(
            starting_page=tool_config["url"] + "/login",
            headless=True,
            workflow=workflow,
            ignore_https_errors=True,
        ) as nova:
            # --- Login using SDK's secure credential pattern ---
            nova.act("Click on the username input field")
            nova.page.keyboard.type(tool_config["username"])

            nova.act("Click on the password input field")
            nova.page.keyboard.type(tool_config["password"])

            nova.act("Click the submit button inside the login form to log in (it may say 'Sign In', 'Login', or 'Authenticate')")

            # --- Navigate to user list ---
            nova.act(
                "Navigate to the user management page or click on Users in the navigation menu"
            )

            # --- Structured data extraction ---
            result = nova.act_get(
                SCAN_INSTRUCTIONS,
                schema=UserList.model_json_schema(),
            )

            users: list[dict[str, Any]] = []
            if result.matches_schema and result.parsed_response:
                user_list = UserList.model_validate(result.parsed_response)
                users = [u.model_dump() for u in user_list.users]
                logger.info(
                    "Extracted %d users from %s", len(users), tool_name
                )
            else:
                logger.warning(
                    "Extraction did not match schema for %s. Raw: %s",
                    tool_name,
                    result.response,
                )

            # --- Screenshot for audit evidence ---
            screenshot_path = _save_screenshot(nova, tool_name)

            return {
                "tool": tool_name,
                "users": users,
                "screenshot_path": screenshot_path,
                "success": True,
                "error": None,
            }

    except Exception as exc:
        logger.error("Scan failed for tool %s: %s", tool_name, exc, exc_info=True)
        return {
            "tool": tool_name,
            "users": [],
            "screenshot_path": None,
            "success": False,
            "error": str(exc),
        }


def scan_all_tools() -> list[dict[str, Any]]:
    """
    Scan all three legacy tools in parallel using a shared Workflow context.
    Returns combined results list.
    """
    # Refresh tool configs in case env vars changed at runtime
    configs = _get_tool_configs()

    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    workflow_name = os.environ.get("NOVA_ACT_WORKFLOW_NAME", "sentinel-scan")

    logger.info("Starting parallel scan of %d tools", len(configs))

    results: list[dict[str, Any]] = []

    with Workflow(
        model_id="nova-act-latest",
        workflow_definition_name=workflow_name,
        boto_session_kwargs={"region_name": region},
    ) as workflow:
        with ThreadPoolExecutor(max_workers=len(configs)) as executor:
            future_to_config = {
                executor.submit(scan_tool, config, workflow): config
                for config in configs
            }
            for future in as_completed(future_to_config):
                config = future_to_config[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as exc:
                    logger.error(
                        "Unexpected error scanning %s: %s",
                        config["name"],
                        exc,
                        exc_info=True,
                    )
                    results.append(
                        {
                            "tool": config["name"],
                            "users": [],
                            "screenshot_path": None,
                            "success": False,
                            "error": str(exc),
                        }
                    )

    logger.info(
        "Parallel scan complete. Tools scanned: %d, successful: %d",
        len(results),
        sum(1 for r in results if r["success"]),
    )
    return results
