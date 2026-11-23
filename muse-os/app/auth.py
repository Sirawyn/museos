"""Logins, sessions, CSRF and who can see what.

Passwords: scrypt (stdlib). Sessions: a random token in an HttpOnly, SameSite=Lax, Secure cookie; only its SHA-256
is stored, so a leaked database can't be used to log in. Every form post carries a per-session CSRF token.
Failed logins are rate limited per IP and per username.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

ROLES = {
    "admin": "Admin",
    "host": "Host",
    "promoter": "Promoter",
    "social": "Social media",
    "scout": "Scout",
}
TEAM_ROLE_TO_USER = {"Administrator": "admin", "Host": "host", "Promoter": "promoter", "Social Media": "social",
                     "Scout": "scout"}

SESSION_DAYS = 30
COOKIE = "muse_session"


def now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(t: datetime) -> str:
    return t.isoformat()


# ---------- passwords ----------
def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, h = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                              dklen=len(base64.b64decode(h)))
        return hmac.compare_digest(calc, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


DUMMY_HASH = hash_password(secrets.token_hex(8))  # equal-time check for unknown usernames


def password_problem(pw: str, username: str = "") -> str | None:
    if len(pw) < 10:
        return "Use at least 10 characters."
    if username and username.lower() in pw.lower():
        return "Don't put your username in your password."
    if pw.lower() in {"password123", "musehospitality", "1234567890", "qwertyuiop"}:
        return "That password is too common."
    return None


def sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------- invite links ----------
INVITE_DAYS = 7


def create_invite(con, user_id: int, by: str = "") -> str:
    """One-time link that lets a person choose their own password. Replaces any earlier link for them."""
    token = secrets.token_urlsafe(32)
    t = now()
    con.execute("DELETE FROM invites WHERE user_id=?", (user_id,))
    con.execute("INSERT INTO invites(token_hash, user_id, created_at, expires_at, created_by) VALUES (?,?,?,?,?)",
                (sha(token), user_id, iso(t), iso(t + timedelta(days=INVITE_DAYS)), by))
    return token


def load_invite(con, token: str | None) -> dict | None:
    if not token or len(token) > 100:
        return None
    r = con.execute("SELECT i.token_hash, i.expires_at, u.* FROM invites i JOIN users u ON u.id=i.user_id "
                    "WHERE i.token_hash=? AND u.active=1", (sha(token),)).fetchone()
    if not r:
        return None
    r = dict(r)
    return r if r["expires_at"] > iso(now()) else None


def use_invite(con, token: str, pw: str) -> None:
    inv = load_invite(con, token)
    con.execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?", (hash_password(pw), inv["id"]))
    con.execute("DELETE FROM invites WHERE user_id=?", (inv["id"],))
    end_all_sessions(con, inv["id"])


# ---------- sessions ----------
def create_session(con, user_id: int, ip: str, ua: str) -> str:
    token = secrets.token_urlsafe(32)
    t = now()
    con.execute("INSERT INTO sessions(token_hash, user_id, csrf, created_at, last_seen_at, expires_at, ip, user_agent)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (sha(token), user_id, secrets.token_urlsafe(24), iso(t), iso(t), iso(t + timedelta(days=SESSION_DAYS)),
                 ip, (ua or "")[:200]))
    con.execute("UPDATE users SET last_login_at=? WHERE id=?", (iso(t), user_id))
    con.execute("DELETE FROM sessions WHERE expires_at < ?", (iso(t),))
    con.commit()
    return token


def load_session(con, token: str | None) -> dict | None:
    if not token:
        return None
    row = con.execute(
        "SELECT s.token_hash, s.csrf, s.expires_at, s.last_seen_at, u.* FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.token_hash=?", (sha(token),)).fetchone()
    if not row:
        return None
    u = dict(row)
    if u["expires_at"] < iso(now()) or not u["active"]:
        con.execute("DELETE FROM sessions WHERE token_hash=?", (u["token_hash"],))
        con.commit()
        return None
    if u["last_seen_at"] < iso(now() - timedelta(minutes=5)):
        con.execute("UPDATE sessions SET last_seen_at=? WHERE token_hash=?", (iso(now()), u["token_hash"]))
        con.commit()
    u.pop("password_hash", None)
    return u


def end_session(con, token: str | None) -> None:
    if token:
        con.execute("DELETE FROM sessions WHERE token_hash=?", (sha(token),))
        con.commit()


def end_all_sessions(con, user_id: int, except_hash: str | None = None) -> None:
    con.execute("DELETE FROM sessions WHERE user_id=? AND token_hash IS NOT ?", (user_id, except_hash))
    con.commit()


# ---------- login throttling ----------
class Throttle:
    def __init__(self, limit: int = 8, window: int = 900):
        self.limit, self.window = limit, window
        self.hits: dict[str, deque] = defaultdict(deque)

    def _trim(self, key):
        q = self.hits[key]
        while q and q[0] < time.time() - self.window:
            q.popleft()
        return q

    def blocked(self, *keys) -> bool:
        return any(len(self._trim(k)) >= self.limit for k in keys)

    def fail(self, *keys) -> None:
        for k in keys:
            self._trim(k).append(time.time())

    def clear(self, *keys) -> None:
        for k in keys:
            self.hits.pop(k, None)


throttle = Throttle()


# ---------- API keys (DM bot) ----------
def create_api_key(con, name: str) -> str:
    key = "muse_" + secrets.token_urlsafe(32)
    con.execute("INSERT INTO api_keys(name, key_hash, prefix, created_at) VALUES (?,?,?,?)",
                (name, sha(key), key[:10], iso(now())))
    con.commit()
    return key


def check_api_key(con, key: str) -> dict | None:
    row = con.execute("SELECT * FROM api_keys WHERE key_hash=? AND revoked=0", (sha(key),)).fetchone()
    if row:
        con.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (iso(now()), row["id"]))
        con.commit()
        return dict(row)
    return None


# ---------- permissions ----------
# What each role can open. Hosts and promoters are scoped to their own rows (see scope()).
SOCIAL_PAGES = ["social", "calendar", "plan", "campaigns", "ideas", "shoots", "growth"]
SOCIAL_TABLES = {"plan", "campaigns", "ideas", "shoots", "growth"}
PAGES = {
    "admin": ["dashboard", "tonight", "leads", "guests", "bookings", "nights", "venues", "team", "content", "ledger",
              *SOCIAL_PAGES],
    "host": ["dashboard", "tonight", "leads", "guests", "bookings", "nights", "venues"],
    "promoter": ["dashboard", "tonight", "leads", "guests", "bookings", "nights", "venues"],
    "social": ["dashboard", "content", "venues", *SOCIAL_PAGES],
    "scout": ["dashboard"],
}
CAN_WRITE = {
    "admin": {"leads", "guests", "bookings", "nights", "venues", "team", "content", "ledger", *SOCIAL_TABLES},
    "host": {"leads", "guests", "bookings"},
    "promoter": {"leads", "guests", "bookings"},
    "social": {"content", *SOCIAL_TABLES},
    "scout": set(),
}


def is_admin(u: dict) -> bool:
    return u["role"] == "admin"


def is_staff(u: dict) -> bool:
    return u["role"] in ("host", "promoter")


def can_view(u: dict, page: str) -> bool:
    return page in PAGES.get(u["role"], [])


def can_write(u: dict, entity: str) -> bool:
    return entity in CAN_WRITE.get(u["role"], set())


def can_delete(u: dict, entity: str) -> bool:
    return is_admin(u)


def scope(u: dict, entity: str) -> tuple[str, list]:
    """SQL WHERE fragment limiting rows to what this user may see."""
    if is_admin(u) or entity in ("venues",) or (u["role"] == "social" and (entity == "content" or entity in SOCIAL_TABLES)):
        return "1=1", []
    me = u.get("team_name") or "\x00no-team"
    if is_staff(u):
        on_duty = "(SELECT 1 FROM nights n WHERE n.night=bookings.night AND n.venue=bookings.venue AND n.host=? COLLATE NOCASE)"
        if entity == "bookings":
            return f"(host=? COLLATE NOCASE OR EXISTS {on_duty})", [me, me]
        if entity == "leads":
            return "host=? COLLATE NOCASE", [me]
        if entity == "nights":
            return "host=? COLLATE NOCASE", [me]
        if entity == "guests":
            return ("(ig_handle IN (SELECT ig_handle FROM leads WHERE host=? COLLATE NOCASE) OR ig_handle IN "
                    f"(SELECT ig_handle FROM bookings WHERE host=? COLLATE NOCASE OR EXISTS {on_duty}))"), [me, me, me]
    return "0=1", []
