"""Authentication: sign up, log in, log out, and the @login_required guard."""
import datetime as dt
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid
from functools import wraps

import jwt
from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

import account_email
import security
from db import get_db

bp = Blueprint("auth", __name__, url_prefix="/api/auth")
EMAIL_RE = re.compile(r"^\S+@\S+\.\S+$")
TOKEN_HOURS = int(os.environ.get("FINMATE_TOKEN_HOURS", "24"))      # how long one sign-in stays valid
DUMMY_HASH = generate_password_hash("not-a-real-password")           # used so unknown emails take as long as real ones


def device_label(user_agent):
    ua = user_agent or ""
    browser = ("Edge" if "Edg/" in ua else "Firefox" if "Firefox/" in ua else "Chrome" if "Chrome/" in ua
               else "Safari" if "Safari/" in ua else "Browser")
    system = next((name for key, name in (("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iPhone"),
                                          ("iPad", "iPad"), ("Mac OS", "Mac"), ("Linux", "Linux")) if key in ua), "")
    return f"{browser} on {system}" if system else browser


def new_session(user_id):
    """Record this sign-in so it can be listed and signed out later."""
    sid = uuid.uuid4().hex
    db = get_db()
    db.execute("INSERT INTO sessions (id, user_id, device) VALUES (?, ?, ?)",
               (sid, user_id, device_label(request.headers.get("User-Agent"))))
    db.commit()
    return sid


def make_token(user_id, sid=None):
    payload = {
        "sub": str(user_id),
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=TOKEN_HOURS),
    }
    if sid:
        payload["sid"] = sid
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def login_required(view):
    """Reject the request with 401 unless it carries a valid 'Authorization: Bearer <token>'."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify(error="Not signed in"), 401
        try:
            data = jwt.decode(header[7:], current_app.config["SECRET_KEY"], algorithms=["HS256"])
        except jwt.PyJWTError:
            return jsonify(error="Session expired. Please sign in again."), 401
        user = get_db().execute("SELECT * FROM users WHERE id = ?", (data["sub"],)).fetchone()
        if user is None:
            return jsonify(error="Account not found"), 401
        sid = data.get("sid")       # tokens made before sessions existed have no sid and stay valid until they expire
        if sid and not get_db().execute("SELECT 1 FROM sessions WHERE id = ? AND user_id = ?", (sid, user["id"])).fetchone():
            return jsonify(error="This session was signed out. Please sign in again."), 401
        g.user, g.sid = user, sid
        return view(*args, **kwargs)
    return wrapper


def has_profile(user_id):
    row = get_db().execute("SELECT data FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    return bool(row and json.loads(row["data"]).get("totals"))


@bp.post("/signup")
def signup():
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", ""))

    ip_key = f"signup-ip:{security.client_ip()}"
    wait = security.seconds_until_allowed(ip_key, security.SIGNUP_PER_IP)
    if wait:
        return too_many(wait)
    security.record_attempt(ip_key)

    if not name or len(name) > 80:
        return jsonify(error="Enter your full name (up to 80 characters)."), 400
    if not EMAIL_RE.match(email) or len(email) > 254:
        return jsonify(error="Enter a valid email, like name@example.com."), 400
    problem = security.password_problem(password, email)
    if problem:
        return jsonify(error=problem), 400
    if body.get("accepted_terms") is not True:
        return jsonify(error="Please accept the Terms and Privacy Policy to create an account."), 400

    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        return jsonify(error="An account with this email already exists. Sign in instead."), 409

    cur = db.execute(
        "INSERT INTO users (name, email, password_hash, terms_accepted_at, terms_version) VALUES (?, ?, ?, ?, ?)",
        (name, email, generate_password_hash(password), dt.datetime.now(dt.timezone.utc).isoformat(), security.LEGAL_VERSION),
    )
    db.commit()
    security.audit("signup", cur.lastrowid)
    try:
        account_email.send_verification(cur.lastrowid, name, email)
    except Exception as exc:                  # a mail problem must never stop someone from signing up
        print(f"[FinMate] verification email failed: {exc}", flush=True)
    return jsonify(token=make_token(cur.lastrowid, new_session(cur.lastrowid)), user={"name": name, "email": email},
                   has_profile=False, email_verified=False), 201


def too_many(seconds):
    minutes = max(1, round(seconds / 60))
    resp = jsonify(error=f"Too many attempts. Please wait about {minutes} minute{'s' if minutes != 1 else ''} and try again.")
    resp.status_code = 429
    resp.headers["Retry-After"] = str(seconds)
    return resp


@bp.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    email = str(body.get("email", "")).strip().lower()[:254]
    password = str(body.get("password", ""))[:128]

    email_key, ip_key = f"login:{email}", f"login-ip:{security.client_ip()}"
    wait = max(security.seconds_until_allowed(email_key, security.LOGIN_PER_EMAIL),
               security.seconds_until_allowed(ip_key, security.LOGIN_PER_IP))
    if wait:
        return too_many(wait)

    user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    # Always do one password check, even for unknown emails, so response time does not reveal which emails exist
    valid = check_password_hash(user["password_hash"] if user else DUMMY_HASH, password) and user is not None
    if not valid:
        security.record_attempt(email_key)
        security.record_attempt(ip_key)
        security.audit("login_failed", user["id"] if user else None)
        return jsonify(error="Incorrect email or password."), 401       # same message for both cases on purpose

    security.clear_attempts(email_key)
    security.audit("login_success", user["id"])
    return jsonify(
        token=make_token(user["id"], new_session(user["id"])),
        user={"name": user["name"], "email": user["email"]},
        has_profile=has_profile(user["id"]),
        email_verified=bool(user["email_verified_at"]),
    )


@bp.post("/logout")
@login_required
def logout():
    if g.sid:
        db = get_db()
        db.execute("DELETE FROM sessions WHERE id = ?", (g.sid,))
        db.commit()
    security.audit("logout", g.user["id"])
    return jsonify(ok=True)


@bp.post("/change-password")
@login_required
def change_password():
    body = request.get_json(silent=True) or {}
    current, new = str(body.get("currentPassword", "")), str(body.get("newPassword", ""))
    if not check_password_hash(g.user["password_hash"], current):
        return jsonify(error="Your current password is wrong."), 400
    problem = security.password_problem(new, g.user["email"])
    if problem:
        return jsonify(error=problem), 400
    db = get_db()
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new), g.user["id"]))
    db.execute("DELETE FROM sessions WHERE user_id = ? AND id IS NOT ?", (g.user["id"], g.sid))   # sign out other devices
    db.commit()
    security.audit("password_changed", g.user["id"])
    return jsonify(ok=True)


@bp.get("/sessions")
@login_required
def list_sessions():
    rows = get_db().execute("SELECT * FROM sessions WHERE user_id = ? ORDER BY created_at DESC", (g.user["id"],)).fetchall()
    return jsonify([{"id": r["id"], "device": r["device"], "current": r["id"] == g.sid,
                     "lastActive": "Signed in " + r["created_at"][:16] + " UTC"} for r in rows])


@bp.delete("/sessions/<sid>")
@login_required
def revoke_session(sid):
    db = get_db()
    db.execute("DELETE FROM sessions WHERE id = ? AND user_id = ?", (sid, g.user["id"]))
    db.commit()
    security.audit("session_revoked", g.user["id"])
    return "", 204


# ------------------------------------------------- email verification + forgot password
GENERIC_RESET_MESSAGE = "If an account exists for that email, we have sent a password reset link. It works for 30 minutes."


@bp.get("/status")
@login_required
def status():
    return jsonify(email=g.user["email"], email_verified=bool(g.user["email_verified_at"]))


@bp.post("/resend-verification")
@login_required
def resend_verification():
    if g.user["email_verified_at"]:
        return jsonify(message="Your email is already verified.")
    key = f"resend:{g.user['id']}"
    wait = security.seconds_until_allowed(key, security.RESEND_PER_USER)
    if wait:
        return too_many(wait)
    security.record_attempt(key)
    account_email.send_verification(g.user["id"], g.user["name"], g.user["email"])
    return jsonify(message="We sent a new verification link to " + g.user["email"] + ".")


@bp.post("/verify-email")
def verify_email():
    ip_key = f"token-ip:{security.client_ip()}"
    wait = security.seconds_until_allowed(ip_key, security.TOKEN_TRIES_PER_IP)
    if wait:
        return too_many(wait)
    security.record_attempt(ip_key)

    row = account_email.find_token(str((request.get_json(silent=True) or {}).get("token", "")), "verify")
    if row is None or not account_email.use_token(row):
        return jsonify(error="This verification link is invalid or has expired. Sign in and request a new one."), 400
    db = get_db()
    db.execute("UPDATE users SET email_verified_at = ? WHERE id = ? AND email_verified_at IS NULL",
               (dt.datetime.now(dt.timezone.utc).isoformat(), row["user_id"]))
    db.commit()
    security.audit("email_verified", row["user_id"])
    return jsonify(ok=True, message="Your email is verified. Thank you!")


@bp.post("/forgot-password")
def forgot_password():
    email = str((request.get_json(silent=True) or {}).get("email", "")).strip().lower()[:254]
    email_key, ip_key = f"forgot:{email}", f"forgot-ip:{security.client_ip()}"
    wait = max(security.seconds_until_allowed(email_key, security.FORGOT_PER_EMAIL),
               security.seconds_until_allowed(ip_key, security.FORGOT_PER_IP))
    if wait:
        return too_many(wait)
    security.record_attempt(email_key)          # counted whether or not the account exists, so nothing is revealed
    security.record_attempt(ip_key)

    user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone() if EMAIL_RE.match(email) else None
    if user:
        security.audit("password_reset_requested", user["id"])
        try:
            account_email.send_reset(user["id"], user["name"], user["email"])
        except Exception as exc:
            print(f"[FinMate] reset email failed: {exc}", flush=True)
    return jsonify(message=GENERIC_RESET_MESSAGE)          # same answer for every address


@bp.post("/reset-password")
def reset_password():
    ip_key = f"token-ip:{security.client_ip()}"
    wait = security.seconds_until_allowed(ip_key, security.TOKEN_TRIES_PER_IP)
    if wait:
        return too_many(wait)
    security.record_attempt(ip_key)

    body = request.get_json(silent=True) or {}
    row = account_email.find_token(str(body.get("token", "")), "reset")
    if row is None:
        return jsonify(error="This reset link is invalid or has expired. Please request a new one."), 400
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    new = str(body.get("newPassword", ""))
    problem = security.password_problem(new, user["email"])
    if problem:                                   # the link stays usable so they can try another password
        return jsonify(error=problem), 400
    if not account_email.use_token(row):
        return jsonify(error="This reset link is invalid or has expired. Please request a new one."), 400

    db.execute("UPDATE users SET password_hash = ?, email_verified_at = COALESCE(email_verified_at, ?) WHERE id = ?",
               (generate_password_hash(new), dt.datetime.now(dt.timezone.utc).isoformat(), user["id"]))   # opening the link proves the email is theirs
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))      # sign out every device
    db.commit()
    security.clear_attempts(f"login:{user['email']}")
    security.audit("password_reset", user["id"])
    return jsonify(ok=True, message="Your password was changed. Please sign in with the new password.")


@bp.post("/magic-link")
def request_magic_link():
    body = request.get_json(silent=True) or {}
    email = str(body.get("email", "")).strip().lower()[:254]
    name = str(body.get("name", "")).strip() or email.split("@")[0]

    if not email or not EMAIL_RE.match(email):
        return jsonify(error="Enter a valid email address, like name@gmail.com."), 400

    ip_key = f"magic-ip:{security.client_ip()}"
    email_key = f"magic:{email}"
    wait = max(security.seconds_until_allowed(ip_key, security.FORGOT_PER_IP),
               security.seconds_until_allowed(email_key, security.FORGOT_PER_EMAIL))
    if wait:
        return too_many(wait)

    security.record_attempt(ip_key)
    security.record_attempt(email_key)

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None:
        now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
        cur = db.execute(
            """INSERT INTO users (name, email, password_hash, terms_accepted_at, terms_version, email_verified_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, email, generate_password_hash(uuid.uuid4().hex), now_iso, security.LEGAL_VERSION, now_iso),
        )
        db.commit()
        user_id = cur.lastrowid
        user_name = name
    else:
        user_id = user["id"]
        user_name = user["name"]

    security.audit("magic_link_requested", user_id)
    send_res = {"mode": "console", "code": "", "token": "", "link": ""}
    try:
        send_res = account_email.send_magic_login(user_id, user_name, email)
    except Exception as exc:
        print(f"[FinMate] Magic link email failed: {exc}", flush=True)

    mode = send_res.get("mode", "console")
    code = send_res.get("code", "")
    link = send_res.get("link", "")

    if mode == "smtp":
        msg = f"A 6-digit sign-in code and direct link have been sent directly to {email}. Check your Gmail!"
    else:
        msg = f"Sign-in code generated. (SMTP is not set up in .env; check terminal or use code below)"

    return jsonify(
        ok=True,
        mode=mode,
        message=msg,
        code=code,
        link=link
    )


@bp.post("/magic-login")
def magic_login():
    ip_key = f"token-ip:{security.client_ip()}"
    wait = security.seconds_until_allowed(ip_key, security.TOKEN_TRIES_PER_IP)
    if wait:
        return too_many(wait)
    security.record_attempt(ip_key)

    body = request.get_json(silent=True) or {}
    token = str(body.get("token") or body.get("code") or "").strip()
    row = account_email.find_token(token, "login")
    if row is None or not account_email.use_token(row):
        return jsonify(error="This code or link is invalid or has expired. Please request a new one."), 400

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    if not user:
        return jsonify(error="User account not found."), 404

    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    if not user["email_verified_at"]:
        db.execute("UPDATE users SET email_verified_at = ? WHERE id = ?", (now_iso, user["id"]))
        db.commit()

    security.clear_attempts(f"login:{user['email']}")
    security.audit("magic_login_success", user["id"])
    return jsonify(
        token=make_token(user["id"], new_session(user["id"])),
        user={"name": user["name"], "email": user["email"]},
        has_profile=has_profile(user["id"]),
        email_verified=True,
    )


@bp.get("/google/config")
def google_config():
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    return jsonify(client_id=client_id, enabled=bool(client_id))


@bp.post("/google/config")
def save_google_config():
    """Allows configuring Google Client ID directly from the UI during setup."""
    body = request.get_json(silent=True) or {}
    client_id = str(body.get("client_id", "")).strip()
    if not client_id:
        return jsonify(error="Google Client ID cannot be empty."), 400
    if len(client_id) > 200:
        return jsonify(error="Invalid Google Client ID format."), 400

    os.environ["GOOGLE_CLIENT_ID"] = client_id

    # Persist to .env in app root
    env_path = os.path.join(current_app.root_path, ".env")
    lines = []
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            lines = []

    found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith("GOOGLE_CLIENT_ID="):
            new_lines.append(f"GOOGLE_CLIENT_ID={client_id}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append(f"GOOGLE_CLIENT_ID={client_id}\n")

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as exc:
        print(f"[FinMate] Note: Could not write to .env: {exc}", flush=True)

    return jsonify(ok=True, client_id=client_id, enabled=True)


@bp.post("/google")
def google_auth():
    body = request.get_json(silent=True) or {}
    credential = str(body.get("credential", "")).strip()
    if not credential:
        return jsonify(error="Missing Google credential token."), 400

    google_client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    email = None
    name = None

    is_dev = current_app.debug or current_app.config.get("TESTING") or os.environ.get("FINMATE_DEBUG", "1") == "1"

    # Development demo fallback if configured or testing without real Client ID
    if credential == "demo-google-token":
        if not is_dev:
            return jsonify(error="Demo login is only available in development mode."), 403
        email = str(body.get("email", "demo.user@gmail.com")).strip().lower()
        name = str(body.get("name", "Demo Google User")).strip()
    else:
        # Real Google ID token verification with Google's tokeninfo endpoint
        info = None
        try:
            req = urllib.request.Request(
                f"https://oauth2.googleapis.com/tokeninfo?id_token={urllib.parse.quote(credential)}",
                headers={"User-Agent": "FinMate/1.0"}
            )
            ctx = ssl.create_default_context()
            try:
                with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                    info = json.loads(response.read().decode("utf-8"))
            except urllib.error.URLError as uerr:
                # If Windows root certificate store has an issue, retry with unverified context as fallback
                if "CERTIFICATE_VERIFY_FAILED" in str(uerr):
                    unverified_ctx = ssl._create_unverified_context()
                    with urllib.request.urlopen(req, timeout=10, context=unverified_ctx) as response:
                        info = json.loads(response.read().decode("utf-8"))
                else:
                    raise uerr
        except urllib.error.HTTPError as he:
            err_msg = "Google token could not be verified."
            try:
                err_body = json.loads(he.read().decode("utf-8", errors="ignore"))
                err_desc = err_body.get("error_description", err_body.get("error", ""))
                if err_desc:
                    err_msg = f"Google verification error: {err_desc}"
            except Exception:
                pass
            return jsonify(error=err_msg), 401
        except Exception as exc:
            print(f"[FinMate] Google token verification error: {exc}", flush=True)
            return jsonify(error=f"Could not reach Google verification servers: {exc}"), 401

        # Check token validity
        if not info or "error_description" in info or "error" in info:
            return jsonify(error=info.get("error_description", "Invalid Google credential.") if info else "Empty response from Google."), 401

        # Verify audience if client id is set
        token_aud = info.get("aud")
        token_azp = info.get("azp")
        if google_client_id and (token_aud != google_client_id and token_azp != google_client_id):
            return jsonify(error="Google Client ID mismatch: Token was not issued for this application."), 401

        email = str(info.get("email", "")).strip().lower()
        name = str(info.get("name", "")).strip() or email.split("@")[0]

    if not email or not EMAIL_RE.match(email):
        return jsonify(error="Valid email not returned by Google."), 400

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    if user is None:
        # Auto-create new user account verified via Google
        cur = db.execute(
            """INSERT INTO users (name, email, password_hash, terms_accepted_at, terms_version, email_verified_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, email, generate_password_hash(uuid.uuid4().hex), now_iso, security.LEGAL_VERSION, now_iso),
        )
        db.commit()
        user_id = cur.lastrowid
        security.audit("signup_google", user_id)
    else:
        user_id = user["id"]
        # Mark email verified if not already verified
        if not user["email_verified_at"]:
            db.execute("UPDATE users SET email_verified_at = ? WHERE id = ?", (now_iso, user_id))
            db.commit()
        security.audit("login_google", user_id)

    security.clear_attempts(f"login:{email}")
    token = make_token(user_id, new_session(user_id))
    return jsonify(
        token=token,
        user={"name": name, "email": email},
        has_profile=has_profile(user_id),
        email_verified=True
    ), 200

