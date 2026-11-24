"""API for the DM bot. Auth: `Authorization: Bearer <key>` from Admin > API keys.

  PUT  /api/v1/leads/{lead_id}        upsert a lead (the bot's DM-00001 ids)
  PUT  /api/v1/guests/{ig_handle}     add a guest; existing guests are left alone (tags and notes stay)
  PUT  /api/v1/bookings/{booking_id}  upsert a booking; never overwrites a host's check-in
  GET  /api/v1/venues                 nights we run, confirmation message, ticket link, host, door info
  GET  /api/v1/scouts                 active scouts (name, IG handle)
  GET  /api/v1/checkins?since=...     bookings checked in or marked no-show in the app, for the bot's follow-ups
"""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, field_validator

from . import auth, db
from .schema import BOOKING_STATUS, CHANNELS, LEAD_STATUS
from .web import audit, ensure_night, local_now

router = APIRouter(prefix="/api/v1")
ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
FINAL = {"Arrived", "No-show", "Cancelled"}
LEAD_RANK = {s: i for i, s in enumerate(LEAD_STATUS)}


def get_con():
    con = db.connect()
    try:
        yield con
    finally:
        con.close()


def bot(request: Request, con=Depends(get_con)) -> dict:
    h = request.headers.get("authorization", "")
    key = h[7:].strip() if h.lower().startswith("bearer ") else ""
    k = auth.check_api_key(con, key) if key else None
    if not k:
        raise HTTPException(401, "missing or bad API key", headers={"WWW-Authenticate": "Bearer"})
    return k


def _id(v: str) -> str:
    if not ID_RE.match(v):
        raise HTTPException(400, "bad id")
    return v


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=5000)


class LeadIn(Strict):
    created_at: str | None = None
    channel: str | None = None
    ig_handle: str | None = None
    name: str | None = None
    night: str | None = None
    venue: str | None = None
    party_size: int | None = None
    girls: int | None = None
    guys: int | None = None
    status: str | None = None
    host: str | None = None
    first_reply_at: str | None = None
    source_content_id: str | None = None
    last_message_at: str | None = None
    notes: str | None = None
    referred_by: str | None = None

    @field_validator("status")
    @classmethod
    def _st(cls, v):
        if v is not None and v not in LEAD_STATUS:
            raise ValueError(f"status must be one of {LEAD_STATUS}")
        return v

    @field_validator("channel")
    @classmethod
    def _ch(cls, v):
        return v if v is None or v in CHANNELS else "Other"


class GuestIn(Strict):
    name: str | None = None
    phone: str | None = None
    first_contact: str | None = None
    first_channel: str | None = None
    first_content_id: str | None = None
    tags: str | None = None
    notes: str | None = None


class BookingIn(Strict):
    night: str
    venue: str
    ig_handle: str
    lead_id: str | None = None
    host: str | None = None
    stop: int | None = 1
    party_size: int | None = None
    girls: int | None = None
    guys: int | None = None
    status: str | None = "Confirmed"
    girls_arrived: int | None = None
    confirmation_sent: bool | None = None
    thank_you_sent: bool | None = None
    notes: str | None = None
    referred_by: str | None = None

    @field_validator("status")
    @classmethod
    def _st(cls, v):
        if v is not None and v not in BOOKING_STATUS:
            raise ValueError(f"status must be one of {BOOKING_STATUS}")
        return v


def _clean_handle(h: str | None) -> str | None:
    return h.lstrip("@").strip().lower() if h else h


def _upsert(con, table: str, pk: str, key: str, vals: dict, actor: str) -> str:
    vals = {k: v for k, v in vals.items() if v is not None}
    vals["updated_at"] = local_now(con).strftime("%Y-%m-%d %H:%M")
    if table in ("leads", "bookings"):
        vals["updated_by"] = actor
    exists = con.execute(f"SELECT 1 FROM {table} WHERE {pk}=?", (key,)).fetchone()
    if exists:
        con.execute(f"UPDATE {table} SET {', '.join(k + '=?' for k in vals)} WHERE {pk}=?", (*vals.values(), key))
        return "updated"
    vals[pk] = key
    con.execute(f"INSERT INTO {table} ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})", list(vals.values()))
    return "created"


@router.put("/leads/{lead_id}")
def put_lead(lead_id: str, body: LeadIn, con=Depends(get_con), k=Depends(bot)):
    _id(lead_id)
    vals = body.model_dump(exclude_unset=True)
    vals["ig_handle"] = _clean_handle(vals.get("ig_handle"))
    old = db.one(con, "SELECT status FROM leads WHERE id=?", (lead_id,))
    # A host's check-in in the app wins over the bot's view of the night
    if old and old["status"] in ("Arrived", "No-show") and vals.get("status") in ("New", "Qualifying", "Qualified", "Confirmed"):
        vals.pop("status")
    res = _upsert(con, "leads", "id", lead_id, vals, "api:" + k["name"])
    if vals.get("ig_handle"):
        con.execute("INSERT OR IGNORE INTO guests(ig_handle, name, first_contact, first_channel, notes, updated_at) "
                    "VALUES (?,?,?,?,?,?)", (vals["ig_handle"], vals.get("name"), (vals.get("created_at") or "")[:10] or None,
                                             vals.get("channel"), "Added by DM bot", vals.get("created_at")))
    audit(con, "api:" + k["name"], "leads", lead_id, res, vals)
    con.commit()
    return {"ok": True, "result": res, "id": lead_id}


@router.put("/guests/{ig_handle}")
def put_guest(ig_handle: str, body: GuestIn, overwrite: bool = False, con=Depends(get_con), k=Depends(bot)):
    h = _clean_handle(_id(ig_handle))
    vals = body.model_dump(exclude_unset=True)
    if db.one(con, "SELECT 1 FROM guests WHERE ig_handle=?", (h,)) and not overwrite:
        return {"ok": True, "result": "exists", "id": h}
    res = _upsert(con, "guests", "ig_handle", h, vals, "api:" + k["name"])
    audit(con, "api:" + k["name"], "guests", h, res, vals)
    con.commit()
    return {"ok": True, "result": res, "id": h}


@router.put("/bookings/{booking_id}")
def put_booking(booking_id: str, body: BookingIn, con=Depends(get_con), k=Depends(bot)):
    _id(booking_id)
    vals = body.model_dump(exclude_unset=True)
    vals["ig_handle"] = _clean_handle(vals["ig_handle"])
    for b in ("confirmation_sent", "thank_you_sent"):
        if b in vals and vals[b] is not None:
            vals[b] = int(vals[b])
    old = db.one(con, "SELECT status, girls_arrived, checked_in_by FROM bookings WHERE id=?", (booking_id,))
    if old and old["status"] in FINAL and old.get("checked_in_by"):
        # a host already settled this booking at the door: keep their status and count
        vals.pop("status", None)
        vals.pop("girls_arrived", None)
    if old:
        vals.pop("host", None)   # once a booking exists, its host is managed in the app
    else:
        duty = db.one(con, "SELECT host FROM nights WHERE night=? AND venue=? COLLATE NOCASE AND IFNULL(host,'')!=''",
                      (vals["night"], vals["venue"]))
        if duty:
            vals["host"] = duty["host"]   # the host on duty that night walks them in and gets the credit
    res = _upsert(con, "bookings", "id", booking_id, vals, "api:" + k["name"])
    ensure_night(con, vals.get("night"), vals.get("venue"))
    audit(con, "api:" + k["name"], "bookings", booking_id, res, vals)
    con.commit()
    return {"ok": True, "result": res, "id": booking_id}


GUYS_POLICY_CODE = {"Ticket": "ticket", "Cover at the door": "cover", "Free": "free", "Ask the team": "ask"}


@router.get("/venues")
def venues(con=Depends(get_con), k=Depends(bot)):
    out = []
    today = local_now(con).date().isoformat()
    for v in db.rows(con, "SELECT * FROM venues ORDER BY name"):
        nights = [n.strip().lower() for n in re.split(r"[,/&]| and ", v.get("nights") or "") if n.strip()]
        upcoming = [{"night": n["night"], "host": n["host"], "dress_code": n["dress_code"] or v.get("dress_code") or None,
                     "cover": n["cover"] or None, "ticket_link": n["ticket_link"] or None,
                     "list_closes": n["list_closes"] or None,
                     "guys_policy": GUYS_POLICY_CODE.get(n["guys_policy"] or "")}
                    for n in db.rows(con, "SELECT night, host, dress_code, cover, ticket_link, list_closes, guys_policy "
                                          "FROM nights WHERE venue=? AND night>=? "
                                          "ORDER BY night LIMIT 14", (v["name"], today))]
        out.append({"name": v["name"], "status": v.get("status"), "nights": nights,
                    "confirmation_message": v.get("confirmation_message") or "", "ticket_link": v.get("ticket_link") or "",
                    "arrive_by": v.get("arrive_by"), "dress_code": v.get("dress_code"), "men_policy": v.get("men_policy"),
                    "guys_policy": GUYS_POLICY_CODE.get(v.get("guys_policy") or ""),
                    "list_closes": v.get("list_closes") or None,
                    "upcoming": upcoming})
    return {"venues": out}


@router.get("/scouts")
def scouts(con=Depends(get_con), k=Depends(bot)):
    return {"scouts": db.rows(con, "SELECT name, ig_handle AS handle FROM team WHERE role='Scout' "
                                   "AND IFNULL(status,'') NOT IN ('Inactive') ORDER BY name")}


@router.get("/checkins")
def checkins(since: str = "", con=Depends(get_con), k=Depends(bot)):
    """Every booking a host checked in, marked no-show, or undid at or after `since` (pass back the previous
    response's `now`). Entries can repeat across calls, so apply them idempotently."""
    rows = db.rows(con, "SELECT id, lead_id, night, venue, ig_handle, status, girls, girls_arrived, checked_in_at, "
                        "checkin_changed_at AS changed_at FROM bookings WHERE checkin_changed_at >= ? "
                        "ORDER BY checkin_changed_at", (since or "0",))
    return {"bookings": rows, "now": local_now(con).strftime("%Y-%m-%d %H:%M:%S")}
