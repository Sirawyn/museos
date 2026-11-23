"""Card Instagrams: the Instagrams the Muse NFC cards collected (tap.musehospitality.social, the muse-cards app).

Muse OS doesn't store them. Each time the page opens it asks the cards app for its list, live:
  CARDS_URL    where Muse OS reaches the cards app, e.g. http://muse-cards:8000 (same Docker network)
  CARDS_TOKEN  the cards app's ADMIN_TOKEN
Admins only: the friend sign-ups agreed to Muse DMing them about nights out, nothing else.
"""
from __future__ import annotations

import csv
import io
import json
import os
import urllib.error
import urllib.request
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

HOW = {"owner": "Card owner", "friend": "Friend sign-up"}


class FeedError(Exception):
    pass


def fetch() -> list[dict]:
    url = os.getenv("CARDS_URL", "").rstrip("/")
    token = os.getenv("CARDS_TOKEN", "")
    if not url or not token:
        raise FeedError("Not connected yet. Set CARDS_URL and CARDS_TOKEN in Muse OS's .env, then restart it.")
    req = urllib.request.Request(url + "/instagrams.json", headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise FeedError("The cards app turned down the token. Check CARDS_TOKEN matches its ADMIN_TOKEN.") from e
        raise FeedError(f"The cards app answered with an error ({e.code}).") from e
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise FeedError("Can't reach the cards app at CARDS_URL right now.") from e
    return list(data.get("instagrams") or [])


def when(v: str | None) -> str:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).strftime("%b %-d, %Y")
    except (TypeError, ValueError):
        return v or ""


def rows(con, items: list[dict]) -> list[dict]:
    """Add how she came in, and whether Muse OS already knows her (guest or lead)."""
    guests = {r[0] for r in con.execute("SELECT LOWER(ig_handle) FROM guests WHERE ig_handle IS NOT NULL")}
    leads = {r[0] for r in con.execute("SELECT LOWER(ig_handle) FROM leads WHERE ig_handle IS NOT NULL")}
    out = []
    for x in items:
        h = str(x.get("instagram") or "").lstrip("@").lower()
        if not h:
            continue
        how = list(x.get("how") or [])
        out.append({
            "instagram": h,
            "how": ", ".join(HOW.get(k, k) for k in how),
            "kind": "owner" if "owner" in how else "friend",
            "referred_by": ["@" + v for v in (x.get("referred_by") or [])],
            "cards": list(x.get("cards") or []),
            "first_seen": when(x.get("first_seen")),
            "last_seen": when(x.get("last_seen")),
            "known": "Guest" if h in guests else ("Lead" if h in leads else ""),
        })
    return out


def register(app: FastAPI, get_con, current_user, render) -> None:
    def need_admin(user):
        if user["role"] != "admin":
            raise HTTPException(403, "You don't have access to this page.")

    @app.get("/instagrams", response_class=HTMLResponse)
    def instagrams(request: Request, q: str = "", how: str = "", new: str = "", con=Depends(get_con),
                   user=Depends(current_user)):
        need_admin(user)
        error, items = None, []
        try:
            items = rows(con, fetch())
        except FeedError as e:
            error = str(e)
        counts = {"all": len(items), "owner": sum(i["kind"] == "owner" for i in items),
                  "friend": sum(i["kind"] == "friend" for i in items)}
        ql = q.strip().lstrip("@").lower()
        shown = [i for i in items
                 if (not ql or ql in i["instagram"] or any(ql in r.lower() for r in i["referred_by"]))
                 and (how not in ("owner", "friend") or i["kind"] == how)
                 and (not new or not i["known"])]
        return render(request, "instagrams.html", user, rows=shown, counts=counts, error=error, q=q, how=how,
                      new=new, qs=str(request.url.query))

    @app.get("/instagrams.csv")
    def instagrams_csv(con=Depends(get_con), user=Depends(current_user)):
        need_admin(user)
        try:
            items = rows(con, fetch())
        except FeedError as e:
            raise HTTPException(502, str(e)) from e
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["instagram", "how", "referred_by", "cards", "first_seen", "last_seen", "in_muse_os"])
        for i in items:
            w.writerow([i["instagram"], i["how"], " ".join(i["referred_by"]), " ".join(i["cards"]),
                        i["first_seen"], i["last_seen"], i["known"]])
        return PlainTextResponse(out.getvalue(), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=card-instagrams.csv"})
