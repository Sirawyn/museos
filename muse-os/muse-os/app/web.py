"""Shared web helpers: templates, formatting, form parsing, ids, audit, renames."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from . import calc, db
from .auth import ROLES, can_delete, can_view, can_write, is_admin
from .schema import ENTITIES, Entity, Field

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))


def money(v) -> str:
    if v in (None, ""):
        return ""
    v = float(v)
    s = f"${abs(v):,.0f}" if v == int(v) else f"${abs(v):,.2f}"
    return "-" + s if v < 0 else s


def pct(v) -> str:
    return "" if v in (None, "") else f"{float(v) * 100:.0f}%"


def nice_date(v) -> str:
    x = calc.d(v)
    return x.strftime("%a %b %-d") if x else (v or "")


def nice_dt(v) -> str:
    x = calc.dt(v)
    return x.strftime("%b %-d, %-I:%M %p").replace(":00 ", " ") if x else (v or "")


def nice_time(v) -> str:
    if not v:
        return ""
    try:
        t = datetime.strptime(str(v)[:5], "%H:%M")
        return t.strftime("%-I:%M %p").replace(":00 ", " ")
    except ValueError:
        return str(v)


def fmt(v, ftype: str = "text") -> str:
    if v in (None, ""):
        return ""
    if ftype == "money":
        return money(v)
    if ftype == "pct":
        return f"{float(v):g}%"
    if ftype == "date":
        return nice_date(v)
    if ftype == "datetime":
        return nice_dt(v)
    if ftype == "time":
        return nice_time(v)
    if ftype == "bool":
        return "Yes" if v in (1, "1", True) else "No"
    if ftype == "ratio":
        return pct(v)
    if isinstance(v, float):
        return f"{v:g}" if v != int(v) else str(int(v))
    return str(v)


COMPUTED_TYPES = {"reply_min": "text", "revenue": "money", "commission": "money", "door_pay": "money",
                  "total": "money", "earned": "money", "paid": "money", "balance": "money", "received": "money",
                  "owed": "money", "signed": "money", "show_rate": "ratio", "no_show_rate": "ratio",
                  "quota_pct": "ratio", "engagement": "ratio", "last_night_out": "date"}


def ctype(key: str) -> str:
    return COMPUTED_TYPES.get(key, "text")


def av(name) -> str:
    """Avatar colour class (av-0..av-5), stable per name."""
    n = str(name or "").lstrip("@").lower()
    return f"av-{sum(map(ord, n)) % 6}"


def initial(name) -> str:
    n = str(name or "").lstrip("@").strip()
    return n[:1].upper() or "?"


templates.env.filters.update(money=money, pct=pct, nice_date=nice_date, nice_dt=nice_dt, nice_time=nice_time, fmt=fmt,
                             av=av, initial=initial)
templates.env.globals.update(WEEKDAY_NAMES=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], ROLES=ROLES, ENTITIES=ENTITIES, can_view=can_view, can_write=can_write,
                             can_delete=can_delete, is_admin=is_admin, ctype=ctype)


def get_pref(con, user: dict, key: str, default=None):
    """Per-person view settings (hidden columns, hidden weekdays), stored on their account so they follow them."""
    import json
    r = con.execute("SELECT value FROM user_prefs WHERE user_id=? AND key=?", (user["id"], key)).fetchone()
    try:
        return json.loads(r[0]) if r else default
    except (ValueError, TypeError):
        return default


def set_pref(con, user: dict, key: str, value) -> None:
    import json
    if value is None:
        con.execute("DELETE FROM user_prefs WHERE user_id=? AND key=?", (user["id"], key))
    else:
        con.execute("INSERT INTO user_prefs(user_id, key, value) VALUES (?,?,?) "
                    "ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value", (user["id"], key, json.dumps(value)))


WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def hidden_days(con, user: dict) -> set[int]:
    return {int(x) for x in (get_pref(con, user, "hidden_days", []) or []) if str(x).isdigit() and 0 <= int(x) < 7}


def tz(con) -> ZoneInfo:
    return ZoneInfo(db.settings(con).get("timezone") or "America/New_York")


def local_now(con) -> datetime:
    return datetime.now(tz(con)).replace(tzinfo=None, microsecond=0)


def tonight(con) -> date:
    """Before the cutoff hour (6am), 'tonight' is still last night, so hosts closing out see the right list."""
    n = local_now(con)
    cutoff = int(db.settings(con).get("night_cutoff_hour") or 6)
    return (n - timedelta(days=1)).date() if n.hour < cutoff else n.date()


def visible_fields(e: Entity, user: dict) -> list[Field]:
    return [f for f in e.fields if is_admin(user) or not f.money]


def visible_computed(e: Entity, user: dict) -> list[tuple[str, str, bool]]:
    return [c for c in e.computed if is_admin(user) or not c[2]]


class FormError(ValueError):
    pass


def parse_value(f: Field, raw):
    if f.type == "bool":
        return 1 if raw in ("1", "on", "true", "TRUE", True, 1) else 0
    raw = (raw or "").strip() if isinstance(raw, str) else raw
    if raw in (None, ""):
        if f.required:
            raise FormError(f"{f.label} is required.")
        return None
    try:
        if f.type == "int":
            return int(float(raw))
        if f.type in ("money", "pct"):
            return round(float(str(raw).replace("$", "").replace(",", "").replace("%", "")), 2)
    except ValueError:
        raise FormError(f"{f.label} must be a number.")
    if f.type == "date":
        if not calc.d(raw):
            raise FormError(f"{f.label} must be a date.")
        return calc.d(raw).isoformat()
    if f.type == "datetime":
        x = calc.dt(raw)
        if not x:
            raise FormError(f"{f.label} must be a date and time.")
        return x.strftime("%Y-%m-%d %H:%M")
    if f.type == "time":
        if not re.fullmatch(r"\d{1,2}:\d{2}", raw):
            raise FormError(f"{f.label} must be a time like 23:00.")
        return raw.zfill(5)
    if f.type == "url" and not re.match(r"https?://", raw):
        raise FormError(f"{f.label} must start with http:// or https://")
    if f.type == "choice" and f.choices and raw not in f.choices:
        raise FormError(f"{f.label}: pick one of the options.")
    if f.name == "ig_handle":
        raw = raw.lstrip("@").strip().lower()
    return str(raw)[:5000]


def next_id(con, e: Entity) -> str:
    prefix = e.id_prefix or ""
    ids = [r[0] for r in con.execute(f"SELECT {e.pk} FROM {e.table} WHERE {e.pk} LIKE ?", (prefix + "%",))]
    nums = [int(m.group(1)) for i in ids if (m := re.fullmatch(re.escape(prefix) + r"(\d+)", i))]
    return f"{prefix}{(max(nums) if nums else 0) + 1:05d}"


def audit(con, actor: str, entity: str, entity_id, action: str, changes: dict | None = None) -> None:
    con.execute("INSERT INTO audit(at, actor, entity, entity_id, action, changes) VALUES (?,?,?,?,?,?)",
                (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), actor, entity, str(entity_id), action,
                 json.dumps(changes or {}, default=str)[:8000]))


def cascade_rename(con, kind: str, old: str, new: str) -> None:
    if not old or old == new:
        return
    if kind == "campaign":
        for t in ("plan", "ideas"):
            con.execute(f"UPDATE {t} SET campaign=? WHERE campaign=? COLLATE NOCASE", (new, old))
        return
    if kind == "venue":
        for t, c in (("leads", "venue"), ("bookings", "venue"), ("nights", "venue"), ("ledger", "venue"),
                     ("team", "home_venue"), ("shoots", "venue")):
            con.execute(f"UPDATE {t} SET {c}=? WHERE {c}=? COLLATE NOCASE", (new, old))
    else:
        for t, c in (("leads", "host"), ("leads", "referred_by"), ("bookings", "host"), ("bookings", "referred_by"),
                     ("bookings", "checked_in_by"), ("nights", "host"), ("content", "creator"), ("ledger", "person"),
                     ("users", "team_name"), ("plan", "owner"), ("campaigns", "owner"), ("ideas", "added_by"),
                     ("shoots", "who")):
            con.execute(f"UPDATE {t} SET {c}=? WHERE {c}=? COLLATE NOCASE", (new, old))


def ensure_night(con, night: str | None, venue: str | None) -> None:
    """A booking at a venue on a date makes that venue night exist, so its revenue is counted."""
    if night and venue:
        con.execute("INSERT OR IGNORE INTO nights(night, venue, updated_at) VALUES (?,?,?)",
                    (night, venue, datetime.now(timezone.utc).isoformat(timespec="seconds")))


def options(con) -> dict:
    return {
        "venues": [r[0] for r in con.execute("SELECT name FROM venues ORDER BY status!='Active', name")],
        "team": db.rows(con, "SELECT name, role, status FROM team ORDER BY status='Inactive', name"),
        "campaigns": [r[0] for r in con.execute("SELECT name FROM campaigns ORDER BY status IN ('Done','Cancelled'), "
                                                "start_date, name")],
    }
