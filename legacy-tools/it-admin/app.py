"""
IT Administration Console v2.4 — ServiceNow / BMC Remedy style legacy IT portal.
Simulates a legacy enterprise IT admin system circa 2014 with seeded compliance violations.
"""

import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = "itadmin-legacy-secret-2014"


@app.context_processor
def inject_now() -> dict:
    return {"now": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

# Seeded user data with compliance violations baked in
USERS = [
    {
        "id": 1,
        "username": "admin_jsmith",
        "full_name": "John Smith",
        "role": "Network Administrator",
        "department": "IT",
        "last_login": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        "status": "Active",
        "access_level": "Administrator",
        "email": "jsmith@acmecorp.com",
    },
    {
        "id": 2,
        "username": "it_shared",
        "full_name": "IT Team Shared Account",
        "role": "System Administrator",
        "department": "IT",
        "last_login": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
        "status": "Active",  # VIOLATION: Shared account with admin privileges
        "access_level": "Administrator",
        "email": "it-team@acmecorp.com",
        "_note": "SHARED_ACCOUNT — shared account with admin privileges",
    },
    {
        "id": 3,
        "username": "jlee",
        "full_name": "Jason Lee",
        "role": "Intern",
        "department": "Engineering",
        "last_login": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
        "status": "Active",  # VIOLATION: Intern with admin access
        "access_level": "Administrator",
        "email": "jlee@acmecorp.com",
        "_note": "PERMISSION_CREEP — intern with admin access",
    },
    {
        "id": 4,
        "username": "bchen",
        "full_name": "Brian Chen",
        "role": "DevOps Engineer",
        "department": "Engineering",
        "last_login": (datetime.now() - timedelta(days=4)).strftime("%Y-%m-%d"),
        "status": "Active",
        "access_level": "Administrator",
        "email": "bchen@acmecorp.com",
    },
    {
        "id": 5,
        "username": "lnguyen",
        "full_name": "Lisa Nguyen",
        "role": "Security Engineer",
        "department": "Security",
        "last_login": (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d"),
        "status": "Active",
        "access_level": "Power User",
        "email": "lnguyen@acmecorp.com",
    },
    {
        "id": 6,
        "username": "alopez",
        "full_name": "Ana Lopez",
        "role": "Marketing Manager",
        "department": "Marketing",
        "last_login": (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"),
        "status": "Active",
        "access_level": "Standard User",
        "email": "alopez@acmecorp.com",
    },
    {
        "id": 7,
        "username": "rthompson",
        "full_name": "Robert Thompson",
        "role": "Sales Representative",
        "department": "Sales",
        "last_login": (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d"),
        "status": "Active",
        "access_level": "Standard User",
        "email": "rthompson@acmecorp.com",
    },
    {
        "id": 8,
        "username": "kpatel",
        "full_name": "Kavya Patel",
        "role": "Finance Manager",
        "department": "Finance",
        "last_login": (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d"),
        "status": "Active",
        "access_level": "Standard User",
        "email": "kpatel@acmecorp.com",
    },
]

ACCESS_LEVELS = [
    {"name": "Administrator", "count": len([u for u in USERS if u["access_level"] == "Administrator"])},
    {"name": "Power User", "count": len([u for u in USERS if u["access_level"] == "Power User"])},
    {"name": "Standard User", "count": len([u for u in USERS if u["access_level"] == "Standard User"])},
]


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
        error = "Authentication failed. Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/users")
def users():
    if "logged_in" not in session:
        return redirect(url_for("login"))
    return render_template("users.html", users=USERS, access_levels=ACCESS_LEVELS)


@app.route("/access-levels")
def access_levels():
    if "logged_in" not in session:
        return redirect(url_for("login"))
    return render_template("users.html", users=[u for u in USERS if u["access_level"] == "Administrator"], access_levels=ACCESS_LEVELS)


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
            user["access_level"] = "Disabled"
            message = f"Account '{user['username']}' has been disabled."
        elif action == "revoke_admin":
            user["access_level"] = "Standard User"
            message = f"Administrator privileges revoked for '{user['username']}'."
        elif action == "save":
            user["access_level"] = request.form.get("access_level", user["access_level"])
            user["role"] = request.form.get("role", user["role"])
            message = f"User '{user['username']}' updated successfully."

    return render_template("edit_user.html", user=user, message=message)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    app.run(host="0.0.0.0", port=port, debug=False)
