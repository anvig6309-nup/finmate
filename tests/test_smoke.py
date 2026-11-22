"""Run with:  python -m pytest -q   (or: python tests/test_smoke.py)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app


def make_app(path=None):
    if path is None:
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
    return create_app({"DATABASE": path, "TESTING": True, "SECRET_KEY": "test-secret-key-used-only-by-the-tests"})


def make_client():
    return make_app().test_client()


def signup(c, email="asha@example.com"):
    r = c.post("/api/auth/signup", json={"name": "Asha", "email": email, "password": "secret123", "accepted_terms": True})
    assert r.status_code == 201, r.get_json()
    return {"Authorization": "Bearer " + r.get_json()["token"]}


def test_auth_flow():
    c = make_client()
    h = signup(c)
    assert c.post("/api/auth/signup", json={"name": "A", "email": "asha@example.com", "password": "secret123", "accepted_terms": True}).status_code == 409
    assert c.post("/api/auth/login", json={"email": "asha@example.com", "password": "bad"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "asha@example.com", "password": "secret123"}).status_code == 200
    assert c.get("/api/profile").status_code == 401
    assert c.get("/api/profile", headers=h).get_json()["name"] == "Asha"


def test_profile_expenses_goals():
    c = make_client()
    h = signup(c)
    c.put("/api/profile", headers=h, json={"persona": "salaried", "totals": {"monthly": 50000, "yearly": 600000}})
    p = c.get("/api/profile", headers=h).get_json()
    assert p["totals"]["monthly"] == 50000
    assert c.post("/api/auth/login", json={"email": "asha@example.com", "password": "secret123"}).get_json()["has_profile"]

    ex = [{"id": "e1", "category": "Rent", "priority": "High", "negotiable": False, "amount": 12000, "period": "Monthly"}]
    assert c.put("/api/expenses", headers=h, json=ex).get_json()[0]["amount"] == 12000
    assert c.put("/api/goals", headers=h, json=[{"id": "g1", "name": "Laptop", "target": 60000, "months": 12}]).status_code == 200
    assert c.put("/api/goals", headers=h, json=[{"name": "", "months": 0}]).status_code == 400


def test_users_cannot_see_each_other():
    c = make_client()
    h1 = signup(c, "one@example.com")
    h2 = signup(c, "two@example.com")
    c.put("/api/goals", headers=h1, json=[{"id": "g1", "name": "Bike", "target": 1000, "months": 6}])
    assert c.get("/api/goals", headers=h2).get_json() == []


def test_funds_planner_fields():
    c = make_client()
    h = signup(c)
    assert c.get("/api/budget/settings", headers=h).status_code == 404
    funds = {"persona": "business", "monthly": 50000, "yearly": 600000,  # yearly == monthly x 12, so it is ignored
             "sources": [{"name": "Rent", "amount": 5000, "frequency": "monthly"},
                         {"name": "Bonus", "amount": 12000, "frequency": "one-time"}]}
    r = c.put("/api/funds", headers=h, json=funds).get_json()
    assert r["persona"] == "business_owner" and r["available_monthly_funds"] == 50000
    assert r["total_yearly_funds"] == 50000 * 12 + 5000 * 12 + 12000
    assert r["additional_income"][0]["name"] == "Rent"
    assert c.post("/api/auth/login", json={"email": "asha@example.com", "password": "secret123"}).get_json()["has_profile"]
    assert c.put("/api/funds", headers=h, json={"monthly": -5}).status_code == 400

    ex = [{"id": "e1", "category": "Rent", "negotiability": "non-negotiable", "tentative_amount": 12000},
          {"id": "e2", "category": "Food", "negotiable": True, "amount": 6000}]
    out = c.put("/api/expenses", headers=h, json=ex).get_json()
    assert out[0]["negotiability"] == "non-negotiable" and out[0]["amount"] == 12000
    assert out[1]["negotiability"] == "negotiable"

    g = c.put("/api/goals", headers=h, json=[{"id": "g1", "name": "Bike", "target": 90000, "months": 14, "startDate": "2026-11-30"}]).get_json()
    assert g[0]["deadline"] == "2028-01-30" and g[0]["target_amount"] == 90000

    body = {"period": "yearly", "protected_amount": 2000, "items": {"Food": {"estM": 5000}}}
    assert c.put("/api/budget/settings", headers=h, json=body).status_code == 200
    assert c.get("/api/budget/settings", headers=h).get_json()["items"]["Food"]["estM"] == 5000
    assert c.delete("/api/budget/settings", headers=h).status_code == 204
    assert c.get("/api/budget/settings", headers=h).status_code == 404


def test_pages_own_shapes():
    """The exact objects the funds / category / goals pages save in the browser."""
    c = make_client()
    h = signup(c)
    profile = {"persona": "salaried", "incomeType": "monthly", "income": {"monthly": 60000, "yearly": None},
               "extraSources": [{"id": "yearly-funds", "name": "Yearly funds", "amount": 120000, "frequency": "Yearly"},
                                {"id": "src1", "name": "Tuition", "amount": 2000, "frequency": "Weekly", "startDate": None, "endDate": None}],
               "totals": {"monthly": 0, "yearly": 0}, "minimumFloor": 20000}
    r = c.put("/api/funds", headers=h, json={**profile, "_ui_key": "finmate_profile"}).get_json()
    assert r["persona"] == "salaried_employee" and r["monthly_funds"] == 60000
    assert r["total_yearly_funds"] == 60000 * 12 + 120000 + 2000 * 52     # server recomputes totals itself
    assert r["ui_key"] == "finmate_profile" and r["ui_value"]["extraSources"][1]["name"] == "Tuition"
    biz = {"persona": "business_owner", "monthlyFunds": 50000, "yearlyFunds": 0, "sources": [], "minimumMonthlyFunds": 40000}
    b = c.put("/api/funds", headers=h, json={**biz, "_ui_key": "finmate_business_funds"}).get_json()
    assert b["persona"] == "business_owner" and b["total_monthly_funds"] == 50000 and b["ui_key"] == "finmate_business_funds"
    assert c.put("/api/funds", headers=h, json={"_ui_key": "evil", "monthly": 1}).get_json()["ui_key"] != "evil"   # unknown keys are ignored

    entries = {"persona": "salaried", "entries": [
        {"id": "e1", "category": "Housing", "subcategory": "Rent", "name": "Rent", "priority": "High", "negotiable": False, "amount": 15000, "period": "Monthly", "custom": False},
        {"id": "e2", "category": "Food", "subcategory": "Eating out", "name": "Cafes", "priority": "Low", "negotiable": True, "amount": None, "period": "Monthly", "custom": True}]}
    out = c.put("/api/expenses", headers=h, json=entries).get_json()
    assert [e["negotiable"] for e in out] == [False, True] and out[0]["amount"] == 15000

    goal = {"id": "g1", "name": "Trip", "category": "Travel", "target": 40000, "saved": 5000, "remaining": 35000,
            "months": 10, "monthlyRequired": 3500, "priority": "High", "startDate": "2026-11-13"}
    g = c.put("/api/goals", headers=h, json=[goal]).get_json()
    assert g[0]["saved"] == 5000 and g[0]["startDate"] == "2026-11-13"
    assert c.put("/api/goals", headers=h, json=[]).get_json() == []


def test_dashboard_summary_numbers():
    """Hand-calculated example. Funds 50,000/month + rent 5,000/month = 55,000/month."""
    import datetime as dt
    import finance
    funds = {"total_monthly_funds": 55000, "total_yearly_funds": 660000,
             "additional_income": [{"amount": 5000, "frequency": "monthly"}]}
    expenses = [{"category": "Housing", "negotiable": False, "amount": 15000, "period": "Monthly"},
                {"category": "Insurance", "negotiable": False, "amount": 12000, "period": "Yearly"},       # = 1,000 a month
                {"category": "Food", "negotiable": True, "amount": None, "period": "Monthly"}]
    goals = [{"target": 120000, "saved": 0, "deadline": "2027-11-13"}]                                       # 12 months -> 10,000 a month
    settings = {"period": "monthly", "protected_amount": 3000, "items": {"c:food": {"estM": 8000, "nn": False}}}
    s = finance.build_summary(funds, expenses, goals, settings, "monthly", dt.date(2026, 11, 13))
    assert s["funds_total"] == 55000 and s["additional_income"] == 5000
    assert s["non_negotiable"] == 16000 and s["negotiable"] == 8000 and s["planned_expenses"] == 24000
    assert s["expected_savings"] == 10000 and s["remaining"] == 55000 - 24000 - 10000
    assert s["buffer"]["target"] == 3000
    y = finance.build_summary(funds, expenses, goals, settings, "yearly", dt.date(2026, 11, 13))
    assert y["funds_total"] == 660000 and y["planned_expenses"] == 24000 * 12 and y["expected_savings"] == 120000
    assert len(s["predictions"]["actual"]["timeline"]) == 12 and s["predictions"]["actual"]["surplus_deficit"] == (55000 - 24000) * 12
    assert finance.build_insights(s, goals)


def test_dashboard_endpoints():
    c = make_client()
    h = signup(c)
    empty = c.get("/api/dashboard/summary", headers=h).get_json()
    assert empty["has_data"] is False
    c.put("/api/funds", headers=h, json={"persona": "salaried", "income": {"monthly": 60000}, "extraSources": []})
    c.put("/api/expenses", headers=h, json=[{"id": "e1", "category": "Rent", "negotiable": False, "amount": 15000, "period": "Monthly"}])
    s = c.get("/api/dashboard/summary?period=monthly", headers=h).get_json()
    assert s["has_data"] and s["funds_total"] == 60000 and s["planned_expenses"] == 15000 and s["remaining"] == 45000
    assert c.get("/api/insights", headers=h).status_code == 200
    for path in ("/api/purchase-plans", "/api/scenarios", "/api/activity", "/api/pocket-ca/conversations"):
        assert c.get(path, headers=h).get_json() == []
    r = c.post("/api/pocket-ca/chat", headers=h, json={"message": "hi"})
    assert r.status_code == 503 and r.get_json()["code"] == "AI_NOT_CONFIGURED"
    assert c.get("/api/dashboard/summary").status_code == 401


def test_settings_sessions_account():
    import io, json, zipfile
    c = make_client()
    h1 = signup(c)
    h2 = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "asha@example.com", "password": "secret123"},
                                              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/120 Safari/537"}).get_json()["token"]}
    # preferences
    assert c.get("/api/settings", headers=h1).get_json()["theme"] == "system"
    saved = c.put("/api/settings", headers=h1, json={"theme": "dark", "period": "yearly", "bufferPct": "10", "carryOver": True,
                                                      "notifications": {"goalReminders": True, "bogus": True}}).get_json()
    assert saved["theme"] == "dark" and saved["bufferPct"] == 10 and saved["notifications"] == {"goalReminders": True}
    assert c.put("/api/settings", headers=h1, json={"theme": "pink"}).status_code == 400
    assert c.put("/api/settings", headers=h1, json={"bufferPct": 500}).status_code == 400
    # sessions: two sign-ins listed, signing one out kills its token only
    sessions = c.get("/api/auth/sessions", headers=h1).get_json()
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    assert any(s["device"] == "Chrome on Windows" for s in sessions)
    other = next(s for s in sessions if not s["current"])
    assert c.delete("/api/auth/sessions/" + other["id"], headers=h1).status_code == 204
    assert c.get("/api/profile", headers=h2).status_code == 401 and c.get("/api/profile", headers=h1).status_code == 200
    # password change
    assert c.post("/api/auth/change-password", headers=h1, json={"currentPassword": "nope", "newPassword": "longenough1"}).status_code == 400
    assert c.post("/api/auth/change-password", headers=h1, json={"currentPassword": "secret123", "newPassword": "short"}).status_code == 400
    assert c.post("/api/auth/change-password", headers=h1, json={"currentPassword": "secret123", "newPassword": "newsecret1"}).status_code == 200
    assert c.post("/api/auth/login", json={"email": "asha@example.com", "password": "secret123"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "asha@example.com", "password": "newsecret1"}).status_code == 200
    # export
    c.put("/api/expenses", headers=h1, json=[{"id": "e1", "category": "Rent", "negotiable": False, "amount": 1000}])
    assert json.loads(c.get("/api/export?format=json", headers=h1).data)["expenses"][0]["category"] == "Rent"
    z = zipfile.ZipFile(io.BytesIO(c.get("/api/export?format=csv", headers=h1).data))
    assert "Rent" in z.read("expenses.csv").decode()
    for path in ("/api/budgets", "/api/saving-plans"):
        assert c.get(path, headers=h1).get_json() == []
    # logout then delete account
    h3 = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "asha@example.com", "password": "newsecret1"}).get_json()["token"]}
    assert c.post("/api/auth/logout", headers=h3).status_code == 200 and c.get("/api/profile", headers=h3).status_code == 401
    assert c.delete("/api/account", headers=h1, json={"password": "wrong"}).status_code == 400
    assert c.delete("/api/account", headers=h1, json={"password": "newsecret1"}).status_code == 204
    assert c.post("/api/auth/login", json={"email": "asha@example.com", "password": "newsecret1"}).status_code == 401


def test_password_rules_and_consent():
    c = make_client()
    base = {"name": "Ravi", "email": "ravi.kumar@example.com", "accepted_terms": True}
    for bad in ("short1", "onlyletters", "123456789", "password1", "ravi.kumar99", "x" * 129):
        r = c.post("/api/auth/signup", json={**base, "password": bad})
        assert r.status_code == 400, bad
    assert c.post("/api/auth/signup", json={**base, "password": "goodpass99"}).status_code == 201
    no_consent = {"name": "B", "email": "b@example.com", "password": "goodpass99"}
    r = c.post("/api/auth/signup", json=no_consent)
    assert r.status_code == 400 and "Terms" in r.get_json()["error"]
    assert c.post("/api/auth/signup", json={**no_consent, "accepted_terms": "yes"}).status_code == 400     # must be exactly true


def test_login_is_generic_and_rate_limited():
    c = make_client()
    signup(c, "real@example.com")
    unknown = c.post("/api/auth/login", json={"email": "ghost@example.com", "password": "whatever1"})
    wrong = c.post("/api/auth/login", json={"email": "real@example.com", "password": "whatever1"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.get_json() == wrong.get_json()                      # cannot tell which emails exist
    for _ in range(4):                                                  # 5 failures are allowed in 15 minutes (1 used above)
        assert c.post("/api/auth/login", json={"email": "real@example.com", "password": "nope12345"}).status_code == 401
    locked = c.post("/api/auth/login", json={"email": "real@example.com", "password": "nope12345"})
    assert locked.status_code == 429 and int(locked.headers["Retry-After"]) > 0
    assert c.post("/api/auth/login", json={"email": "real@example.com", "password": "secret123"}).status_code == 429   # even the right password waits
    assert c.post("/api/auth/login", json={"email": "other@example.com", "password": "whatever1"}).status_code == 401    # other emails unaffected


def test_signup_rate_limit_and_success_resets_counter():
    c = make_client()
    for i in range(10):
        c.post("/api/auth/signup", json={"name": "X", "email": f"u{i}@example.com", "password": "short"})     # 10 attempts counted
    assert c.post("/api/auth/signup", json={"name": "X", "email": "late@example.com", "password": "goodpass99", "accepted_terms": True}).status_code == 429
    c2 = make_client()
    signup(c2, "ok@example.com")
    for _ in range(3):
        c2.post("/api/auth/login", json={"email": "ok@example.com", "password": "bad-pass-1"})
    assert c2.post("/api/auth/login", json={"email": "ok@example.com", "password": "secret123"}).status_code == 200   # success clears the counter
    for _ in range(4):
        assert c2.post("/api/auth/login", json={"email": "ok@example.com", "password": "bad-pass-1"}).status_code == 401


def test_security_headers_audit_consent_token():
    import datetime as dt, jwt
    from db import get_db
    app = make_app()
    c = app.test_client()
    r = c.get("/login.html")
    assert r.headers["X-Frame-Options"] == "DENY" and r.headers["X-Content-Type-Options"] == "nosniff"
    csp = r.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp and "unsafe-eval" not in csp and "fonts.googleapis.com" in csp
    assert "unsafe-eval" in c.get("/persona.html").headers["Content-Security-Policy"]
    assert c.get("/api/profile").headers["Cache-Control"] == "no-store"

    h = signup(c, "audit@example.com")
    token = h["Authorization"][7:]
    exp = jwt.decode(token, "test-secret-key-used-only-by-the-tests", algorithms=["HS256"])["exp"]
    hours = (dt.datetime.fromtimestamp(exp, dt.timezone.utc) - dt.datetime.now(dt.timezone.utc)).total_seconds() / 3600
    assert 23 < hours <= 24
    c.post("/api/auth/login", json={"email": "audit@example.com", "password": "wrongpass1"})
    c.post("/api/auth/login", json={"email": "audit@example.com", "password": "secret123"})
    with app.app_context():
        events = [r["event"] for r in get_db().execute("SELECT event FROM audit_log ORDER BY id")]
        assert events == ["signup", "login_failed", "login_success"], events
        user = get_db().execute("SELECT terms_version, terms_accepted_at FROM users").fetchone()
        import security
        assert user["terms_version"] == security.LEGAL_VERSION and user["terms_accepted_at"]
    big = c.put("/api/goals", headers=h, data="x" * 1_100_000, content_type="application/json")
    assert big.status_code == 413                                       # oversized request refused


def test_secret_key_and_migration():
    import sqlite3, security
    folder = tempfile.mkdtemp()
    os.environ.pop("FINMATE_SECRET", None)
    first = security.load_secret_key(folder)
    assert len(first) == 64 and security.load_secret_key(folder) == first and os.path.exists(os.path.join(folder, "secret.key"))
    os.environ["FINMATE_SECRET"] = "short"
    try:
        security.load_secret_key(folder)
        raise AssertionError("a short FINMATE_SECRET should be refused")
    except RuntimeError:
        pass
    finally:
        os.environ.pop("FINMATE_SECRET", None)
    # an old database whose users table has no consent columns gets them added automatically
    fd, old = tempfile.mkstemp(suffix=".db"); os.close(fd)
    con = sqlite3.connect(old)
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    con.execute("INSERT INTO users (name, email, password_hash) VALUES ('Old', 'old@example.com', 'x')")
    con.commit(); con.close()
    make_app(old)
    cols = [r[1] for r in sqlite3.connect(old).execute("PRAGMA table_info(users)")]
    assert {"terms_accepted_at", "terms_version", "email_verified_at"} <= set(cols)


def first_link(app, page):
    """The newest emailed link to `page` (verify.html or reset.html) and its raw token."""
    import re
    for mail in reversed(app.extensions.get("outbox", [])):
        m = re.search(r"(http\S+/" + re.escape(page) + r"#token=([\w-]+))", mail["body"])
        if m:
            return m.group(1), m.group(2)
    return None, None


def test_email_verification():
    import sqlite3
    from db import get_db
    app = make_app(); c = app.test_client()
    h = signup(c, "verify@example.com")
    assert len(app.extensions["outbox"]) == 1 and app.extensions["outbox"][0]["to"] == "verify@example.com"
    link, token = first_link(app, "verify.html")
    assert link.startswith("http://127.0.0.1:5000/verify.html#token=")              # fixed base URL, token after '#'
    assert c.get("/api/auth/status", headers=h).get_json() == {"email": "verify@example.com", "email_verified": False}
    assert c.post("/api/auth/verify-email", json={"token": "not-a-real-token"}).status_code == 400
    assert c.post("/api/auth/verify-email", json={"token": token}).status_code == 200
    assert c.get("/api/auth/status", headers=h).get_json()["email_verified"] is True
    assert c.post("/api/auth/verify-email", json={"token": token}).status_code == 400          # one use only
    assert c.post("/api/auth/resend-verification", headers=h).get_json()["message"].startswith("Your email is already")
    assert c.post("/api/auth/login", json={"email": "verify@example.com", "password": "secret123"}).get_json()["email_verified"] is True
    # the raw token is never stored, only its hash
    with app.app_context():
        stored = [r["token_hash"] for r in get_db().execute("SELECT token_hash FROM email_tokens")]
        assert token not in stored and all(len(x) == 64 for x in stored)


def test_verification_expiry_resend_and_email_change():
    import time
    from db import get_db
    app = make_app(); c = app.test_client()
    h = signup(c, "old@example.com")
    _, t1 = first_link(app, "verify.html")
    with app.app_context():                                                         # make the link expire
        get_db().execute("UPDATE email_tokens SET expires_at = ?", (time.time() - 5,)); get_db().commit()
    assert c.post("/api/auth/verify-email", json={"token": t1}).status_code == 400
    assert c.post("/api/auth/resend-verification", headers=h).status_code == 200      # new link replaces the old one
    _, t2 = first_link(app, "verify.html")
    assert t2 != t1 and c.post("/api/auth/resend-verification", headers=h).status_code == 200
    assert c.post("/api/auth/resend-verification", headers=h).status_code == 200
    assert c.post("/api/auth/resend-verification", headers=h).status_code == 429       # 3 per hour
    assert c.post("/api/auth/resend-verification").status_code == 401                 # must be signed in
    _, latest = first_link(app, "verify.html")
    assert c.post("/api/auth/verify-email", json={"token": t2}).status_code == 400    # replaced by a newer one
    assert c.post("/api/auth/verify-email", json={"token": latest}).status_code == 200
    # changing the email needs the password, and the new address must be verified again
    assert c.patch("/api/profile", headers=h, json={"email": "new@example.com"}).status_code == 403
    assert c.patch("/api/profile", headers=h, json={"email": "new@example.com", "current_password": "wrong-pass1"}).status_code == 403
    r = c.patch("/api/profile", headers=h, json={"email": "new@example.com", "current_password": "secret123"})
    assert r.status_code == 200 and r.get_json()["email"] == "new@example.com"
    assert c.get("/api/auth/status", headers=h).get_json() == {"email": "new@example.com", "email_verified": False}
    assert app.extensions["outbox"][-1]["to"] == "new@example.com"


def test_forgot_and_reset_password():
    app = make_app(); c = app.test_client()
    h = signup(c, "forgot@example.com")
    before = len(app.extensions["outbox"])
    known = c.post("/api/auth/forgot-password", json={"email": "forgot@example.com"})
    unknown = c.post("/api/auth/forgot-password", json={"email": "ghost@example.com"})
    assert known.status_code == unknown.status_code == 200 and known.get_json() == unknown.get_json()     # no clue which exist
    assert len(app.extensions["outbox"]) == before + 1                                  # only the real account got an email
    link, token = first_link(app, "reset.html")
    assert link.startswith("http://127.0.0.1:5000/reset.html#token=")
    assert c.post("/api/auth/reset-password", json={"token": token, "newPassword": "short"}).status_code == 400
    assert c.post("/api/auth/reset-password", json={"token": token, "newPassword": "password1"}).status_code == 400   # weak, link still valid
    assert c.post("/api/auth/reset-password", json={"token": "bogus", "newPassword": "brandnew99"}).status_code == 400
    assert c.post("/api/auth/reset-password", json={"token": token, "newPassword": "brandnew99"}).status_code == 200
    assert c.post("/api/auth/reset-password", json={"token": token, "newPassword": "another99x"}).status_code == 400   # one use
    assert c.get("/api/profile", headers=h).status_code == 401                          # every old login was signed out
    assert c.post("/api/auth/login", json={"email": "forgot@example.com", "password": "secret123"}).status_code == 401
    ok = c.post("/api/auth/login", json={"email": "forgot@example.com", "password": "brandnew99"})
    assert ok.status_code == 200 and ok.get_json()["email_verified"] is True            # opening the email link proves ownership
    # a newer request cancels the older link
    c.post("/api/auth/forgot-password", json={"email": "forgot@example.com"}); _, t_old = first_link(app, "reset.html")
    c.post("/api/auth/forgot-password", json={"email": "forgot@example.com"}); _, t_new = first_link(app, "reset.html")
    assert c.post("/api/auth/reset-password", json={"token": t_old, "newPassword": "brandnew98"}).status_code == 400
    assert c.post("/api/auth/reset-password", json={"token": t_new, "newPassword": "brandnew98"}).status_code == 200


def test_forgot_password_rate_limit_and_audit():
    from db import get_db
    app = make_app(); c = app.test_client()
    signup(c, "limit@example.com")
    for _ in range(3):
        assert c.post("/api/auth/forgot-password", json={"email": "limit@example.com"}).status_code == 200
    r = c.post("/api/auth/forgot-password", json={"email": "limit@example.com"})
    assert r.status_code == 429 and "Retry-After" in r.headers
    assert c.post("/api/auth/forgot-password", json={"email": "other@example.com"}).status_code == 200     # other emails are fine
    with app.app_context():
        events = [r["event"] for r in get_db().execute("SELECT event FROM audit_log")]
        assert events.count("password_reset_requested") == 3
    # link host comes from config, not from a forged Host header
    c.post("/api/auth/forgot-password", json={"email": "limit@example.com"}, headers={"Host": "evil.example"})
    app2 = make_app(); c2 = app2.test_client(); signup(c2, "host@example.com")
    c2.post("/api/auth/forgot-password", json={"email": "host@example.com"}, headers={"Host": "evil.example"})
    assert "evil.example" not in first_link(app2, "reset.html")[0]


def test_real_smtp_path_with_fake_mail_server():
    """Starts a tiny mail server on this computer and checks that email_service really speaks SMTP to it."""
    import socket, threading, email_service
    received = []
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1); port = srv.getsockname()[1]

    def serve():
        conn, _ = srv.accept(); f = conn.makefile("rwb", buffering=0)
        f.write(b"220 fake ready\r\n"); data_mode, lines = False, []
        while True:
            line = f.readline()
            if not line: break
            if data_mode:
                if line.strip() == b".":
                    data_mode = False; received.append(b"".join(lines).decode()); f.write(b"250 queued\r\n")
                else: lines.append(line)
                continue
            cmd = line[:4].upper()
            if cmd in (b"EHLO", b"HELO"): f.write(b"250 hello\r\n")
            elif cmd in (b"MAIL", b"RCPT"): f.write(b"250 ok\r\n")
            elif cmd == b"DATA": data_mode = True; f.write(b"354 go\r\n")
            elif cmd == b"QUIT": f.write(b"221 bye\r\n"); break
            else: f.write(b"250 ok\r\n")
        conn.close()
    t = threading.Thread(target=serve, daemon=True); t.start()
    cfg = {"host": "127.0.0.1", "port": port, "user": "", "password": "", "security": "none", "sender": "FinMate <no-reply@example.com>"}
    msg = email_service.build_message("person@example.com", "Reset your FinMate password", "Open http://127.0.0.1:5000/reset.html#token=abc", cfg["sender"])
    email_service.send_via_smtp(msg, cfg); t.join(5)
    assert received and "To: person@example.com" in received[0] and "reset.html#token=abc" in received[0] and "Subject: Reset your FinMate password" in received[0]


def test_google_auth():
    c = make_client()
    r = c.get("/api/auth/google/config")
    assert r.status_code == 200
    # Save google config
    r_cfg = c.post("/api/auth/google/config", json={"client_id": "test-client-id.apps.googleusercontent.com"})
    assert r_cfg.status_code == 200 and r_cfg.get_json()["enabled"] is True
    # Signup with Google token
    r_up = c.post("/api/auth/google", json={"credential": "demo-google-token", "email": "googleuser@example.com", "name": "Google User"})
    assert r_up.status_code == 200, r_up.get_json()
    assert "token" in r_up.get_json()
    assert r_up.get_json()["email_verified"] is True
    # Login again with same Google account
    r_in = c.post("/api/auth/google", json={"credential": "demo-google-token", "email": "googleuser@example.com", "name": "Google User"})
    assert r_in.status_code == 200
    assert "token" in r_in.get_json()


def test_magic_link_and_code_auth():
    app = make_app(); c = app.test_client()
    # Request magic link for new user
    r = c.post("/api/auth/magic-link", json={"email": "magic@example.com", "name": "Magic User"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True
    assert "code" in d and len(d["code"]) == 6
    assert "link" in d and "#magicToken=" in d["link"]
    code = d["code"]
    token = d["link"].split("#magicToken=")[1]

    # Test login with 6-digit code
    r_code = c.post("/api/auth/magic-login", json={"code": code})
    assert r_code.status_code == 200, r_code.get_json()
    assert "token" in r_code.get_json()
    assert r_code.get_json()["email_verified"] is True

    # Companion URL token should now be expired / used
    r_used = c.post("/api/auth/magic-login", json={"token": token})
    assert r_used.status_code == 400

    # Request new magic link for existing user and test with token
    r2 = c.post("/api/auth/magic-link", json={"email": "magic@example.com"})
    assert r2.status_code == 200
    d2 = r2.get_json()
    token2 = d2["link"].split("#magicToken=")[1]
    r_token = c.post("/api/auth/magic-login", json={"token": token2})
    assert r_token.status_code == 200
    assert "token" in r_token.get_json()


if __name__ == "__main__":
    for t in (test_auth_flow, test_profile_expenses_goals, test_users_cannot_see_each_other, test_funds_planner_fields, test_pages_own_shapes, test_dashboard_summary_numbers, test_dashboard_endpoints, test_settings_sessions_account,\
              test_password_rules_and_consent, test_login_is_generic_and_rate_limited,\
              test_signup_rate_limit_and_success_resets_counter, test_security_headers_audit_consent_token, test_secret_key_and_migration,\
              test_email_verification, test_verification_expiry_resend_and_email_change, test_forgot_and_reset_password,\
              test_forgot_password_rate_limit_and_audit, test_real_smtp_path_with_fake_mail_server, test_google_auth, test_magic_link_and_code_auth):
        t()
        print("PASS", t.__name__)
