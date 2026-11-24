"""Social planner: seeding, permissions, the approval rule, posted -> Content, ideas -> calendar, follower goal."""
from tests.conftest import csrf, login


def test_seeded_campaigns_and_posts(con):
    names = {r[0] for r in con.execute("SELECT name FROM campaigns")}
    assert {"Going Out With Muse", "Why we made Thalia", "Dayguard pilot"} <= names
    assert con.execute("SELECT status FROM campaigns WHERE name='Dayguard pilot'").fetchone()[0] == "Unconfirmed"
    thalia = con.execute("SELECT COUNT(*), SUM(needs_approval) FROM plan WHERE campaign='Why we made Thalia'").fetchone()
    assert tuple(thalia) == (14, 14)
    assert con.execute("SELECT planned_date FROM plan WHERE title LIKE 'Thalia #1:%Reel%'").fetchone()[0] == "2026-11-22"
    assert con.execute("SELECT COUNT(*) FROM ideas").fetchone()[0] >= 10
    # runs once: init again doesn't duplicate
    from app import db
    db.init(con)
    assert con.execute("SELECT COUNT(*) FROM plan WHERE campaign='Why we made Thalia'").fetchone()[0] == 14


def test_social_pages_and_who_sees_them(client):
    login(client, "rae")
    assert client.get("/", follow_redirects=False).headers["location"] == "/social"
    for p in ["/social", "/calendar", "/calendar?month=2026-12", "/plan", "/campaigns", "/ideas", "/shoots", "/growth",
              "/plan/new", "/ideas/new", "/shoots/new", "/campaigns/1", "/plan/P-00001"]:
        r = client.get(p)
        assert r.status_code == 200, p
    assert "Why we made Thalia" in client.get("/calendar?month=2026-11").text
    login(client, "mia")
    for p in ["/social", "/calendar", "/plan", "/ideas"]:
        assert client.get(p).status_code == 403, p
    login(client, "boss")
    assert client.get("/social").status_code == 200


def _plan(client, **kw):
    data = {"csrf": csrf(client), "planned_date": "2026-11-20", "title": "Test post", "format": "Reel",
            "status": "Planned", "owner": "Rae", "needs_approval": "0"}
    data.update(kw)
    return client.post("/plan/new", data=data, follow_redirects=False)


def test_approval_rule(client, con):
    login(client, "rae")
    r = _plan(client, needs_approval="1", title="New series")
    assert r.status_code == 303
    pid = r.headers["location"].split("/")[2].split("?")[0]
    # social can't schedule, post or approve it herself
    for st in ("Approved", "Scheduled", "Posted"):
        r = client.post(f"/plan/{pid}", data={"csrf": csrf(client), "planned_date": "2026-11-20", "title": "New series",
                                               "format": "Reel", "status": st, "needs_approval": "1"})
        assert r.status_code == 400 and "founder" in r.text, st
    # nor untick the approval box
    client.post(f"/plan/{pid}", data={"csrf": csrf(client), "planned_date": "2026-11-20", "title": "New series",
                                      "format": "Reel", "status": "Editing", "needs_approval": "0"})
    assert con.execute("SELECT needs_approval FROM plan WHERE id=?", (pid,)).fetchone()[0] == 1
    # quick-move from the board is gated too
    r = client.post(f"/plan/{pid}/review", data={"csrf": csrf(client), "action": "status", "status": "Scheduled", "back": "/social"},
                    follow_redirects=False)
    assert "err=" in r.headers["location"]
    client.post(f"/plan/{pid}/review", data={"csrf": csrf(client), "action": "submit"})
    assert con.execute("SELECT status FROM plan WHERE id=?", (pid,)).fetchone()[0] == "Ready for review"
    assert client.post(f"/plan/{pid}/review", data={"csrf": csrf(client), "action": "approve"}).status_code == 403
    assert "New series" in client.get("/social").text
    # founder approves with a note, then she can schedule it
    login(client, "boss")
    client.post(f"/plan/{pid}/review", data={"csrf": csrf(client), "action": "approve", "note": "Love it"})
    row = con.execute("SELECT status, approved_by, review_note FROM plan WHERE id=?", (pid,)).fetchone()
    assert tuple(row) == ("Approved", "boss", "Love it")
    login(client, "rae")
    r = client.post(f"/plan/{pid}/review", data={"csrf": csrf(client), "action": "status", "status": "Scheduled"},
                    follow_redirects=False)
    assert "err=" not in r.headers["location"]
    assert con.execute("SELECT status FROM plan WHERE id=?", (pid,)).fetchone()[0] == "Scheduled"
    # send back clears the approval
    login(client, "boss")
    client.post(f"/plan/{pid}/review", data={"csrf": csrf(client), "action": "sendback", "note": "Shorter hook"})
    assert tuple(con.execute("SELECT status, approved_at FROM plan WHERE id=?", (pid,)).fetchone()) == ("Editing", None)


def test_posts_without_approval_flow_freely_and_land_on_content(client, con):
    login(client, "rae")
    r = _plan(client, content_type="Street interview", hook="Rate your fit")
    pid = r.headers["location"].split("/")[2].split("?")[0]
    client.post(f"/plan/{pid}/review", data={"csrf": csrf(client), "action": "status", "status": "Posted"})
    c = con.execute("SELECT post_id, format, creator, hook FROM content WHERE post_id=?", (pid,)).fetchone()
    assert tuple(c) == (pid, "Street interview", "Rae", "Rate your fit")
    assert con.execute("SELECT post_id FROM plan WHERE id=?", (pid,)).fetchone()[0] == pid
    con.execute("UPDATE content SET views=150000 WHERE post_id=?", (pid,))
    con.execute("INSERT INTO leads(id, ig_handle, source_content_id) VALUES ('DM-1', 'zoe', ?)", (pid,))
    con.commit()
    assert "150000" in client.get(f"/plan/{pid}").text


def test_social_cannot_approve_in_form(client):
    login(client, "rae")
    r = _plan(client, status="Approved")
    assert r.status_code == 400


def test_idea_to_calendar(client, con):
    login(client, "rae")
    r = client.post("/ideas/new", data={"csrf": csrf(client), "title": "Rate my fit series", "format": "Reel",
                                        "status": "New", "new_format": "1", "priority": "High"}, follow_redirects=False)
    iid = r.headers["location"].split("/")[2].split("?")[0]
    assert "Rate my fit series" in client.get("/social").text   # new-format idea shows in the founder queue
    r = client.post(f"/ideas/{iid}/schedule", data={"csrf": csrf(client), "date": "2026-11-28"}, follow_redirects=False)
    pid = r.headers["location"].split("/")[2].split("?")[0]
    p = con.execute("SELECT title, planned_date, needs_approval, owner, idea_id FROM plan WHERE id=?", (pid,)).fetchone()
    assert tuple(p) == ("Rate my fit series", "2026-11-28", 1, "Rae", iid)
    assert con.execute("SELECT status, plan_id FROM ideas WHERE id=?", (iid,)).fetchone()[0] == "On the calendar"


def test_follower_goal(client, con):
    con.execute("INSERT INTO growth(date, followers) VALUES ('2026-11-10', 4000)")
    con.commit()
    login(client, "rae")
    client.post("/growth/quick", data={"csrf": csrf(client), "followers": "4,700"})
    html = client.get("/social").text
    assert "4,700" in html and "5,300" in html
    assert client.get("/growth").status_code == 200


def test_campaign_rename_moves_posts(client, con):
    login(client, "boss")
    cid = con.execute("SELECT id FROM campaigns WHERE name='Dayguard pilot'").fetchone()[0]
    r = client.post(f"/campaigns/{cid}", data={"csrf": csrf(client), "name": "Dayguard x Muse", "status": "Active"})
    assert r.status_code == 200
    login(client, "rae")
    _plan(client, campaign="Dayguard x Muse")
    assert con.execute("SELECT COUNT(*) FROM plan WHERE campaign='Dayguard x Muse'").fetchone()[0] == 1
