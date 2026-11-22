"""One-time email links: create, send and use verification and password-reset tokens.
Only a SHA-256 hash of each token is stored, so a leaked database cannot be used to reset anyone's password."""
import hashlib
import secrets
import time

from flask import current_app

import email_service
from db import get_db

LIFETIME_MINUTES = {"verify": 24 * 60, "reset": 30, "login": 15}


def _hash(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_token(user_id, purpose):
    """Make a new token and cancel any older unused ones for the same purpose."""
    raw = secrets.token_urlsafe(32)
    db = get_db()
    db.execute("UPDATE email_tokens SET used_at = ? WHERE user_id = ? AND purpose = ? AND used_at IS NULL",
               (time.time(), user_id, purpose))
    db.execute("INSERT INTO email_tokens (user_id, purpose, token_hash, expires_at) VALUES (?, ?, ?, ?)",
               (user_id, purpose, _hash(raw), time.time() + LIFETIME_MINUTES[purpose] * 60))
    db.commit()
    return raw


def find_token(raw, purpose):
    """Return the token row if it is real, unused and not expired, otherwise None."""
    if not raw or len(raw) > 200:
        return None
    row = get_db().execute("SELECT * FROM email_tokens WHERE token_hash = ? AND purpose = ?", (_hash(raw), purpose)).fetchone()
    if row is None or row["used_at"] is not None or row["expires_at"] < time.time():
        return None
    return row


def use_token(row):
    """Mark a token as used. False if someone else used it a moment earlier."""
    db = get_db()
    cur = db.execute("UPDATE email_tokens SET used_at = ? WHERE id = ? AND used_at IS NULL", (time.time(), row["id"]))
    if row["purpose"] == "login":
        # Invalidate any companion tokens/codes for this user
        db.execute("UPDATE email_tokens SET used_at = ? WHERE user_id = ? AND purpose = 'login' AND used_at IS NULL",
                   (time.time(), row["user_id"]))
    db.commit()
    return cur.rowcount == 1


def create_magic_login_tokens(user_id):
    """Make both a one-click URL token and a 6-digit numeric OTP code."""
    raw = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(900000) + 100000}"
    db = get_db()
    db.execute("UPDATE email_tokens SET used_at = ? WHERE user_id = ? AND purpose = ? AND used_at IS NULL",
               (time.time(), user_id, "login"))
    expires = time.time() + LIFETIME_MINUTES["login"] * 60
    db.execute("INSERT INTO email_tokens (user_id, purpose, token_hash, expires_at) VALUES (?, ?, ?, ?)",
               (user_id, "login", _hash(raw), expires))
    db.execute("INSERT INTO email_tokens (user_id, purpose, token_hash, expires_at) VALUES (?, ?, ?, ?)",
               (user_id, "login", _hash(code), expires))
    db.commit()
    return raw, code


def _link(page, raw, fragment_key="token"):
    # The token goes after '#', so it is never sent to the server in the URL or leaked through a Referer header
    return f"{current_app.config['BASE_URL'].rstrip('/')}/{page}#{fragment_key}={raw}"


def send_verification(user_id, name, email):
    raw = create_token(user_id, "verify")
    body = (f"Hi {name},\n\nPlease confirm your email address for FinMate by opening this link:\n\n{_link('verify.html', raw)}\n\n"
            "The link works for 24 hours. If you did not create a FinMate account, you can ignore this email.\n\n- FinMate")
    return email_service.deliver(current_app._get_current_object(), email, "Confirm your FinMate email", body)


def send_reset(user_id, name, email):
    raw = create_token(user_id, "reset")
    body = (f"Hi {name},\n\nWe received a request to reset your FinMate password. Open this link to choose a new one:\n\n{_link('reset.html', raw)}\n\n"
            "The link works for 30 minutes and can be used once. If you did not ask for this, ignore this email: "
            "your password will not change.\n\n- FinMate")
    return email_service.deliver(current_app._get_current_object(), email, "Reset your FinMate password", body)


def send_magic_login(user_id, name, email):
    raw, code = create_magic_login_tokens(user_id)
    direct_link = _link('login.html', raw, 'magicToken')
    body = (f"Hi {name},\n\n"
            f"Your 6-digit FinMate sign-in code is: {code}\n\n"
            f"Or click this direct sign-in link:\n\n{direct_link}\n\n"
            "This code and link work for 15 minutes and can only be used once.\n"
            "If you did not request this link, you can safely ignore this email.\n\n- FinMate")
    mode = email_service.deliver(current_app._get_current_object(), email, f"Your FinMate Sign-In Code: {code}", body)
    return {"mode": mode, "code": code, "token": raw, "link": direct_link}
