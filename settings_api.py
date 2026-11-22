"""Settings page endpoints: preferences, delete account, data export, saved-data lists."""
import csv
import io
import json
import re
import zipfile

from flask import Blueprint, Response, g, jsonify, request
from werkzeug.security import check_password_hash

from api import expense_json, goal_json, read_funds, read_profile
from auth import login_required
from db import get_db

bp = Blueprint("settings", __name__, url_prefix="/api")

THEMES = ("system", "light", "dark")
PERIODS = ("monthly", "yearly")
NOTIFICATIONS = ("budgetSummary", "spendingSummary", "budgetAlerts", "goalReminders",
                 "savingReminders", "purchaseReminders", "paymentReminders")
DEFAULTS = {"theme": "system", "currency": "INR", "period": "monthly", "bufferPct": "", "savingsTarget": "",
            "carryOver": False, "notifications": {}}


def blank_or_number(value, maximum=None):
    """'' means 'not set'. Otherwise a number from 0 up to maximum. Returns (ok, cleaned)."""
    if value in ("", None):
        return True, ""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return False, None
    if n < 0 or (maximum is not None and n > maximum):
        return False, None
    return True, n


def read_settings(user_id):
    row = get_db().execute("SELECT data FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
    return {**DEFAULTS, **(json.loads(row["data"]) if row else {})}


@bp.get("/settings")
@login_required
def get_settings():
    return jsonify(read_settings(g.user["id"]))


@bp.put("/settings")
@login_required
def save_settings():
    body = request.get_json(silent=True) or {}
    out = dict(DEFAULTS)
    if body.get("theme", "system") not in THEMES:
        return jsonify(error="theme must be system, light or dark"), 400
    out["theme"] = body.get("theme", "system")
    if body.get("period", "monthly") not in PERIODS:
        return jsonify(error="period must be monthly or yearly"), 400
    out["period"] = body.get("period", "monthly")
    currency = str(body.get("currency", "INR")).upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        return jsonify(error="currency must be a 3-letter code such as INR"), 400
    out["currency"] = currency
    ok1, out["bufferPct"] = blank_or_number(body.get("bufferPct"), 100)
    ok2, out["savingsTarget"] = blank_or_number(body.get("savingsTarget"))
    if not (ok1 and ok2):
        return jsonify(error="Buffer must be 0-100 and savings target cannot be negative."), 400
    out["carryOver"] = bool(body.get("carryOver"))
    notes = body.get("notifications") if isinstance(body.get("notifications"), dict) else {}
    out["notifications"] = {k: bool(notes[k]) for k in NOTIFICATIONS if k in notes}

    db = get_db()
    db.execute("""INSERT INTO user_settings (user_id, data) VALUES (?, ?)
                  ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated_at = CURRENT_TIMESTAMP""",
               (g.user["id"], json.dumps(out)))
    db.commit()
    return jsonify(out)


@bp.delete("/account")
@login_required
def delete_account():
    body = request.get_json(silent=True) or {}
    if not check_password_hash(g.user["password_hash"], str(body.get("password", ""))):
        return jsonify(error="Wrong password."), 400
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (g.user["id"],))      # ON DELETE CASCADE removes everything they own
    db.commit()
    return "", 204


def collect_export(user):
    db = get_db()
    return {
        "account": {"name": user["name"], "email": user["email"], "created_at": user["created_at"]},
        "profile": read_profile(user), "funds": read_funds(user["id"]),
        "expenses": [expense_json(r) for r in db.execute("SELECT * FROM expenses WHERE user_id = ? ORDER BY id", (user["id"],))],
        "goals": [goal_json(r) for r in db.execute("SELECT * FROM goals WHERE user_id = ? ORDER BY id", (user["id"],))],
        "settings": read_settings(user["id"]),
    }


def csv_text(rows, columns):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(columns)
    for r in rows:
        w.writerow([r.get(c, "") for c in columns])
    return buf.getvalue()


@bp.get("/export")
@login_required
def export_data():
    data = collect_export(g.user)
    if request.args.get("format") == "csv":
        mem = io.BytesIO()
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("expenses.csv", csv_text(data["expenses"], ["category", "subcategory", "name", "priority", "negotiability", "amount", "period"]))
            z.writestr("goals.csv", csv_text(data["goals"], ["name", "category", "target", "saved", "months", "priority", "startDate", "deadline"]))
            z.writestr("income_sources.csv", csv_text(data["funds"]["additional_income"], ["name", "amount", "frequency", "start_date", "end_date"]))
        return Response(mem.getvalue(), mimetype="application/zip",
                        headers={"Content-Disposition": "attachment; filename=finmate-export.zip"})
    return Response(json.dumps(data, indent=2), mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=finmate-export.json"})


# Saved-data lists that have no feature behind them yet answer with an empty list.
@bp.get("/budgets")
@login_required
def budgets():
    return jsonify([])


@bp.get("/saving-plans")
@login_required
def saving_plans():
    return jsonify([])
