"""All of Muse OS's calculations. Every number on the Dashboard, Nights, Venues, Team, Guests, Leads and Content
tabs comes from here, so the revenue rules live in one place:

  Flat per night        door pay = the venue's flat rate, or the night's override (Public Hotel $150, Den Social $100)
  Per guest (capped)    door pay = girls arrived x rate, up to the cap   (Nebula $12/girl, cap $180 = 15 girls)
  Per guest (uncapped)  door pay = girls arrived x rate                  (NOFLEX $10/girl)
  + table/bottle commission = table spend x the venue's commission %

Girls counted for a booking = girls arrived if the host entered a count, otherwise the booked girls, and only when
the booking is Arrived. Scouts earn their rate per counted girl, at per-girl venues only.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import db
from .schema import INCOME_TYPES, PER_GIRL_MODELS


def num(v) -> float:
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def d(v) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def dt(v) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("T", " ")[:16])
    except ValueError:
        return None


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def months_between(start: date, today: date) -> int:
    """Whole months from start to today."""
    m = (today.year - start.year) * 12 + today.month - start.month
    if today.day < start.day:
        m -= 1
    return max(m, 0)


def girls_counted(b: dict) -> int:
    if b.get("status") != "Arrived":
        return 0
    if b.get("girls_arrived") not in (None, ""):
        return int(num(b["girls_arrived"]))
    return int(num(b.get("girls")))


def commission_rate(venue: dict | None) -> float:
    """Stored as a percent (10 = 10%)."""
    return num((venue or {}).get("commission_pct")) / 100


def door_pay(venue: dict | None, girls_arrived: int, flat_override=None) -> float:
    if not venue:
        return 0.0
    model = venue.get("pay_model") or ""
    if model == "Flat per night":
        return num(flat_override) if flat_override not in (None, "") else num(venue.get("flat_rate"))
    gross = girls_arrived * num(venue.get("rate_per_guest"))
    cap = num(venue.get("cap_per_night"))
    if model == "Per guest (capped)" and cap > 0 and gross > cap:
        return cap
    return gross


@dataclass
class World:
    venues: dict[str, dict]
    team: dict[str, dict]
    leads: list[dict]
    guests: list[dict]
    bookings: list[dict]
    nights: list[dict]
    content: list[dict]
    ledger: list[dict]
    settings: dict[str, str]
    today: date

    @classmethod
    def load(cls, con, today: date) -> "World":
        return cls(
            venues={v["name"].lower(): v for v in db.rows(con, "SELECT * FROM venues")},
            team={t["name"].lower(): t for t in db.rows(con, "SELECT * FROM team")},
            leads=db.rows(con, "SELECT * FROM leads"),
            guests=db.rows(con, "SELECT * FROM guests"),
            bookings=db.rows(con, "SELECT * FROM bookings"),
            nights=db.rows(con, "SELECT * FROM nights"),
            content=db.rows(con, "SELECT * FROM content"),
            ledger=db.rows(con, "SELECT * FROM ledger"),
            settings=db.settings(con),
            today=today,
        )

    def venue(self, name) -> dict | None:
        return self.venues.get((name or "").lower())

    def member(self, name) -> dict | None:
        return self.team.get((name or "").lower())

    # ---------- bookings ----------
    def lead_by_id(self) -> dict[str, dict]:
        if not hasattr(self, "_leads_by_id"):
            self._leads_by_id = {l["id"]: l for l in self.leads}
        return self._leads_by_id

    def first_visits(self) -> dict[str, tuple]:
        """Each guest's first night in through Muse: handle -> (night, stop, id) of their earliest Arrived booking."""
        if not hasattr(self, "_first_visits"):
            first: dict[str, tuple] = {}
            for b in self.bookings:
                h = (b.get("ig_handle") or "").lower()
                if h and b.get("status") == "Arrived":
                    k = (b.get("night") or "", int(num(b.get("stop")) or 1), b.get("id") or "")
                    if h not in first or k < first[h]:
                        first[h] = k
            self._first_visits = first
        return self._first_visits

    def is_first_time(self, b: dict) -> bool:
        """True unless this guest already got in on an earlier booking. Scouts are only paid for first-time girls."""
        h = (b.get("ig_handle") or "").lower()
        first = self.first_visits().get(h)
        if not h or not first:
            return True
        return (b.get("night") or "", int(num(b.get("stop")) or 1), b.get("id") or "") <= first

    def scout_for(self, b: dict) -> str:
        """The scout who gets paid for this booking: per-girl venue and the guest's first time in."""
        v = self.venue(b.get("venue"))
        if not v or (v.get("pay_model") or "") not in PER_GIRL_MODELS:
            return ""
        if not self.is_first_time(b):
            return ""
        if b.get("referred_by"):
            return b["referred_by"]
        lead = self.lead_by_id().get(b.get("lead_id") or "")
        return (lead or {}).get("referred_by") or ""

    def booking_commission(self, b: dict) -> float:
        return num(b.get("table_spend")) * commission_rate(self.venue(b.get("venue")))

    def booking_row(self, b: dict) -> dict:
        v = self.venue(b.get("venue"))
        per_girl = bool(v) and (v.get("pay_model") or "") != "Flat per night"
        g = girls_counted(b)
        com = self.booking_commission(b)
        return {"girls_counted": g, "commission": round(com, 2),
                "revenue": round(g * num((v or {}).get("rate_per_guest")) * per_girl + com, 2),
                "scout": self.scout_for(b)}

    # ---------- nights ----------
    def night_keys(self) -> list[tuple[str, str]]:
        """Every (night, venue) with a Nights row or a booking."""
        keys = {(n["night"], n["venue"].lower()) for n in self.nights}
        keys |= {(b["night"], (b["venue"] or "").lower()) for b in self.bookings if b.get("night") and b.get("venue")}
        return sorted(keys)

    def night_row(self, night: str, venue: str, flat_override=None) -> dict:
        bs = [b for b in self.bookings if b.get("night") == night and (b.get("venue") or "").lower() == venue.lower()]
        v = self.venue(venue)
        confirmed = sum(int(num(b.get("girls"))) for b in bs if b.get("status") != "Cancelled")
        arrived = sum(girls_counted(b) for b in bs)
        door = door_pay(v, arrived, flat_override)
        com = sum(self.booking_commission(b) for b in bs)
        return {"girls_confirmed": confirmed, "girls_arrived": arrived,
                "show_rate": arrived / confirmed if confirmed else 0,
                "pay_model": (v or {}).get("pay_model") or ("Venue not set up" if not v else ""),
                "door_pay": round(door, 2), "commission": round(com, 2), "total": round(door + com, 2)}

    def all_nights(self) -> list[dict]:
        if "_nights" in self.__dict__:
            return self._nights
        explicit = {(n["night"], n["venue"].lower()): n for n in self.nights}
        out = []
        for night, vkey in self.night_keys():
            n = explicit.get((night, vkey))
            venue_name = n["venue"] if n else (self.venue(vkey) or {}).get("name", vkey)
            row = {"night": night, "venue": venue_name, "host": (n or {}).get("host"), "id": (n or {}).get("id"),
                   "dress_code": (n or {}).get("dress_code"), "cover": (n or {}).get("cover"),
                   "ticket_link": (n or {}).get("ticket_link"), "list_closes": (n or {}).get("list_closes"),
                   "guys_policy": (n or {}).get("guys_policy")}
            row.update(self.night_row(night, venue_name, (n or {}).get("flat_override")))
            out.append(row)
        self._nights = out
        return out

    # ---------- guests ----------
    def guest_stats(self) -> dict[str, dict]:
        risk, vip = num(self.settings.get("noshow_risk_rate", 0.34)), num(self.settings.get("vip_nights", 5))
        by = defaultdict(lambda: {"bookings": 0, "nights_out": 0, "no_shows": 0, "last_night_out": None})
        for b in self.bookings:
            h = (b.get("ig_handle") or "").lower()
            if not h:
                continue
            s = by[h]
            if b.get("status") != "Cancelled":
                s["bookings"] += 1
            if b.get("status") == "Arrived":
                s["nights_out"] += 1
                if not s["last_night_out"] or (b.get("night") or "") > s["last_night_out"]:
                    s["last_night_out"] = b.get("night")
            elif b.get("status") == "No-show":
                s["no_shows"] += 1
        out = {}
        for h, s in by.items():
            played = s["nights_out"] + s["no_shows"]
            s["no_show_rate"] = s["no_shows"] / played if played else 0
            if played >= 2 and s["no_show_rate"] >= risk:
                s["tier"] = "No-show risk"
            elif s["nights_out"] >= vip:
                s["tier"] = "Muse VIP"
            elif s["nights_out"] >= 1:
                s["tier"] = "Muse Girl"
            else:
                s["tier"] = "Prospect"
            out[h] = s
        return out

    def guest_row(self, g: dict, stats=None) -> dict:
        stats = stats if stats is not None else self.guest_stats()
        return stats.get((g.get("ig_handle") or "").lower(),
                         {"bookings": 0, "nights_out": 0, "no_shows": 0, "no_show_rate": 0,
                          "last_night_out": None, "tier": "Prospect"})

    # ---------- leads ----------
    def lead_row(self, l: dict, stats=None, brows=None) -> dict:
        stats = stats if stats is not None else self.guest_stats()
        a, r = dt(l.get("created_at")), dt(l.get("first_reply_at"))
        bs = [b for b in self.bookings if b.get("lead_id") == l["id"]]
        tier = "New"
        h = (l.get("ig_handle") or "").lower()
        if h and any((g.get("ig_handle") or "").lower() == h for g in self.guests):
            tier = stats.get(h, {}).get("tier", "Prospect")
        elif h in stats:
            tier = stats[h]["tier"]
        return {"reply_min": round((r - a).total_seconds() / 60, 1) if a and r else None,
                "guests_arrived": sum(girls_counted(b) for b in bs),
                "revenue": round(sum(self.booking_row(b)["revenue"] for b in bs), 2),
                "tier": tier}

    # ---------- team ----------
    def team_row(self, t: dict) -> dict:
        name = t["name"].lower()
        mine = [b for b in self.bookings if (b.get("host") or "").lower() == name]
        confirmed = sum(int(num(b.get("girls"))) for b in mine if b.get("status") != "Cancelled")
        arrived = sum(girls_counted(b) for b in mine)
        played = sum(int(num(b.get("girls"))) for b in mine if b.get("status") in ("Arrived", "No-show"))
        nights = sum(1 for n in self.nights if (n.get("host") or "").lower() == name)
        leads = sum(1 for l in self.leads if (l.get("host") or "").lower() == name)
        referred = sum(girls_counted(b) for b in self.bookings if self.scout_for(b).lower() == name)
        rate, pt = num(t.get("pay_rate")), t.get("pay_type") or ""
        if pt == "Per guest":
            earned = arrived * rate
        elif pt == "Per night":
            earned = nights * rate
        elif pt == "Per girl referred":
            earned = referred * rate
        elif pt == "Monthly flat" and d(t.get("start_date")):
            earned = rate * (months_between(d(t["start_date"]), self.today) + 1)
        else:
            earned = 0
        paid = sum(num(x.get("amount")) for x in self.ledger
                   if (x.get("person") or "").lower() == name and x.get("status") == "Paid")
        return {"girls_confirmed": confirmed, "girls_arrived": arrived, "show_rate": arrived / played if played else 0,
                "nights_worked": nights, "leads_handled": leads, "earned": round(earned, 2), "paid": round(paid, 2),
                "balance": round(earned - paid, 2), "referred": referred}

    # ---------- venues ----------
    def venue_row(self, v: dict, week: date | None = None) -> dict:
        week = week or week_start(self.today)
        name = v["name"].lower()
        wk = [b for b in self.bookings if (b.get("venue") or "").lower() == name and d(b.get("night"))
              and week <= d(b["night"]) < week + timedelta(days=7)]
        girls = sum(girls_counted(b) for b in wk)
        quota = num(v.get("weekly_quota"))
        earned = sum(n["total"] for n in self.all_nights() if n["venue"].lower() == name)
        received = sum(num(x.get("amount")) for x in self.ledger if (x.get("venue") or "").lower() == name
                       and x.get("status") == "Paid" and x.get("type") in ("Venue payment", "Table/bottle commission"))
        return {"girls_week": girls, "quota_pct": girls / quota if quota else 0, "earned": round(earned, 2),
                "received": round(received, 2), "owed": round(earned - received, 2)}

    # ---------- content ----------
    def content_row(self, c: dict) -> dict:
        pid = c["post_id"]
        views = num(c.get("views"))
        eng = sum(num(c.get(k)) for k in ("likes", "comments", "shares", "saves"))
        leads = [l for l in self.leads if l.get("source_content_id") == pid]
        stats = None
        girls = rev = 0
        for l in leads:
            r = self.lead_row(l, stats or {})
            girls += r["guests_arrived"]
            rev += r["revenue"]
        return {"engagement": eng / views if views else 0, "dms": len(leads), "girls_out": girls,
                "revenue": round(rev, 2), "dms_per_10k": len(leads) / views * 10000 if views else 0}

    def ledger_row(self, x: dict) -> dict:
        amt = num(x.get("amount"))
        return {"signed": amt if x.get("type") in INCOME_TYPES else -amt, "month": (x.get("date") or "")[:7]}

    # ---------- dashboard ----------
    def dashboard(self, week: date) -> dict:
        end = week + timedelta(days=7)
        in_week = lambda v: (d(v) is not None) and week <= d(v) < end
        wl = [l for l in self.leads if in_week(l.get("created_at"))]
        wb = [b for b in self.bookings if in_week(b.get("night"))]
        st = lambda s: sum(1 for l in wl if l.get("status") in s)
        views = sum(num(c.get("views")) for c in self.content if in_week(c.get("date_posted")))
        funnel = [("Content views (posts this week)", int(views)), ("DMs received", len(wl)),
                  ("Leads qualified", st({"Qualified", "Confirmed", "Arrived", "No-show"})),
                  ("Leads confirmed", st({"Confirmed", "Arrived", "No-show"})),
                  ("Leads that showed up", st({"Arrived"}))]
        funnel = [(label, n, (n / funnel[i - 1][1] if i and funnel[i - 1][1] else None))
                  for i, (label, n) in enumerate(funnel)]
        confirmed = sum(int(num(b.get("girls"))) for b in wb if b.get("status") != "Cancelled")
        arrived = sum(girls_counted(b) for b in wb)
        played = sum(int(num(b.get("girls"))) for b in wb if b.get("status") in ("Arrived", "No-show"))
        nights = [n for n in self.all_nights() if in_week(n["night"])]
        revenue = sum(n["total"] for n in nights)
        replies = [r for r in (self.lead_row(l, {})["reply_min"] for l in wl) if r is not None]
        target = num(self.settings.get("reply_target_min", 5))
        stats = self.guest_stats()
        played_all = sum(1 for b in self.bookings if b.get("status") in ("Arrived", "No-show"))
        noshow_all = sum(1 for b in self.bookings if b.get("status") == "No-show")

        venues = []
        for v in sorted(self.venues.values(), key=lambda v: v["name"].lower()):
            if v.get("status") != "Active":
                continue
            vr = self.venue_row(v, week)
            venues.append({"name": v["name"], "quota": int(num(v.get("weekly_quota"))), "girls": vr["girls_week"],
                           "quota_pct": vr["quota_pct"],
                           "revenue": round(sum(n["total"] for n in nights if n["venue"].lower() == v["name"].lower()), 2)})
        team = []
        for t in sorted(self.team.values(), key=lambda t: t["name"].lower()):
            if t.get("status") == "Inactive":
                continue
            n = t["name"].lower()
            mine = [b for b in wb if (b.get("host") or "").lower() == n]
            a = sum(girls_counted(b) for b in mine)
            p = sum(int(num(b.get("girls"))) for b in mine if b.get("status") in ("Arrived", "No-show"))
            team.append({"name": t["name"], "role": t.get("role"), "girls_arrived": a, "show_rate": a / p if p else 0,
                         "leads": sum(1 for l in wl if (l.get("host") or "").lower() == n)})
        scouts = [{"name": t["name"], "girls": sum(girls_counted(b) for b in wb if self.scout_for(b).lower() == t["name"].lower())}
                  for t in self.team.values() if t.get("role") == "Scout" and t.get("status") != "Inactive"]
        content = sorted(({**c, **self.content_row(c)} for c in self.content), key=lambda c: -c["dms"])[:10]
        formats = defaultdict(lambda: {"posts": 0, "dms": 0, "views": 0})
        for c in self.content:
            f = formats[c.get("format") or "Other"]
            f["posts"] += 1
            f["dms"] += sum(1 for l in self.leads if l.get("source_content_id") == c["post_id"])
            f["views"] += num(c.get("views"))
        fmt = sorted(({"format": k, **v, "dms_per_post": v["dms"] / v["posts"] if v["posts"] else 0}
                      for k, v in formats.items()), key=lambda f: -f["dms_per_post"])

        month = week.replace(day=1)
        nm = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
        in_month = lambda v: (d(v) is not None) and month <= d(v) < nm
        paid = lambda types: sum(num(x.get("amount")) for x in self.ledger if x.get("type") in types
                                 and x.get("status") == "Paid" and in_month(x.get("date")))
        m_rev = sum(n["total"] for n in self.all_nights() if in_month(n["night"]))
        cash_in, other = paid({"Venue payment", "Table/bottle commission"}), paid({"Other income"})
        payouts, expenses = paid({"Host payout", "Social payout", "Scout payout", "Engineer payout"}), paid({"Expense"})
        owed_team = sum(self.team_row(t)["balance"] for t in self.team.values())
        owed_venues = sum(self.venue_row(v)["owed"] for v in self.venues.values())
        return {
            "week": week, "week_end": end - timedelta(days=1), "funnel": funnel,
            "girls_confirmed": confirmed, "girls_arrived": arrived, "show_rate": arrived / played if played else 0,
            "revenue": round(revenue, 2), "rev_per_girl": revenue / arrived if arrived else 0,
            "median_reply": statistics.median(replies) if replies else 0, "reply_target": target,
            "within_target": (sum(1 for r in replies if r <= target) / len(wl)) if wl else 0,
            "no_reply": sum(1 for l in wl if not l.get("first_reply_at")),
            "muse_girls": sum(1 for s in stats.values() if s["nights_out"] >= 1),
            "vips": sum(1 for s in stats.values() if s["tier"] == "Muse VIP"),
            "risk": sum(1 for s in stats.values() if s["tier"] == "No-show risk"),
            "noshow_rate_all": noshow_all / played_all if played_all else 0,
            "venues": venues, "team": team, "scouts": scouts, "top_posts": content, "formats": fmt,
            "month": month, "month_revenue": round(m_rev, 2), "cash_in": cash_in, "other_income": other,
            "payouts": payouts, "expenses": expenses, "net_cash": cash_in + other - payouts - expenses,
            "owed_team": round(owed_team, 2), "owed_venues": round(owed_venues, 2),
        }
