"""Dashboard endpoints. Computation lives in finance.py; this file only loads data and returns JSON."""
import datetime as dt
import json
import os
import ssl
import urllib.error
import urllib.request

from flask import Blueprint, current_app, g, jsonify, request

import finance
from api import expense_json, goal_json, read_funds
from auth import login_required
from db import get_db

bp = Blueprint("dashboard", __name__, url_prefix="/api")


def load_user_data(user_id):
    db = get_db()
    expenses = [expense_json(r) for r in db.execute("SELECT * FROM expenses WHERE user_id = ? ORDER BY id", (user_id,))]
    goals = [goal_json(r) for r in db.execute("SELECT * FROM goals WHERE user_id = ? ORDER BY id", (user_id,))]
    row = db.execute("SELECT * FROM budget_settings WHERE user_id = ?", (user_id,)).fetchone()
    settings = {"period": row["period"], "protected_amount": row["protected_amount"], "items": json.loads(row["items"])} if row else None
    return read_funds(user_id), expenses, goals, settings


@bp.get("/dashboard/summary")
@login_required
def summary():
    period = "yearly" if request.args.get("period") == "yearly" else "monthly"
    funds, expenses, goals, settings = load_user_data(g.user["id"])
    return jsonify(finance.build_summary(funds, expenses, goals, settings, period))


@bp.get("/insights")
@login_required
def insights():
    funds, expenses, goals, settings = load_user_data(g.user["id"])
    return jsonify(finance.build_insights(finance.build_summary(funds, expenses, goals, settings, "monthly"), goals))


# Sections that are not built yet answer with an empty list so the page shows its "nothing here yet" state.
@bp.get("/purchase-plans")
@login_required
def purchase_plans():
    return jsonify([])


@bp.get("/scenarios")
@login_required
def scenarios():
    return jsonify([])


@bp.get("/activity")
@login_required
def activity():
    return jsonify([])


# Pocket CA: Gemini-powered personal financial assistant ("Pocket CA")
@bp.get("/pocket-ca/conversations")
@login_required
def pocket_conversations():
    db = get_db()
    rows = db.execute(
        "SELECT id, title, created_at FROM pocket_ca_chats WHERE user_id = ? ORDER BY updated_at DESC",
        (g.user["id"],)
    ).fetchall()
    return jsonify([{"id": r["id"], "title": r["title"], "created_at": r["created_at"]} for r in rows])


@bp.get("/pocket-ca/conversations/<int:cid>/messages")
@login_required
def pocket_messages(cid):
    db = get_db()
    row = db.execute(
        "SELECT messages FROM pocket_ca_chats WHERE id = ? AND user_id = ?",
        (cid, g.user["id"])
    ).fetchone()
    if not row:
        return jsonify(error="Conversation not found"), 404
    return jsonify(json.loads(row["messages"]))


@bp.delete("/pocket-ca/conversations/<int:cid>")
@login_required
def pocket_delete_conv(cid):
    db = get_db()
    db.execute("DELETE FROM pocket_ca_chats WHERE id = ? AND user_id = ?", (cid, g.user["id"]))
    db.commit()
    return "", 204


@bp.delete("/pocket-ca/conversations")
@login_required
def pocket_clear():
    db = get_db()
    db.execute("DELETE FROM pocket_ca_chats WHERE user_id = ?", (g.user["id"],))
    db.commit()
    return "", 204


@bp.post("/pocket-ca/chat")
@login_required
def pocket_chat():
    body = request.get_json(silent=True) or {}
    user_msg = str(body.get("message", "")).strip()
    cid = body.get("conversation_id")
    if not user_msg:
        return jsonify(error="Message cannot be empty"), 400

    gemini_key = "" if current_app.config.get("TESTING") else os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_key and not current_app.config.get("TESTING"):
        env_path = os.path.join(current_app.root_path, ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("GEMINI_API_KEY="):
                            gemini_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                            os.environ["GEMINI_API_KEY"] = gemini_key
                            break
            except Exception:
                pass

    if not gemini_key:
        return jsonify(
            error="Pocket CA’s AI service isn’t configured. Please add your GEMINI_API_KEY in your .env file.",
            code="AI_NOT_CONFIGURED"
        ), 503

    # Load live user financial context
    funds, expenses, goals, settings = load_user_data(g.user["id"])
    summary_data = finance.build_summary(funds, expenses, goals, settings, "monthly")

    income = float(summary_data.get("income") or 0)
    expense_total = float(summary_data.get("expenses") or 0)
    unallocated = float(summary_data.get("unallocated") or 0)
    goals_summary = (
        ", ".join([f"{g['name']} (target ₹{(g.get('target') or 0):,.0f}, saved ₹{(g.get('saved') or 0):,.0f})" for g in goals])
        if goals else "No active financial goals yet"
    )
    top_expenses = (
        ", ".join([f"{e['category']}: ₹{(e.get('amount') or 0):,.0f}" for e in expenses[:4]])
        if expenses else "No recurring expenses logged"
    )

    system_context = f"""You are FinMate's Pocket CA (Chartered Accountant & Behavioral Financial Advisor).
You are talking to {g.user['name']}. Give personalized, practical, empathetic financial advice based on their real data:
- Monthly Income: ₹{income:,.2f}
- Monthly Expenses: ₹{expense_total:,.2f}
- Monthly Savings Buffer / Unallocated: ₹{unallocated:,.2f}
- Top Expense Categories: {top_expenses}
- Goals: {goals_summary}

Rules:
1. Always maintain a warm, professional, encouraging Chartered Accountant tone.
2. Keep answers concise, actionable, and structured with bullet points.
3. Incorporate behavioral economics principles (50/30/20 mental accounting, loss aversion, runway protection).
4. Do NOT make speculative stock picks or guarantee tax exemptions without local verification."""

    prompt = f"{system_context}\n\nUser Question: {user_msg}"

    # Query Google Gemini API (gemini-3.5-flash-lite / gemini-3.5-flash / gemini-3.8-flash)
    reply_text = None
    models = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash"]
    for model in models:
        try:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}",
                data=json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}]}).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            ctx = ssl.create_default_context()
            try:
                with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
                    g_data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.URLError as ue:
                if "CERTIFICATE_VERIFY_FAILED" in str(ue):
                    with urllib.request.urlopen(req, timeout=15, context=ssl._create_unverified_context()) as resp:
                        g_data = json.loads(resp.read().decode("utf-8"))
                else:
                    raise ue

            candidates = g_data.get("candidates", [])
            if candidates and "content" in candidates[0] and "parts" in candidates[0]["content"]:
                reply_text = candidates[0]["content"]["parts"][0].get("text", "")
                if reply_text:
                    break
        except Exception as exc:
            print(f"[Pocket CA] Gemini {model} attempt: {exc}", flush=True)
            continue

    if not reply_text:
        return jsonify(error="Could not get a response from Gemini AI. Please check your GEMINI_API_KEY and internet connection."), 502

    # Save conversation to SQLite
    db = get_db()
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    conv_title = (user_msg[:30] + ("..." if len(user_msg) > 30 else "")).capitalize()

    conv_row = None
    if cid:
        try:
            conv_row = db.execute("SELECT * FROM pocket_ca_chats WHERE id = ? AND user_id = ?", (int(cid), g.user["id"])).fetchone()
        except (ValueError, TypeError):
            conv_row = None

    if conv_row:
        msgs = json.loads(conv_row["messages"])
        msgs.append({"role": "user", "content": user_msg})
        msgs.append({"role": "assistant", "content": reply_text})
        db.execute("UPDATE pocket_ca_chats SET messages = ?, updated_at = ? WHERE id = ?", (json.dumps(msgs), now_iso, conv_row["id"]))
        db.commit()
        active_id = conv_row["id"]
    else:
        msgs = [
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": reply_text}
        ]
        cur = db.execute(
            """INSERT INTO pocket_ca_chats (user_id, title, messages, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (g.user["id"], conv_title, json.dumps(msgs), now_iso, now_iso)
        )
        db.commit()
        active_id = cur.lastrowid

    return jsonify(
        message={"role": "assistant", "content": reply_text},
        conversation={"id": active_id, "title": conv_title}
    )
