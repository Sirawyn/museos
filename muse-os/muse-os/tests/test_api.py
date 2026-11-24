from app import auth


def key(con):
    return {"Authorization": "Bearer " + auth.create_api_key(con, "DM bot")}


def test_api_needs_a_key(client):
    assert client.get("/api/v1/venues").status_code == 401
    assert client.get("/api/v1/venues", headers={"Authorization": "Bearer muse_wrong"}).status_code == 401


def test_revoked_key_rejected(client, con):
    h = key(con)
    con.execute("UPDATE api_keys SET revoked=1")
    con.commit()
    assert client.get("/api/v1/venues", headers=h).status_code == 401


def test_lead_upsert_and_guest(client, con):
    h = key(con)
    body = {"created_at": "2026-11-13 21:00", "channel": "Instagram", "ig_handle": "@Alice", "name": "Alice",
            "night": "2026-11-13", "venue": "Nebula", "party_size": 4, "girls": 4, "guys": 0, "status": "Qualifying",
            "host": "Mia", "first_reply_at": "2026-11-13 21:00", "referred_by": "Jess"}
    r = client.put("/api/v1/leads/DM-00001", json=body, headers=h)
    assert r.status_code == 200 and r.json()["result"] == "created"
    r = client.put("/api/v1/leads/DM-00001", json={"status": "Confirmed"}, headers=h)
    assert r.json()["result"] == "updated"
    row = con.execute("SELECT status, ig_handle, referred_by FROM leads WHERE id='DM-00001'").fetchone()
    assert tuple(row) == ("Confirmed", "alice", "Jess")
    assert con.execute("SELECT 1 FROM guests WHERE ig_handle='alice'").fetchone()


def test_guest_insert_only(client, con):
    h = key(con)
    con.execute("INSERT INTO guests(ig_handle, tags, notes) VALUES ('alice', 'UGC creator', 'loves Nebula')")
    con.commit()
    r = client.put("/api/v1/guests/alice", json={"name": "A", "notes": "Added by DM bot"}, headers=h)
    assert r.json()["result"] == "exists"
    assert con.execute("SELECT notes FROM guests WHERE ig_handle='alice'").fetchone()[0] == "loves Nebula"


def test_booking_never_overwrites_host_checkin(client, con):
    h = key(con)
    b = {"night": "2026-11-13", "venue": "Nebula", "ig_handle": "alice", "lead_id": "DM-00001", "host": "Mia",
         "stop": 1, "party_size": 4, "girls": 4, "guys": 0, "status": "Confirmed", "confirmation_sent": True}
    assert client.put("/api/v1/bookings/BK-DM-00001", json=b, headers=h).json()["result"] == "created"
    assert con.execute("SELECT 1 FROM nights WHERE night='2026-11-13' AND venue='Nebula'").fetchone()
    con.execute("UPDATE bookings SET status='Arrived', girls_arrived=3, checked_in_by='mia', "
                "checkin_changed_at='2026-11-13 23:40:00'")
    con.commit()
    client.put("/api/v1/bookings/BK-DM-00001", json={**b, "thank_you_sent": True}, headers=h)
    row = con.execute("SELECT status, girls_arrived, thank_you_sent FROM bookings").fetchone()
    assert tuple(row) == ("Arrived", 3, 1)
    r = client.get("/api/v1/checkins?since=2026-11-13 00:00", headers=h).json()
    assert r["bookings"][0]["lead_id"] == "DM-00001" and r["bookings"][0]["girls_arrived"] == 3


def test_bad_input_rejected(client, con):
    h = key(con)
    assert client.put("/api/v1/leads/DM-1", json={"status": "Bogus"}, headers=h).status_code == 422
    assert client.put("/api/v1/leads/DM-1", json={"unknown_field": 1}, headers=h).status_code == 422
    assert client.put("/api/v1/leads/bad id!", json={}, headers=h).status_code in (400, 404)


def test_venues_and_scouts(client, con):
    h = key(con)
    con.execute("UPDATE venues SET confirmation_message='Ask for [HOST]', ticket_link='https://t.example/x' WHERE name='Nebula'")
    con.commit()
    v = {x["name"]: x for x in client.get("/api/v1/venues", headers=h).json()["venues"]}
    assert v["Nebula"]["nights"] == ["friday", "saturday"]
    assert v["Nebula"]["confirmation_message"] == "Ask for [HOST]"
    assert v["Nebula"]["ticket_link"] == "https://t.example/x"
    assert "rate_per_guest" not in v["Nebula"] and "flat_rate" not in v["Public Hotel"]
    scouts = client.get("/api/v1/scouts", headers=h).json()["scouts"]
    assert {s["name"] for s in scouts} == {"Jess", "Kim"}


def test_booking_host_is_the_host_on_duty(client, con):
    h = key(con)
    con.execute("INSERT INTO nights(night, venue, host) VALUES ('2026-11-14','Nebula','Mia')")
    con.commit()
    b = {"night": "2026-11-14", "venue": "Nebula", "ig_handle": "zoe", "host": "Devin", "girls": 3}
    client.put("/api/v1/bookings/BK-DM-00009", json=b, headers=h)
    assert con.execute("SELECT host FROM bookings WHERE id='BK-DM-00009'").fetchone()[0] == "Mia"
    con.execute("UPDATE bookings SET host='Sam' WHERE id='BK-DM-00009'")   # admin reassigns in the app
    con.commit()
    client.put("/api/v1/bookings/BK-DM-00009", json={**b, "status": "Confirmed"}, headers=h)
    assert con.execute("SELECT host FROM bookings WHERE id='BK-DM-00009'").fetchone()[0] == "Sam"
    v = {x["name"]: x for x in client.get("/api/v1/venues", headers=h).json()["venues"]}
    assert {"night": "2026-11-14", "host": "Mia", "dress_code": None, "cover": None, "ticket_link": None, "list_closes": None, "guys_policy": None} in v["Nebula"]["upcoming"]
