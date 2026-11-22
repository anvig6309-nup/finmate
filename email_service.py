"""Sending email. Three modes, chosen automatically:
   - tests    : messages are collected in app.extensions["outbox"]
   - SMTP     : real email, when FINMATE_SMTP_HOST is set (see .env.example)
   - console  : no SMTP settings, so the email is printed in the terminal (handy for development and demos)"""
import os
import smtplib
import ssl
import threading
from email.message import EmailMessage


def smtp_settings():
    return {
        "host": os.environ.get("FINMATE_SMTP_HOST", "").strip(),
        "port": int(os.environ.get("FINMATE_SMTP_PORT", "587") or 587),
        "user": os.environ.get("FINMATE_SMTP_USER", "").strip(),
        "password": os.environ.get("FINMATE_SMTP_PASSWORD", "").replace(" ", ""),      # Gmail shows app passwords with spaces
        "security": os.environ.get("FINMATE_SMTP_SECURITY", "starttls").strip().lower(),   # starttls | ssl | none
        "sender": os.environ.get("FINMATE_MAIL_FROM", "").strip(),
    }


def build_message(to, subject, body, sender):
    msg = EmailMessage()
    msg["To"], msg["Subject"], msg["From"] = to, subject, sender
    msg.set_content(body)
    return msg


def send_via_smtp(msg, cfg):
    """Blocking send. Raises on failure."""
    if cfg["security"] == "ssl":
        server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=15, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=15)
    with server:
        if cfg["security"] == "starttls":
            server.starttls(context=ssl.create_default_context())
        if cfg["user"]:
            server.login(cfg["user"], cfg["password"])
        server.send_message(msg)


def _send_in_background(msg, cfg):
    try:
        send_via_smtp(msg, cfg)
    except Exception as exc:                      # never crash the app because mail failed
        print(f"[FinMate] Could not send email to {msg['To']}: {exc}", flush=True)


def deliver(app, to, subject, body):
    """Send one email. Returns which mode was used."""
    if app.config.get("TESTING"):
        app.extensions.setdefault("outbox", []).append({"to": to, "subject": subject, "body": body})
        return "test"
    cfg = smtp_settings()
    if not cfg["host"]:
        print("\n" + "=" * 20 + " EMAIL (console mode: add SMTP settings to .env to send real email) " + "=" * 20, flush=True)
        print(f"To: {to}\nSubject: {subject}\n\n{body}", flush=True)
        print("=" * 110 + "\n", flush=True)
        return "console"
    msg = build_message(to, subject, body, cfg["sender"] or cfg["user"] or "FinMate <no-reply@localhost>")
    # A background thread keeps the page fast and makes "unknown email" and "known email" take the same time
    threading.Thread(target=_send_in_background, args=(msg, cfg), daemon=True).start()
    return "smtp"
