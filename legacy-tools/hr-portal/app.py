"""
AcmeCorp HRMS v3.1 — PeopleSoft HCM style legacy HR portal.
Simulates a legacy enterprise HR system circa 2013 with seeded compliance violations.
"""

import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = "hrms-legacy-secret-2013"


@app.context_processor
def inject_now() -> dict:
    return {"now": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

# Seeded user data with compliance violations baked in
USERS = [
    {
        "id": 1,
        "username": "jsmith",
        "full_name": "John Smith",
        "role": "Engineering Manager",
        "department": "Engineering",
        "last_login": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
        "status": "Active",
        "is_admin": True,
        "last_password_change": (datetime.now() - timedelta(days=28)).strftime("%Y-%m-%d"),
    },
    {
        "id": 2,
        "username": "mwilson",
        "full_name": "Mary Wilson",
        "role": "System Administrator",
        "department": "IT",
        "last_login": (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d"),
        "status": "Active",  # VIOLATION: Terminated employee with active admin access
        "is_admin": True,
        "_note": "TERMINATED in HR records — ACCESS_VIOLATION",
        "last_password_change": (datetime.now() - timedelta(days=312)).strftime("%Y-%m-%d"),
    },
    {
        "id": 3,
        "username": "dpark",
        "full_name": "David Park",
        "role": "IT Administrator",
        "department": "IT",
        "last_login": (datetime.now() - timedelta(days=125)).strftime("%Y-%m-%d"),
        "status": "Active",  # VIOLATION: Admin account inactive 125 days
        "is_admin": True,
        "_note": "INACTIVE_ADMIN — last login > 90 days",
        "last_password_change": (datetime.now() - timedelta(days=140)).strftime("%Y-%m-%d"),
    },
    {
        "id": 4,
        "username": "alopez",
        "full_name": "Ana Lopez",
        "role": "Marketing Manager",
        "department": "Marketing",
        "last_login": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        "status": "Active",
        "is_admin": False,
        "last_password_change": (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d"),
    },
    {
        "id": 5,
        "username": "bchen",
        "full_name": "Brian Chen",
        "role": "DevOps Engineer",
        "department": "Engineering",
        "last_login": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
        "status": "Active",
        "is_admin": True,
        "last_password_change": (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d"),
    },
    {
        "id": 6,
        "username": "lnguyen",
        "full_name": "Lisa Nguyen",
        "role": "Security Engineer",
        "department": "Security",
        "last_login": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
        "status": "Active",
        "is_admin": True,
        "last_password_change": (datetime.now() - timedelta(days=21)).strftime("%Y-%m-%d"),
    },
    {
        "id": 7,
        "username": "rthompson",
        "full_name": "Robert Thompson",
        "role": "Sales Representative",
        "department": "Sales",
        "last_login": (datetime.now() - timedelta(days=4)).strftime("%Y-%m-%d"),
        "status": "Active",
        "is_admin": False,
        "last_password_change": (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d"),
    },
    {
        "id": 8,
        "username": "kpatel",
        "full_name": "Kavya Patel",
        "role": "Finance Manager",
        "department": "Finance",
        "last_login": (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d"),
        "status": "Active",
        "is_admin": False,
        "last_password_change": (datetime.now() - timedelta(days=52)).strftime("%Y-%m-%d"),
    },
]

ADMIN_USERS = [u for u in USERS if u["is_admin"]]


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
        error = "Invalid credentials. Please try again."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/users")
def users():
    if "logged_in" not in session:
        return redirect(url_for("login"))
    return render_template("users.html", users=USERS, page="users")


@app.route("/admin-users")
def admin_users():
    if "logged_in" not in session:
        return redirect(url_for("login"))
    return render_template("users.html", users=ADMIN_USERS, page="admin-users")


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
            message = f"User '{user['username']}' has been disabled successfully."
        elif action == "deactivate":
            user["status"] = "Inactive"
            message = f"User '{user['username']}' has been deactivated successfully."
        elif action == "save":
            user["role"] = request.form.get("role", user["role"])
            user["is_admin"] = request.form.get("is_admin") == "on"
            message = f"User '{user['username']}' updated successfully."

    return render_template("edit_user.html", user=user, message=message)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)
