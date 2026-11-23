import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "integrations"))
from museos import MuseOSSync  # noqa: E402

from app import auth  # noqa: E402

VENUES = {"nebula": {"name": "Nebula", "host": "Mia"}}


def test_bot_client_end_to_end(client, con):
    key = auth.create_api_key(con, "DM bot")
    con.execute("UPDATE venues SET confirmation_message='See [HOST] at the door' WHERE name='Nebula'")
    con.commit()
    sync = MuseOSSync("", key, session=client)
    lead = {"id": 7, "status": "confirmed", "venue": "nebula", "party_size": 4, "guys": 0, "night": "2026-11-13",
            "first_msg_at": "2026-11-13T21:00:00-05:00", "first_reply_at": "2026-11-13T21:00:05-05:00",
            "referred_by": "Jess"}
    convo = {"username": "Amy.B", "name": "Amy", "last_user_msg_at": "2026-11-13T21:02:00-05:00"}
    sync.sync_lead(lead, convo, VENUES)
    b = con.execute("SELECT * FROM bookings WHERE id='BK-DM-00007'").fetchone()
    assert b["ig_handle"] == "amy.b" and b["girls"] == 4 and b["host"] == "Mia" and b["status"] == "Confirmed"
    assert con.execute("SELECT referred_by FROM leads WHERE id='DM-00007'").fetchone()[0] == "Jess"
    assert sync.venue_nights()["nebula"] == ["friday", "saturday"]
    assert sync.venue_confirmations() == {"nebula": "See [HOST] at the door"}
    assert {s["name"] for s in sync.scouts()} == {"Jess", "Kim"}
    assert sync.checkins() == []

    # host checks them in at the door in the app
    from tests.conftest import csrf, login
    login(client, "mia")
    client.post("/bookings/BK-DM-00007/checkin", data={"csrf": csrf(client), "action": "arrived", "count": "3"})
    got = sync.checkins()
    assert got[0]["lead_id"] == "DM-00007" and got[0]["status"] == "Arrived" and got[0]["girls_arrived"] == 3
    # the bot's next sync (still thinks 'confirmed') doesn't undo the check-in
    sync.sync_lead({**lead, "notes": "x"}, convo, VENUES)
    assert con.execute("SELECT status, girls_arrived FROM bookings WHERE id='BK-DM-00007'").fetchone()[:] == ("Arrived", 3)
    assert con.execute("SELECT status FROM leads WHERE id='DM-00007'").fetchone()[0] == "Arrived"
