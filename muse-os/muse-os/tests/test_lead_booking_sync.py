"""A Confirmed lead with a night and venue gets its booking; edits carry over; Lost cancels."""
from tests.conftest import csrf, login

LEAD = {"ig_handle": "zoe", "night": "2026-11-20", "venue": "Nebula", "girls": "3", "party_size": "3",
        "channel": "Instagram", "host": "Mia"}


def _save(client, url, **kw):
    return client.post(url, data={"csrf": csrf(client), **LEAD, **kw}, follow_redirects=False)


def test_confirmed_lead_creates_and_updates_booking(client, con):
    login(client, "boss")
    r = _save(client, "/leads/new", status="Qualifying")
    lid = r.headers["location"].split("/")[2].split("?")[0]
    assert con.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0
    _save(client, f"/leads/{lid}", status="Confirmed")
    b = con.execute("SELECT night, venue, ig_handle, girls, host, status, lead_id FROM bookings").fetchall()
    assert [tuple(x) for x in b] == [("2026-11-20", "Nebula", "zoe", 3, "Mia", "Confirmed", lid)]
    assert con.execute("SELECT 1 FROM nights WHERE night='2026-11-20' AND venue='Nebula'").fetchone()
    assert "zoe" in client.get("/bookings").text
    _save(client, f"/leads/{lid}", status="Confirmed", night="2026-11-21", girls="5")
    b = con.execute("SELECT night, girls FROM bookings").fetchone()
    assert tuple(b) == ("2026-11-21", 5)
    assert con.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 1   # no duplicate
    _save(client, f"/leads/{lid}", status="Lost")
    assert con.execute("SELECT status FROM bookings").fetchone()[0] == "Cancelled"


def test_lead_confirmed_before_gets_booking_on_next_save(client, con):
    con.execute("INSERT INTO leads(id, ig_handle, night, venue, status, girls) VALUES ('DM-00050','amy','2026-11-20','NOFLEX','Confirmed',2)")
    con.commit()
    login(client, "boss")
    client.post("/leads/DM-00050", data={"csrf": csrf(client), "ig_handle": "amy", "night": "2026-11-20",
                                         "venue": "NOFLEX", "status": "Confirmed", "girls": "2"})
    assert con.execute("SELECT ig_handle FROM bookings WHERE lead_id='DM-00050'").fetchone()[0] == "amy"


def test_checked_in_booking_is_not_changed(client, con):
    login(client, "boss")
    r = _save(client, "/leads/new", status="Confirmed")
    lid = r.headers["location"].split("/")[2].split("?")[0]
    con.execute("UPDATE bookings SET status='Arrived', girls_arrived=3")
    con.commit()
    _save(client, f"/leads/{lid}", status="Confirmed", night="2026-11-27")
    assert tuple(con.execute("SELECT night, status FROM bookings").fetchone()) == ("2026-11-20", "Arrived")


def test_host_lead_sync_stays_scoped(client, con):
    login(client, "mia")
    r = _save(client, "/leads/new", status="Confirmed")
    assert r.status_code == 303
    assert con.execute("SELECT host FROM bookings").fetchone()[0] == "Mia"
