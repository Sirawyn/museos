from datetime import date

from app import calc


def add_booking(con, bid, night, venue, girls, status="Arrived", arrived=None, host="Mia", spend=None, scout=None,
                lead=None, handle=None):
    con.execute("INSERT INTO bookings(id, night, venue, ig_handle, host, girls, status, girls_arrived, table_spend, "
                "referred_by, lead_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (bid, night, venue, handle or bid.lower(), host, girls, status, arrived, spend, scout, lead))


def w(con):
    return calc.World.load(con, date(2026, 11, 20))


def night(con, n, v):
    return w(con).night_row(n, v)


def test_nebula_is_capped_at_15_girls(con):
    add_booking(con, "B1", "2026-11-13", "Nebula", 12)
    add_booking(con, "B2", "2026-11-13", "Nebula", 8)
    assert night(con, "2026-11-13", "Nebula")["door_pay"] == 180       # 20 girls x $12 = 240, capped at 180
    add_booking(con, "B3", "2026-11-14", "Nebula", 10)
    assert night(con, "2026-11-14", "Nebula")["door_pay"] == 120       # under the cap


def test_noflex_is_uncapped(con):
    add_booking(con, "B1", "2026-11-13", "NOFLEX", 25)
    assert night(con, "2026-11-13", "NOFLEX")["door_pay"] == 250


def test_flat_rates_and_override(con):
    add_booking(con, "B1", "2026-11-12", "Public Hotel", 3)
    assert night(con, "2026-11-12", "Public Hotel")["door_pay"] == 150
    rows = w(con).all_nights()
    assert any(n["venue"] == "Public Hotel" and n["total"] == 150 for n in rows)  # night counted without a Nights row
    con.execute("INSERT INTO nights(night, venue, flat_override) VALUES ('2026-11-12', 'Public Hotel', 200)")
    assert next(n for n in w(con).all_nights() if n["venue"] == "Public Hotel")["door_pay"] == 200
    add_booking(con, "B2", "2026-11-15", "Den Social", 40)
    assert night(con, "2026-11-15", "Den Social")["door_pay"] == 100


def test_arrived_count_overrides_booked_girls_and_no_shows_count_zero(con):
    add_booking(con, "B1", "2026-11-13", "NOFLEX", 5, arrived=3)
    add_booking(con, "B2", "2026-11-13", "NOFLEX", 4, status="No-show")
    add_booking(con, "B3", "2026-11-13", "NOFLEX", 4, status="Confirmed")
    n = night(con, "2026-11-13", "NOFLEX")
    assert n["girls_arrived"] == 3 and n["door_pay"] == 30 and n["girls_confirmed"] == 13


def test_table_commission(con):
    add_booking(con, "B1", "2026-11-12", "Public Hotel", 4, spend=1000)
    n = night(con, "2026-11-12", "Public Hotel")
    assert n["commission"] == 100 and n["total"] == 250


def test_scouts_paid_only_at_per_girl_venues(con):
    con.execute("INSERT INTO leads(id, ig_handle, referred_by, status) VALUES ('DM-00001', 'a', 'Jess', 'Arrived')")
    add_booking(con, "B1", "2026-11-13", "Nebula", 4, lead="DM-00001", handle="a")    # credited via the lead
    add_booking(con, "B2", "2026-11-13", "NOFLEX", 3, scout="Jess")                  # credited on the booking
    add_booking(con, "B3", "2026-11-12", "Public Hotel", 6, scout="Jess")            # flat rate: no credit
    add_booking(con, "B4", "2026-11-14", "Nebula", 5, status="No-show", scout="Jess")  # didn't show
    world = w(con)
    jess = world.team_row(world.member("Jess"))
    assert jess["referred"] == 7 and jess["earned"] == 35
    assert world.team_row(world.member("Kim"))["earned"] == 0


def test_host_payout_and_balance(con):
    add_booking(con, "B1", "2026-11-13", "Nebula", 6, host="Mia")
    add_booking(con, "B2", "2026-11-13", "Nebula", 4, host="Mia", status="No-show")
    con.execute("INSERT INTO ledger(date, type, person, amount, status) VALUES ('2026-11-14','Host payout','Mia',20,'Paid')")
    world = w(con)
    mia = world.team_row(world.member("Mia"))
    assert mia["earned"] == 60 and mia["paid"] == 20 and mia["balance"] == 40
    assert round(mia["show_rate"], 2) == 0.6


def test_monthly_flat_pay(con):
    world = w(con)   # started 2026-10-01, today 2026-11-20 -> 2 months
    assert world.team_row(world.member("Rae"))["earned"] == 1000


def test_no_show_risk_and_vip_tiers(con):
    for i, st in enumerate(["No-show", "No-show", "Arrived"]):
        add_booking(con, f"F{i}", f"2026-11-0{i+1}", "NOFLEX", 2, status=st, handle="flaky")
    for i in range(5):
        add_booking(con, f"V{i}", f"2026-10-0{i+1}", "NOFLEX", 2, handle="queen")
    stats = w(con).guest_stats()
    assert stats["flaky"]["tier"] == "No-show risk"
    assert stats["queen"]["tier"] == "Muse VIP"


def test_venue_owed(con):
    add_booking(con, "B1", "2026-11-12", "Public Hotel", 3)
    con.execute("INSERT INTO ledger(date, type, venue, amount, status) VALUES ('2026-11-14','Venue payment','Public Hotel',100,'Paid')")
    world = w(con)
    v = world.venue_row(world.venue("Public Hotel"))
    assert v["earned"] == 150 and v["received"] == 100 and v["owed"] == 50


def test_dashboard_week(con):
    add_booking(con, "B1", "2026-11-19", "NOFLEX", 5)
    add_booking(con, "B2", "2026-11-20", "Nebula", 20)
    con.execute("INSERT INTO leads(id, created_at, first_reply_at, status) VALUES ('L1','2026-11-18 22:00','2026-11-18 22:02','Arrived')")
    dsh = w(con).dashboard(date(2026, 11, 16))
    assert dsh["revenue"] == 230 and dsh["girls_arrived"] == 25 and dsh["median_reply"] == 2.0


def test_scouts_paid_only_for_first_time_girls(con):
    # @sofia gets in for the first time on the 13th: Jess earns for 4 girls.
    add_booking(con, "B1", "2026-11-13", "Nebula", 4, scout="Jess", handle="sofia")
    # She comes back the next night, tagged again (by Jess and by Kim): nobody earns.
    add_booking(con, "B2", "2026-11-14", "Nebula", 4, scout="Jess", handle="Sofia")
    add_booking(con, "B3", "2026-11-15", "NOFLEX", 3, scout="Kim", handle="sofia")
    # A no-show doesn't use up her first time: @lena's first real visit still pays.
    add_booking(con, "B4", "2026-11-13", "Nebula", 2, status="No-show", scout="Kim", handle="lena")
    add_booking(con, "B5", "2026-11-14", "Nebula", 2, scout="Kim", handle="lena")
    world = w(con)
    assert world.team_row(world.member("Jess"))["earned"] == 20
    assert world.team_row(world.member("Kim"))["earned"] == 10
    assert world.booking_row(next(b for b in world.bookings if b["id"] == "B2"))["scout"] == ""
    assert {s["name"]: s["girls"] for s in world.dashboard(date(2026, 11, 9))["scouts"]} == {"Jess": 4, "Kim": 2}
