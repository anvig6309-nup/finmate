"""Data endpoints: profile, expenses, goals. Every query is filtered by the logged-in user's id."""
import json

from flask import Blueprint, g, jsonify, request
from werkzeug.security import check_password_hash

import account_email
from auth import EMAIL_RE, login_required
from db import get_db
import finance

bp = Blueprint("api", __name__, url_prefix="/api")
PRIORITIES = {"High", "Medium", "Low"}


def num(value, default=None):
    """Convert to a non-negative float, or return default."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return n if n >= 0 else default


# ---------------------------------------------------------------- profile
def read_profile(user):
    row = get_db().execute("SELECT persona, data FROM profiles WHERE user_id = ?", (user["id"],)).fetchone()
    data = json.loads(row["data"]) if row else {}
    return {"name": user["name"], "email": user["email"], **data}


@bp.get("/profile")
@login_required
def get_profile():
    return jsonify(read_profile(g.user))


@bp.route("/profile", methods=["PUT", "PATCH"])
@login_required
def save_profile():
    body = request.get_json(silent=True) or {}
    db = get_db()

    # Account fields live in the users table
    if "name" in body or "full_name" in body:
        name = str(body.get("full_name") or body.get("name") or "").strip()
        if not name:
            return jsonify(error="Name cannot be empty."), 400
        db.execute("UPDATE users SET name = ? WHERE id = ?", (name, g.user["id"]))
    if "email" in body:
        email = str(body["email"]).strip().lower()
        if not EMAIL_RE.match(email):
            return jsonify(error="Enter a valid email."), 400
        if email != g.user["email"]:
            # Changing the email is a sensitive action: ask for the password, then verify the new address again
            if not check_password_hash(g.user["password_hash"], str(body.get("current_password", ""))):
                return jsonify(error="Your current password is wrong."), 403
            taken = db.execute("SELECT 1 FROM users WHERE email = ? AND id != ?", (email, g.user["id"])).fetchone()
            if taken:
                return jsonify(error="That email is already used by another account."), 409
            db.execute("UPDATE users SET email = ?, email_verified_at = NULL WHERE id = ?", (email, g.user["id"]))
            db.commit()
            account_email.send_verification(g.user["id"], g.user["name"], email)

    # Everything else (persona, income, totals, ...) is the financial profile, merged into the saved JSON
    extra = {k: v for k, v in body.items() if k not in ("name", "full_name", "email", "password", "current_password")}
    if extra:
        row = db.execute("SELECT data FROM profiles WHERE user_id = ?", (g.user["id"],)).fetchone()
        merged = {**(json.loads(row["data"]) if row else {}), **extra}
        db.execute(
            """INSERT INTO profiles (user_id, persona, data) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET persona = excluded.persona, data = excluded.data,
               updated_at = CURRENT_TIMESTAMP""",
            (g.user["id"], merged.get("persona"), json.dumps(merged)),
        )
    db.commit()
    user = db.execute("SELECT * FROM users WHERE id = ?", (g.user["id"],)).fetchone()
    return jsonify(read_profile(user))


# --------------------------------------------------------------- expenses
def parse_negotiable(e):
    """Accepts negotiable=true/false OR negotiability/type = 'negotiable' / 'non-negotiable'."""
    if e.get("negotiable") is not None:
        return int(bool(e["negotiable"]))
    text = e.get("negotiability") or e.get("type")
    if isinstance(text, str) and text:
        return 0 if text.lower().startswith("non") else 1
    return None


def expense_json(r):
    return {
        "id": r["client_id"], "category": r["category"], "subcategory": r["subcategory"], "name": r["name"],
        "priority": r["priority"], "negotiable": None if r["negotiable"] is None else bool(r["negotiable"]),
        "amount": r["amount"], "period": r["period"], "custom": bool(r["custom"]),
        # extra names read by budget_planner.html
        "expense_name": r["name"], "tentative_amount": r["amount"],
        "negotiability": "" if r["negotiable"] is None else ("negotiable" if r["negotiable"] else "non-negotiable"),
    }


@bp.get("/expenses")
@login_required
def get_expenses():
    rows = get_db().execute("SELECT * FROM expenses WHERE user_id = ? ORDER BY id", (g.user["id"],)).fetchall()
    return jsonify([expense_json(r) for r in rows])


@bp.put("/expenses")
@login_required
def replace_expenses():
    """Save the whole expense list the page is showing (replace-all keeps the frontend simple)."""
    items = request.get_json(silent=True)
    if isinstance(items, dict):
        items = items.get("entries")
    if not isinstance(items, list):
        return jsonify(error="Send a list of expenses."), 400

    clean = []
    for i, e in enumerate(items):
        category = str(e.get("category", "")).strip()
        if not category:
            return jsonify(error=f"Expense #{i + 1} is missing a category."), 400
        negotiable = parse_negotiable(e)
        amount = e.get("amount") if e.get("amount") not in (None, "") else e.get("tentative_amount")
        clean.append((
            g.user["id"], str(e.get("id") or f"e{i + 1}"), category, str(e.get("subcategory") or ""),
            str(e.get("name") or e.get("expense_name") or ""), e.get("priority") if e.get("priority") in PRIORITIES else None,
            negotiable, num(amount), str(e.get("period") or "Monthly"), int(bool(e.get("custom"))),
        ))

    db = get_db()
    db.execute("DELETE FROM expenses WHERE user_id = ?", (g.user["id"],))
    db.executemany(
        """INSERT INTO expenses (user_id, client_id, category, subcategory, name, priority,
                                 negotiable, amount, period, custom) VALUES (?,?,?,?,?,?,?,?,?,?)""", clean)
    db.commit()
    return get_expenses()


# ------------------------------------------------------------------ goals
def goal_json(r):
    return {
        "id": r["client_id"], "name": r["name"], "category": r["category"], "customCategory": r["custom_category"],
        "target": r["target"], "saved": r["saved"], "months": r["months"], "priority": r["priority"],
        "startDate": r["start_date"],
        # extra names read by budget_planner.html
        "target_amount": r["target"], "saved_amount": r["saved"],
        "deadline": finance.add_months(r["start_date"], r["months"]),
    }


@bp.get("/goals")
@login_required
def get_goals():
    rows = get_db().execute("SELECT * FROM goals WHERE user_id = ? ORDER BY id", (g.user["id"],)).fetchall()
    return jsonify([goal_json(r) for r in rows])


@bp.put("/goals")
@login_required
def replace_goals():
    items = request.get_json(silent=True)
    if not isinstance(items, list):
        return jsonify(error="Send a list of goals."), 400

    clean = []
    for i, x in enumerate(items):
        name = str(x.get("name", "")).strip()
        months = int(num(x.get("months"), 0) or 0)
        if not name or months < 1:
            return jsonify(error=f"Goal #{i + 1} needs a name and a duration in months."), 400
        clean.append((
            g.user["id"], str(x.get("id") or f"g{i + 1}"), name, x.get("category"), x.get("customCategory"),
            num(x.get("target")), num(x.get("saved"), 0), months, x.get("priority"), x.get("startDate"),
        ))

    db = get_db()
    db.execute("DELETE FROM goals WHERE user_id = ?", (g.user["id"],))
    db.executemany(
        """INSERT INTO goals (user_id, client_id, name, category, custom_category, target, saved,
                              months, priority, start_date) VALUES (?,?,?,?,?,?,?,?,?,?)""", clean)
    db.commit()
    return get_goals()


# ------------------------------------------------------------------ funds
def read_funds(user_id):
    db = get_db()
    row = db.execute("SELECT persona, data FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    data = json.loads(row["data"]) if row else {}
    rows = db.execute("SELECT * FROM income_sources WHERE user_id = ? ORDER BY id", (user_id,)).fetchall()
    totals = data.get("totals") or {}
    monthly, yearly = data.get("monthly_funds"), data.get("yearly_funds")
    return {
        "persona": row["persona"] if row else None,
        "monthly_funds": monthly, "yearly_funds": yearly,
        "available_monthly_funds": monthly, "available_yearly_funds": yearly,
        "minimum_monthly_funds": data.get("minimum_monthly_funds"),
        "ui_key": data.get("ui_key"), "ui_value": data.get("ui_value"),
        "total_monthly_funds": totals.get("monthly"), "total_yearly_funds": totals.get("yearly"),
        "additional_income": [
            {"id": r["id"], "name": r["name"], "amount": r["amount"], "frequency": r["frequency"],
             "start_date": r["start_date"], "end_date": r["end_date"]} for r in rows
        ],
    }


@bp.get("/funds")
@login_required
def get_funds():
    return jsonify(read_funds(g.user["id"]))


def first(body, *keys):
    for k in keys:
        if body.get(k) not in (None, ""):
            return body[k]
    return None


@bp.put("/funds")
@login_required
def save_funds():
    body = request.get_json(silent=True) or {}
    income = body.get("income") if isinstance(body.get("income"), dict) else {}
    raw_monthly = first(body, "monthly_funds", "monthlyFunds", "monthly")
    raw_yearly = first(body, "yearly_funds", "yearlyFunds", "yearly")
    if raw_monthly is None:
        raw_monthly = income.get("monthly")
    if raw_yearly is None:
        raw_yearly = income.get("yearly")
    monthly = 0.0 if raw_monthly is None else num(raw_monthly)   # num() gives None for negative or invalid values
    yearly = 0.0 if raw_yearly is None else num(raw_yearly)
    if monthly is None or yearly is None:
        return jsonify(error="Monthly and yearly funds cannot be negative."), 400
    persona = finance.norm_persona(body.get("persona"))
    if persona and persona not in finance.PERSONAS:
        return jsonify(error="Unknown persona: " + persona), 400

    sources = []
    for i, s in enumerate(first(body, "sources", "extraSources", "additional_income") or []):
        freq = finance.norm_frequency(s.get("frequency") or s.get("period"))
        amount = num(s.get("amount"))
        if freq is None or amount is None:
            return jsonify(error=f"Income source #{i + 1} has an invalid amount or frequency."), 400
        start, end = first(s, "startDate", "start_date"), first(s, "endDate", "end_date")
        if start and end and end < start:
            return jsonify(error=f"Income source #{i + 1}: end date is before start date."), 400
        sources.append({"name": str(s.get("name") or "Other")[:50], "amount": amount, "frequency": freq, "start": start, "end": end})

    totals = finance.funds_totals(monthly, yearly, sources)
    db = get_db()
    row = db.execute("SELECT data FROM profiles WHERE user_id = ?", (g.user["id"],)).fetchone()
    data = json.loads(row["data"]) if row else {}
    # Keep the page's own saved object so the page can restore itself exactly after a login on any browser
    ui_key = body.get("_ui_key")
    if ui_key in ("finmate_profile", "finmate_business_funds"):
        snapshot = {k: v for k, v in body.items() if k != "_ui_key"}
        if len(json.dumps(snapshot)) < 50000:
            data["ui_key"], data["ui_value"] = ui_key, snapshot
    data.update({
        "persona": persona, "monthly_funds": monthly, "yearly_funds": yearly,
        "minimum_monthly_funds": num(first(body, "minimumFloor", "minimumMonthlyFunds", "minimum_monthly_funds")),
        "totals": {"monthly": totals["monthly"], "yearly": totals["yearly"]},
    })
    db.execute(
        """INSERT INTO profiles (user_id, persona, data) VALUES (?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET persona = excluded.persona, data = excluded.data,
           updated_at = CURRENT_TIMESTAMP""",
        (g.user["id"], persona, json.dumps(data)),
    )
    db.execute("DELETE FROM income_sources WHERE user_id = ?", (g.user["id"],))
    db.executemany(
        "INSERT INTO income_sources (user_id, name, amount, frequency, start_date, end_date) VALUES (?,?,?,?,?,?)",
        [(g.user["id"], s["name"], s["amount"], s["frequency"], s["start"], s["end"]) for s in sources],
    )
    db.commit()
    return jsonify(read_funds(g.user["id"]))


# -------------------------------------------------------- budget settings
@bp.get("/budget/settings")
@login_required
def get_budget_settings():
    row = get_db().execute("SELECT * FROM budget_settings WHERE user_id = ?", (g.user["id"],)).fetchone()
    if row is None:
        return jsonify(error="No saved settings yet"), 404
    return jsonify(period=row["period"], protected_amount=row["protected_amount"], items=json.loads(row["items"]))


@bp.put("/budget/settings")
@login_required
def save_budget_settings():
    body = request.get_json(silent=True) or {}
    period = body.get("period", "monthly")
    protected = num(body.get("protected_amount"), 0)
    items = body.get("items", {})
    if period not in ("monthly", "yearly") or not isinstance(items, dict):
        return jsonify(error="period must be monthly or yearly, and items must be an object."), 400
    db = get_db()
    db.execute(
        """INSERT INTO budget_settings (user_id, period, protected_amount, items) VALUES (?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET period = excluded.period, protected_amount = excluded.protected_amount,
           items = excluded.items, updated_at = CURRENT_TIMESTAMP""",
        (g.user["id"], period, protected, json.dumps(items)),
    )
    db.commit()
    return jsonify(period=period, protected_amount=protected, items=items)


@bp.delete("/budget/settings")
@login_required
def delete_budget_settings():
    db = get_db()
    db.execute("DELETE FROM budget_settings WHERE user_id = ?", (g.user["id"],))
    db.commit()
    return "", 204
