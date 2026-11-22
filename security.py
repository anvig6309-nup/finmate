"""Security helpers: secret key, password rules, rate limiting, audit log and safe response headers."""
import os
import secrets
import time

from flask import request

from db import get_db

LEGAL_VERSION = "2026-11-14"        # bump this when the Privacy Policy / Terms change

# Rate limits: (maximum attempts, window in seconds)
LOGIN_PER_EMAIL = (5, 15 * 60)
LOGIN_PER_IP = (20, 15 * 60)
SIGNUP_PER_IP = (10, 60 * 60)
FORGOT_PER_EMAIL = (3, 60 * 60)        # reset emails per address per hour
FORGOT_PER_IP = (10, 60 * 60)
RESEND_PER_USER = (3, 60 * 60)         # verification emails per account per hour
TOKEN_TRIES_PER_IP = (20, 60 * 60)     # tries to use verify / reset links per IP per hour

COMMON_PASSWORDS = {
    "password", "password1", "password123", "passw0rd", "12345678", "123456789", "1234567890", "qwerty123",
    "qwertyuiop", "iloveyou1", "admin123", "welcome1", "welcome123", "letmein1", "abc12345", "11111111",
    "00000000", "football1", "monkey123", "dragon123", "finmate123", "finmate1",
}


# ---------------------------------------------------------------- secret key
def load_secret_key(root_path):
    """Use FINMATE_SECRET if set. Otherwise create a random key once and keep it in secret.key (never committed)."""
    from_env = os.environ.get("FINMATE_SECRET")
    if from_env:
        if len(from_env) < 16:
            raise RuntimeError("FINMATE_SECRET must be at least 16 characters long.")
        return from_env
    path = os.path.join(root_path, "secret.key")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as f:
        f.write(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


# ------------------------------------------------------------ password rules
def password_problem(password, email=""):
    """Return a short message if the password is not acceptable, else None."""
    if len(password) < 8:
        return "Use at least 8 characters for your password."
    if len(password) > 128:
        return "Use at most 128 characters for your password."
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "Use at least one letter and one number in your password."
    if password.lower() in COMMON_PASSWORDS:
        return "That password is too common. Pick something harder to guess."
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in password.lower():
        return "Don't put your email name inside your password."
    return None


# ------------------------------------------------------------- rate limiting
def client_ip():
    return request.remote_addr or "unknown"


def seconds_until_allowed(key, limit):
    """0 if the caller may try again now, otherwise how many seconds they must wait."""
    maximum, window = limit
    now = time.time()
    db = get_db()
    db.execute("DELETE FROM auth_attempts WHERE created_at < ?", (now - 24 * 3600,))       # tidy old rows
    rows = db.execute("SELECT created_at FROM auth_attempts WHERE key = ? AND created_at > ? ORDER BY created_at",
                      (key, now - window)).fetchall()
    if len(rows) < maximum:
        return 0
    return max(1, int(rows[len(rows) - maximum]["created_at"] + window - now) + 1)


def record_attempt(key):
    db = get_db()
    db.execute("INSERT INTO auth_attempts (key, created_at) VALUES (?, ?)", (key, time.time()))
    db.commit()


def clear_attempts(key):
    db = get_db()
    db.execute("DELETE FROM auth_attempts WHERE key = ?", (key,))
    db.commit()


# ----------------------------------------------------------------- audit log
def audit(event, user_id=None):
    """Remember important account events (sign in, failed sign in, password change ...)."""
    db = get_db()
    db.execute("INSERT INTO audit_log (user_id, event, ip, user_agent) VALUES (?, ?, ?, ?)",
               (user_id, event, client_ip(), (request.headers.get("User-Agent") or "")[:200]))
    db.commit()


# ----------------------------------------------------------- response headers
def content_security_policy(path):
    scripts = "'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com"
    if path.endswith("persona.html"):
        scripts += " 'unsafe-eval'"          # the Tailwind CDN script on this page needs it
    return ("default-src 'self'; script-src " + scripts + "; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com data:; img-src 'self' data: blob:; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = content_security_policy(request.path)
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"        # never let the browser keep private data
    return response
