"""
Profile storage — one interface, two backends.

    DATABASE_URL set    -> PostgreSQL (Supabase). Used in deployment.
    DATABASE_URL unset  -> SQLite on local disk. Used for offline development.

Nothing above this layer knows which backend is live. The five functions below
are the whole contract; `astro_engine_v2` re-exports them, so existing imports
keep working unchanged.

Why both: the app is developed offline against a local file and deployed to a
serverless runtime with an ephemeral filesystem, where a SQLite file would be
silently discarded between invocations. Keeping SQLite for local work means
`python app.py` still runs with no Supabase account and no network.

Serverless note: every call opens and closes its own connection. That is
deliberate — a serverless invocation may be frozen or killed at any point, so a
module-level pooled connection would leak. Point DATABASE_URL at Supabase's
transaction pooler (port 6543), not the direct database port.
"""

import os
import sqlite3
from datetime import datetime

# DATABASE_URL is the name to set by hand. POSTGRES_URL is accepted as a
# fallback because Vercel's native Supabase integration injects that name
# automatically — without it, wiring the two together through the Vercel
# marketplace would silently fall back to SQLite and lose every saved chart.
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
USE_POSTGRES = bool(DATABASE_URL)

# On a serverless host the SQLite fallback cannot work: the deployment
# directory is read-only, so sqlite3 fails with "unable to open database file"
# during import — a message that gives no hint about the actual cause. Fail
# here instead, while there is still room to say what is wrong.
#
# Refusing to start is deliberate. Writing to /tmp would let the app boot and
# appear to save birth charts, then lose them when the instance is recycled,
# which is far worse than not starting at all.
if os.environ.get("VERCEL") and not USE_POSTGRES:
    raise RuntimeError(
        "DATABASE_URL is not set. Running on Vercel without it would fall back "
        "to SQLite on a read-only, ephemeral filesystem and lose every saved "
        "chart. Set DATABASE_URL in Vercel to the Supabase transaction pooler "
        "connection string (port 6543), or connect the Supabase integration, "
        "which provides POSTGRES_URL."
    )

# Local SQLite path. Defaults beside this file rather than an absolute path,
# so it works on any machine and any operating system.
DB_PATH = os.environ.get(
    "ASTRO_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "astro_profiles.db"),
)

# Columns in declaration order. Shared by both backends so the row shape
# returned by get_profile() is identical either way.
COLUMNS = [
    "id", "name", "full_birth_name",
    "year", "month", "day", "hour", "minute",
    "tz_offset", "lat", "lon", "place", "created_at",
]


def _connect():
    """Open a connection to whichever backend is configured."""
    if USE_POSTGRES:
        import psycopg  # imported lazily so local SQLite use needs no driver
        return psycopg.connect(DATABASE_URL)

    conn = sqlite3.connect(DB_PATH)
    # SQLite ignores REFERENCES ... ON DELETE CASCADE unless foreign keys are
    # switched on, and the pragma is per-connection rather than per-database.
    # Without this, deleting a profile silently leaves its readings behind as
    # orphaned rows — personal data outliving the chart it belongs to, and a
    # difference in behaviour from Postgres, which enforces the constraint.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _q(sql):
    """Translate the SQLite placeholder style to psycopg's.

    Queries below are written once with '?', which SQLite takes literally and
    PostgreSQL needs as '%s'. Keeping one spelling avoids two near-identical
    copies of every statement drifting apart.
    """
    return sql.replace("?", "%s") if USE_POSTGRES else sql


# ---------------------------------------------------------------- schema

_SQLITE_HOROSCOPES = """
CREATE TABLE IF NOT EXISTS horoscopes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    period_key TEXT NOT NULL,
    content TEXT NOT NULL,
    persona TEXT,
    provider TEXT,
    model TEXT,
    cost_usd REAL DEFAULT 0,
    created_at TEXT,
    UNIQUE (profile_id, kind, period_key)
)
"""

_POSTGRES_HOROSCOPES = """
CREATE TABLE IF NOT EXISTS horoscopes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    profile_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    period_key TEXT NOT NULL,
    content TEXT NOT NULL,
    persona TEXT,
    provider TEXT,
    model TEXT,
    cost_usd DOUBLE PRECISION DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (profile_id, kind, period_key)
)
"""

_SQLITE_USERS = """
CREATE TABLE IF NOT EXISTS app_users (
    id          TEXT PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT,
    approved_at TEXT,
    approved_by TEXT
)
"""

_POSTGRES_USERS = """
CREATE TABLE IF NOT EXISTS app_users (
    id          UUID PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    approved_at TIMESTAMPTZ,
    approved_by UUID
)
"""

_SQLITE_READINGS = """
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    persona TEXT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    cost_usd REAL DEFAULT 0,
    created_at TEXT
)
"""

_POSTGRES_READINGS = """
CREATE TABLE IF NOT EXISTS readings (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    profile_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    persona TEXT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    cost_usd DOUBLE PRECISION DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
)
"""

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    full_birth_name TEXT,
    year INTEGER, month INTEGER, day INTEGER,
    hour INTEGER, minute INTEGER,
    tz_offset REAL, lat REAL, lon REAL, place TEXT,
    created_at TEXT
)
"""

_POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    full_birth_name TEXT,
    year INTEGER, month INTEGER, day INTEGER,
    hour INTEGER, minute INTEGER,
    tz_offset DOUBLE PRECISION, lat DOUBLE PRECISION, lon DOUBLE PRECISION,
    place TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
)
"""


def init_db():
    """Create the profiles table if it is absent.

    On PostgreSQL this is a convenience for first run; the authoritative schema
    is supabase_schema.sql, which also turns on row level security. Run that
    once against a new Supabase project rather than relying on this.
    """
    conn = _connect()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(_POSTGRES_USERS if USE_POSTGRES else _SQLITE_USERS)
            cur.execute(_POSTGRES_SCHEMA if USE_POSTGRES else _SQLITE_SCHEMA)
            cur.execute(_POSTGRES_READINGS if USE_POSTGRES else _SQLITE_READINGS)
            cur.execute(_POSTGRES_HOROSCOPES if USE_POSTGRES else _SQLITE_HOROSCOPES)

            if not USE_POSTGRES:
                # Migration safety for databases created before this column existed.
                cols = [r[1] for r in cur.execute("PRAGMA table_info(profiles)")]
                if "full_birth_name" not in cols:
                    cur.execute("ALTER TABLE profiles ADD COLUMN full_birth_name TEXT")
                if "user_id" not in cols:
                    cur.execute("ALTER TABLE profiles ADD COLUMN user_id TEXT")
                rcols = [r[1] for r in cur.execute("PRAGMA table_info(readings)")]
                if rcols and "cost_usd" not in rcols:
                    cur.execute("ALTER TABLE readings ADD COLUMN cost_usd REAL DEFAULT 0")
    finally:
        conn.close()


# -------------------------------------------------------------- accounts

USER_COLUMNS = ["id", "email", "status", "created_at", "approved_at", "approved_by"]


def get_user(user_id):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_q("SELECT " + ", ".join(USER_COLUMNS) +
                       " FROM app_users WHERE id=?"), (str(user_id),))
        row = cur.fetchone()
        return dict(zip(USER_COLUMNS, row)) if row else None
    finally:
        conn.close()


def upsert_user(user_id, email, default_status="pending"):
    """Return the account for a verified identity, creating it if new.

    default_status is only consulted when the row does not exist. An existing
    account's status is never overwritten here, so removing someone from
    ADMIN_EMAILS does not silently demote them, and re-signing in does not
    reset a rejection back to pending.
    """
    existing = get_user(user_id)
    if existing:
        return existing

    conn = _connect()
    try:
        with conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute(_q("""
                    INSERT INTO app_users (id, email, status, approved_at)
                    VALUES (?,?,?, CASE WHEN ?='admin' THEN NOW() ELSE NULL END)
                    ON CONFLICT (id) DO NOTHING
                """), (str(user_id), email, default_status, default_status))
            else:
                cur.execute("""
                    INSERT OR IGNORE INTO app_users
                        (id, email, status, created_at, approved_at)
                    VALUES (?,?,?,?,?)
                """, (str(user_id), email, default_status,
                      datetime.utcnow().isoformat(),
                      datetime.utcnow().isoformat() if default_status == "admin" else None))
    finally:
        conn.close()
    return get_user(user_id)


def list_users():
    """Every account, newest first. Admin only — enforced by the caller."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT " + ", ".join(USER_COLUMNS) +
                    " FROM app_users ORDER BY created_at DESC")
        return [dict(zip(USER_COLUMNS, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def set_user_status(user_id, status, approved_by=None):
    """Move an account between pending, approved and rejected.

    'admin' is deliberately not settable here: admin comes from ADMIN_EMAILS,
    so the set of administrators is configuration rather than something a
    compromised session could grant itself.
    """
    if status not in ("pending", "approved", "rejected"):
        raise ValueError("status must be pending, approved or rejected")

    conn = _connect()
    try:
        with conn:
            stamp = datetime.utcnow().isoformat() if not USE_POSTGRES else None
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute(_q("""
                    UPDATE app_users
                       SET status=?,
                           approved_at = CASE WHEN ?='approved' THEN NOW() ELSE NULL END,
                           approved_by = ?
                     WHERE id=? AND status <> 'admin'
                """), (status, status, str(approved_by) if approved_by else None,
                       str(user_id)))
            else:
                cur.execute("""
                    UPDATE app_users
                       SET status=?, approved_at=?, approved_by=?
                     WHERE id=? AND status <> 'admin'
                """, (status, stamp if status == "approved" else None,
                      str(approved_by) if approved_by else None, str(user_id)))
    finally:
        conn.close()
    return get_user(user_id)


def adopt_orphan_profiles(user_id):
    """Give an admin the charts that predate authentication.

    Profiles saved before sign-in existed have no owner. Rather than delete
    them or leave them unreachable, the first admin to sign in takes them.
    Runs at most once meaningfully: afterwards there are no orphans left.
    """
    conn = _connect()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(_q("UPDATE profiles SET user_id=? WHERE user_id IS NULL"),
                        (str(user_id),))
            return cur.rowcount
    finally:
        conn.close()


def can_access_profile(profile_id, user_id, is_admin=False):
    """Whether this account may read or change this chart.

    Called before every profile-scoped operation. Without it, an id in the URL
    is enough to read somebody else's birth details — the ids are sequential
    integers, so they are trivially guessable.
    """
    if is_admin:
        return True
    if not user_id:
        return False
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_q("SELECT 1 FROM profiles WHERE id=? AND user_id=?"),
                    (profile_id, str(user_id)))
        return cur.fetchone() is not None
    finally:
        conn.close()


# ---------------------------------------------------------------- writes

def save_profile(name, year, month, day, hour, minute, tz_offset,
                 lat, lon, place, full_birth_name=None, user_id=None):
    """Insert a birth profile and return its new id."""
    conn = _connect()
    try:
        with conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute(_q("""
                    INSERT INTO profiles
                        (name, full_birth_name, year, month, day, hour, minute,
                         tz_offset, lat, lon, place, user_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    RETURNING id
                """), (name, full_birth_name or name, year, month, day, hour,
                       minute, tz_offset, lat, lon, place,
                       str(user_id) if user_id else None))
                return cur.fetchone()[0]

            cur.execute("""
                INSERT INTO profiles
                    (name, full_birth_name, year, month, day, hour, minute,
                     tz_offset, lat, lon, place, created_at, user_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (name, full_birth_name or name, year, month, day, hour,
                  minute, tz_offset, lat, lon, place,
                  datetime.utcnow().isoformat(),
                  str(user_id) if user_id else None))
            return cur.lastrowid
    finally:
        conn.close()


def save_reading(profile_id, question, answer, persona=None,
                 provider=None, model=None, cost_usd=0.0):
    """Record one question and the answer given to it.

    Kept deliberately separate from the conversation history the model is
    sent. History exists to give the model continuity within a session; this
    table is the querent's own record, and it stores what was actually said
    rather than the chart block that produced it.
    """
    conn = _connect()
    try:
        with conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute(_q("""
                    INSERT INTO readings
                        (profile_id, persona, question, answer, provider, model, cost_usd)
                    VALUES (?,?,?,?,?,?,?)
                    RETURNING id
                """), (profile_id, persona, question, answer, provider, model,
                       cost_usd or 0.0))
                return cur.fetchone()[0]

            cur.execute("""
                INSERT INTO readings
                    (profile_id, persona, question, answer, provider, model,
                     cost_usd, created_at)
                VALUES (?,?,?,?,?,?,?,?)
            """, (profile_id, persona, question, answer, provider, model,
                  cost_usd or 0.0, datetime.utcnow().isoformat()))
            return cur.lastrowid
    finally:
        conn.close()


def _start_of_today():
    """Midnight UTC today, in the type each backend stores.

    SQLite keeps created_at as an ISO string, so the comparison there is
    lexicographic and needs a string; PostgreSQL keeps a timestamptz and wants
    a datetime. Getting this wrong compares a string to a timestamp and
    silently counts nothing, which would make a cap that never triggers.
    """
    midnight = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight if USE_POSTGRES else midnight.isoformat()


def count_readings_today(user_id):
    """How many readings this account has asked for since midnight UTC.

    Counted across all of their charts, because the cost is per question, not
    per chart — otherwise adding a second chart would double the allowance.
    """
    if not user_id:
        return 0
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_q("""
            SELECT COUNT(*) FROM readings r
            JOIN profiles p ON r.profile_id = p.id
            WHERE p.user_id = ? AND r.created_at >= ?
        """), (str(user_id), _start_of_today()))
        row = cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


HOROSCOPE_COLUMNS = ["id", "kind", "period_key", "content", "persona",
                     "provider", "model", "cost_usd", "created_at"]


def get_horoscope(profile_id, kind, period_key):
    """A cached horoscope for one chart and one period, or None.

    This is the whole point of the table: a hit costs nothing, and a miss is
    the only time a model is called.
    """
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_q("SELECT " + ", ".join(HOROSCOPE_COLUMNS) +
                       " FROM horoscopes WHERE profile_id=? AND kind=? "
                       "AND period_key=?"), (profile_id, kind, period_key))
        row = cur.fetchone()
        return dict(zip(HOROSCOPE_COLUMNS, row)) if row else None
    finally:
        conn.close()


def save_horoscope(profile_id, kind, period_key, content, persona=None,
                   provider=None, model=None, cost_usd=0.0):
    """Store a generated horoscope.

    Two people opening the same tab at once would both miss the cache and both
    generate; the unique constraint means the second write loses rather than
    duplicating, and the reader then gets the first one. Paying twice once is
    better than locking, and the row is identical either way.
    """
    conn = _connect()
    try:
        with conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute(_q("""
                    INSERT INTO horoscopes
                        (profile_id, kind, period_key, content, persona,
                         provider, model, cost_usd)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT (profile_id, kind, period_key) DO NOTHING
                """), (profile_id, kind, period_key, content, persona,
                       provider, model, cost_usd or 0.0))
            else:
                cur.execute("""
                    INSERT OR IGNORE INTO horoscopes
                        (profile_id, kind, period_key, content, persona,
                         provider, model, cost_usd, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (profile_id, kind, period_key, content, persona,
                      provider, model, cost_usd or 0.0,
                      datetime.utcnow().isoformat()))
    finally:
        conn.close()
    return get_horoscope(profile_id, kind, period_key)


def delete_horoscope(profile_id, kind, period_key):
    """Drop one cached horoscope, so the next request regenerates it."""
    conn = _connect()
    try:
        with conn:
            conn.cursor().execute(
                _q("DELETE FROM horoscopes WHERE profile_id=? AND kind=? "
                   "AND period_key=?"), (profile_id, kind, period_key))
    finally:
        conn.close()


def spend_today():
    """Total dollars spent across the whole app since midnight UTC.

    Global rather than per-account on purpose: this exists to cap the BILL, and
    the bill does not care which account ran it up.
    """
    conn = _connect()
    try:
        cur = conn.cursor()
        # Horoscopes are generated by the same models and cost the same
        # money, so they must count against the same budget. Leaving them
        # out would make the cap describe only part of the bill.
        cur.execute(_q("SELECT COALESCE(SUM(cost_usd), 0) FROM readings "
                       "WHERE created_at >= ?"), (_start_of_today(),))
        row = cur.fetchone()
        total = float(row[0]) if row and row[0] is not None else 0.0
        cur.execute(_q("SELECT COALESCE(SUM(cost_usd), 0) FROM horoscopes "
                       "WHERE created_at >= ?"), (_start_of_today(),))
        row = cur.fetchone()
        total += float(row[0]) if row and row[0] is not None else 0.0
        return total
    finally:
        conn.close()


def usage_summary():
    """Per account: charts held, readings today, readings ever.

    For the admin page — the point is to see who is spending the API budget
    before the bill says so.
    """
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_q("""
            SELECT u.id, u.email, u.status,
                   (SELECT COUNT(*) FROM profiles p WHERE p.user_id = u.id),
                   (SELECT COUNT(*) FROM readings r
                      JOIN profiles p2 ON r.profile_id = p2.id
                     WHERE p2.user_id = u.id AND r.created_at >= ?),
                   (SELECT COUNT(*) FROM readings r2
                      JOIN profiles p3 ON r2.profile_id = p3.id
                     WHERE p3.user_id = u.id),
                   (SELECT COALESCE(SUM(r3.cost_usd), 0) FROM readings r3
                      JOIN profiles p4 ON r3.profile_id = p4.id
                     WHERE p4.user_id = u.id AND r3.created_at >= ?)
              FROM app_users u
             ORDER BY u.created_at DESC
        """), (_start_of_today(), _start_of_today()))
        cols = ["id", "email", "status", "charts", "today", "total", "spent_today"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def list_readings(profile_id, limit=50):
    """Past readings for one profile, newest first."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_q("""
            SELECT id, persona, question, answer, provider, model, created_at
            FROM readings WHERE profile_id=?
            ORDER BY id DESC LIMIT ?
        """), (profile_id, max(1, min(int(limit), 200))))
        cols = ["id", "persona", "question", "answer", "provider", "model", "created_at"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def delete_profile(profile_id):
    """Remove a profile and, by cascade, its readings.
    Silent if the id does not exist."""
    conn = _connect()
    try:
        with conn:
            conn.cursor().execute(
                _q("DELETE FROM profiles WHERE id=?"), (profile_id,))
    finally:
        conn.close()


# ---------------------------------------------------------------- reads

def list_profiles(user_id=None, include_all=False):
    """Rows of (id, name, place, year, month, day), oldest first.

    include_all is the admin view. Otherwise the list is restricted to charts
    this account owns; passing neither returns nothing rather than everything,
    so a missing user cannot accidentally open the whole table.

    The tuple shape and column order are load-bearing: app.py indexes into
    them positionally when building the profile list for the UI.
    """
    select = "SELECT id, name, place, year, month, day FROM profiles"
    conn = _connect()
    try:
        cur = conn.cursor()
        if include_all:
            cur.execute(select + " ORDER BY id")
        elif user_id:
            cur.execute(_q(select + " WHERE user_id=? ORDER BY id"), (str(user_id),))
        else:
            return []
        return cur.fetchall()
    finally:
        conn.close()


def get_profile(profile_id):
    """One profile as a dict keyed by COLUMNS, or None if absent."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_q(
            "SELECT " + ", ".join(COLUMNS) + " FROM profiles WHERE id=?"),
            (profile_id,))
        row = cur.fetchone()
        return dict(zip(COLUMNS, row)) if row else None
    finally:
        conn.close()
