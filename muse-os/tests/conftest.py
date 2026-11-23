import os
import re

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("MUSE_INSECURE_COOKIES", "1")

from app import auth, db  # noqa: E402

PW = "correct-horse-battery"


@pytest.fixture
def con(tmp_path, monkeypatch):
    path = str(tmp_path / "muse.db")
    monkeypatch.setenv("MUSE_DB", path)
    c = db.connect(path)
    db.init(c)
    c.execute("DELETE FROM venues")   # tests use their own venues
    seed(c)
    yield c
    c.close()


def seed(c):
    venues = [
        ("Public Hotel", "Thursday", "Flat per night", None, None, 150, 20, "Men welcome", "22:30"),
        ("Den Social", "", "Flat per night", None, None, 100, None, "Men welcome", None),
        ("Nebula", "Friday, Saturday", "Per guest (capped)", 12, 180, None, 40, "Girls only", "23:00"),
        ("NOFLEX", "Thursday, Friday", "Per guest (uncapped)", 10, None, None, None, "Girls only", None),
    ]
    for v in venues:
        c.execute("INSERT INTO venues(name, nights, pay_model, rate_per_guest, cap_per_night, flat_rate, weekly_quota,"
                  " men_policy, arrive_by, status, commission_pct) VALUES (?,?,?,?,?,?,?,?,?,'Active',10)", v)
    team = [("Boss", "Administrator", None, None), ("Mia", "Host", "Per guest", 10), ("Sam", "Promoter", "Per guest", 8),
            ("Rae", "Social Media", "Monthly flat", 500), ("Jess", "Scout", "Per girl referred", 5),
            ("Kim", "Scout", "Per girl referred", 5)]
    for t in team:
        c.execute("INSERT INTO team(name, role, pay_type, pay_rate, status, start_date) VALUES (?,?,?,?,'Active','2026-10-01')", t)
    for u, role, team_name in [("boss", "admin", None), ("mia", "host", "Mia"), ("sam", "promoter", "Sam"),
                               ("rae", "social", "Rae"), ("jess", "scout", "Jess")]:
        c.execute("INSERT INTO users(username, password_hash, role, team_name, must_change_password) VALUES (?,?,?,?,0)",
                  (u, auth.hash_password(PW), role, team_name))
    c.commit()


@pytest.fixture
def client(con):
    from app.main import create_app
    auth.throttle.hits.clear()
    return TestClient(create_app())


def login(client, username, pw=PW):
    client.cookies.clear()
    r = client.post("/login", data={"username": username, "password": pw, "next": "/"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return client


def csrf(client, path="/more"):
    html = client.get(path).text
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)
