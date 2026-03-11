"""
AcmeCorp Procurement Portal v1.8.2 — SAP SRM / Ariba style legacy procurement system.
Simulates a legacy enterprise procurement system circa 2014 with seeded compliance violations.
"""

import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = "procurement-legacy-secret-2014"


@app.context_processor
def inject_now() -> dict:
    return {"now": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

# Seeded user data with compliance violations baked in
USERS = [
    {
        "id": 1,
        "username": "kpatel",
        "full_name": "Kavya Patel",
        "role": "Finance Manager",
        "department": "Finance",
        "last_login": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
        "status": "Active",
        "approval_rights": True,
        "spending_limit": "$50,000",
        "approval_status": "Approved",
        "contract_expiry": (datetime.now() + timedelta(days=274)).strftime("%Y-%m-%d"),
    },
    {
        "id": 2,
        "username": "finance_shared",
        "full_name": "Finance Team Shared",
        "role": "Finance Administrator",
        "department": "Finance",
        "last_login": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        "status": "Active",  # VIOLATION: Shared finance account with approval rights
        "approval_rights": True,
        "spending_limit": "$500,000",
        "approval_status": "Approved",
        "_note": "SHARED_ACCOUNT — shared finance account with approval rights",
        "contract_expiry": (datetime.now() - timedelta(days=18)).strftime("%Y-%m-%d"),
    },
    {
        "id": 3,
        "username": "proc_admin1",
        "full_name": "Procurement Admin 1",
        "role": "Procurement Manager",
        "department": "Procurement",
        "last_login": (datetime.now() - timedelta(days=95)).strftime("%Y-%m-%d"),
        "status": "Active",  # VIOLATION: Inactive admin 95 days
        "approval_rights": True,
        "spending_limit": "$200,000",
        "approval_status": "Approved",
        "_note": "INACTIVE_ADMIN — last login > 90 days",
        "contract_expiry": (datetime.now() - timedelta(days=42)).strftime("%Y-%m-%d"),
    },
    {
        "id": 4,
        "username": "proc_admin2",
        "full_name": "Procurement Admin 2",
        "role": "Procurement Manager",
        "department": "Procurement",
        "last_login": (datetime.now() - timedelta(days=110)).strftime("%Y-%m-%d"),
        "status": "Active",  # VIOLATION: Inactive admin 110 days
        "approval_rights": True,
        "spending_limit": "$100,000",
        "approval_status": "Approved",
        "_note": "INACTIVE_ADMIN — last login > 90 days",
        "contract_expiry": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
    },
    {
        "id": 5,
        "username": "jsmith",
        "full_name": "John Smith",
        "role": "Engineering Manager",
        "department": "Engineering",
        "last_login": (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d"),
        "status": "Active",
        "approval_rights": False,
        "spending_limit": "$10,000",
        "approval_status": "Pending",
        "contract_expiry": "N/A",
    },
    {
        "id": 6,
        "username": "alopez",
        "full_name": "Ana Lopez",
        "role": "Marketing Manager",
        "department": "Marketing",
        "last_login": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
        "status": "Active",
        "approval_rights": False,
        "spending_limit": "$5,000",
        "approval_status": "Approved",
        "contract_expiry": "N/A",
    },
    {
        "id": 7,
        "username": "rthompson",
        "full_name": "Robert Thompson",
        "role": "Sales Representative",
        "department": "Sales",
        "last_login": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
        "status": "Active",
        "approval_rights": False,
        "spending_limit": "$2,000",
        "approval_status": "Approved",
        "contract_expiry": "N/A",
    },
]

APPROVERS = [u for u in USERS if u["approval_rights"]]


@app.route("/")
def index():
    if "logged_in" not in session:
        return redirect(url_for("login"))
    return redirect(url_for("users"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("username") == "admin" and request.form.get("password") == "admin123":
            session["logged_in"] = True
            session["username"] = "admin"
            return redirect(url_for("users"))
        error = "Login failed. Please check your credentials."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/users")
def users():
    if "logged_in" not in session:
        return redirect(url_for("login"))
    return render_template("users.html", users=USERS, tab="users")


@app.route("/approvers")
def approvers():
    if "logged_in" not in session:
        return redirect(url_for("login"))
    return render_template("users.html", users=APPROVERS, tab="approvers")


@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
def edit_user(user_id):
    if "logged_in" not in session:
        return redirect(url_for("login"))
    user = next((u for u in USERS if u["id"] == user_id), None)
    if not user:
        return "User not found", 404

    message = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "disable":
            user["status"] = "Disabled"
            user["approval_rights"] = False
            message = f"User '{user['username']}' account disabled and approval rights revoked."
        elif action == "revoke_approval":
            user["approval_rights"] = False
            user["spending_limit"] = "$0"
            message = f"Approval rights revoked for '{user['username']}'."
        elif action == "save":
            user["role"] = request.form.get("role", user["role"])
            user["spending_limit"] = request.form.get("spending_limit", user["spending_limit"])
            user["approval_rights"] = request.form.get("approval_rights") == "on"
            message = f"User '{user['username']}' updated successfully."

    return render_template("edit_user.html", user=user, message=message)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5003))
    app.run(host="0.0.0.0", port=port, debug=False)
