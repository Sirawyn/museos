"""Muse OS web app.  Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000"""
from __future__ import annotations

import csv
import io
import os
from datetime import date, timedelta
from urllib.parse import quote, urlencode

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import auth, calc, db, social
from .auth import COOKIE, SOCIAL_TABLES, can_view, can_write, is_admin, is_staff, scope
from .schema import BOOKING_STATUS, ENTITIES, LEAD_STATUS
from .web import (BASE, FormError, get_pref, set_pref, hidden_days, WEEKDAY_NAMES, audit, cascade_rename, ensure_night, local_now, next_id, options, parse_value,
                  templates, tonight, visible_computed, visible_fields)

SECURE_COOKIES = os.getenv("MUSE_INSECURE_COOKIES", "") != "1"
PAGE_SIZE = 100


class Redirect(Exception):
    def __init__(self, url: str):
        self.url = url


def create_app() -> FastAPI:
    app = FastAPI(title="Muse OS", docs_url=None, redoc_url=None, openapi_url=None)
    with db.session() as con:
        db.init(con)
    app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not request.url.path.startswith("/static"):
            resp.headers["Cache-Control"] = "no-store"
        if SECURE_COOKIES:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        return resp

    @app.exception_handler(Redirect)
    async def _redir(request: Request, exc: Redirect):
        return RedirectResponse(exc.url, status_code=303)

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException):
        if request.url.path.startswith("/api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=exc.headers)
        return templates.TemplateResponse(request, "error.html", {"code": exc.status_code, "detail": exc.detail,
                                                                  "user": None}, status_code=exc.status_code)

    from .api import router as api_router
    app.include_router(api_router)
    register(app)
    return app


# ---------- dependencies ----------
def get_con():
    con = db.connect()
    try:
        yield con
    finally:
        con.close()


def current_user(request: Request, con=Depends(get_con)) -> dict:
    u = auth.load_session(con, request.cookies.get(COOKIE))
    if not u:
        nxt = request.url.path + (("?" + request.url.query) if request.url.query else "")
        raise Redirect("/login?next=" + quote(nxt))
    if u["must_change_password"] and request.url.path not in ("/account", "/logout"):
        raise Redirect("/account?first=1")
    return u


async def form_data(request: Request, user: dict) -> dict:
    form = await request.form()
    token = form.get("csrf") or request.headers.get("x-csrf-token")
    if not token or token != user["csrf"]:
        raise HTTPException(403, "This form expired. Go back, refresh the page and try again.")
    return form


def render(request: Request, name: str, user: dict | None, status_code: int = 200, **ctx):
    ctx.update(user=user, csrf=(user or {}).get("csrf", ""), path=request.url.path)
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def need(user: dict, page: str) -> None:
    if not can_view(user, page):
        raise HTTPException(403, "You don't have access to this page.")


def world(con) -> calc.World:
    return calc.World.load(con, local_now(con).date())


def safe_next(nxt: str | None) -> str:
    return nxt if nxt and nxt.startswith("/") and not nxt.startswith("//") else "/"


def register(app: FastAPI) -> None:
    # ---------- login ----------
    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, next: str = "/", con=Depends(get_con)):
        if auth.load_session(con, request.cookies.get(COOKIE)):
            return RedirectResponse(safe_next(next), 303)
        return render(request, "login.html", None, next=next, error=None)

    @app.post("/login")
    async def login(request: Request, con=Depends(get_con)):
        form = await request.form()
        username, pw = (form.get("username") or "").strip(), form.get("password") or ""
        ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
        keys = ("ip:" + ip, "user:" + username.lower())
        if auth.throttle.blocked(*keys):
            return render(request, "login.html", None, 429, next=form.get("next"),
                          error="Too many tries. Wait 15 minutes and try again.")
        row = db.one(con, "SELECT * FROM users WHERE username=? AND active=1", (username,))
        ok = auth.verify_password(pw, row["password_hash"] if row else auth.DUMMY_HASH)
        if not (row and ok):
            auth.throttle.fail(*keys)
            return render(request, "login.html", None, 401, next=form.get("next"),
                          error="That username and password don't match.")
        auth.throttle.clear(*keys)
        token = auth.create_session(con, row["id"], ip, request.headers.get("user-agent", ""))
        resp = RedirectResponse(safe_next(form.get("next")), 303)
        resp.set_cookie(COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, secure=SECURE_COOKIES,
                        samesite="lax", path="/")
        return resp

    # ---------- invite links: each person sets their own password ----------
    INTRO = {
        "admin": "You're an admin: you see everything, including money, and manage logins.",
        "host": "You'll see Tonight's door list with check-in, plus your own leads, bookings, guests and pay.",
        "promoter": "You'll see Tonight's door list with check-in, plus your own leads, bookings, guests and pay.",
        "social": "You'll see Social: the content calendar, campaigns, the idea backlog, shoot nights, follower goal and the format scoreboard.",
        "scout": "You'll see the girls you've referred and what you've earned.",
    }

    @app.get("/invite/{token}", response_class=HTMLResponse)
    def invite_page(request: Request, token: str, con=Depends(get_con)):
        inv = auth.load_invite(con, token)
        return render(request, "invite.html", None, 200 if inv else 410, invite=inv,
                      intro=INTRO.get((inv or {}).get("role"), ""), error=None)

    @app.post("/invite/{token}")
    async def invite_set(request: Request, token: str, con=Depends(get_con)):
        inv = auth.load_invite(con, token)
        if not inv:
            return render(request, "invite.html", None, 410, invite=None)
        form = await request.form()
        pw, again = form.get("new_password") or "", form.get("confirm_password") or ""
        problem = "The two passwords don't match." if pw != again else auth.password_problem(pw, inv["username"])
        if problem:
            return render(request, "invite.html", None, 400, invite=inv, intro=INTRO.get(inv["role"], ""), error=problem)
        auth.use_invite(con, token, pw)
        audit(con, inv["username"], "users", inv["username"], "set password from login link")
        ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
        session = auth.create_session(con, inv["id"], ip, request.headers.get("user-agent", ""))
        con.commit()
        resp = RedirectResponse("/", 303)
        resp.set_cookie(COOKIE, session, max_age=auth.SESSION_DAYS * 86400, httponly=True, secure=SECURE_COOKIES,
                        samesite="lax", path="/")
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    @app.post("/logout")
    async def logout(request: Request, con=Depends(get_con), user=Depends(current_user)):
        await form_data(request, user)
        auth.end_session(con, request.cookies.get(COOKIE))
        resp = RedirectResponse("/login", 303)
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.get("/account", response_class=HTMLResponse)
    def account(request: Request, first: int = 0, user=Depends(current_user)):
        return render(request, "account.html", user, first=first, error=None, done=False)

    @app.post("/account")
    async def account_save(request: Request, con=Depends(get_con), user=Depends(current_user)):
        form = await form_data(request, user)
        row = db.one(con, "SELECT * FROM users WHERE id=?", (user["id"],))
        new = form.get("new_password") or ""
        err = None
        if not auth.verify_password(form.get("current_password") or "", row["password_hash"]):
            err = "Your current password is wrong."
        elif new != form.get("confirm_password"):
            err = "The new passwords don't match."
        else:
            err = auth.password_problem(new, user["username"])
        if err:
            return render(request, "account.html", user, 400, first=0, error=err, done=False)
        con.execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
                    (auth.hash_password(new), user["id"]))
        auth.end_all_sessions(con, user["id"], except_hash=user["token_hash"])
        audit(con, user["username"], "users", user["id"], "password changed")
        con.commit()
        user["must_change_password"] = 0
        return render(request, "account.html", user, first=0, error=None, done=True)

    # ---------- home ----------
    @app.get("/")
    def home(user=Depends(current_user)):
        return RedirectResponse("/tonight" if is_staff(user) else ("/social" if user["role"] == "social" else "/dashboard"), 303)

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request, week: str | None = None, con=Depends(get_con), user=Depends(current_user)):
        need(user, "dashboard")
        w = world(con)
        start = calc.week_start(calc.d(week) or w.today)
        nav = {"prev": (start - timedelta(days=7)).isoformat(), "next": (start + timedelta(days=7)).isoformat(),
               "this": calc.week_start(w.today).isoformat()}
        if is_admin(user):
            return render(request, "dashboard.html", user, dash=w.dashboard(start), nav=nav)
        me = w.member(user.get("team_name"))
        ctx = {"me": me, "nav": nav, "week": start}
        if me:
            ctx["stats"] = w.team_row(me)
        if user["role"] == "scout":
            name = (user.get("team_name") or "").lower()
            refs = []
            for b in w.bookings:
                lead = w.lead_by_id().get(b.get("lead_id") or "") or {}
                credited = w.scout_for(b)
                tagged = (b.get("referred_by") or lead.get("referred_by") or "").lower() == name
                if tagged and name:
                    refs.append({"night": b["night"], "venue": b["venue"], "handle": b.get("ig_handle"),
                                 "girls": b.get("girls"), "status": b.get("status"),
                                 "counted": calc.girls_counted(b) if credited.lower() == name else 0,
                                 "eligible": credited.lower() == name,
                                 "why": "" if credited.lower() == name else
                                        ("returning guest" if not w.is_first_time(b) else "flat-rate venue")})
            refs.sort(key=lambda r: r["night"] or "", reverse=True)
            ctx["refs"] = refs
            ctx["payouts"] = [x for x in w.ledger if (x.get("person") or "").lower() == name]
            ctx["week_girls"] = sum(r["counted"] for r in refs if calc.d(r["night"]) and
                                    start <= calc.d(r["night"]) < start + timedelta(days=7))
        if user["role"] == "social":
            posts = [c for c in w.content if (c.get("creator") or "").lower() == (user.get("team_name") or "").lower()]
            ctx["formats"] = w.dashboard(start)["formats"]
            ctx["my_posts"] = sorted(({**c, **w.content_row(c)} for c in posts),
                                     key=lambda c: c.get("date_posted") or "", reverse=True)[:20]
        if is_staff(user):
            name = (user.get("team_name") or "").lower()
            ctx["my_nights"] = sorted((n for n in w.all_nights() if (n.get("host") or "").lower() == name
                                       and (calc.d(n["night"]) or date.min) >= w.today - timedelta(days=1)),
                                      key=lambda n: n["night"])[:10]
            ctx["payouts"] = [x for x in w.ledger if (x.get("person") or "").lower() == name]
        return render(request, "home.html", user, **ctx)

    @app.get("/more", response_class=HTMLResponse)
    def more(request: Request, user=Depends(current_user)):
        return render(request, "more.html", user)

    # ---------- tonight ----------
    def tonight_rows(con, user, night: str, venue: str | None):
        where, params = scope(user, "bookings")
        sql = f"SELECT * FROM bookings WHERE night=? AND {where}"
        args = [night, *params]
        if venue:
            sql += " AND venue=? COLLATE NOCASE"
            args.append(venue)
        return db.rows(con, sql + " ORDER BY ig_handle, stop", args)

    @app.get("/tonight", response_class=HTMLResponse)
    def tonight_page(request: Request, night: str | None = None, venue: str | None = None,
                     con=Depends(get_con), user=Depends(current_user)):
        need(user, "tonight")
        w = world(con)
        day = calc.d(night) or tonight(con)
        n = day.isoformat()
        rows = tonight_rows(con, user, n, venue)
        stats = w.guest_stats()
        for b in rows:
            b["tier"] = stats.get((b.get("ig_handle") or "").lower(), {}).get("tier", "Prospect")
            g = next((x for x in w.guests if (x["ig_handle"] or "").lower() == (b.get("ig_handle") or "").lower()), None)
            b["guest_name"] = (g or {}).get("name") or ""
            b["stops"] = sum(1 for r in rows if r["ig_handle"] == b["ig_handle"])
        venues_open = []
        all_n = [x for x in w.all_nights() if x["night"] == n]
        visible_venues = {r["venue"].lower() for r in rows}
        for x in all_n:
            if not is_admin(user) and x["venue"].lower() not in visible_venues and \
                    (x.get("host") or "").lower() != (user.get("team_name") or "").lower():
                continue
            v = w.venue(x["venue"]) or {}
            venues_open.append({**x, "arrive_by": v.get("arrive_by"), "men_policy": v.get("men_policy"),
                                "list_closes": x.get("list_closes") or v.get("list_closes"),
                                "guys_policy": x.get("guys_policy") or v.get("guys_policy"),
                                "dress_code": x.get("dress_code") or v.get("dress_code"), "pending": sum(
                                    1 for r in rows if r["venue"].lower() == x["venue"].lower() and r["status"] == "Confirmed")})
        week = calc.week_start(day)
        hide = hidden_days(con, user)
        lineup = sorted((x for x in w.all_nights() if week <= calc.d(x["night"]) < week + timedelta(days=7)
                         and calc.d(x["night"]).weekday() not in hide),
                        key=lambda x: (x["night"], x["venue"])) if is_admin(user) else []
        return render(request, "tonight.html", user, night=day, rows=rows, venues_open=venues_open, venue=venue,
                      prev=(day - timedelta(days=1)).isoformat(), next=(day + timedelta(days=1)).isoformat(),
                      lineup=lineup, hidden=sorted(hide), today=tonight(con).isoformat())

    @app.post("/bookings/{bid}/checkin")
    async def checkin(request: Request, bid: str, con=Depends(get_con), user=Depends(current_user)):
        form = await form_data(request, user)
        if not can_write(user, "bookings"):
            raise HTTPException(403, "You can't check guests in.")
        where, params = scope(user, "bookings")
        b = db.one(con, f"SELECT * FROM bookings WHERE id=? AND {where}", (bid, *params))
        if not b:
            raise HTTPException(404, "Booking not found.")
        action = form.get("action")
        now = local_now(con).strftime("%Y-%m-%d %H:%M")
        if action == "arrived":
            try:
                count = int(form.get("count")) if form.get("count") not in (None, "") else None
            except ValueError:
                count = None
            if count is not None:
                count = max(0, min(count, 200))
            new = {"status": "Arrived", "girls_arrived": count, "checked_in_at": now, "checked_in_by": user["username"]}
        elif action == "no_show":
            new = {"status": "No-show", "girls_arrived": 0, "checked_in_at": now, "checked_in_by": user["username"]}
        elif action == "undo":
            new = {"status": "Confirmed", "girls_arrived": None, "checked_in_at": None, "checked_in_by": None}
        else:
            raise HTTPException(400, "Unknown action.")
        new["updated_at"], new["updated_by"] = now, user["username"]
        new["checkin_changed_at"] = local_now(con).strftime("%Y-%m-%d %H:%M:%S")
        con.execute(f"UPDATE bookings SET {', '.join(k + '=?' for k in new)} WHERE id=?", (*new.values(), bid))
        # Keep the lead's status in step, so the DM bot sends a thank-you or a "we missed you"
        if b.get("lead_id"):
            others = db.rows(con, "SELECT status FROM bookings WHERE lead_id=?", (b["lead_id"],))
            st = {o["status"] for o in others}
            lead_status = "Arrived" if "Arrived" in st else ("No-show" if st == {"No-show"} else "Confirmed")
            con.execute("UPDATE leads SET status=?, updated_at=?, updated_by=? WHERE id=?",
                        (lead_status, now, user["username"], b["lead_id"]))
        audit(con, user["username"], "bookings", bid, "check-in", new)
        con.commit()
        if request.headers.get("x-requested-with") == "fetch":
            b = db.one(con, "SELECT * FROM bookings WHERE id=?", (bid,))
            w = world(con)
            b["tier"] = w.guest_stats().get((b.get("ig_handle") or "").lower(), {}).get("tier", "Prospect")
            g = next((x for x in w.guests if (x["ig_handle"] or "").lower() == (b.get("ig_handle") or "").lower()), None)
            b["guest_name"] = (g or {}).get("name") or ""
            b["stops"] = 1
            return templates.TemplateResponse(request, "_guest_card.html", {"b": b, "user": user, "csrf": user["csrf"]})
        back = form.get("back") or f"/tonight?night={b['night']}"
        return RedirectResponse(safe_next(back) + f"#b-{bid}", 303)

    # ---------- admin pages (before the generic /{slug} routes) ----------
    from .admin import register as register_admin, register_setup
    register_admin(app, get_con, current_user, form_data, render)
    register_setup(app, get_con, current_user, form_data, render)
    social.register(app, get_con, current_user, form_data, render, world)
    from .cards_feed import register as register_cards
    register_cards(app, get_con, current_user, render)

    # ---------- generic tabs ----------
    def entity_or_404(slug: str, user: dict):
        e = ENTITIES.get(slug)
        if not e:
            raise HTTPException(404, "Page not found.")
        need(user, slug)
        return e

    def computed_for(w: calc.World, e, rows: list[dict]) -> None:
        stats = w.guest_stats() if e.slug in ("leads", "guests") else None
        for r in rows:
            if e.slug == "leads":
                r.update(w.lead_row(r, stats))
            elif e.slug == "guests":
                r.update(w.guest_row(r, stats))
            elif e.slug == "bookings":
                r.update(w.booking_row(r))
            elif e.slug == "nights":
                r.update(w.night_row(r["night"], r["venue"], r.get("flat_override")))
            elif e.slug == "venues":
                r.update(w.venue_row(r))
            elif e.slug == "team":
                r.update(w.team_row(r))
            elif e.slug == "content":
                r.update(w.content_row(r))
            elif e.slug == "ledger":
                r.update(w.ledger_row(r))
        if e.slug in SOCIAL_TABLES:
            with db.session() as con2:
                social.computed(con2, w, e.slug, rows)

    def query_rows(con, e, user, q: str, status: str, venue: str, frm: str, to: str, page: int, limit=PAGE_SIZE):
        where, params = scope(user, e.slug)
        clauses, args = [where], list(params)
        if q:
            clauses.append("(" + " OR ".join(f"{c} LIKE ?" for c in e.search) + ")")
            args += [f"%{q}%"] * len(e.search)
        names = {f.name for f in e.fields}
        if status and "status" in names:
            clauses.append("status=?")
            args.append(status)
        vcol = "venue" if "venue" in names else ("name" if e.slug == "venues" else None)
        if venue and vcol:
            clauses.append(f"{vcol}=? COLLATE NOCASE")
            args.append(venue)
        dcol = next((c for c in ("night", "created_at", "date", "date_posted") if c in names), None)
        if dcol and frm:
            clauses.append(f"{dcol} >= ?")
            args.append(frm)
        if dcol and to:
            clauses.append(f"{dcol} < ?")
            args.append((calc.d(to) + timedelta(days=1)).isoformat() if calc.d(to) else to)
        sql = f"FROM {e.table} WHERE {' AND '.join(clauses)}"
        total = con.execute(f"SELECT COUNT(*) {sql}", args).fetchone()[0]
        sql = f"SELECT * {sql} ORDER BY {e.order or e.pk}"
        if limit:
            sql += f" LIMIT {int(limit)} OFFSET {int(max(page - 1, 0) * limit)}"
        return db.rows(con, sql, args), total, dcol

    @app.get("/export/{slug}.csv")
    def export(slug: str, con=Depends(get_con), user=Depends(current_user)):
        e = entity_or_404(slug, user)
        if not is_admin(user):
            raise HTTPException(403, "Only admins can export.")
        rows, _, _ = query_rows(con, e, user, "", "", "", "", "", 1, limit=0)
        computed_for(world(con), e, rows)
        cols = [(f.name, f.label) for f in e.fields] + [(k, label) for k, label, _ in e.computed]
        buf = io.StringIO()
        wr = csv.writer(buf)
        wr.writerow([label for _, label in cols])
        for r in rows:
            wr.writerow(["" if r.get(k) is None else r.get(k) for k, _ in cols])
        audit(con, user["username"], slug, "*", "export")
        con.commit()
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="muse-{slug}.csv"'})

    # ---------- bulk delete (admins): tick rows on the list and delete them together ----------
    BULK_DELETE = ("leads", "guests", "bookings")

    @app.post("/{slug}/delete-selected")
    async def delete_selected(request: Request, slug: str, con=Depends(get_con), user=Depends(current_user)):
        e = entity_or_404(slug, user)
        form = await form_data(request, user)
        if not is_admin(user) or slug not in BULK_DELETE:
            raise HTTPException(403, "Only admins can delete.")
        ids = list(dict.fromkeys(i for i in form.getlist("ids") if i))[:1000]
        deleted = 0
        for rid in ids:
            old = db.one(con, f"SELECT * FROM {e.table} WHERE {e.pk}=?", (rid,))
            if not old:
                continue
            con.execute(f"DELETE FROM {e.table} WHERE {e.pk}=?", (rid,))
            audit(con, user["username"], slug, rid, "delete (bulk)", old)
            deleted += 1
        con.commit()
        back = form.get("back") or f"/{slug}"
        back = back if back.startswith("/") and not back.startswith("//") else f"/{slug}"
        return RedirectResponse(back + ("&" if "?" in back else "?") + f"deleted={deleted}", 303)

    # ---------- per-person view settings ----------
    @app.post("/prefs/columns/{slug}")
    async def prefs_columns(request: Request, slug: str, con=Depends(get_con), user=Depends(current_user)):
        e = entity_or_404(slug, user)
        form = await form_data(request, user)
        if form.get("reset"):
            set_pref(con, user, "cols:" + slug, None)
        else:
            allowed = {f.name for f in visible_fields(e, user)} | {c[0] for c in visible_computed(e, user)}
            set_pref(con, user, "cols:" + slug, [c for c in form.getlist("col") if c in allowed])
        con.commit()
        return RedirectResponse(safe_next(form.get("back") or f"/{slug}"), 303)

    @app.post("/prefs/days")
    async def prefs_days(request: Request, con=Depends(get_con), user=Depends(current_user)):
        form = await form_data(request, user)
        shown = {int(x) for x in form.getlist("day") if str(x).isdigit()}
        hide = sorted(set(range(7)) - shown)
        set_pref(con, user, "hidden_days", None if not hide or len(hide) == 7 else hide)
        con.commit()
        return RedirectResponse(safe_next(form.get("back") or "/"), 303)

    @app.get("/{slug}", response_class=HTMLResponse)
    def list_page(request: Request, slug: str, q: str = "", status: str = "", venue: str = "", frm: str = "",
                  to: str = "", page: int = 1, con=Depends(get_con), user=Depends(current_user)):
        e = entity_or_404(slug, user)
        rows, total, dcol = query_rows(con, e, user, q.strip(), status, venue, frm, to, page)
        computed_for(world(con), e, rows)
        qs = {k: v for k, v in {"q": q, "status": status, "venue": venue, "frm": frm, "to": to}.items() if v}
        all_fields, all_computed = visible_fields(e, user), visible_computed(e, user)
        shown = get_pref(con, user, "cols:" + slug)            # None = the default columns
        if shown is None:
            fields, computed = [f for f in all_fields if f.list], all_computed
        else:
            shown = set(shown)
            fields = [f for i, f in enumerate(all_fields) if i == 0 or f.name in shown]   # first column always stays
            computed = [c for c in all_computed if c[0] in shown]
        col_choices = [(f.name, f.label, f in fields, i == 0) for i, f in enumerate(all_fields)] + \
                      [(c[0], c[1], c in computed, False) for c in all_computed]
        return render(request, "list.html", user, e=e, rows=rows, deleted=request.query_params.get("deleted"),
                      bulk=is_admin(user) and slug in BULK_DELETE, total=total, page=page, pages=max(1, -(-total // PAGE_SIZE)),
                      fields=fields, computed=computed, col_choices=col_choices, cols_custom=shown is not None,
                      q=q, status=status, venue=venue, frm=frm, to=to, dcol=dcol, qs=urlencode(qs),
                      opts=options(con), status_choices=next((f.choices for f in e.fields if f.name == "status"), None))

    def load_row(con, e, user, rid):
        where, params = scope(user, e.slug)
        r = db.one(con, f"SELECT * FROM {e.table} WHERE {e.pk}=? AND {where}", (rid, *params))
        if not r:
            raise HTTPException(404, f"That {e.singular} doesn't exist or isn't yours.")
        return r

    def related(con, w, e, user, r) -> dict:
        out = {}
        if e.slug in ("guests", "leads"):
            where, params = scope(user, "bookings")
            col, val = ("ig_handle", r["ig_handle"]) if e.slug == "guests" else ("lead_id", r["id"])
            bs = db.rows(con, f"SELECT * FROM bookings WHERE {col}=? AND {where} ORDER BY night DESC, stop", (val, *params))
            for b in bs:
                b.update(w.booking_row(b))
            out["bookings"] = bs
        if e.slug == "guests":
            where, params = scope(user, "leads")
            out["leads"] = db.rows(con, f"SELECT * FROM leads WHERE ig_handle=? AND {where} ORDER BY created_at DESC",
                                   (r["ig_handle"], *params))
        if e.slug in SOCIAL_TABLES:
            out.update(social.related(con, e.slug, r))
        if e.slug == "nights":
            where, params = scope(user, "bookings")
            out["bookings"] = db.rows(con, f"SELECT * FROM bookings WHERE night=? AND venue=? AND {where} ORDER BY ig_handle",
                                      (r["night"], r["venue"], *params))
        return out

    def defaults(con, e, user, request: Request) -> dict:
        r = {}
        qp = request.query_params
        if e.slug == "leads":
            r = {"created_at": local_now(con).strftime("%Y-%m-%d %H:%M"), "status": "New", "channel": "Instagram"}
        elif e.slug == "bookings":
            r = {"night": tonight(con).isoformat(), "status": "Confirmed", "stop": 1, "confirmation_sent": 1}
            lid = qp.get("lead")
            if lid:
                lead = db.one(con, f"SELECT * FROM leads WHERE id=? AND {scope(user, 'leads')[0]}",
                              (lid, *scope(user, "leads")[1]))
                if lead:
                    r.update(night=lead["night"] or r["night"], venue=lead["venue"], ig_handle=lead["ig_handle"],
                             lead_id=lead["id"], host=lead["host"], party_size=lead["party_size"],
                             girls=lead["girls"], guys=lead["guys"])
            for k in ("night", "venue", "ig_handle", "stop"):
                if qp.get(k):
                    r[k] = qp.get(k)
        elif e.slug == "ledger":
            r = {"date": local_now(con).date().isoformat(), "status": "Paid"}
        elif e.slug == "nights":
            r = {"night": tonight(con).isoformat()}
        elif e.slug in ("venues", "team"):
            r = {"status": "Active"}
        elif e.slug == "content":
            r = {"date_posted": local_now(con).date().isoformat(), "platform": "Instagram",
                 "creator": user.get("team_name")}
        elif e.slug in SOCIAL_TABLES:
            r = social.defaults(con, e.slug, user, qp)
        if is_staff(user) and e.slug in ("leads", "bookings"):
            r["host"] = user.get("team_name")
        return r

    def form_ctx(con, e, user, r, error=None, new=False, rel=None, w=None):
        computed = []
        if not new and w is not None:
            rr = dict(r)
            computed_for(w, e, [rr])
            computed = [(label, rr.get(k), k) for k, label, _ in visible_computed(e, user)]
        return dict(e=e, r=r, error=error, new=new, fields=visible_fields(e, user), opts=options(con),
                    editable=can_write(user, e.slug), related=rel or {}, computed=computed,
                    host_locked=is_staff(user) and e.slug in ("leads", "bookings"))

    @app.get("/{slug}/new", response_class=HTMLResponse)
    def new_page(request: Request, slug: str, con=Depends(get_con), user=Depends(current_user)):
        e = entity_or_404(slug, user)
        if not can_write(user, slug):
            raise HTTPException(403, "You can't add to this tab.")
        return render(request, "form.html", user, **form_ctx(con, e, user, defaults(con, e, user, request), new=True))

    def save(con, e, user, form, existing: dict | None) -> dict:
        vals = {}
        for f in visible_fields(e, user):
            if f.name == e.pk and e.id_prefix:
                continue
            if f.name not in form and f.type != "bool":
                continue
            vals[f.name] = parse_value(f, form.get(f.name))
        if is_staff(user) and e.slug in ("leads", "bookings"):
            vals["host"] = (existing or {}).get("host") or user.get("team_name")
            if not existing:
                vals["host"] = user.get("team_name")
        if e.slug == "bookings" and vals.get("status") == "No-show":
            vals["girls_arrived"] = 0
        if e.slug == "plan":
            vals.update(social.check_plan(con, user, vals, existing))
        if e.slug == "team" and vals.get("role") == "Engineer" and not existing:
            # engineers get a flat $50 a month unless something else is filled in
            vals["pay_type"] = vals.get("pay_type") or "Monthly flat"
            vals["pay_rate"] = vals.get("pay_rate") if vals.get("pay_rate") is not None else 50
            vals["start_date"] = vals.get("start_date") or local_now(con).date().isoformat()
        return vals

    def sync_lead_booking(con, user, lead_id: str) -> None:
        """A lead marked Confirmed with a night and venue gets its booking automatically, and later edits to the lead
        (night, venue, party, host) carry over to that booking while it's still unplayed. A lead marked Lost cancels
        its unplayed bookings. Multi-stop leads (2+ bookings) are left alone: edit those bookings directly."""
        lead = db.one(con, "SELECT * FROM leads WHERE id=?", (lead_id,))
        if not lead:
            return
        bks = db.rows(con, "SELECT * FROM bookings WHERE lead_id=? ORDER BY stop", (lead_id,))
        now = local_now(con).strftime("%Y-%m-%d %H:%M")
        keys = ("night", "venue", "ig_handle", "host", "party_size", "girls", "guys")
        if lead["status"] == "Confirmed" and lead.get("night") and lead.get("venue") and lead.get("ig_handle"):
            if not bks:
                bid = next_id(con, ENTITIES["bookings"])
                vals = {"id": bid, **{k: lead.get(k) for k in keys}, "lead_id": lead_id, "stop": 1,
                        "status": "Confirmed", "updated_at": now, "updated_by": user["username"]}
                con.execute(f"INSERT INTO bookings ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})",
                            list(vals.values()))
                ensure_night(con, lead["night"], lead["venue"])
                audit(con, user["username"], "bookings", bid, "create from lead", vals)
            elif len(bks) == 1 and bks[0]["status"] == "Confirmed":
                b = bks[0]
                ch = {k: lead.get(k) for k in keys if lead.get(k) not in (None, "") and lead.get(k) != b.get(k)}
                if ch:
                    ch.update(updated_at=now, updated_by=user["username"])
                    con.execute(f"UPDATE bookings SET {', '.join(k + '=?' for k in ch)} WHERE id=?", (*ch.values(), b["id"]))
                    ensure_night(con, lead["night"], lead["venue"])
                    audit(con, user["username"], "bookings", b["id"], "update from lead", ch)
        elif lead["status"] == "Lost":
            for b in bks:
                if b["status"] == "Confirmed":
                    con.execute("UPDATE bookings SET status='Cancelled', updated_at=?, updated_by=? WHERE id=?",
                                (now, user["username"], b["id"]))
                    audit(con, user["username"], "bookings", b["id"], "cancelled (lead lost)")

    @app.post("/{slug}/new")
    async def create(request: Request, slug: str, con=Depends(get_con), user=Depends(current_user)):
        e = entity_or_404(slug, user)
        form = await form_data(request, user)
        if not can_write(user, slug):
            raise HTTPException(403, "You can't add to this tab.")
        try:
            vals = save(con, e, user, form, None)
            if e.id_prefix:
                vals[e.pk] = next_id(con, e)
            if e.slug == "guests" and db.one(con, "SELECT 1 FROM guests WHERE ig_handle=?", (vals["ig_handle"],)):
                raise FormError("A guest with that IG handle already exists.")
            if e.slug == "content" and db.one(con, "SELECT 1 FROM content WHERE post_id=?", (vals["post_id"],)):
                raise FormError("That Post ID is already used.")
            if e.slug in ("venues", "team", "campaigns") and db.one(con, f"SELECT 1 FROM {e.table} WHERE name=?", (vals["name"],)):
                raise FormError(f"There's already a {e.singular} called {vals['name']}.")
            if e.slug == "nights" and db.one(con, "SELECT 1 FROM nights WHERE night=? AND venue=?",
                                             (vals["night"], vals["venue"])):
                raise FormError("That venue already has this night on the lineup.")
        except FormError as err:
            r = {f.name: form.get(f.name) for f in e.fields}
            return render(request, "form.html", user, 400, **form_ctx(con, e, user, r, str(err), new=True))
        vals["updated_at"] = local_now(con).strftime("%Y-%m-%d %H:%M")
        if e.slug in ("leads", "bookings", "plan"):
            vals["updated_by"] = user["username"]
        cur = con.execute(f"INSERT INTO {e.table} ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})",
                          list(vals.values()))
        rid = vals.get(e.pk) or cur.lastrowid
        if e.slug == "bookings":
            ensure_night(con, vals.get("night"), vals.get("venue"))
        if e.slug in ("leads", "bookings") and vals.get("ig_handle"):
            con.execute("INSERT OR IGNORE INTO guests(ig_handle, first_contact, first_channel, updated_at) VALUES (?,?,?,?)",
                        (vals["ig_handle"], (vals.get("created_at") or vals.get("night") or "")[:10] or None,
                         vals.get("channel"), vals["updated_at"]))
        social.after_save(con, user, slug, rid)
        audit(con, user["username"], slug, rid, "create", vals)
        if e.slug == "leads":
            sync_lead_booking(con, user, rid)
        con.commit()
        return RedirectResponse(f"/{slug}/{quote(str(rid), safe='')}?saved=1", 303)

    @app.get("/{slug}/{rid}", response_class=HTMLResponse)
    def detail(request: Request, slug: str, rid: str, con=Depends(get_con), user=Depends(current_user)):
        e = entity_or_404(slug, user)
        r = load_row(con, e, user, rid)
        w = world(con)
        return render(request, "form.html", user, saved=request.query_params.get("saved"),
                      **form_ctx(con, e, user, r, rel=related(con, w, e, user, r), w=w))

    @app.post("/{slug}/{rid}")
    async def update(request: Request, slug: str, rid: str, con=Depends(get_con), user=Depends(current_user)):
        e = entity_or_404(slug, user)
        form = await form_data(request, user)
        if not can_write(user, slug):
            raise HTTPException(403, "This tab is read-only for you.")
        old = load_row(con, e, user, rid)
        try:
            vals = save(con, e, user, form, old)
            if e.slug in ("venues", "team", "campaigns") and vals.get("name") and vals["name"].lower() != old["name"].lower() and \
                    db.one(con, f"SELECT 1 FROM {e.table} WHERE name=?", (vals["name"],)):
                raise FormError(f"There's already a {e.singular} called {vals['name']}.")
        except FormError as err:
            r = {**old, **{f.name: form.get(f.name) for f in e.fields if f.name in form}}
            return render(request, "form.html", user, 400, **form_ctx(con, e, user, r, str(err)))
        if e.slug in ("guests", "content"):
            vals.pop(e.pk, None)   # the handle / post ID links rows together, so it can't be renamed here
        changes = {k: v for k, v in vals.items() if old.get(k) != v}
        if changes:
            changes["updated_at"] = local_now(con).strftime("%Y-%m-%d %H:%M")
            if e.slug in ("leads", "bookings", "plan"):
                changes["updated_by"] = user["username"]
            con.execute(f"UPDATE {e.table} SET {', '.join(k + '=?' for k in changes)} WHERE {e.pk}=?",
                        (*changes.values(), rid))
            if e.slug == "venues" and "ticket_link" in changes:
                con.execute("UPDATE venues SET ticket_link_updated_at=? WHERE id=?",
                            (local_now(con).date().isoformat(), rid))
            if e.slug == "venues" and "name" in changes:
                cascade_rename(con, "venue", old["name"], changes["name"])
            if e.slug == "team" and "name" in changes:
                cascade_rename(con, "team", old["name"], changes["name"])
            if e.slug == "campaigns" and "name" in changes:
                cascade_rename(con, "campaign", old["name"], changes["name"])
            social.after_save(con, user, slug, rid)
            if e.slug == "bookings":
                ensure_night(con, vals.get("night", old["night"]), vals.get("venue", old["venue"]))
            audit(con, user["username"], slug, rid, "update", {k: [old.get(k), v] for k, v in changes.items()
                                                                if k != "updated_at"})
        if e.slug == "leads":   # also on a save with no changes, so leads confirmed earlier get their booking
            sync_lead_booking(con, user, rid)
        con.commit()
        return RedirectResponse(f"/{slug}/{quote(str(rid), safe='')}?saved=1", 303)

    @app.post("/{slug}/{rid}/delete")
    async def delete(request: Request, slug: str, rid: str, con=Depends(get_con), user=Depends(current_user)):
        e = entity_or_404(slug, user)
        await form_data(request, user)
        if not is_admin(user):
            raise HTTPException(403, "Only admins can delete. Set the status to Cancelled or Lost instead.")
        old = load_row(con, e, user, rid)
        con.execute(f"DELETE FROM {e.table} WHERE {e.pk}=?", (rid,))
        audit(con, user["username"], slug, rid, "delete", old)
        con.commit()
        return RedirectResponse(f"/{slug}", 303)


app = create_app()
