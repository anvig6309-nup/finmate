# FinMate (Flask + SQLite backend, HTML frontend)

## Run on Windows (VS Code terminal = PowerShell)
    py -m venv venv
    .\venv\Scripts\python.exe -m pip install -r requirements.txt
    .\venv\Scripts\python.exe tests\test_smoke.py
    .\venv\Scripts\python.exe app.py
Open http://127.0.0.1:5000  (not Live Server). Stop the server with Ctrl+C.
A random secret.key file is created on first run. On a real server set FINMATE_SECRET (16+ characters) and FINMATE_DEBUG=0.

## How data flows
1. Sign up / log in  -> server issues a token (stored in the browser as "token").
2. Persona -> funds -> category -> goals pages save in the browser AND send the same data to the server (api.js).
3. Logging in on any browser loads the server's data back into the pages (FM.hydrate in api.js).
4. budget_planner, profile and dashboard read the server directly.

## Files
- app.py        creates the app and serves ./frontend          - db.py / schema.sql   SQLite connection and tables
- auth.py       signup, login, logout, @login_required (JWT)   - api.py   /api/profile, /funds, /expenses, /goals, /budget/settings
- dashboard_api.py  /api/dashboard/summary, /insights and placeholders
- settings_api.py   /api/settings, /export, /account
- email_service.py  sends email (SMTP, console or test mode)   - account_email.py  verify / reset tokens
- finance.py    pure calculation helpers                         - tests/   automated tests
- frontend/api.js  shared helper used by every data-entry page

## Email: verification, direct links, 6-digit codes and forgot password
- Without any SMTP setup, emails are printed in the terminal where `app.py` runs ("console mode"), and the UI displays the 6-digit code and direct link on screen so you are never blocked.
- To send real email directly to Gmail inboxes: open `.env` (in the finmate root folder), fill in the SMTP lines with your Gmail and a 16-character Google App Password, and restart the server.
- Supported authentication modes:
  - 6-digit OTP code (enter directly into the input box on the Sign In / Sign Up page)
  - 1-click magic link (`login.html#magicToken=...`)
  - Google OAuth / Demo Account (1-click instant login)
- Tokens expire in 15 minutes (login code/link), 30 minutes (password reset), or 24 hours (email verification).
- Only a SHA-256 hash of each code/token is stored in `email_tokens`.
- Changing your email (profile page) needs your password and must be verified again.

## Dashboard (done)
- finance.py build_summary() / build_insights() do the maths; dashboard_api.py serves /api/dashboard/summary and /api/insights.
- Rules: expected savings = what each goal needs per month to reach its deadline; remaining = funds - planned expenses - expected savings.

## Settings page (done)
settings_api.py: preferences (/api/settings), export (/api/export?format=json|csv), delete account (/api/account).
auth.py also has change-password and active sessions (each sign-in is a row in `sessions`; signing one out revokes its token).
legal.html holds the Privacy Policy, Terms and Disclaimer (linked from Settings and from the signup checkbox). Add your contact email in section 9 of the privacy policy.

## Security (security.py + auth.py)
| Threat | Defence | Where |
|---|---|---|
| Stolen database | Passwords stored only as salted scrypt hashes | auth.py |
| Weak passwords | 8+ characters, a letter and a number, no common passwords | security.password_problem |
| Password guessing | 5 wrong tries per email / 20 per IP per 15 min, then HTTP 429; signups limited per IP | security.py, table auth_attempts |
| Finding which emails exist | One generic login message and equal timing for unknown emails | auth.login |
| Stolen or old logins | Token expires after 24 h; every sign-in is a revocable session; password change signs out other devices | auth.py, table sessions |
| Forged tokens | Secret key from FINMATE_SECRET or a random secret.key file (never committed) | security.load_secret_key |
| Browser attacks | CSP, X-Frame-Options, nosniff, no-store on API replies | security.add_security_headers |
| Huge requests | 1 MB request limit | app.py |
| Account takeover | Email-verified recovery: hashed, expiring, single-use reset tokens; same reply for every address | account_email.py, auth.py |
| Accountability | audit_log table records sign-ups, sign-ins, failures, password changes | security.audit |
| Consent | Terms/Privacy checkbox at signup; version and time stored on the user | auth.signup, legal.html |
Not included yet: HTTPS (needed once it is online) and two-step login.

## Not built yet
/api/purchase-plans, /scenarios, /activity, /budgets, /saving-plans return empty lists for now, and the Pocket CA AI chat answers "not configured".
The afford, what-if and predictions pages need these.

## Reset the database
Stop the server, delete finmate.db, start again.
