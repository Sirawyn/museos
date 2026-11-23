"""Card Instagrams page: reads the muse-cards app's /instagrams.json live."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from conftest import login

FEED = {"instagrams": [
    {"instagram": "kat.ny", "how": ["friend"], "cards": ["04a1b2c3d4e5f6"], "referred_by": ["lena"],
     "first_seen": "2026-11-22T03:10:00+00:00", "last_seen": "2026-11-22T03:10:00+00:00"},
    {"instagram": "lena", "how": ["owner"], "cards": ["04a1b2c3d4e5f6"], "referred_by": [],
     "first_seen": "2026-11-21T02:00:00+00:00", "last_seen": "2026-11-21T02:00:00+00:00"},
]}


@pytest.fixture
def cards_app(monkeypatch):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/instagrams.json" or self.headers.get("Authorization") != "Bearer secret":
                self.send_response(401); self.end_headers(); return
            body = json.dumps(FEED).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("CARDS_URL", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setenv("CARDS_TOKEN", "secret")
    yield
    srv.shutdown()


def test_admin_sees_card_instagrams(client, con, cards_app):
    con.execute("INSERT INTO guests(ig_handle, name) VALUES ('lena', 'Lena')")
    con.commit()
    login(client, "boss")
    r = client.get("/instagrams")
    assert r.status_code == 200
    assert "@kat.ny" in r.text and "Friend sign-up" in r.text and "@lena" in r.text
    assert 'href="/guests/lena"' in r.text                       # already a guest in Muse OS
    r = client.get("/instagrams?how=friend")
    assert "@kat.ny" in r.text and "https://instagram.com/lena" not in r.text
    r = client.get("/instagrams?new=1")
    assert "@kat.ny" in r.text and "https://instagram.com/lena" not in r.text
    r = client.get("/instagrams?q=lena")                          # finds her and who she referred
    assert "@kat.ny" in r.text and "@lena" in r.text
    csv = client.get("/instagrams.csv").text
    assert csv.splitlines()[0].startswith("instagram,how,referred_by") and "kat.ny,Friend sign-up,@lena" in csv


def test_only_admins(client, cards_app):
    for u in ("mia", "sam", "rae", "jess"):
        login(client, u)
        assert client.get("/instagrams").status_code == 403
        assert client.get("/instagrams.csv").status_code == 403


def test_not_connected_or_wrong_token(client, monkeypatch, cards_app):
    login(client, "boss")
    monkeypatch.setenv("CARDS_TOKEN", "wrong")
    assert "turned down the token" in client.get("/instagrams").text
    monkeypatch.delenv("CARDS_URL")
    r = client.get("/instagrams")
    assert r.status_code == 200 and "Not connected yet" in r.text
    monkeypatch.setenv("CARDS_URL", "http://127.0.0.1:9")
    assert "reach the cards app at CARDS_URL" in client.get("/instagrams").text
