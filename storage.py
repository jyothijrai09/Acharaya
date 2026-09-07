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

DATABASE_URL = os.environ.get("DATABASE_URL")
USE_POSTGRES = bool(DATABASE_URL)

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
    return sqlite3.connect(DB_PATH)


def _q(sql):
    """Translate the SQLite placeholder style to psycopg's.

    Queries below are written once with '?', which SQLite takes literally and
    PostgreSQL needs as '%s'. Keeping one spelling avoids two near-identical
    copies of every statement drifting apart.
    """
    return sql.replace("?", "%s") if USE_POSTGRES else sql


# ---------------------------------------------------------------- schema

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
            cur.execute(_POSTGRES_SCHEMA if USE_POSTGRES else _SQLITE_SCHEMA)

            if not USE_POSTGRES:
                # Migration safety for databases created before this column existed.
                cols = [r[1] for r in cur.execute("PRAGMA table_info(profiles)")]
                if "full_birth_name" not in cols:
                    cur.execute("ALTER TABLE profiles ADD COLUMN full_birth_name TEXT")
    finally:
        conn.close()


# ---------------------------------------------------------------- writes

def save_profile(name, year, month, day, hour, minute, tz_offset,
                 lat, lon, place, full_birth_name=None):
    """Insert a birth profile and return its new id."""
    conn = _connect()
    try:
        with conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute(_q("""
                    INSERT INTO profiles
                        (name, full_birth_name, year, month, day, hour, minute,
                         tz_offset, lat, lon, place)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    RETURNING id
                """), (name, full_birth_name or name, year, month, day, hour,
                       minute, tz_offset, lat, lon, place))
                return cur.fetchone()[0]

            cur.execute("""
                INSERT INTO profiles
                    (name, full_birth_name, year, month, day, hour, minute,
                     tz_offset, lat, lon, place, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (name, full_birth_name or name, year, month, day, hour,
                  minute, tz_offset, lat, lon, place,
                  datetime.utcnow().isoformat()))
            return cur.lastrowid
    finally:
        conn.close()


def delete_profile(profile_id):
    """Remove a profile. Silent if the id does not exist."""
    conn = _connect()
    try:
        with conn:
            conn.cursor().execute(
                _q("DELETE FROM profiles WHERE id=?"), (profile_id,))
    finally:
        conn.close()


# ---------------------------------------------------------------- reads

def list_profiles():
    """Rows of (id, name, place, year, month, day), oldest first.

    The tuple shape and column order are load-bearing: app.py indexes into
    them positionally when building the profile list for the UI.
    """
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, place, year, month, day FROM profiles ORDER BY id")
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
