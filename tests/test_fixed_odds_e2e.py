"""End-to-end HTTP proof of fixed-odds mode: a bet locks its odds at submit, the bettor sees the
frozen payout, and settlement pays stake × locked odds (not the pool split) — with the house's loss
bounded to the cap. Reuses the real-app TestClient harness from test_e2e."""
import pytest
# test_e2e sets the test env vars at import time and then imports api/store — importing from it first
# guarantees that happens before we touch `api`, so the app boots with a test SESSION_SECRET + temp DB.
from test_e2e import admin_client, user_client, fresh_db  # noqa: F401 (fresh_db is an autouse fixture)
import api  # noqa: E402  (must follow test_e2e's env setup above)


@pytest.fixture
def fixed_mode():
    prev = api.FIXED_ODDS_ENABLED
    api.FIXED_ODDS_ENABLED = True
    try:
        yield
    finally:
        api.FIXED_ODDS_ENABLED = prev


def _run_khuseel_2_0(admin):
    # prerace → lap1 → (khuseel) → break1 → lap2 → (khuseel) → finished
    assert admin.post("/api/admin/race/start-lap").status_code == 200
    assert admin.post("/api/admin/race/lap-result", json={"winner": "khuseel"}).status_code == 200
    assert admin.post("/api/admin/race/start-lap").status_code == 200
    assert admin.post("/api/admin/race/lap-result", json={"winner": "khuseel"}).status_code == 200


def test_fixed_bet_locks_odds_and_settles_at_them(fixed_mode):
    admin = admin_client()
    alice = user_client("Alice Fixed")

    # board carries fixed odds for a nominal stake; Bansod short, Khuseel long
    board = {o["id"]: o["fixed_odds"]
             for m in alice.get("/api/state").json()["markets"] if m["id"] == "match"
             for o in m["outcomes"]}
    assert board["bansod"] and board["bansod"] < 1.3
    assert board["khuseel"] and board["khuseel"] > 4.0

    # Alice bets ₹5,000 on Khuseel → locks the board price (uncapped: stake never shortens it)
    assert alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 5000}).status_code == 200
    pend = next(m for m in alice.get("/api/state").json()["markets"] if m["id"] == "match")["my_pending"]
    assert pend["locked_odds"] == 4.5
    assert pend["locked_payout"] == 22500

    # admin approves → the frozen odds ride through to the live bet
    pid = admin.get("/api/admin/pending").json()["pending"][0]["id"]
    assert admin.post(f"/api/admin/bets/{pid}/approve").status_code == 200
    mine = next(m for m in alice.get("/api/state").json()["markets"] if m["id"] == "match")["my_bet"]
    assert mine["locked_odds"] == 4.5 and mine["locked_payout"] == 22500

    # owner sees the (now unbounded) fixed exposure: Khuseel wins → pay 22.5k against a 5k pool
    house = admin.get("/api/state").json()["house"]
    assert house["fixed_exposure"] == -17500

    # run Khuseel 2–0 and settle → Alice is paid EXACTLY her locked 22,500 (not a pool split)
    _run_khuseel_2_0(admin)
    res = admin.post("/api/admin/settle").json()
    alice_row = next(p for p in res["aggregate"] if p["display_name"] == "Alice Fixed")
    assert alice_row["payout"] == 22500
    assert alice_row["net"] == 17500
    assert res["house_take"] == -17500  # house covered the locked payout out of its own pocket


def test_fixed_off_by_default_is_pure_parimutuel():
    """With the flag off (the default), a bet is a plain pool bet — no locked odds anywhere."""
    assert api.FIXED_ODDS_ENABLED is False
    admin = admin_client()
    bob = user_client("Bob Pool")
    bob.post("/api/bets", json={"market": "match", "outcome": "bansod", "amount": 1000})
    pend = next(m for m in bob.get("/api/state").json()["markets"] if m["id"] == "match")["my_pending"]
    assert pend["locked_odds"] is None and pend["locked_payout"] is None
    board = next(m for m in bob.get("/api/state").json()["markets"] if m["id"] == "match")
    assert all(o["fixed_odds"] is None for o in board["outcomes"])
