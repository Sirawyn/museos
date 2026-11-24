from tests.conftest import PW, csrf, login


def seed_night(con):
    con.execute("INSERT INTO nights(night, venue, host) VALUES ('2026-11-13','Nebula','Mia')")
    con.execute("INSERT INTO nights(night, venue, host) VALUES ('2026-11-13','NOFLEX','Sam')")
    rows = [("BK-1", "Nebula", "alice", "Mia", None), ("BK-2", "NOFLEX", "bella", "Sam", None),
            ("BK-3", "Nebula", "cara", "Sam", "Jess"), ("BK-4", "NOFLEX", "dana", "Sam", "Kim")]
    for bid, v, h, host, scout in rows:
        con.execute("INSERT INTO bookings(id, night, venue, ig_handle, host, girls, status, referred_by, table_spend) "
                    "VALUES (?, '2026-11-13', ?, ?, ?, 4, 'Confirmed', ?, 500)", (bid, v, h, host, scout))
    con.execute("INSERT INTO leads(id, ig_handle, host, status) VALUES ('DM-00001','alice','Mia','Confirmed')")
    con.execute("UPDATE bookings SET lead_id='DM-00001' WHERE id='BK-1'")
    con.execute("INSERT INTO leads(id, ig_handle, host, status) VALUES ('DM-00002','bella','Sam','Confirmed')")
    for h in ("alice", "bella", "cara", "dana"):
        con.execute("INSERT INTO guests(ig_handle, phone) VALUES (?, '555-0100')", (h,))
    con.execute("INSERT INTO ledger(date, type, venue, amount, status) VALUES ('2026-11-14','Venue payment','Nebula',999,'Paid')")
    con.commit()


def test_login_required_everywhere(client):
    for p in ["/dashboard", "/tonight", "/leads", "/guests", "/bookings", "/ledger", "/admin/users", "/leads/DM-00001"]:
        r = client.get(p, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/login"), p


def test_bad_password_and_throttle(client):
    for _ in range(8):
        r = client.post("/login", data={"username": "boss", "password": "nope"})
        assert r.status_code == 401
    r = client.post("/login", data={"username": "boss", "password": PW})
    assert r.status_code == 429


def test_session_cookie_flags(client):
    r = client.post("/login", data={"username": "boss", "password": PW}, follow_redirects=False)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_security_headers(client):
    r = client.get("/login")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"


def test_csrf_required(client, con):
    seed_night(con)
    login(client, "mia")
    r = client.post("/bookings/BK-1/checkin", data={"action": "arrived", "count": "3"})
    assert r.status_code == 403
    assert con.execute("SELECT status FROM bookings WHERE id='BK-1'").fetchone()[0] == "Confirmed"


def test_logout_kills_session(client):
    login(client, "boss")
    token = csrf(client)
    client.post("/logout", data={"csrf": token})
    assert client.get("/dashboard", follow_redirects=False).status_code == 303


def test_first_login_must_change_password(client, con):
    con.execute("UPDATE users SET must_change_password=1 WHERE username='mia'")
    con.commit()
    login(client, "mia")
    r = client.get("/tonight", follow_redirects=False)
    assert r.headers["location"] == "/account?first=1"
    token = csrf(client, "/account")
    r = client.post("/account", data={"csrf": token, "current_password": PW, "new_password": "short",
                                      "confirm_password": "short"})
    assert r.status_code == 400
    r = client.post("/account", data={"csrf": token, "current_password": PW, "new_password": "a-much-longer-pass",
                                      "confirm_password": "a-much-longer-pass"})
    assert r.status_code == 200
    assert client.get("/tonight", follow_redirects=False).status_code == 200


def test_admin_sees_everything(client, con):
    seed_night(con)
    login(client, "boss")
    for p in ["/dashboard", "/tonight?night=2026-11-13", "/leads", "/guests", "/bookings", "/nights", "/venues",
              "/team", "/content", "/ledger", "/admin/users", "/admin/keys", "/admin/settings", "/admin/audit"]:
        assert client.get(p).status_code == 200, p
    html = client.get("/tonight?night=2026-11-13").text
    assert all(h in html for h in ("alice", "bella", "cara", "dana"))
    assert "Flat per night" in client.get("/venues").text


def test_host_sees_only_their_guests_and_no_money(client, con):
    seed_night(con)
    login(client, "mia")
    html = client.get("/tonight?night=2026-11-13").text
    # Mia is on duty at Nebula: her own booking and Sam's booking at Nebula, nothing at NOFLEX
    assert "alice" in html and "cara" in html and "bella" not in html and "dana" not in html
    assert "bella" not in client.get("/bookings").text
    assert "bella" not in client.get("/guests").text
    assert client.get("/leads/DM-00002").status_code == 404
    assert client.get("/bookings/BK-2").status_code == 404
    for p in ["/ledger", "/team", "/content", "/admin/users", "/export/leads.csv"]:
        assert client.get(p).status_code == 403, p
    for p in ["/venues", "/bookings", "/bookings/BK-1", "/nights", "/tonight?night=2026-11-13", "/dashboard"]:
        html = client.get(p).text
        assert "Revenue" not in html and "Commission" not in html and "Table/bottle" not in html, p
        assert "Flat per night" not in html and "Rate per guest" not in html, p


def test_host_checkin_flow(client, con):
    seed_night(con)
    login(client, "mia")
    token = csrf(client)
    r = client.post("/bookings/BK-1/checkin", data={"csrf": token, "action": "arrived", "count": "3"},
                    headers={"X-Requested-With": "fetch"})
    assert r.status_code == 200 and "3 in" in r.text
    b = con.execute("SELECT status, girls_arrived, checked_in_by FROM bookings WHERE id='BK-1'").fetchone()
    assert tuple(b) == ("Arrived", 3, "mia")
    assert con.execute("SELECT status FROM leads WHERE id='DM-00001'").fetchone()[0] == "Arrived"
    # can't touch a booking outside their scope
    r = client.post("/bookings/BK-2/checkin", data={"csrf": token, "action": "no_show"})
    assert r.status_code == 404
    r = client.post("/bookings/BK-3/checkin", data={"csrf": token, "action": "no_show"}, follow_redirects=False)
    assert r.status_code == 303
    assert con.execute("SELECT status FROM bookings WHERE id='BK-3'").fetchone()[0] == "No-show"


def test_host_creates_booking_as_themselves(client, con):
    seed_night(con)
    login(client, "mia")
    token = csrf(client)
    r = client.post("/bookings/new", data={"csrf": token, "night": "2026-11-13", "venue": "Nebula", "ig_handle": "@NewGirl",
                                           "girls": "3", "status": "Confirmed", "host": "Sam", "table_spend": "999"},
                    follow_redirects=False)
    assert r.status_code == 303
    row = con.execute("SELECT host, ig_handle, table_spend FROM bookings WHERE ig_handle='newgirl'").fetchone()
    assert tuple(row) == ("Mia", "newgirl", None)
    assert con.execute("SELECT 1 FROM guests WHERE ig_handle='newgirl'").fetchone()


def test_only_admin_deletes(client, con):
    seed_night(con)
    login(client, "mia")
    token = csrf(client)
    assert client.post("/bookings/BK-1/delete", data={"csrf": token}).status_code == 403
    login(client, "boss")
    token = csrf(client)
    assert client.post("/bookings/BK-1/delete", data={"csrf": token}, follow_redirects=False).status_code == 303
    assert con.execute("SELECT 1 FROM bookings WHERE id='BK-1'").fetchone() is None
    assert con.execute("SELECT 1 FROM audit WHERE action='delete' AND entity_id='BK-1'").fetchone()


def test_social_sees_content_only(client, con):
    seed_night(con)
    login(client, "rae")
    assert client.get("/content").status_code == 200
    for p in ["/leads", "/guests", "/bookings", "/tonight", "/ledger", "/team"]:
        assert client.get(p).status_code == 403, p
    token = csrf(client)
    r = client.post("/content/new", data={"csrf": token, "post_id": "C-1", "date_posted": "2026-11-10",
                                          "platform": "Instagram", "format": "UGC", "views": "1000"}, follow_redirects=False)
    assert r.status_code == 303
    assert "Revenue" not in client.get("/content/C-1").text


def test_scout_sees_only_own_referrals(client, con):
    seed_night(con)
    con.execute("UPDATE bookings SET status='Arrived' WHERE id IN ('BK-3','BK-4')")
    con.commit()
    login(client, "jess")
    html = client.get("/dashboard").text
    assert "cara" in html and "dana" not in html and "alice" not in html
    assert "$20" in html                    # 4 girls x $5 at Nebula
    for p in ["/leads", "/guests", "/bookings", "/tonight", "/venues", "/content", "/ledger"]:
        assert client.get(p).status_code == 403, p


def test_admin_creates_login_and_person_sets_password_from_link(client, con):
    import re
    login(client, "boss")
    token = csrf(client)
    r = client.post("/admin/users", data={"csrf": token, "username": "Kim", "role": "scout", "team_name": "Kim"})
    assert r.status_code == 200 and "Copy message" in r.text
    link = re.search(r"(/invite/[A-Za-z0-9_-]+)", r.text).group(1)
    # no password works before the link is used
    client.cookies.clear()
    assert client.post("/login", data={"username": "kim", "password": "anything-at-all"}).status_code == 401
    page = client.get(link)
    assert page.status_code == 200 and "Welcome, Kim" in page.text and "girls you&#39;ve referred" in page.text
    # mismatched / weak passwords are refused
    assert client.post(link, data={"new_password": "a-good-long-pw", "confirm_password": "different-pw-1"}).status_code == 400
    assert client.post(link, data={"new_password": "short", "confirm_password": "short"}).status_code == 400
    r = client.post(link, data={"new_password": "scout-secret-2026", "confirm_password": "scout-secret-2026"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers.get("set-cookie")
    # logged straight in, lands on her own page, no forced password change
    assert client.get("/dashboard").status_code == 200
    # link is single-use
    client.cookies.clear()
    assert client.get(link).status_code == 410
    login(client, "kim", "scout-secret-2026")


def test_reset_sends_new_link_and_kills_old_password(client, con):
    import re
    login(client, "boss")
    uid = con.execute("SELECT id FROM users WHERE username='mia'").fetchone()[0]
    r = client.post(f"/admin/users/{uid}", data={"csrf": csrf(client), "action": "reset"})
    link = re.search(r"(/invite/[A-Za-z0-9_-]+)", r.text).group(1)
    client.cookies.clear()
    assert client.post("/login", data={"username": "mia", "password": PW}).status_code == 401
    # a second reset replaces the first link
    login(client, "boss")
    r2 = client.post(f"/admin/users/{uid}", data={"csrf": csrf(client), "action": "reset"})
    link2 = re.search(r"(/invite/[A-Za-z0-9_-]+)", r2.text).group(1)
    client.cookies.clear()
    assert client.get(link).status_code == 410 and client.get(link2).status_code == 200


def test_expired_or_bogus_link(client, con):
    from app import auth
    uid = con.execute("SELECT id FROM users WHERE username='sam'").fetchone()[0]
    tok = auth.create_invite(con, uid)
    con.execute("UPDATE invites SET expires_at='2000-01-01T00:00:00+00:00'")
    con.commit()
    assert client.get(f"/invite/{tok}").status_code == 410
    assert client.get("/invite/nope").status_code == 410
    assert client.post(f"/invite/{tok}", data={"new_password": "x" * 12, "confirm_password": "x" * 12}).status_code == 410


def test_venue_rename_cascades(client, con):
    seed_night(con)
    login(client, "boss")
    token = csrf(client)
    vid = con.execute("SELECT id FROM venues WHERE name='Nebula'").fetchone()[0]
    data = {"csrf": token, "name": "Nebula NYC", "pay_model": "Per guest (capped)", "rate_per_guest": "12",
            "cap_per_night": "180", "status": "Active"}
    assert client.post(f"/venues/{vid}", data=data, follow_redirects=False).status_code == 303
    assert con.execute("SELECT COUNT(*) FROM bookings WHERE venue='Nebula NYC'").fetchone()[0] == 2


def test_list_pages_render_on_empty_db(client):
    login(client, "boss")
    for p in ["/leads", "/guests", "/bookings", "/nights", "/venues", "/team", "/content", "/ledger",
              "/leads/new", "/bookings/new", "/ledger/new", "/tonight", "/dashboard?week=2026-11-09"]:
        assert client.get(p).status_code == 200, p
