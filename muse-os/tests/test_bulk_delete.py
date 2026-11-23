"""Admins can tick leads, guests and bookings on the list and delete them together."""
from tests.conftest import csrf, login
from tests.test_web import seed_night


def test_bulk_delete_bookings_leads_guests(client, con):
    seed_night(con)
    login(client, "boss")
    html = client.get("/bookings").text
    assert 'name="ids"' in html and "Delete selected" in html
    r = client.post("/bookings/delete-selected", data={"csrf": csrf(client), "ids": ["BK-1", "BK-2", "nope"],
                                                       "back": "/bookings?venue=Nebula"}, follow_redirects=False)
    assert r.headers["location"] == "/bookings?venue=Nebula&deleted=2"
    assert {x[0] for x in con.execute("SELECT id FROM bookings")} == {"BK-3", "BK-4"}
    assert con.execute("SELECT COUNT(*) FROM audit WHERE action='delete (bulk)'").fetchone()[0] == 2
    client.post("/leads/delete-selected", data={"csrf": csrf(client), "ids": ["DM-00001", "DM-00002"]})
    assert con.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 0
    client.post("/guests/delete-selected", data={"csrf": csrf(client), "ids": ["alice"]})
    assert con.execute("SELECT COUNT(*) FROM guests WHERE ig_handle='alice'").fetchone()[0] == 0
    assert "Deleted 1 guest." in client.get("/guests?deleted=1").text


def test_bulk_delete_admin_only_and_csrf(client, con):
    seed_night(con)
    login(client, "mia")
    assert 'name="ids"' not in client.get("/bookings").text
    r = client.post("/bookings/delete-selected", data={"csrf": csrf(client), "ids": ["BK-1"]})
    assert r.status_code == 403
    login(client, "boss")
    r = client.post("/bookings/delete-selected", data={"ids": ["BK-1"]})
    assert r.status_code == 403
    r = client.post("/venues/delete-selected", data={"csrf": csrf(client), "ids": ["1"]})
    assert r.status_code == 403   # only leads, guests and bookings
    assert con.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 4
