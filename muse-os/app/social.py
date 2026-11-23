"""Social: the planning side of Muse's Instagram.

Pages: /social (the team's hub: this week's board, approvals, goals, campaigns, shoots, ideas) and /calendar (month view).
The plan, campaigns, ideas, shoots and follower log tabs are ordinary Muse OS tabs (schema.py); this module adds their
calculated columns, the approval rule, and the one-tap actions (approve, send back, move an idea onto the calendar,
log today's follower count).

Approval rule: a post marked "Needs founder approval" (new formats, series, collabs) can't be Approved, Scheduled or
Posted until an admin approves it. Only admins can approve. Marking a post Posted logs it on the Content tab, where its
views and DMs are tracked.
"""
from __future__ import annotations

import calendar as pycal
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import calc, db
from .auth import can_view, can_write, is_admin
from .schema import NEEDS_OK, PLAN_STATUS
from .web import FormError, audit, local_now, next_id
from .schema import ENTITIES

REEL_FORMATS = ("Reel", "Collab Reel")
BOARD = [("To make", ("Planned", "Filming", "Editing")), ("In review", ("Ready for review",)),
         ("Ready to post", ("Approved", "Scheduled")), ("Posted", ("Posted",))]

DEFAULT_SHOT_LIST = """Before and arriving
- Getting ready or a mirror shot of the fit
- Uber or walking up with the girls
- The host walking the group in past the line (the money shot)
- 2 or 3 street interviews in line or outside
Inside and after
- The table, cheers, girls laughing
- Dance floor and DJ; cinematic b-roll (lights, the room)
- The host taking photos of the group
- An interview at the table; shoes off in the Uber or late-night food
Aim for 10+ usable clips. Everyone on camera says yes. No one under 21 or drunk. No men's faces without permission."""

DEFAULT_QUESTIONS = """- What's your craziest night out story?
- Rate your fit for tonight
- Red flag on a night out?
- Is a 5am night worth it?
- What's the one thing you never leave without?
- Advice for a girl going out in NYC for the first time?
- Best club in the city right now?"""


def num(v) -> float:
    return calc.num(v)


def settings_int(s: dict, key: str, default: int) -> int:
    try:
        return int(float(s.get(key) or default))
    except ValueError:
        return default


# ---------- calculated columns ----------
def content_stats(w: calc.World) -> dict[str, dict]:
    out = {}
    for c in w.content:
        out[c["post_id"]] = {"views": c.get("views"), "dms": sum(1 for l in w.leads if l.get("source_content_id") == c["post_id"])}
    return out


def approval_label(p: dict) -> str:
    if not p.get("needs_approval") or p.get("needs_approval") in ("0", 0):
        return ""
    if p.get("approved_at"):
        return "Approved"
    return "Waiting" if p.get("status") == "Ready for review" else "Needed"


def plan_row(p: dict, stats: dict) -> dict:
    st = stats.get(p.get("post_id") or "", {})
    return {"approval": approval_label(p), "views": st.get("views"), "dms": st.get("dms") if p.get("post_id") else None}


def campaign_row(c: dict, plans: list[dict], stats: dict) -> dict:
    mine = [p for p in plans if (p.get("campaign") or "").lower() == (c.get("name") or "").lower()
            and p.get("status") != "Skipped"]
    posted = [p for p in mine if p.get("status") == "Posted"]
    views = sum(num(stats.get(p.get("post_id") or "", {}).get("views")) for p in posted)
    dms = sum(stats.get(p.get("post_id") or "", {}).get("dms") or 0 for p in posted)
    return {"posts": len(mine), "posted": len(posted),
            "progress": f"{round(100 * len(posted) / len(mine))}%" if mine else "", "views": int(views) if views else None,
            "dms": dms if posted else None}


def computed(con, w: calc.World, slug: str, rows: list[dict]) -> None:
    if slug == "plan":
        stats = content_stats(w)
        for r in rows:
            r.update(plan_row(r, stats))
    elif slug == "campaigns":
        stats, plans = content_stats(w), db.rows(con, "SELECT * FROM plan")
        for r in rows:
            r.update(campaign_row(r, plans, stats))
    elif slug == "growth":
        allrows = db.rows(con, "SELECT date, followers FROM growth ORDER BY date, id")
        for r in rows:
            prev = [x for x in allrows if (x["date"] or "") < (r.get("date") or "")]
            r["change"] = (f"{int(num(r.get('followers')) - num(prev[-1]['followers'])):+d}" if prev and
                           r.get("followers") is not None else "")


# ---------- form defaults and save rules (called from main.py's generic tabs) ----------
def defaults(con, slug: str, user: dict, qp) -> dict:
    today = local_now(con).date().isoformat()
    me = user.get("team_name")
    if slug == "plan":
        r = {"planned_date": qp.get("date") or today, "status": "Planned", "format": "Reel", "owner": me}
        if qp.get("campaign"):
            r["campaign"] = qp.get("campaign")
        return r
    if slug == "ideas":
        return {"status": "New", "priority": "Medium", "added_by": me}
    if slug == "shoots":
        return {"date": qp.get("date") or today, "status": "Planned", "who": me, "shot_list": DEFAULT_SHOT_LIST,
                "questions": DEFAULT_QUESTIONS}
    if slug == "growth":
        return {"date": today}
    if slug == "campaigns":
        return {"status": "Planned", "start_date": today}
    return {}


def check_plan(con, user: dict, vals: dict, old: dict | None) -> dict:
    """The approval rule. Returns extra columns to save (approved_by/at)."""
    old = old or {}
    extra = {}
    status = vals.get("status", old.get("status")) or "Planned"
    needs = vals.get("needs_approval", old.get("needs_approval"))
    if not is_admin(user) and old.get("needs_approval") and not old.get("approved_at") and not vals.get("needs_approval"):
        vals["needs_approval"] = 1          # only the founder can take a post off the approval list
        needs = 1
    approved = old.get("approved_at")
    if is_admin(user):
        if needs and status in NEEDS_OK and not approved:
            extra = {"approved_by": user["username"], "approved_at": local_now(con).strftime("%Y-%m-%d %H:%M")}
        return extra
    if status == "Approved" and old.get("status") != "Approved":
        raise FormError("Only the founder can approve a post. Set it to Ready for review and it goes to the approval queue.")
    if needs and not approved and status in NEEDS_OK:
        raise FormError("This post needs the founder's OK first. Set it to Ready for review.")
    return extra


def after_save(con, user: dict, slug: str, rid) -> None:
    """Posted plan items get a row on the Content tab so their views and DMs are tracked."""
    if slug != "plan":
        return
    p = db.one(con, "SELECT * FROM plan WHERE id=?", (rid,))
    if not p or p.get("status") != "Posted":
        return
    pid = p.get("post_id") or p["id"]
    if not db.one(con, "SELECT 1 FROM content WHERE post_id=?", (pid,)):
        con.execute("INSERT INTO content(post_id, date_posted, platform, format, hook, creator, link, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (pid, p.get("planned_date"), "TikTok" if p.get("format") == "TikTok repost" else "Instagram",
                     p.get("content_type") or "Other", p.get("hook") or p.get("title"), p.get("owner"),
                     p.get("post_link"), local_now(con).strftime("%Y-%m-%d %H:%M")))
        audit(con, user["username"], "content", pid, "create from plan", {"plan": p["id"]})
    elif p.get("post_link"):
        con.execute("UPDATE content SET link=COALESCE(NULLIF(link, ''), ?) WHERE post_id=?", (p["post_link"], pid))
    if not p.get("post_id"):
        con.execute("UPDATE plan SET post_id=? WHERE id=?", (pid, p["id"]))


def related(con, slug: str, r: dict) -> dict:
    if slug == "campaigns":
        return {"posts": db.rows(con, "SELECT * FROM plan WHERE campaign=? COLLATE NOCASE ORDER BY planned_date, planned_time",
                                 (r["name"],)),
                "ideas": db.rows(con, "SELECT * FROM ideas WHERE campaign=? COLLATE NOCASE AND status NOT IN "
                                      "('On the calendar','Parked')", (r["name"],))}
    return {}


# ---------- the hub ----------
def followers_goal(con, today: date) -> dict:
    s = db.settings(con)
    goal = settings_int(s, "follower_goal", 10000)
    goal_date = calc.d(s.get("follower_goal_date")) or date(2026, 12, 15)
    log = db.rows(con, "SELECT date, followers FROM growth WHERE followers IS NOT NULL ORDER BY date, id")
    out = {"goal": goal, "goal_date": goal_date, "days_left": max((goal_date - today).days, 0), "log": log[-8:][::-1]}
    if not log:
        return out
    last = log[-1]
    now = int(num(last["followers"]))
    out.update(now=now, as_of=last["date"], to_go=max(goal - now, 0), pct=min(round(100 * now / goal), 100) if goal else 0)
    out["per_day_needed"] = round(out["to_go"] / out["days_left"]) if out["days_left"] else None
    # pace: average daily gain over the last ~2 weeks of entries
    base = next((x for x in log if (calc.d(last["date"]) - calc.d(x["date"])).days <= 14), None)
    span = (calc.d(last["date"]) - calc.d(base["date"])).days if base else 0
    if base and span > 0:
        pace = (now - int(num(base["followers"]))) / span
        out["pace"] = round(pace)
        out["projected"] = int(now + pace * max((goal_date - calc.d(last["date"])).days, 0))
        out["on_track"] = out["projected"] >= goal
    return out


def hub(con, w: calc.World, user: dict, start: date) -> dict:
    s = db.settings(con)
    today = local_now(con).date()
    end = start + timedelta(days=7)
    stats = content_stats(w)
    plans = db.rows(con, "SELECT * FROM plan ORDER BY planned_date, planned_time, id")
    for p in plans:
        p.update(plan_row(p, stats))
    week = [p for p in plans if start <= (calc.d(p["planned_date"]) or date.min) < end and p["status"] != "Skipped"]
    board = [(label, [p for p in week if p["status"] in sts]) for label, sts in BOARD]
    overdue = [p for p in plans if (calc.d(p["planned_date"]) or date.max) < today and p["status"] not in ("Posted", "Skipped")]
    review = [p for p in plans if p["status"] == "Ready for review"]
    new_format_ideas = db.rows(con, "SELECT * FROM ideas WHERE new_format=1 AND status IN ('New','Shortlisted') ORDER BY id")

    # each social manager's week against the quota
    reels_q, car_q = settings_int(s, "weekly_reels", 3), settings_int(s, "weekly_carousels", 1)
    managers = [t["name"] for t in w.team.values() if t.get("role") == "Social Media" and t.get("status") != "Inactive"]
    quotas = []
    for m in managers:
        mine = [p for p in week if (p.get("owner") or "").lower() == m.lower()]
        reels = [p for p in mine if p["format"] in REEL_FORMATS]
        cars = [p for p in mine if p["format"] == "Carousel"]
        quotas.append({"name": m, "reels": len(reels), "reels_posted": sum(p["status"] == "Posted" for p in reels),
                       "carousels": len(cars), "carousels_posted": sum(p["status"] == "Posted" for p in cars),
                       "reels_q": reels_q, "car_q": car_q})
    unassigned = [p for p in week if not p.get("owner")]

    # Reels over the bonus threshold this month (Instagram only), per person
    thr, cap = settings_int(s, "reel_bonus_views", 100000), settings_int(s, "reel_bonus_max", 4)
    month = today.strftime("%Y-%m")
    big = [c for c in w.content if (c.get("date_posted") or "").startswith(month) and num(c.get("views")) >= thr
           and (c.get("platform") or "Instagram") == "Instagram"]
    bonus = {}
    for c in big:
        bonus.setdefault(c.get("creator") or "No creator set", []).append(c)
    bonus_rows = [{"name": k, "count": len(v), "counted": min(len(v), cap), "posts": v} for k, v in sorted(bonus.items())]
    if not is_admin(user):
        me = (user.get("team_name") or "").lower()
        bonus_rows = [b for b in bonus_rows if b["name"].lower() == me]

    camps = db.rows(con, "SELECT * FROM campaigns WHERE status NOT IN ('Done','Cancelled') ORDER BY start_date, name")
    for c in camps:
        c.update(campaign_row(c, plans, stats))
        sd, ed = calc.d(c.get("start_date")), calc.d(c.get("end_date"))
        c["live"] = bool(sd and ed and sd <= today <= ed)
        c["days_left"] = (ed - today).days if ed and ed >= today else None
    shoots = db.rows(con, "SELECT * FROM shoots WHERE date >= ? ORDER BY date LIMIT 6", (today.isoformat(),))
    ideas = db.rows(con, "SELECT * FROM ideas WHERE status IN ('New','Shortlisted') ORDER BY status='New', "
                         "CASE priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END, id LIMIT 8")
    idea_count = con.execute("SELECT COUNT(*) FROM ideas WHERE status IN ('New','Shortlisted')").fetchone()[0]
    return dict(week=week, board=board, overdue=overdue, review=review, new_format_ideas=new_format_ideas,
                quotas=quotas, unassigned=unassigned, managers=managers, bonus=bonus_rows, bonus_thr=thr, bonus_cap=cap,
                campaigns=camps, shoots=shoots, ideas=ideas, idea_count=idea_count, fol=followers_goal(con, today),
                tracker=s.get("creator_tracker_url") or "", today=today, start=start, end=end - timedelta(days=1))


def month_grid(year: int, month: int) -> list[list[date]]:
    return pycal.Calendar(firstweekday=0).monthdatescalendar(year, month)


# ---------- routes ----------
def register(app: FastAPI, get_con, current_user, form_data, render, world) -> None:
    def need(user, page):
        if not can_view(user, page):
            raise HTTPException(403, "You don't have access to this page.")

    def back_to(form, default):
        b = form.get("back") or default
        return b if b.startswith("/") and not b.startswith("//") else default

    @app.get("/social", response_class=HTMLResponse)
    def social_hub(request: Request, week: str | None = None, con=Depends(get_con), user=Depends(current_user)):
        need(user, "social")
        w = world(con)
        start = calc.week_start(calc.d(week) or local_now(con).date())
        nav = {"prev": (start - timedelta(days=7)).isoformat(), "next": (start + timedelta(days=7)).isoformat(),
               "this": calc.week_start(local_now(con).date()).isoformat()}
        return render(request, "social.html", user, h=hub(con, w, user, start), nav=nav, week=start, statuses=PLAN_STATUS,
                      saved=request.query_params.get("saved"), err=request.query_params.get("err"))

    @app.get("/calendar", response_class=HTMLResponse)
    def calendar_page(request: Request, month: str = "", owner: str = "", campaign: str = "",
                      con=Depends(get_con), user=Depends(current_user)):
        need(user, "calendar")
        today = local_now(con).date()
        try:
            y, m = (int(x) for x in month.split("-")[:2]) if month else (today.year, today.month)
            first = date(y, m, 1)
        except ValueError:
            first = today.replace(day=1)
        weeks = month_grid(first.year, first.month)
        lo, hi = weeks[0][0].isoformat(), weeks[-1][-1].isoformat()
        sql, args = "SELECT * FROM plan WHERE planned_date BETWEEN ? AND ?", [lo, hi]
        if owner:
            sql += " AND owner=? COLLATE NOCASE"
            args.append(owner)
        if campaign:
            sql += " AND campaign=? COLLATE NOCASE"
            args.append(campaign)
        posts = db.rows(con, sql + " ORDER BY planned_time, id", args)
        for p in posts:
            p["approval"] = approval_label(p)
        shoots = db.rows(con, "SELECT * FROM shoots WHERE date BETWEEN ? AND ?" + (" AND who=? COLLATE NOCASE" if owner else ""),
                         [lo, hi] + ([owner] if owner else []))
        camps = db.rows(con, "SELECT * FROM campaigns WHERE status!='Cancelled' AND start_date<=? AND "
                             "COALESCE(end_date, start_date)>=? ORDER BY start_date", (hi, lo))
        by_day: dict[str, dict] = {}
        for p in posts:
            by_day.setdefault(p["planned_date"], {"posts": [], "shoots": [], "marks": []})["posts"].append(p)
        for x in shoots:
            by_day.setdefault(x["date"], {"posts": [], "shoots": [], "marks": []})["shoots"].append(x)
        for c in camps:
            if c.get("start_date"):
                by_day.setdefault(c["start_date"], {"posts": [], "shoots": [], "marks": []})["marks"].append(f"{c['name']} starts")
            if c.get("end_date"):
                by_day.setdefault(c["end_date"], {"posts": [], "shoots": [], "marks": []})["marks"].append(f"{c['name']} ends")
        prev_m = (first - timedelta(days=1)).replace(day=1)
        next_m = (first + timedelta(days=32)).replace(day=1)
        qs = urlencode({k: v for k, v in {"owner": owner, "campaign": campaign}.items() if v})
        team = [t["name"] for t in db.rows(con, "SELECT name FROM team WHERE status!='Inactive' AND role IN "
                                                "('Social Media','Administrator') ORDER BY name")]
        return render(request, "calendar.html", user, first=first, weeks=weeks, by_day=by_day, today=today,
                      prev=prev_m.strftime("%Y-%m"), next=next_m.strftime("%Y-%m"), this=today.strftime("%Y-%m"),
                      owner=owner, campaign=campaign, qs=qs, team=team, camps=camps,
                      campaigns=[r[0] for r in con.execute("SELECT name FROM campaigns ORDER BY start_date")])

    @app.post("/plan/{pid}/review")
    async def review(request: Request, pid: str, con=Depends(get_con), user=Depends(current_user)):
        form = await form_data(request, user)
        if not can_write(user, "plan"):
            raise HTTPException(403, "You can't change the content plan.")
        p = db.one(con, "SELECT * FROM plan WHERE id=?", (pid,))
        if not p:
            raise HTTPException(404, "That planned post doesn't exist.")
        action, note = form.get("action"), (form.get("note") or "").strip()[:2000]
        now = local_now(con).strftime("%Y-%m-%d %H:%M")
        new: dict = {}
        if action == "submit":
            new = {"status": "Ready for review"}
        elif action in ("approve", "sendback"):
            if not is_admin(user):
                raise HTTPException(403, "Only the founder can approve or send back posts.")
            if action == "approve":
                new = {"status": "Approved" if p["status"] in ("Planned", "Filming", "Editing", "Ready for review") else p["status"],
                       "approved_by": user["username"], "approved_at": now}
            else:
                new = {"status": "Editing", "approved_by": None, "approved_at": None}
            if note:
                new["review_note"] = note
        elif action == "status":
            st = form.get("status")
            if st not in PLAN_STATUS:
                raise HTTPException(400, "Unknown status.")
            vals = {"status": st}
            try:
                new = {**vals, **check_plan(con, user, vals, p)}
            except FormError as err:
                url = back_to(form, "/social").split("#")[0]
                return RedirectResponse(url + ("&" if "?" in url else "?") + "err=" + quote(str(err)), 303)
        else:
            raise HTTPException(400, "Unknown action.")
        new["updated_at"], new["updated_by"] = now, user["username"]
        con.execute(f"UPDATE plan SET {', '.join(k + '=?' for k in new)} WHERE id=?", (*new.values(), pid))
        after_save(con, user, "plan", pid)
        audit(con, user["username"], "plan", pid, action, new)
        con.commit()
        return RedirectResponse(back_to(form, f"/plan/{quote(pid)}?saved=1"), 303)

    @app.post("/ideas/{iid}/schedule")
    async def schedule_idea(request: Request, iid: str, con=Depends(get_con), user=Depends(current_user)):
        form = await form_data(request, user)
        if not can_write(user, "plan"):
            raise HTTPException(403, "You can't change the content plan.")
        i = db.one(con, "SELECT * FROM ideas WHERE id=?", (iid,))
        if not i:
            raise HTTPException(404, "That idea doesn't exist.")
        day = calc.d(form.get("date")) or local_now(con).date()
        e = ENTITIES["plan"]
        pid = next_id(con, e)
        now = local_now(con).strftime("%Y-%m-%d %H:%M")
        vals = {"id": pid, "planned_date": day.isoformat(), "title": i["title"], "format": i.get("format") or "Reel",
                "pillar": i.get("pillar"), "campaign": i.get("campaign"),
                "owner": form.get("owner") or user.get("team_name") or i.get("added_by"),
                "status": "Planned", "needs_approval": 1 if i.get("new_format") else 0, "notes": i.get("details"),
                "idea_id": iid, "updated_at": now, "updated_by": user["username"]}
        con.execute(f"INSERT INTO plan ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})", list(vals.values()))
        con.execute("UPDATE ideas SET status='On the calendar', plan_id=?, updated_at=? WHERE id=?", (pid, now, iid))
        audit(con, user["username"], "plan", pid, "create from idea", {"idea": iid})
        con.commit()
        return RedirectResponse(f"/plan/{quote(pid)}?saved=1", 303)

    @app.post("/growth/quick")
    async def growth_quick(request: Request, con=Depends(get_con), user=Depends(current_user)):
        form = await form_data(request, user)
        if not can_write(user, "growth"):
            raise HTTPException(403, "You can't log followers.")
        try:
            n = int(str(form.get("followers") or "").replace(",", "").strip())
        except ValueError:
            return RedirectResponse("/social?err=" + quote("Type the follower count as a number."), 303)
        today = local_now(con).date().isoformat()
        now = local_now(con).strftime("%Y-%m-%d %H:%M")
        row = db.one(con, "SELECT id FROM growth WHERE date=?", (today,))
        if row:
            con.execute("UPDATE growth SET followers=?, updated_at=? WHERE id=?", (n, now, row["id"]))
        else:
            con.execute("INSERT INTO growth(date, followers, updated_at) VALUES (?,?,?)", (today, n, now))
        audit(con, user["username"], "growth", today, "log followers", {"followers": n})
        con.commit()
        return RedirectResponse("/social?saved=1", 303)
