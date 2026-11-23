"""Weekly setup page: one form for the lineup (venue nights + host on duty) and the guys' ticket links."""
from datetime import timedelta

from app import auth
from app.web import local_now
from tests.conftest import csrf, login


def ids(con):
    return {r[1]: r[0] for r in con.execute("SELECT id, name FROM venues")}


def test_setup_admin_only(client):
    login(client, "mia")
    assert client.get("/setup").status_code == 403
    login(client, "boss")
    r = client.get("/setup")
    assert r.status_code == 200 and "Weekly setup" in r.text


def test_setup_suggests_usual_nights(client, con):
    start = local_now(con).date() + timedelta(days=14)
    start -= timedelta(days=start.weekday())          # a Monday with nothing set yet
    friday = (start + timedelta(days=4)).isoformat()
    con.execute("INSERT INTO nights(night, venue, host) VALUES (?, 'Nebula', 'Mia')",
                ((start + timedelta(days=-3)).isoformat(),))   # last week's Friday host
    con.commit()
    login(client, "boss")
    html = client.get(f"/setup?start={start.isoformat()}").text
    v = ids(con)
    assert f'name="n_{friday}_{v["Nebula"]}" value="1" checked' in html      # Nebula runs Fridays
    assert f'name="n_{friday}_{v["Den Social"]}" value="1" >' in html        # Den Social has no usual nights


def test_setup_saves_lineup_and_links_and_bot_sees_them(client, con):
    start = local_now(con).date() + timedelta(days=7)
    d0, d1 = start.isoformat(), (start + timedelta(days=1)).isoformat()
    v = ids(con)
    # an existing night with a booking can't be dropped by unticking it
    con.execute("INSERT INTO nights(night, venue, host) VALUES (?, 'NOFLEX', 'Sam')", (d1,))
    con.execute("INSERT INTO bookings(id, night, venue, ig_handle, status) VALUES ('BK-9', ?, 'NOFLEX', 'x', 'Confirmed')", (d1,))
    con.execute("INSERT INTO nights(night, venue, host) VALUES (?, 'Den Social', 'Sam')", (d1,))
    con.commit()
    login(client, "boss")
    tok = csrf(client, f"/setup?start={d0}")
    data = {"csrf": tok, "start": d0,
            f"n_{d0}_{v['Nebula']}": "1", f"h_{d0}_{v['Nebula']}": "Mia",
            f"n_{d0}_{v['Public Hotel']}": "1", f"h_{d0}_{v['Public Hotel']}": "",
            f"link_{v['Nebula']}": "https://tix.example/nebula-wk",
            f"link_{v['NOFLEX']}": ""}
    r = client.post("/setup", data=data, follow_redirects=False)
    assert r.status_code == 303 and "saved=1" in r.headers["location"] and "kept=" in r.headers["location"]
    nights = {(n, ve): h for n, ve, h in con.execute("SELECT night, venue, host FROM nights")}
    assert nights[(d0, "Nebula")] == "Mia"
    assert nights[(d0, "Public Hotel")] is None
    assert (d1, "NOFLEX") in nights                # kept: has a booking
    assert (d1, "Den Social") not in nights        # unticked, no bookings: removed
    row = con.execute("SELECT ticket_link, ticket_link_updated_at FROM venues WHERE name='Nebula'").fetchone()
    assert row[0] == "https://tix.example/nebula-wk" and row[1]

    # the DM bot sees the same lineup and link, in the same API shape as before
    key = auth.create_api_key(con, "DM bot")
    con.commit()
    out = client.get("/api/v1/venues", headers={"Authorization": "Bearer " + key}).json()["venues"]
    neb = next(x for x in out if x["name"] == "Nebula")
    assert neb["ticket_link"] == "https://tix.example/nebula-wk"
    assert {"night": d0, "host": "Mia", "dress_code": None, "cover": None, "ticket_link": None, "list_closes": None, "guys_policy": None} in neb["upcoming"]


def test_setup_rejects_bad_link_without_saving(client, con):
    start = local_now(con).date() + timedelta(days=7)
    v = ids(con)
    login(client, "boss")
    tok = csrf(client, "/setup")
    r = client.post("/setup", data={"csrf": tok, "start": start.isoformat(),
                                    f"n_{start.isoformat()}_{v['Nebula']}": "1",
                                    f"link_{v['Nebula']}": "tix.example/nope"}, follow_redirects=False)
    assert "error=" in r.headers["location"]
    assert not con.execute("SELECT 1 FROM nights WHERE night=?", (start.isoformat(),)).fetchone()


def test_setup_needs_csrf(client):
    login(client, "boss")
    assert client.post("/setup", data={"start": "2026-12-01"}).status_code == 403


def test_setup_dress_code_per_night(client, con):
    start = local_now(con).date() + timedelta(days=7)
    d0, d1 = start.isoformat(), (start + timedelta(days=1)).isoformat()
    v = ids(con)
    con.execute("UPDATE venues SET dress_code='Heels, no sneakers' WHERE name='Nebula'")
    con.commit()
    login(client, "boss")
    tok = csrf(client, f"/setup?start={d0}")
    r = client.post("/setup", data={"csrf": tok, "start": d0,
                                    f"n_{d0}_{v['Nebula']}": "1", f"h_{d0}_{v['Nebula']}": "Mia",
                                    f"dc_{d0}_{v['Nebula']}": "All black",
                                    f"n_{d1}_{v['Nebula']}": "1", f"dc_{d1}_{v['Nebula']}": ""},
                    follow_redirects=False)
    assert r.status_code == 303
    got = dict(con.execute("SELECT night, dress_code FROM nights WHERE venue='Nebula'").fetchall())
    assert got == {d0: "All black", d1: None}
    # form shows it back, with the venue's usual code as the placeholder
    html = client.get(f"/setup?start={d0}").text
    assert 'value="All black"' in html and 'placeholder="Dress code: Heels, no sneakers"' in html
    # the bot gets that night's code, or the venue's usual one when the night has none
    key = auth.create_api_key(con, "DM bot")
    con.commit()
    neb = next(x for x in client.get("/api/v1/venues", headers={"Authorization": "Bearer " + key}).json()["venues"]
               if x["name"] == "Nebula")
    assert {"night": d0, "host": "Mia", "dress_code": "All black", "cover": None, "ticket_link": None, "list_closes": None, "guys_policy": None} in neb["upcoming"]
    assert {"night": d1, "host": None, "dress_code": "Heels, no sneakers", "cover": None, "ticket_link": None, "list_closes": None, "guys_policy": None} in neb["upcoming"]
    # and it's on the Tonight venue card for that night
    assert "All black" in client.get(f"/tonight?night={d0}").text
    # changing only the dress code updates the night
    tok = csrf(client, f"/setup?start={d0}")
    client.post("/setup", data={"csrf": tok, "start": d0, f"n_{d0}_{v['Nebula']}": "1", f"h_{d0}_{v['Nebula']}": "Mia",
                                f"dc_{d0}_{v['Nebula']}": "Dresses only", f"n_{d1}_{v['Nebula']}": "1"})
    assert con.execute("SELECT dress_code FROM nights WHERE venue='Nebula' AND night=?", (d0,)).fetchone()[0] == "Dresses only"


def test_setup_guys_cover_per_night(client, con):
    start = local_now(con).date() + timedelta(days=21)
    start -= timedelta(days=start.weekday())
    fri = (start + timedelta(days=4)).isoformat()
    v = ids(con)
    login(client, "boss")
    tok = csrf(client, f"/setup?start={start.isoformat()}")
    client.post("/setup", data={"csrf": tok, "start": start.isoformat(),
                                f"n_{fri}_{v['Nebula']}": "1", f"cv_{fri}_{v['Nebula']}": "$30 before 12"})
    assert con.execute("SELECT cover FROM nights WHERE night=? AND venue='Nebula'", (fri,)).fetchone()[0] == "$30 before 12"
    key = auth.create_api_key(con, "DM bot")
    con.commit()
    neb = next(x for x in client.get("/api/v1/venues", headers={"Authorization": "Bearer " + key}).json()["venues"]
               if x["name"] == "Nebula")
    assert next(u for u in neb["upcoming"] if u["night"] == fri)["cover"] == "$30 before 12"
    assert "Guys' cover $30 before 12" in client.get(f"/tonight?night={fri}").text
    # next week's form starts from last week's cover
    nxt = (start + timedelta(days=7)).isoformat()
    assert 'value="$30 before 12"' in client.get(f"/setup?start={nxt}").text


def test_setup_ticket_link_per_night(client, con):
    start = local_now(con).date() + timedelta(days=28)
    start -= timedelta(days=start.weekday())
    fri, sat = (start + timedelta(days=4)).isoformat(), (start + timedelta(days=5)).isoformat()
    v = ids(con)
    login(client, "boss")
    tok = csrf(client, f"/setup?start={start.isoformat()}")
    base = {"csrf": tok, "start": start.isoformat(), f"n_{fri}_{v['Nebula']}": "1", f"n_{sat}_{v['Nebula']}": "1",
            f"link_{v['Nebula']}": "https://tix.example/nebula-week"}
    r = client.post("/setup", data={**base, f"tl_{fri}_{v['Nebula']}": "https://tix.example/nebula-fri",
                                    f"tl_{sat}_{v['Nebula']}": "https://tix.example/nebula-sat"}, follow_redirects=False)
    assert "saved=1" in r.headers["location"]
    key = auth.create_api_key(con, "DM bot")
    con.commit()
    neb = next(x for x in client.get("/api/v1/venues", headers={"Authorization": "Bearer " + key}).json()["venues"]
               if x["name"] == "Nebula")
    up = {u["night"]: u for u in neb["upcoming"]}
    assert up[fri]["ticket_link"] == "https://tix.example/nebula-fri"
    assert up[sat]["ticket_link"] == "https://tix.example/nebula-sat"
    assert neb["ticket_link"] == "https://tix.example/nebula-week"     # venue-level link still there as the fallback
    # clearing a night's link falls back to the venue's (null per night)
    tok = csrf(client, f"/setup?start={start.isoformat()}")
    client.post("/setup", data={**base, "csrf": tok, f"tl_{fri}_{v['Nebula']}": "https://tix.example/nebula-fri"})
    assert con.execute("SELECT ticket_link FROM nights WHERE night=? AND venue='Nebula'", (sat,)).fetchone()[0] is None
    # a bad per-night link saves nothing
    tok = csrf(client, f"/setup?start={start.isoformat()}")
    r = client.post("/setup", data={**base, "csrf": tok, f"tl_{fri}_{v['Nebula']}": "nebula-fri"}, follow_redirects=False)
    assert "error=" in r.headers["location"]
    assert con.execute("SELECT ticket_link FROM nights WHERE night=? AND venue='Nebula'", (fri,)).fetchone()[0] == "https://tix.example/nebula-fri"


def test_venue_guys_policy(client, con):
    login(client, "boss")
    nid = ids(con)["Nebula"]
    form = client.get(f"/venues/{nid}").text
    assert "Guys&#39; entry" in form or "Guys' entry" in form
    key = auth.create_api_key(con, "DM bot")
    con.commit()
    h = {"Authorization": "Bearer " + key}
    assert next(x for x in client.get("/api/v1/venues", headers=h).json()["venues"] if x["name"] == "Nebula")["guys_policy"] is None
    for label, code in [("Ticket", "ticket"), ("Cover at the door", "cover"), ("Free", "free"), ("Ask the team", "ask")]:
        con.execute("UPDATE venues SET guys_policy=? WHERE id=?", (label, nid))
        con.commit()
        assert next(x for x in client.get("/api/v1/venues", headers=h).json()["venues"] if x["name"] == "Nebula")["guys_policy"] == code


def test_guestlist_closing_time(client, con):
    start = local_now(con).date() + timedelta(days=35)
    start -= timedelta(days=start.weekday())
    fri, sat = (start + timedelta(days=4)).isoformat(), (start + timedelta(days=5)).isoformat()
    v = ids(con)
    con.execute("UPDATE venues SET list_closes='01:30' WHERE name='Nebula'")
    con.execute("UPDATE venues SET list_closes='20:00' WHERE name='Public Hotel'")
    con.commit()
    login(client, "boss")
    html = client.get(f"/setup?start={start.isoformat()}").text
    assert "usual 1:30 AM" in html
    tok = csrf(client, f"/setup?start={start.isoformat()}")
    base = {"csrf": tok, "start": start.isoformat(), f"n_{fri}_{v['Nebula']}": "1", f"n_{sat}_{v['Nebula']}": "1"}
    client.post("/setup", data={**base, f"lc_{sat}_{v['Nebula']}": "0:45"})
    key = auth.create_api_key(con, "DM bot")
    con.commit()
    out = {x["name"]: x for x in client.get("/api/v1/venues", headers={"Authorization": "Bearer " + key}).json()["venues"]}
    assert out["Nebula"]["list_closes"] == "01:30" and out["Public Hotel"]["list_closes"] == "20:00"
    assert out["Den Social"]["list_closes"] is None
    up = {u["night"]: u for u in out["Nebula"]["upcoming"]}
    assert up[fri]["list_closes"] is None and up[sat]["list_closes"] == "00:45"
    # hosts see it on Tonight: the night's override, else the venue's
    assert "List closes 1:30 AM" in client.get(f"/tonight?night={fri}").text
    assert "List closes 12:45 AM" in client.get(f"/tonight?night={sat}").text
    # a bad time saves nothing
    tok = csrf(client, f"/setup?start={start.isoformat()}")
    r = client.post("/setup", data={**base, "csrf": tok, f"lc_{fri}_{v['Nebula']}": "late"}, follow_redirects=False)
    assert "error=" in r.headers["location"]


def test_guys_free_one_night(client, con):
    start = local_now(con).date() + timedelta(days=42)
    start -= timedelta(days=start.weekday())
    fri, sat = (start + timedelta(days=4)).isoformat(), (start + timedelta(days=5)).isoformat()
    v = ids(con)
    con.execute("UPDATE venues SET guys_policy='Ticket' WHERE name='Nebula'")
    con.commit()
    login(client, "boss")
    assert "Guys: ticket (usual)" in client.get(f"/setup?start={start.isoformat()}").text
    tok = csrf(client, f"/setup?start={start.isoformat()}")
    client.post("/setup", data={"csrf": tok, "start": start.isoformat(), f"n_{fri}_{v['Nebula']}": "1",
                                f"gp_{fri}_{v['Nebula']}": "Free", f"n_{sat}_{v['Nebula']}": "1",
                                f"gp_{sat}_{v['Nebula']}": "bogus"})
    key = auth.create_api_key(con, "DM bot")
    con.commit()
    neb = next(x for x in client.get("/api/v1/venues", headers={"Authorization": "Bearer " + key}).json()["venues"]
               if x["name"] == "Nebula")
    up = {u["night"]: u for u in neb["upcoming"]}
    assert neb["guys_policy"] == "ticket" and up[fri]["guys_policy"] == "free" and up[sat]["guys_policy"] is None
    assert "Guys free" in client.get(f"/tonight?night={fri}").text


def test_engineer_gets_50_a_month(client, con):
    login(client, "boss")
    r = client.post("/team/new", data={"csrf": csrf(client), "name": "Alex", "role": "Engineer", "status": "Active"},
                    follow_redirects=False)
    assert r.status_code == 303
    row = con.execute("SELECT pay_type, pay_rate, start_date FROM team WHERE name='Alex'").fetchone()
    assert row[0] == "Monthly flat" and row[1] == 50 and row[2]
    from app import calc
    w = calc.World.load(con, local_now(con).date())
    assert w.team_row(w.team["alex"])["earned"] == 50


def test_hide_columns_saved_per_person(client, con):
    login(client, "boss")
    html = client.get("/leads").text
    assert ">Channel</th>" in html
    r = client.post("/prefs/columns/leads", data={"csrf": csrf(client, "/leads"), "col": ["status", "venue", "notes"],
                                                  "back": "/leads"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/leads"
    html = client.get("/leads").text
    assert ">Channel</th>" not in html and ">Status</th>" in html and ">Notes</th>" in html   # notes isn't shown by default
    # the first column always stays, and it's only this person's view
    assert html.count("<th") >= 4
    login(client, "mia")
    assert ">Channel</th>" in client.get("/leads").text
    # follows the person to a new session (another device)
    login(client, "boss")
    assert ">Channel</th>" not in client.get("/leads").text
    client.post("/prefs/columns/leads", data={"csrf": csrf(client, "/leads"), "reset": "1"})
    assert ">Channel</th>" in client.get("/leads").text
    # can't use it to reveal money columns to staff
    login(client, "mia")
    client.post("/prefs/columns/bookings", data={"csrf": csrf(client, "/bookings"), "col": ["table_spend", "revenue"]})
    assert "Table" not in client.get("/bookings").text.split("<tbody>")[0].split("<thead>")[-1]


def test_hide_days_on_weekly_setup_leaves_them_untouched(client, con):
    start = local_now(con).date() + timedelta(days=49)
    start -= timedelta(days=start.weekday())
    mon, fri = start.isoformat(), (start + timedelta(days=4)).isoformat()
    v = ids(con)
    con.execute("INSERT INTO nights(night, venue, host) VALUES (?, 'Den Social', 'Sam')", (mon,))
    con.commit()
    login(client, "boss")
    client.post("/prefs/days", data={"csrf": csrf(client), "day": ["3", "4", "5"], "back": "/setup"})   # Thu-Sat only
    html = client.get(f"/setup?start={mon}").text
    assert f"n_{mon}_" not in html and f"n_{fri}_" in html and "Hiding Mon, Tue, Wed, Sun" in html
    tok = csrf(client, f"/setup?start={mon}")
    client.post("/setup", data={"csrf": tok, "start": mon, f"n_{fri}_{v['Nebula']}": "1"})
    # Monday's night wasn't on the form, so saving didn't remove it
    assert con.execute("SELECT 1 FROM nights WHERE night=? AND venue='Den Social'", (mon,)).fetchone()
    assert con.execute("SELECT 1 FROM nights WHERE night=? AND venue='Nebula'", (fri,)).fetchone()
    # showing every day again
    client.post("/prefs/days", data={"csrf": csrf(client), "day": [str(i) for i in range(7)]})
    assert f"n_{mon}_" in client.get(f"/setup?start={mon}").text


def test_noflex_cover_price_weekly(client, con):
    """NOFLEX is cover only: Sunday setup asks for the cover price (no ticket link) and the bot reads it."""
    from app import db
    con.execute("UPDATE venues SET guys_policy='Ticket', ticket_link='https://tix.example/old' WHERE name='NOFLEX'")
    con.execute("DELETE FROM settings WHERE key='migrated_noflex_cover'")
    db.init(con)                                      # one-off migration: NOFLEX switches to cover at the door
    assert con.execute("SELECT guys_policy FROM venues WHERE name='NOFLEX'").fetchone()[0] == "Cover at the door"
    con.execute("UPDATE venues SET guys_policy='Ticket' WHERE name='NOFLEX'")
    db.init(con)                                      # runs once: a later change on the Venues page sticks
    assert con.execute("SELECT guys_policy FROM venues WHERE name='NOFLEX'").fetchone()[0] == "Ticket"
    con.execute("UPDATE venues SET guys_policy='Cover at the door' WHERE name='NOFLEX'")
    con.commit()
    start = local_now(con).date() + timedelta(days=35)
    start -= timedelta(days=start.weekday())
    thu = (start + timedelta(days=3)).isoformat()
    v = ids(con)
    login(client, "boss")
    html = client.get(f"/setup?start={start.isoformat()}").text
    assert f'aria-label="Cover at the door for NOFLEX' in html and "Cover this night" in html
    assert f'type="hidden" name="tl_{thu}_{v["NOFLEX"]}"' in html             # no ticket link box for NOFLEX
    assert f'type="url" name="tl_{thu}_{v["Nebula"]}"' in html                # ticket venues keep theirs
    tok = csrf(client, f"/setup?start={start.isoformat()}")
    client.post("/setup", data={"csrf": tok, "start": start.isoformat(), f"n_{thu}_{v['NOFLEX']}": "1",
                                f"cv_{thu}_{v['NOFLEX']}": "$20", f"link_{v['NOFLEX']}": "https://tix.example/old"})
    assert con.execute("SELECT cover FROM nights WHERE night=? AND venue='NOFLEX'", (thu,)).fetchone()[0] == "$20"
    key = auth.create_api_key(con, "DM bot")
    con.commit()
    nf = next(x for x in client.get("/api/v1/venues", headers={"Authorization": "Bearer " + key}).json()["venues"]
              if x["name"] == "NOFLEX")
    assert nf["guys_policy"] == "cover"
    assert next(u for u in nf["upcoming"] if u["night"] == thu)["cover"] == "$20"


def test_fresh_install_noflex_is_cover(tmp_path):
    from app import db
    c = db.connect(str(tmp_path / "fresh.db"))
    db.init(c)
    assert c.execute("SELECT guys_policy FROM venues WHERE name='NOFLEX'").fetchone()[0] == "Cover at the door"
    c.close()
