"""
SQLite database layer for Sentinel compliance monitoring platform.
All queries are parameterized to prevent SQL injection.
No ORM — plain sqlite3 for simplicity and zero dependencies.
"""

import sqlite3
import os
from typing import Any

DB_PATH = os.path.join(os.path.dirname(__file__), "sentinel.db")


def get_connection() -> sqlite3.Connection:
    """Return a sqlite3 connection with row_factory for dict-like access."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create all tables if they do not exist."""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scans (
                scan_id         TEXT PRIMARY KEY,
                status          TEXT NOT NULL,       -- running | completed | failed
                message         TEXT,
                violations_found INTEGER DEFAULT 0,
                started_at      TEXT NOT NULL,
                completed_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS violations (
                violation_id    TEXT PRIMARY KEY,
                scan_id         TEXT NOT NULL,
                tool_name       TEXT NOT NULL,
                username        TEXT NOT NULL,
                full_name       TEXT,
                department      TEXT,
                role            TEXT,
                violation_type  TEXT NOT NULL,       -- ACCESS_VIOLATION | INACTIVE_ADMIN | SHARED_ACCOUNT | PERMISSION_CREEP
                severity        TEXT NOT NULL,       -- CRITICAL | HIGH | MEDIUM
                severity_score  INTEGER NOT NULL,
                evidence        TEXT,
                soc2_control    TEXT,
                screenshot_path TEXT,
                status          TEXT DEFAULT 'open', -- open | resolved | dismissed
                resolved_by     TEXT,
                resolved_at     TEXT,
                dismiss_reason  TEXT,
                detected_at     TEXT NOT NULL,
                FOREIGN KEY (scan_id) REFERENCES scans(scan_id)
            );

            CREATE TABLE IF NOT EXISTS audit_trail (
                entry_id        TEXT PRIMARY KEY,
                event_type      TEXT NOT NULL,       -- scan_started | scan_completed | violation_detected | remediation_approved | violation_dismissed
                violation_id    TEXT,
                scan_id         TEXT,
                actor           TEXT,
                action          TEXT NOT NULL,
                result          TEXT,
                screenshot_path TEXT,
                timestamp       TEXT NOT NULL,
                details         TEXT
            );
        """)
        conn.commit()
    finally:
        conn.close()


def create_scan(scan_id: str, status: str, message: str, started_at: str) -> None:
    """Insert a new scan record."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO scans (scan_id, status, message, started_at) VALUES (?, ?, ?, ?)",
            (scan_id, status, message, started_at),
        )
        conn.commit()
    finally:
        conn.close()


def update_scan(
    scan_id: str,
    status: str,
    message: str,
    violations_found: int = 0,
    completed_at: str | None = None,
) -> None:
    """Update scan status and result."""
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE scans
               SET status = ?, message = ?, violations_found = ?, completed_at = ?
               WHERE scan_id = ?""",
            (status, message, violations_found, completed_at, scan_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_scan(scan_id: str) -> dict[str, Any] | None:
    """Return a single scan record as a dict, or None if not found."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM scans WHERE scan_id = ?", (scan_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_latest_scan() -> dict[str, Any] | None:
    """Return the most recently started scan."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM scans ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def insert_violations(violations: list[dict[str, Any]]) -> None:
    """Bulk insert violation records."""
    if not violations:
        return
    conn = get_connection()
    try:
        conn.executemany(
            """INSERT OR REPLACE INTO violations
               (violation_id, scan_id, tool_name, username, full_name, department, role,
                violation_type, severity, severity_score, evidence, soc2_control,
                screenshot_path, status, detected_at)
               VALUES
               (:violation_id, :scan_id, :tool_name, :username, :full_name, :department, :role,
                :violation_type, :severity, :severity_score, :evidence, :soc2_control,
                :screenshot_path, :status, :detected_at)""",
            violations,
        )
        conn.commit()
    finally:
        conn.close()


def get_violations(filters: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Query violations with optional filters. Returns list of dicts."""
    conn = get_connection()
    try:
        query = "SELECT * FROM violations WHERE 1=1"
        params: list[str] = []
        if filters:
            if filters.get("severity"):
                query += " AND severity = ?"
                params.append(filters["severity"])
            if filters.get("tool"):
                query += " AND tool_name = ?"
                params.append(filters["tool"])
            if filters.get("status"):
                query += " AND status = ?"
                params.append(filters["status"])
        query += " ORDER BY severity_score DESC, detected_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_violation(violation_id: str) -> dict[str, Any] | None:
    """Return a single violation by ID."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM violations WHERE violation_id = ?", (violation_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_violation_status(
    violation_id: str,
    status: str,
    resolved_by: str | None = None,
    resolved_at: str | None = None,
    dismiss_reason: str | None = None,
) -> None:
    """Update violation status (resolved or dismissed)."""
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE violations
               SET status = ?, resolved_by = ?, resolved_at = ?, dismiss_reason = ?
               WHERE violation_id = ?""",
            (status, resolved_by, resolved_at, dismiss_reason, violation_id),
        )
        conn.commit()
    finally:
        conn.close()


def insert_audit_entry(entry: dict[str, Any]) -> None:
    """Insert a single audit trail event."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO audit_trail
               (entry_id, event_type, violation_id, scan_id, actor, action, result,
                screenshot_path, timestamp, details)
               VALUES
               (:entry_id, :event_type, :violation_id, :scan_id, :actor, :action, :result,
                :screenshot_path, :timestamp, :details)""",
            entry,
        )
        conn.commit()
    finally:
        conn.close()


def get_audit_trail() -> list[dict[str, Any]]:
    """Return full audit history, newest first."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM audit_trail ORDER BY timestamp DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_open_violations() -> list[dict[str, Any]]:
    """Return all open violations for compliance score calculation."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM violations WHERE status = 'open'"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
