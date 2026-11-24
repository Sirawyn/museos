"""SQLite storage. One file (MUSE_DB, default data/muse.db), WAL mode, rows link to venues and team members by name."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS venues (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, neighborhood TEXT, nights TEXT,
  pay_model TEXT, rate_per_guest REAL, cap_per_night REAL, flat_rate REAL, weekly_quota INTEGER,
  men_policy TEXT, dress_code TEXT, arrive_by TEXT, confirmation_message TEXT, contact TEXT,
  status TEXT DEFAULT 'Active', ticket_link TEXT, commission_pct REAL, updated_at TEXT,
  ticket_link_updated_at TEXT, guys_policy TEXT, list_closes TEXT);
CREATE TABLE IF NOT EXISTS team (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, role TEXT, ig_handle TEXT, phone TEXT,
  home_venue TEXT, pay_type TEXT, pay_rate REAL, status TEXT DEFAULT 'Active', start_date TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS leads (
  id TEXT PRIMARY KEY, created_at TEXT, channel TEXT, ig_handle TEXT COLLATE NOCASE, name TEXT, night TEXT,
  venue TEXT, party_size INTEGER, girls INTEGER, guys INTEGER, status TEXT DEFAULT 'New', host TEXT,
  first_reply_at TEXT, source_content_id TEXT, last_message_at TEXT, notes TEXT, referred_by TEXT,
  updated_at TEXT, updated_by TEXT);
CREATE TABLE IF NOT EXISTS guests (
  ig_handle TEXT PRIMARY KEY COLLATE NOCASE, name TEXT, phone TEXT, first_contact TEXT, first_channel TEXT,
  first_content_id TEXT, tags TEXT, notes TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS bookings (
  id TEXT PRIMARY KEY, night TEXT, venue TEXT, ig_handle TEXT COLLATE NOCASE, lead_id TEXT, host TEXT,
  stop INTEGER DEFAULT 1, party_size INTEGER, girls INTEGER, guys INTEGER, status TEXT DEFAULT 'Confirmed',
  girls_arrived INTEGER, confirmation_sent INTEGER DEFAULT 0, thank_you_sent INTEGER DEFAULT 0, notes TEXT,
  table_spend REAL, referred_by TEXT, checked_in_at TEXT, checked_in_by TEXT, checkin_changed_at TEXT, updated_at TEXT, updated_by TEXT);
CREATE TABLE IF NOT EXISTS nights (
  id INTEGER PRIMARY KEY, night TEXT NOT NULL, venue TEXT NOT NULL, host TEXT, notes TEXT, flat_override REAL,
  updated_at TEXT, dress_code TEXT, cover TEXT, ticket_link TEXT, list_closes TEXT,
  guys_policy TEXT, UNIQUE(night, venue));
CREATE TABLE IF NOT EXISTS content (
  post_id TEXT PRIMARY KEY, date_posted TEXT, platform TEXT, format TEXT, hook TEXT, creator TEXT, link TEXT,
  views INTEGER, likes INTEGER, comments INTEGER, shares INTEGER, saves INTEGER, new_follows INTEGER, updated_at TEXT);
CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY, date TEXT, type TEXT, venue TEXT, person TEXT, amount REAL, status TEXT, method TEXT,
  covers TEXT, notes TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
-- days the Weekly setup form has been saved for, even with no venues ticked (so empty days stay empty)
CREATE TABLE IF NOT EXISTS setup_days (night TEXT PRIMARY KEY, saved_at TEXT);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL,
  role TEXT NOT NULL, team_name TEXT, active INTEGER DEFAULT 1, must_change_password INTEGER DEFAULT 1,
  created_at TEXT, last_login_at TEXT);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf TEXT NOT NULL, created_at TEXT, last_seen_at TEXT, expires_at TEXT, ip TEXT, user_agent TEXT);
CREATE TABLE IF NOT EXISTS user_prefs (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, key TEXT NOT NULL, value TEXT,
  PRIMARY KEY (user_id, key));
CREATE TABLE IF NOT EXISTS invites (
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT, expires_at TEXT, created_by TEXT);
CREATE TABLE IF NOT EXISTS api_keys (
  id INTEGER PRIMARY KEY, name TEXT, key_hash TEXT NOT NULL UNIQUE, prefix TEXT, created_at TEXT,
  last_used_at TEXT, revoked INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY, at TEXT, actor TEXT, entity TEXT, entity_id TEXT, action TEXT, changes TEXT);
CREATE TABLE IF NOT EXISTS plan (
  id TEXT PRIMARY KEY, planned_date TEXT, planned_time TEXT, title TEXT, format TEXT, pillar TEXT, campaign TEXT,
  owner TEXT, status TEXT DEFAULT 'Planned', needs_approval INTEGER DEFAULT 0, hook TEXT, caption TEXT, cta TEXT,
  shot_list TEXT, asset_link TEXT, brief_link TEXT, content_type TEXT, post_link TEXT, post_id TEXT, review_note TEXT,
  notes TEXT, approved_by TEXT, approved_at TEXT, idea_id TEXT, updated_at TEXT, updated_by TEXT);
CREATE TABLE IF NOT EXISTS campaigns (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, start_date TEXT, end_date TEXT, status TEXT,
  owner TEXT, goal TEXT, keyword TEXT, hashtags TEXT, brief_link TEXT, notes TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS ideas (
  id TEXT PRIMARY KEY, title TEXT, format TEXT, pillar TEXT, campaign TEXT, priority TEXT, status TEXT DEFAULT 'New',
  new_format INTEGER DEFAULT 0, added_by TEXT, details TEXT, example_link TEXT, plan_id TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS shoots (
  id INTEGER PRIMARY KEY, date TEXT, venue TEXT, who TEXT, status TEXT DEFAULT 'Planned', shot_list TEXT,
  questions TEXT, footage_link TEXT, notes TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS growth (
  id INTEGER PRIMARY KEY, date TEXT, followers INTEGER, notes TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS plan_date ON plan(planned_date);
CREATE INDEX IF NOT EXISTS bookings_night ON bookings(night, venue);
CREATE INDEX IF NOT EXISTS bookings_handle ON bookings(ig_handle);
CREATE INDEX IF NOT EXISTS bookings_lead ON bookings(lead_id);
CREATE INDEX IF NOT EXISTS bookings_checkin ON bookings(checkin_changed_at);
CREATE INDEX IF NOT EXISTS leads_created ON leads(created_at);
CREATE INDEX IF NOT EXISTS leads_handle ON leads(ig_handle);
"""

DEFAULT_SETTINGS = {
    "noshow_risk_rate": "0.34",   # 2+ played bookings at or above this no-show rate = No-show risk
    "vip_nights": "5",            # nights out to be a Muse VIP
    "reply_target_min": "5",      # DM reply time target
    "scout_rate_default": "5",
    "timezone": "America/New_York",
    "night_cutoff_hour": "6",     # before 6am, "tonight" still means last night
    # Social
    "follower_goal": "10000",
    "follower_goal_date": "2026-12-15",
    "weekly_reels": "3",          # each social manager, per week
    "weekly_carousels": "1",
    "reel_bonus_views": "100000",
    "reel_bonus_max": "4",        # bonus Reels per person per month
    "creator_tracker_url": "https://hc.retopia.dev/creators",
}


def db_path() -> str:
    return os.getenv("MUSE_DB", "data/muse.db")


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=15, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=15000")
    return con


MIGRATIONS = [("bookings", "checkin_changed_at", "TEXT"), ("venues", "ticket_link_updated_at", "TEXT"),
              ("nights", "dress_code", "TEXT"), ("nights", "cover", "TEXT"), ("nights", "ticket_link", "TEXT"),
              ("venues", "guys_policy", "TEXT"),
              ("venues", "list_closes", "TEXT"), ("nights", "list_closes", "TEXT"),
              ("nights", "guys_policy", "TEXT")]


def init(con: sqlite3.Connection) -> None:
    for table, col, typ in MIGRATIONS:   # add columns to databases created by older versions
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        if cols and col not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    con.executescript(SCHEMA)
    if not con.execute("SELECT 1 FROM venues LIMIT 1").fetchone() and \
            not con.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        seed_venues(con)   # brand-new install: start with Muse's current venues and their pay terms
    # one-off (2026-11-12): NOFLEX has no guys' tickets, only cover at the door. Runs once per database,
    # so changing NOFLEX's Guys' entry on the Venues page later sticks.
    if not con.execute("SELECT 1 FROM settings WHERE key='migrated_noflex_cover'").fetchone():
        for name in COVER_VENUES:
            con.execute("UPDATE venues SET guys_policy='Cover at the door' WHERE upper(name)=? "
                        "AND COALESCE(guys_policy,'') IN ('', 'Ticket')", (name,))
        con.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('migrated_noflex_cover', '1')")
    for k, v in DEFAULT_SETTINGS.items():
        con.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    # one-off (2026-11-17): start the social planner with the campaigns and posts already decided
    if not con.execute("SELECT 1 FROM settings WHERE key='seeded_social_v1'").fetchone():
        from .social_seed import seed_social
        seed_social(con)
        con.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('seeded_social_v1', '1')")
    con.commit()


STARTER_VENUES = [
    # name, nights we run, pay model, rate per girl, cap per night, flat rate, men policy, arrive by
    ("Public Hotel", "Thursday", "Flat per night", None, None, 150, None, None),
    ("Den Social", "", "Flat per night", None, None, 100, "Men welcome", None),
    ("Nebula", "Friday, Saturday", "Per guest (capped)", 12, 180, None, "Girls only", "23:00"),
    ("NOFLEX", "Thursday, Friday", "Per guest (uncapped)", 10, None, None, "Girls only", None),
]
# Venues where guys never buy a ticket, only pay cover at the door (amount typed each Sunday in Weekly setup)
COVER_VENUES = ("NOFLEX",)
NEBULA_CONFIRMATION = ("Heels or leather boots are recommended (please try to avoid sneakers or Uggs). Bring a valid ID "
                       "and try to arrive by 11:00. Just text us when you arrive and our associate [HOST] will come out "
                       "to walk you in. Please let us know if you have any questions.")


def seed_venues(con: sqlite3.Connection) -> None:
    for name, nights, model, rate, cap, flat, men, arrive in STARTER_VENUES:
        con.execute("INSERT OR IGNORE INTO venues(name, nights, pay_model, rate_per_guest, cap_per_night, flat_rate, "
                    "men_policy, arrive_by, status) VALUES (?,?,?,?,?,?,?,?, 'Active')",
                    (name, nights, model, rate, cap, flat, men, arrive))
    for name in COVER_VENUES:
        con.execute("UPDATE venues SET guys_policy='Cover at the door' WHERE upper(name)=?", (name,))
    con.execute("UPDATE venues SET dress_code=?, confirmation_message=? WHERE name='Nebula'",
                ("Heels or leather boots. No sneakers or Uggs.", NEBULA_CONFIRMATION))


@contextmanager
def session(path: str | None = None):
    con = connect(path)
    try:
        yield con
    finally:
        con.close()


def rows(con, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def one(con, sql: str, params=()) -> dict | None:
    r = con.execute(sql, params).fetchone()
    return dict(r) if r else None


def settings(con) -> dict[str, str]:
    return {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM settings")}
