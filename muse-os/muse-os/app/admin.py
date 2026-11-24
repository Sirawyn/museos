"""Admin-only pages: user accounts, DM bot API keys, settings, change log."""
from __future__ import annotations

import secrets

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import auth, db
from .auth import ROLES, TEAM_ROLE_TO_USER, is_admin
from .web import audit


def temp_password() -> str:
    words = secrets.token_urlsafe(9).replace("-", "x").replace("_", "y")
    return f"muse-{words}"


def register(app: FastAPI, get_con, current_user, form_data, render):
    def invite_page(request, user, username, team_name, role, token, reset=False):
        link = str(request.base_url).rstrip("/") + "/invite/" + token
        first = (team_name or username).split()[0].title()
        msg = (f"Hi {first}! {'Here is a new link to log in to' if reset else 'Here is your login for'} Muse OS: {link}\n"
               f"Tap it, choose your password, and you're in. Your username is {username}. "
               f"The link works once and expires in {auth.INVITE_DAYS} days. "
               f"Tip: on your phone, use Share > Add to Home Screen so it opens like an app.")
        return render(request, "admin_invite.html", user, username=username, link=link, msg=msg,
                      role=ROLES.get(role, role), reset=reset)

    def admin_user(user=Depends(current_user)):
        if not is_admin(user):
            raise HTTPException(403, "Admins only.")
        return user

    @app.get("/admin", response_class=HTMLResponse)
    def admin_home(request: Request, user=Depends(admin_user)):
        return RedirectResponse("/admin/users", 303)

    @app.get("/admin/users", response_class=HTMLResponse)
    def users(request: Request, con=Depends(get_con), user=Depends(admin_user)):
        us = db.rows(con, "SELECT u.id, username, role, team_name, active, must_change_password, last_login_at, "
                          "i.expires_at AS invite_expires FROM users u LEFT JOIN invites i ON i.user_id=u.id "
                          "ORDER BY active DESC, role, username")
        team = db.rows(con, "SELECT name, role FROM team WHERE status!='Inactive' ORDER BY name")
        linked = {(u["team_name"] or "").lower() for u in us}
        return render(request, "admin_users.html", user, users=us, team=team, unlinked=[t for t in team
                      if t["name"].lower() not in linked], new_pw=request.query_params.get("pw"),
                      new_for=request.query_params.get("for"), error=request.query_params.get("error"))

    @app.post("/admin/users")
    async def user_create(request: Request, con=Depends(get_con), user=Depends(admin_user)):
        form = await form_data(request, user)
        username = (form.get("username") or "").strip().lower()
        role = form.get("role")
        team_name = form.get("team_name") or None
        if not username or not username.replace(".", "").replace("_", "").replace("-", "").isalnum():
            return RedirectResponse("/admin/users?error=Usernames+can+use+letters,+numbers,+dots,+dashes", 303)
        if role not in ROLES:
            return RedirectResponse("/admin/users?error=Pick+a+role", 303)
        if role != "admin" and not team_name:
            return RedirectResponse("/admin/users?error=Link+non-admin+logins+to+a+Team+member", 303)
        if db.one(con, "SELECT 1 FROM users WHERE username=?", (username,)):
            return RedirectResponse("/admin/users?error=That+username+is+taken", 303)
        # no usable password until they open their invite link and choose one
        cur = con.execute("INSERT INTO users(username, password_hash, role, team_name, created_at) VALUES (?,?,?,?,?)",
                          (username, auth.hash_password(secrets.token_urlsafe(24)), role, team_name, auth.iso(auth.now())))
        token = auth.create_invite(con, cur.lastrowid, user["username"])
        audit(con, user["username"], "users", username, "create", {"role": role, "team_name": team_name})
        con.commit()
        return invite_page(request, user, username, team_name, role, token)

    @app.post("/admin/users/{uid}")
    async def user_update(request: Request, uid: int, con=Depends(get_con), user=Depends(admin_user)):
        form = await form_data(request, user)
        target = db.one(con, "SELECT * FROM users WHERE id=?", (uid,))
        if not target:
            raise HTTPException(404, "No such user.")
        action = form.get("action")
        if action == "reset":
            # forgot password / lost phone: old password stops working, they get a fresh link to set a new one
            con.execute("UPDATE users SET password_hash=?, must_change_password=1 WHERE id=?",
                        (auth.hash_password(secrets.token_urlsafe(24)), uid))
            auth.end_all_sessions(con, uid)
            token = auth.create_invite(con, uid, user["username"])
            audit(con, user["username"], "users", target["username"], "new login link")
            con.commit()
            return invite_page(request, user, target["username"], target["team_name"], target["role"], token, reset=True)
        if action in ("deactivate", "activate"):
            if uid == user["id"]:
                return RedirectResponse("/admin/users?error=You+can't+deactivate+yourself", 303)
            con.execute("UPDATE users SET active=? WHERE id=?", (1 if action == "activate" else 0, uid))
            if action == "deactivate":
                auth.end_all_sessions(con, uid)
            audit(con, user["username"], "users", target["username"], action)
        elif action == "save":
            role, team_name = form.get("role"), form.get("team_name") or None
            if role not in ROLES or (uid == user["id"] and role != "admin"):
                return RedirectResponse("/admin/users?error=Can't+change+that+role", 303)
            con.execute("UPDATE users SET role=?, team_name=? WHERE id=?", (role, team_name, uid))
            auth.end_all_sessions(con, uid) if role != target["role"] else None
            audit(con, user["username"], "users", target["username"], "update", {"role": role, "team_name": team_name})
        con.commit()
        return RedirectResponse("/admin/users", 303)

    # ---------- API keys ----------
    @app.get("/admin/keys", response_class=HTMLResponse)
    def keys(request: Request, con=Depends(get_con), user=Depends(admin_user)):
        return render(request, "admin_keys.html", user, keys=db.rows(con, "SELECT * FROM api_keys ORDER BY revoked, id DESC"),
                      new_key=None)

    @app.post("/admin/keys")
    async def key_create(request: Request, con=Depends(get_con), user=Depends(admin_user)):
        form = await form_data(request, user)
        if form.get("revoke"):
            con.execute("UPDATE api_keys SET revoked=1 WHERE id=?", (int(form.get("revoke")),))
            audit(con, user["username"], "api_keys", form.get("revoke"), "revoke")
            con.commit()
            return RedirectResponse("/admin/keys", 303)
        name = (form.get("name") or "DM bot").strip()[:60]
        key = auth.create_api_key(con, name)
        audit(con, user["username"], "api_keys", name, "create")
        con.commit()
        return render(request, "admin_keys.html", user, keys=db.rows(con, "SELECT * FROM api_keys ORDER BY revoked, id DESC"),
                      new_key=key)

    # ---------- settings ----------
    LABELS = {
        "noshow_risk_rate": "No-show risk: no-show rate at or above (0.34 = 34%)",
        "vip_nights": "Muse VIP: nights out at or above",
        "reply_target_min": "DM reply time target (minutes)",
        "scout_rate_default": "Default scout pay per arrived girl ($)",
        "timezone": "Time zone",
        "night_cutoff_hour": "Tonight switches to the next day at (hour, 0-23)",
    }

    @app.get("/admin/settings", response_class=HTMLResponse)
    def settings_page(request: Request, con=Depends(get_con), user=Depends(admin_user)):
        return render(request, "admin_settings.html", user, settings=db.settings(con), labels=LABELS,
                      saved=request.query_params.get("saved"))

    @app.post("/admin/settings")
    async def settings_save(request: Request, con=Depends(get_con), user=Depends(admin_user)):
        form = await form_data(request, user)
        from zoneinfo import ZoneInfo
        for k in LABELS:
            v = (form.get(k) or "").strip()
            if not v:
                continue
            if k == "timezone":
                try:
                    ZoneInfo(v)
                except Exception:
                    continue
            elif k != "timezone":
                try:
                    float(v)
                except ValueError:
                    continue
            con.execute("UPDATE settings SET value=? WHERE key=?", (v, k))
        audit(con, user["username"], "settings", "*", "update", {k: form.get(k) for k in LABELS})
        con.commit()
        return RedirectResponse("/admin/settings?saved=1", 303)

    # ---------- audit ----------
    @app.get("/admin/audit", response_class=HTMLResponse)
    def audit_page(request: Request, page: int = 1, con=Depends(get_con), user=Depends(admin_user)):
        rows = db.rows(con, "SELECT * FROM audit ORDER BY id DESC LIMIT 200 OFFSET ?", (max(page - 1, 0) * 200,))
        return render(request, "admin_audit.html", user, rows=rows, page=page)


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def runs_on(venue_nights: str | None, d) -> bool:
    """Does the venue's 'Nights we run' text (e.g. 'Fri, Sat' or 'Thursday & Saturday') include this weekday?"""
    import re
    words = [w.strip().lower()[:3] for w in re.split(r"[,/&]| and ", venue_nights or "") if w.strip()]
    return WEEKDAYS[d.weekday()][:3] in words


def register_setup(app: FastAPI, get_con, current_user, form_data, render):
    """Weekly setup: one form for the week's lineup (venue nights + host on duty) and the guys' ticket links.
    The DM bot reads both through GET /api/v1/venues, so saving here is all it needs each week."""
    from datetime import date, timedelta
    from .web import local_now, parse_value, FormError, hidden_days
    from .schema import ENTITIES, GUYS_POLICY

    def admin_user(user=Depends(current_user)):
        if not is_admin(user):
            raise HTTPException(403, "Admins only.")
        return user

    def week_start(con, raw: str | None) -> date:
        if raw:
            try:
                return date.fromisoformat(raw)
            except ValueError:
                pass
        today = local_now(con).date()
        # Sunday (and Saturday) you're planning next week; otherwise this week from today on
        if today.weekday() >= 5:
            return today + timedelta(days=7 - today.weekday())
        return today

    @app.get("/setup", response_class=HTMLResponse)
    def setup_page(request: Request, con=Depends(get_con), user=Depends(admin_user)):
        start = week_start(con, request.query_params.get("start"))
        hide = hidden_days(con, user)
        days = [start + timedelta(days=i) for i in range(7) if (start + timedelta(days=i)).weekday() not in hide]
        if not days:
            days = [start + timedelta(days=i) for i in range(7)]
        venues = db.rows(con, "SELECT * FROM venues WHERE COALESCE(status,'Active')!='Inactive' ORDER BY name")
        hosts = [r["name"] for r in db.rows(con, "SELECT name FROM team WHERE COALESCE(status,'Active')!='Inactive' "
                                                 "AND role IN ('Host','Promoter','Administrator') ORDER BY name")]
        existing = {(r["night"], r["venue"].lower()): r for r in db.rows(
            con, "SELECT * FROM nights WHERE night BETWEEN ? AND ?", (days[0].isoformat(), days[-1].isoformat()))}
        booked = {(r["night"], r["venue"].lower()): r["n"] for r in db.rows(
            con, "SELECT night, venue, COUNT(*) n FROM bookings WHERE night BETWEEN ? AND ? GROUP BY night, venue",
            (days[0].isoformat(), days[-1].isoformat()))}
        # a day counts as set once it has a night OR the form was saved for it (even with nothing ticked),
        # so a day you cleared doesn't get the venue's usual nights pre-ticked again
        set_days = {k[0] for k in existing} | {r["night"] for r in db.rows(
            con, "SELECT night FROM setup_days WHERE night BETWEEN ? AND ?", (days[0].isoformat(), days[-1].isoformat()))}
        rows, suggested = [], False
        for d in days:
            cells = []
            for v in venues:
                key = (d.isoformat(), v["name"].lower())
                n = existing.get(key)
                if n:
                    cells.append({"venue": v["name"], "on": True, "host": n["host"] or "", "suggested": False,
                                  "dress": n.get("dress_code") or "", "default_dress": v.get("dress_code") or "",
                                  "cover": n.get("cover") or "", "link": n.get("ticket_link") or "",
                                  "closes": n.get("list_closes") or "", "default_closes": v.get("list_closes") or "",
                                  "guys": n.get("guys_policy") or "", "default_guys": v.get("guys_policy") or "",
                                  "bookings": booked.get(key, 0)})
                    continue
                # nothing set for this day yet: suggest the venue's usual nights, with last week's host
                sug = d.isoformat() not in set_days and runs_on(v.get("nights"), d)
                # last week's same night gives the usual host and that weekday's dress code
                last = db.one(con, "SELECT host, dress_code, cover, list_closes, guys_policy FROM nights WHERE venue=? AND night=?",
                              (v["name"], (d - timedelta(days=7)).isoformat())) or {}
                if sug:
                    suggested = True
                cells.append({"venue": v["name"], "on": sug, "host": (last.get("host") or "") if sug else "",
                              "suggested": sug, "dress": last.get("dress_code") or "", "cover": last.get("cover") or "", "link": "",
                              "closes": last.get("list_closes") or "", "default_closes": v.get("list_closes") or "",
                              "guys": last.get("guys_policy") or "", "default_guys": v.get("guys_policy") or "",
                              "default_dress": v.get("dress_code") or "", "bookings": booked.get(key, 0)})
            for c, v in zip(cells, venues):   # cover-only nights: ask for the cover amount, no ticket link
                c["is_cover"] = (c["guys"] or v.get("guys_policy") or "") == "Cover at the door"
            rows.append({"date": d, "cells": cells})
        monday = days[0] - timedelta(days=days[0].weekday())
        links = [{"id": v["id"], "name": v["name"], "link": v.get("ticket_link") or "",
                  "updated": v.get("ticket_link_updated_at"),
                  "stale": not v.get("ticket_link_updated_at") or v["ticket_link_updated_at"] < monday.isoformat(),
                  "is_cover": v.get("guys_policy") == "Cover at the door"}
                 for v in venues]
        return render(request, "setup.html", user, guys_options=GUYS_POLICY, hidden=sorted(hide), week_end=start + timedelta(days=6), rows=rows, venues=venues, hosts=hosts, links=links,
                      start=start, prev=(start - timedelta(days=7)).isoformat(),
                      next=(start + timedelta(days=7)).isoformat(), suggested=suggested,
                      saved=request.query_params.get("saved"), kept=request.query_params.get("kept"),
                      error=request.query_params.get("error"))

    @app.post("/setup")
    async def setup_save(request: Request, con=Depends(get_con), user=Depends(admin_user)):
        form = await form_data(request, user)
        start = week_start(con, form.get("start"))
        hide = hidden_days(con, user)       # days hidden from this person's form are left exactly as they are
        days = [(start + timedelta(days=i)).isoformat() for i in range(7)
                if (start + timedelta(days=i)).weekday() not in hide] or \
               [(start + timedelta(days=i)).isoformat() for i in range(7)]
        venues = db.rows(con, "SELECT * FROM venues WHERE COALESCE(status,'Active')!='Inactive' ORDER BY name")
        hosts = {r["name"].lower(): r["name"] for r in db.rows(con, "SELECT name FROM team")}
        link_field = next(f for f in ENTITIES["venues"].fields if f.name == "ticket_link")
        now = local_now(con)
        stamp = now.strftime("%Y-%m-%d %H:%M")
        # validate ticket links first so a typo doesn't half-save the form
        new_links = {}
        for v in venues:
            raw = (form.get(f"link_{v['id']}") or "").strip()
            try:
                new_links[v["id"]] = parse_value(link_field, raw) if raw else None
            except FormError:
                return RedirectResponse(f"/setup?start={start.isoformat()}&error=" +
                                        quote(f"The ticket link for {v['name']} needs to start with https://"), 303)
        time_field = next(f for f in ENTITIES["nights"].fields if f.name == "list_closes")
        night_closes = {}
        for d in days:
            for v in venues:
                raw = (form.get(f"lc_{d}_{v['id']}") or "").strip()
                try:
                    night_closes[(d, v["id"])] = parse_value(time_field, raw) if raw else None
                except FormError:
                    return RedirectResponse(f"/setup?start={start.isoformat()}&error=" + quote(
                        f"The guestlist closing time for {v['name']} on {d} should look like 20:00 or 01:30"), 303)
        night_links = {}
        for d in days:
            for v in venues:
                raw = (form.get(f"tl_{d}_{v['id']}") or "").strip()
                try:
                    night_links[(d, v["id"])] = parse_value(link_field, raw) if raw else None
                except FormError:
                    return RedirectResponse(f"/setup?start={start.isoformat()}&error=" + quote(
                        f"The ticket link for {v['name']} on {d} needs to start with https://"), 303)
        added = removed = changed = 0
        kept = []
        for d in days:
            for v in venues:
                key = f"n_{d}_{v['id']}"
                on = form.get(key) == "1"
                host = hosts.get((form.get(f"h_{d}_{v['id']}") or "").strip().lower())
                dress = (form.get(f"dc_{d}_{v['id']}") or "").strip()[:200] or None
                cover = (form.get(f"cv_{d}_{v['id']}") or "").strip()[:100] or None
                tlink = night_links[(d, v["id"])]
                closes = night_closes[(d, v["id"])]
                guys = form.get(f"gp_{d}_{v['id']}") or None
                guys = guys if guys in GUYS_POLICY else None
                cur = db.one(con, "SELECT * FROM nights WHERE night=? AND venue=?", (d, v["name"]))
                if on and not cur:
                    con.execute("INSERT INTO nights(night, venue, host, dress_code, cover, ticket_link, list_closes, "
                                "guys_policy, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                                (d, v["name"], host, dress, cover, tlink, closes, guys, stamp))
                    added += 1
                elif on and cur and ((cur["host"] or None) != host or (cur.get("dress_code") or None) != dress
                                     or (cur.get("cover") or None) != cover or (cur.get("ticket_link") or None) != tlink
                                     or (cur.get("list_closes") or None) != closes
                                     or (cur.get("guys_policy") or None) != guys):
                    con.execute("UPDATE nights SET host=?, dress_code=?, cover=?, ticket_link=?, list_closes=?, "
                                "guys_policy=?, updated_at=? WHERE id=?",
                                (host, dress, cover, tlink, closes, guys, stamp, cur["id"]))
                    changed += 1
                elif not on and cur:
                    has_bookings = db.one(con, "SELECT 1 FROM bookings WHERE night=? AND venue=? LIMIT 1",
                                          (d, v["name"]))
                    if has_bookings or cur.get("flat_override") is not None or cur.get("notes"):
                        kept.append(f"{v['name']} {d}")   # keep nights that already have bookings or a pay override
                    else:
                        con.execute("DELETE FROM nights WHERE id=?", (cur["id"],))
                        removed += 1
        for d in days:   # remember these days were set, so empty ones aren't re-suggested next time
            con.execute("INSERT INTO setup_days(night, saved_at) VALUES (?, ?) "
                        "ON CONFLICT(night) DO UPDATE SET saved_at=excluded.saved_at", (d, stamp))
        links_changed = 0
        for v in venues:
            new = new_links[v["id"]]
            if (v.get("ticket_link") or None) != new:
                con.execute("UPDATE venues SET ticket_link=?, ticket_link_updated_at=?, updated_at=? WHERE id=?",
                            (new, now.date().isoformat(), stamp, v["id"]))
                links_changed += 1
            elif new and form.get(f"same_{v['id']}") == "1":
                # "still the same link this week" counts as checked
                con.execute("UPDATE venues SET ticket_link_updated_at=? WHERE id=?", (now.date().isoformat(), v["id"]))
        audit(con, user["username"], "setup", start.isoformat(), "update",
              {"nights_added": added, "nights_removed": removed, "nights_changed": changed,
               "ticket_links_changed": links_changed, "kept": kept})
        con.commit()
        q = f"/setup?start={start.isoformat()}&saved=1"
        if kept:
            q += "&kept=" + quote(", ".join(kept))
        return RedirectResponse(q, 303)


from urllib.parse import quote  # noqa: E402
