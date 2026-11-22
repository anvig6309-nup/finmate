-- FinMate database schema (SQLite)
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    terms_accepted_at TEXT,
    terms_version     TEXT,
    email_verified_at TEXT
);

-- One row per user: persona, income and totals saved by the onboarding pages (stored as JSON text)
CREATE TABLE IF NOT EXISTS profiles (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    persona    TEXT,
    data       TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_id   TEXT NOT NULL,
    category    TEXT NOT NULL,
    subcategory TEXT NOT NULL DEFAULT '',
    name        TEXT NOT NULL DEFAULT '',
    priority    TEXT CHECK (priority IN ('High','Medium','Low')),
    negotiable  INTEGER CHECK (negotiable IN (0,1)),
    amount      REAL CHECK (amount IS NULL OR amount >= 0),
    period      TEXT NOT NULL DEFAULT 'Monthly',
    custom      INTEGER NOT NULL DEFAULT 0,
    UNIQUE (user_id, client_id)
);

CREATE TABLE IF NOT EXISTS goals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_id       TEXT NOT NULL,
    name            TEXT NOT NULL,
    category        TEXT,
    custom_category TEXT,
    target          REAL CHECK (target IS NULL OR target >= 0),
    saved           REAL NOT NULL DEFAULT 0 CHECK (saved >= 0),
    months          INTEGER NOT NULL CHECK (months > 0),
    priority        TEXT,
    start_date      TEXT,
    UNIQUE (user_id, client_id)
);

CREATE INDEX IF NOT EXISTS idx_expenses_user ON expenses(user_id);
CREATE INDEX IF NOT EXISTS idx_goals_user    ON goals(user_id);

-- Added in Phase 2
CREATE TABLE IF NOT EXISTS income_sources (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL DEFAULT 'Other',
    amount     REAL NOT NULL CHECK (amount >= 0),
    frequency  TEXT NOT NULL DEFAULT 'monthly',
    start_date TEXT,
    end_date   TEXT
);
CREATE INDEX IF NOT EXISTS idx_income_user ON income_sources(user_id);

CREATE TABLE IF NOT EXISTS budget_settings (
    user_id          INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    period           TEXT NOT NULL DEFAULT 'monthly' CHECK (period IN ('monthly','yearly')),
    protected_amount REAL NOT NULL DEFAULT 0 CHECK (protected_amount >= 0),
    items            TEXT NOT NULL DEFAULT '{}',
    updated_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Added for the Settings page
CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device     TEXT NOT NULL DEFAULT 'Browser',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    data       TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Security: failed-login / signup counters (rate limiting) and a record of important account events
CREATE TABLE IF NOT EXISTS auth_attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    key        TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attempts_key ON auth_attempts(key, created_at);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
    event      TEXT NOT NULL,
    ip         TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);

-- One-time links sent by email (verify address / reset password). Only a hash of the token is stored.
CREATE TABLE IF NOT EXISTS email_tokens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose    TEXT NOT NULL CHECK (purpose IN ('verify','reset','login')),
    token_hash TEXT NOT NULL UNIQUE,
    expires_at REAL NOT NULL,
    used_at    REAL
);
CREATE INDEX IF NOT EXISTS idx_email_tokens_user ON email_tokens(user_id, purpose);

-- Pocket CA chat conversations
CREATE TABLE IF NOT EXISTS pocket_ca_chats (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL DEFAULT 'Financial Advisory',
    messages   TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chats_user ON pocket_ca_chats(user_id);
