"""Database helpers: one SQLite connection per request."""
import sqlite3
from flask import current_app, g


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create all tables (safe to run many times)."""
    db = get_db()
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf-8"))
    # Small migration: databases created before the consent columns existed get them added here
    have = {r["name"] for r in db.execute("PRAGMA table_info(users)")}
    for column in ("terms_accepted_at", "terms_version", "email_verified_at"):
        if column not in have:
            db.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")

    # Migration for email_tokens: ensure 'login' purpose is allowed
    try:
        db.execute("INSERT INTO email_tokens (user_id, purpose, token_hash, expires_at) VALUES (1, 'login', '__check_login__', 0)")
        db.execute("DELETE FROM email_tokens WHERE token_hash = '__check_login__'")
    except sqlite3.IntegrityError:
        db.execute("""
            CREATE TABLE IF NOT EXISTS email_tokens_new (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                purpose    TEXT NOT NULL CHECK (purpose IN ('verify','reset','login')),
                token_hash TEXT NOT NULL UNIQUE,
                expires_at REAL NOT NULL,
                used_at    REAL
            )
        """)
        db.execute("INSERT OR IGNORE INTO email_tokens_new SELECT * FROM email_tokens")
        db.execute("DROP TABLE email_tokens")
        db.execute("ALTER TABLE email_tokens_new RENAME TO email_tokens")
        db.execute("CREATE INDEX IF NOT EXISTS idx_email_tokens_user ON email_tokens(user_id, purpose)")

    db.commit()
