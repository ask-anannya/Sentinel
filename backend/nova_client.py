"""
AWS Bedrock wrapper for Amazon Nova 2 Lite.
Handles violation detection and audit report generation.
Uses exponential backoff for transient errors.
"""

import json
import logging
import time
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

MODEL_ID = "amazon.nova-lite-v1:0"
MAX_RETRIES = 3
BASE_BACKOFF = 1.0  # seconds


def _get_bedrock_client() -> Any:
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    return boto3.Session(region_name=region).client("bedrock-runtime")


def _invoke_with_retry(client: Any, payload: dict[str, Any]) -> str:
    """Invoke Bedrock model with exponential backoff retry."""
    for attempt in range(MAX_RETRIES):
        try:
            response = client.invoke_model(
                modelId=MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(payload),
            )
            body = json.loads(response["body"].read())
            # Nova Lite response format: output.message.content[0].text
            return body["output"]["message"]["content"][0]["text"]
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code in ("ThrottlingException", "ServiceUnavailableException"):
                wait = BASE_BACKOFF * (2**attempt)
                logger.warning(
                    "Bedrock throttled (attempt %d/%d). Retrying in %.1fs...",
                    attempt + 1,
                    MAX_RETRIES,
                    wait,
                )
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"Bedrock call failed after {MAX_RETRIES} attempts")


VIOLATION_DETECTION_PROMPT = """You are a SOC2/HIPAA/GDPR compliance auditor analyzing enterprise user access data.

## Tool Being Audited
Tool: {tool_name}

## HR Source of Truth (Authoritative Employee Records)
{hr_employees}

## Role Policy Rules
{role_policies}

## Users Currently in the Tool (extracted by browser automation)
{extracted_users}

## Today's Date
{today}

## Your Task
Analyze the extracted users against the HR source of truth and role policies.
Identify ALL compliance violations from these categories:

1. **ACCESS_VIOLATION** (CRITICAL, SOC2 CC6.2): A user appears in the tool but is marked TERMINATED in HR records and still has active access.
2. **INACTIVE_ADMIN** (HIGH, SOC2 CC6.1): An admin/elevated-privilege account has not logged in for more than {inactive_threshold} days.
3. **SHARED_ACCOUNT** (HIGH, SOC2 CC6.3): An account username matches shared account patterns (shared, team, generic, group, finance_, hr_, it_, etc.) and has admin/elevated privileges.
4. **PERMISSION_CREEP** (MEDIUM, SOC2 CC6.3): A user's role is in the "never_admin_roles" list (Intern, Contractor, Marketing Manager, Sales Representative, Finance Manager) but they have admin/elevated access.

## Response Format
Respond ONLY with valid JSON. No explanation, no markdown. Example:

{{
  "violations": [
    {{
      "username": "mwilson",
      "full_name": "Mary Wilson",
      "department": "IT",
      "role": "System Administrator",
      "violation_type": "ACCESS_VIOLATION",
      "severity": "CRITICAL",
      "severity_score": 95,
      "soc2_control": "CC6.2",
      "evidence": "Mary Wilson (mwilson) is marked as TERMINATED in HR records but has active System Administrator access in the hr-portal tool."
    }}
  ]
}}

If no violations are found, return: {{"violations": []}}
"""


def detect_violations(
    extracted_users: list[dict[str, Any]],
    hr_employees: list[dict[str, str]],
    role_policies: dict[str, Any],
    tool_name: str,
    today: str,
) -> list[dict[str, Any]]:
    """
    Send extracted user data to Nova 2 Lite for violation detection.
    Returns a list of violation dicts.
    """
    client = _get_bedrock_client()

    prompt = VIOLATION_DETECTION_PROMPT.format(
        tool_name=tool_name,
        hr_employees=json.dumps(hr_employees, indent=2),
        role_policies=json.dumps(role_policies, indent=2),
        extracted_users=json.dumps(extracted_users, indent=2),
        today=today,
        inactive_threshold=role_policies.get("inactive_threshold_days", 90),
    )

    payload = {
        "messages": [
            {
                "role": "user",
                "content": [{"text": prompt}],
            }
        ],
        "inferenceConfig": {
            "maxTokens": 2048,
            "temperature": 0.0,
        },
    }

    logger.info("Calling Nova 2 Lite for violation detection on tool: %s", tool_name)
    raw_response = _invoke_with_retry(client, payload)

    # Strip markdown fences if present
    text = raw_response.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        data = json.loads(text)
        violations = data.get("violations", [])
        logger.info(
            "Nova 2 Lite detected %d violations for %s", len(violations), tool_name
        )
        return violations
    except json.JSONDecodeError as exc:
        logger.error(
            "Failed to parse Nova 2 Lite response for %s: %s\nRaw: %s",
            tool_name,
            exc,
            raw_response,
        )
        return []


AUDIT_REPORT_PROMPT = """You are a compliance report generator for SOC2 auditors.

## Audit Data
{audit_data}

## Task
Generate a professional compliance audit report in plain text format.
Include:
1. Executive Summary
2. Scan Results Overview
3. Violations Found (by severity)
4. Remediations Executed
5. Current Compliance Score
6. Recommendations

Use clear section headers with === underlines. Keep the report professional and concise.
"""


def generate_audit_report(audit_data: dict[str, Any]) -> str:
    """
    Generate a text audit report from audit data via Nova 2 Lite.
    Returns the report as a string.
    """
    client = _get_bedrock_client()

    prompt = AUDIT_REPORT_PROMPT.format(
        audit_data=json.dumps(audit_data, indent=2)
    )

    payload = {
        "messages": [
            {
                "role": "user",
                "content": [{"text": prompt}],
            }
        ],
        "inferenceConfig": {
            "maxTokens": 4096,
            "temperature": 0.1,
        },
    }

    logger.info("Generating audit report via Nova 2 Lite")
    return _invoke_with_retry(client, payload)
