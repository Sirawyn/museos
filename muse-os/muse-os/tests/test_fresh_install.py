from datetime import date

from app import calc, db


def test_fresh_install_starts_with_muse_venues(tmp_path):
    con = db.connect(str(tmp_path / "new.db"))
    db.init(con)
    db.init(con)   # restarting doesn't duplicate anything
    w = calc.World.load(con, date(2026, 11, 20))
    assert len(w.venues) == 4
    assert calc.door_pay(w.venue("Nebula"), 20) == 180
    assert calc.door_pay(w.venue("NOFLEX"), 20) == 200
    assert calc.door_pay(w.venue("Public Hotel"), 2) == 150
    assert calc.door_pay(w.venue("Den Social"), 2) == 100
    assert "[HOST]" in w.venue("Nebula")["confirmation_message"]
