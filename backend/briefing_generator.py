"""
Generates concise spoken-style briefing text from scan results via Nova 2 Lite.
Results are cached per scan_id (5-minute TTL) to avoid duplicate LLM calls
when both /briefing-text and /briefing-audio are fetched in parallel.
"""

import json
import logging
import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

import database

logger = logging.getLogger(__name__)

MODEL_ID = "amazon.nova-lite-v1:0"
MAX_RETRIES = 3
BASE_BACKOFF = 1.0
_CACHE_TTL = 300  # seconds

# In-memory cache: scan_id -> (text, timestamp)
_cache: dict[str, tuple[str, float]] = {}

BRIEFING_PROMPT = """\
You are Sentinel, an autonomous compliance monitoring assistant.
Generate a natural spoken briefing (no bullet points, no markdown, no symbols) \
summarizing the scan results below. Maximum 3 sentences — approximately 15 seconds \
when spoken aloud.

Always include: total violation count, critical count, and the single most urgent \
finding with the username and tool name. Write as if speaking directly to the \
security team. Be direct and professional.

Scan data:
{scan_data}

Respond with ONLY the spoken text. No preamble, no labels."""


def _invoke(prompt: str) -> str:
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    client = boto3.Session(region_name=region).client("bedrock-runtime")
    payload = {
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": 256, "temperature": 0.3},
    }
    for attempt in range(MAX_RETRIES):
        try:
            response = client.invoke_model(
                modelId=MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(payload),
            )
            body = json.loads(response["body"].read())
            return body["output"]["message"]["content"][0]["text"].strip()
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("ThrottlingException", "ServiceUnavailableException") and attempt < MAX_RETRIES - 1:
                time.sleep(BASE_BACKOFF * (2 ** attempt))
            else:
                raise
    raise RuntimeError("Briefing LLM call failed after retries")


def generate_briefing_text(scan_id: str) -> str:
    """
    Generate a spoken briefing for a completed scan.
    Cached per scan_id for 5 minutes — safe to call from parallel endpoints.
    Falls back to a template string if the LLM call fails.
    """
    # Check cache first (solves the double-call problem)
    cached = _cache.get(scan_id)
    if cached and time.time() - cached[1] < _CACHE_TTL:
        logger.debug("Briefing cache hit for scan %s", scan_id)
        return cached[0]

    # Pull violation data for this scan
    try:
        all_violations: list[dict[str, Any]] = database.get_violations()
        violations = [v for v in all_violations if v.get("scan_id") == scan_id]
    except Exception as exc:
        logger.error("DB query failed in briefing generator: %s", exc)
        violations = []

    by_severity: dict[str, int] = {}
    for v in violations:
        sev = v.get("severity", "UNKNOWN")
        by_severity[sev] = by_severity.get(sev, 0) + 1

    # Most critical open violation
    top: dict[str, Any] | None = None
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        candidates = [v for v in violations if v.get("severity") == sev and v.get("status") == "open"]
        if candidates:
            top = candidates[0]
            break

    scan_data = {
        "total_violations": len(violations),
        "open_violations": sum(1 for v in violations if v.get("status") == "open"),
        "by_severity": by_severity,
        "tools_scanned": 3,
        "top_violation": {
            "username": top["username"],
            "violation_type": top["violation_type"].replace("_", " ").title(),
            "tool": top["tool_name"],
            "severity": top["severity"],
            "evidence": top.get("evidence", ""),
        } if top else None,
    }

    try:
        text = _invoke(BRIEFING_PROMPT.format(scan_data=json.dumps(scan_data, indent=2)))
    except Exception as exc:
        logger.error("Briefing LLM call failed, using template fallback: %s", exc)
        critical = by_severity.get("CRITICAL", 0)
        total = len(violations)
        text = (
            f"Scan complete. I found {total} violation{'s' if total != 1 else ''} "
            f"across all three tools"
            + (f", including {critical} critical issue{'s' if critical != 1 else ''}" if critical else "")
            + "."
            + (
                f" The most urgent: {top['username']} on {top['tool_name']} "
                f"has a {top['violation_type'].replace('_', ' ').lower()} violation."
                if top else " No critical issues detected."
            )
        )

    _cache[scan_id] = (text, time.time())
    logger.info("Briefing generated for scan %s: %s", scan_id, text[:80])
    return text
