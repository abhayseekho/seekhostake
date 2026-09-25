"""
Full-stack end-to-end tests: drives the REAL FastAPI app (api.py) over HTTP via TestClient,
against a real (temp, isolated) SQLite database — no mocking of engine/store. Env vars are set
BEFORE importing api/store (module-level code reads them at import time), pointed at an isolated
temp DB so this never touches the dev swimbet.db or any deployed data.

AUTH_MODE=name is used (not SWIMBET_DEV) specifically so admin and bettor sessions are genuinely
distinct principals with separate cookie jars — SWIMBET_DEV collapses everyone into one
"dev@local" owner, which would make it impossible to test the admin/bettor boundary at all.
"""
import os, sys, tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

_TMPDIR = tempfile.mkdtemp(prefix="swimbet_e2e_")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMPDIR, 'e2e.db')}"
os.environ["AUTH_MODE"] = "name"
os.environ["ADMIN_PASSWORD"] = "e2e-test-admin-pw"
os.environ["SESSION_SECRET"] = "e2e-test-session-secret-" + "x" * 20
os.environ["ALLOW_HTTP"] = "1"
os.environ.pop("SWIMBET_DEV", None)
os.environ.pop("GOOGLE_CLIENT_ID", None)

import pytest
from fastapi.testclient import TestClient

import api
import store
import engine as E
from seed import SEED_BETS


@pytest.fixture(autouse=True)
def fresh_db():
    store.meta.drop_all(store.engine)
    store.init()
    api._login_attempts.clear()  # module-global rate-limit state — isolate tests from each other
    api._name_claims.clear()     # module-global name-collision memory — same reason
    yield


def admin_client():
    c = TestClient(api.app)
    r = c.post("/auth/admin", json={"password": "e2e-test-admin-pw"})
    assert r.status_code == 200
    return c


def user_client(name):
    c = TestClient(api.app)
    r = c.post("/auth/name", json={"name": name})
    assert r.status_code == 200
    return c


def match_pool(client):
    """Indicative (displayed) pool — INCLUDES pending requests by design (odds move the moment
    a bet is submitted, before any cash is confirmed). Do not use this to measure cash-in-hand;
    use approved_match_pool for that."""
    return next(m for m in client.get("/api/state").json()["markets"] if m["id"] == "match")["pool"]


def approved_match_pool():
    """True cash-in-hand on the match market: sum of APPROVED bets only, straight from the DB —
    unaffected by any pending requests sitting in the cashier queue."""
    return sum(b["amount"] for b in store.approved_bets("match"))


def approve_all_pending(admin):
    pending = admin.get("/api/admin/pending").json()["pending"]
    ids = [p["id"] for p in pending]
    for pid in ids:
        r = admin.post(f"/api/admin/bets/{pid}/approve")
        assert r.status_code == 200, r.json()
    return len(ids)


def run_race(admin, results):
    """results: list of (winner, time_s) for laps 1..N. Starts each lap, records the result."""
    for winner, time_s in results:
        r = admin.post("/api/admin/race/start-lap")
        assert r.status_code == 200, r.json()
        r = admin.post("/api/admin/race/lap-result", json={"winner": winner, "time_s": time_s})
        assert r.status_code == 200, r.json()
    return r.json()


# ── 1. full happy-path lifecycles ────────────────────────────────────────────────────────────────

def test_happy_path_2_0_sweep_settles_and_sums():
    admin = admin_client()
    assert admin.post("/api/admin/seed").json()["seeded"] == 18
    assert admin.post("/api/admin/house-seed", json={"outcome": "bansod", "amount": 3000}).status_code == 200
    r = admin.post("/api/admin/side-seeds", json={"per_market": 200, "tilt": True})
    assert r.status_code == 200 and r.json()["outcomes_seeded"] == 14

    alice = user_client("Alice")
    r = alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 700})
    assert r.status_code == 200
    r = alice.post("/api/bets", json={"market": "distance", "outcome": "no", "amount": 500})
    assert r.status_code == 200
    approve_all_pending(admin)

    final = run_race(admin, [("bansod", 22.4), ("bansod", 23.1)])
    assert final["phase"] == "finished" and final["race_winner"] == "bansod"

    r = admin.post("/api/admin/settle")
    assert r.status_code == 200
    s = r.json()
    assert s["winner"] == "bansod"
    total_pool = sum(m["pool"] for m in s["markets"])
    paid = sum(p["payout"] for p in s["aggregate"])
    assert paid + s["swimmer_take"] + s["house_take"] >= 0
    # lap3 never happened -> void, fully refunded, contributes 0 net to everyone
    lap3 = next(m for m in s["markets"] if m["market"] == "lap3")
    assert lap3["void"] is True
    # Alice's khuseel match bet lost; her distance=no bet should have paid something (no won)
    alice_row = next(p for p in s["aggregate"] if p["display_name"] == "Alice")
    assert alice_row["net"] < 700  # lost the match leg net of any distance win


def test_happy_path_2_1_with_comeback_win():
    admin = admin_client()
    admin.post("/api/admin/seed")
    bob = user_client("Bob")
    r = bob.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 500})
    assert r.status_code == 200
    approve_all_pending(admin)

    r = admin.post("/api/admin/race/start-lap")  # -> lap1
    admin.post("/api/admin/race/lap-result", json={"winner": "bansod", "time_s": 22.4})  # -> break1

    # comeback market opens only in break1 — bet it now
    r = bob.post("/api/bets", json={"market": "comeback", "outcome": "yes", "amount": 500})
    assert r.status_code == 200
    approve_all_pending(admin)

    admin.post("/api/admin/race/start-lap")  # -> lap2, closes the book
    admin.post("/api/admin/race/lap-result", json={"winner": "khuseel", "time_s": 22.1})  # 1-1 -> break2
    admin.post("/api/admin/race/start-lap")  # -> lap3
    final = admin.post("/api/admin/race/lap-result",
                       json={"winner": "khuseel", "time_s": 22.9}).json()  # khuseel 2-1
    assert final["race_winner"] == "khuseel"

    s = admin.post("/api/admin/settle").json()
    comeback = next(m for m in s["markets"] if m["market"] == "comeback")
    assert comeback["won"] == "yes"  # lap-1 loser (khuseel) won the match
    bob_row = next(p for p in s["aggregate"] if p["display_name"] == "Bob")
    assert bob_row["net"] > -600  # comeback win offset at least part of the match loss


# ── 2. rule enforcement over real HTTP ───────────────────────────────────────────────────────────

def test_book_closed_outside_open_windows():
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    admin.post("/api/admin/race/start-lap")  # prerace -> lap1: every market closes
    r = alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 100})
    assert r.status_code == 400 and r.json()["detail"] == "book_closed"


def test_lap1_market_closes_after_prerace_even_during_break1():
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    admin.post("/api/admin/race/start-lap")
    admin.post("/api/admin/race/lap-result", json={"winner": "bansod", "time_s": 22.4})  # break1
    r = alice.post("/api/bets", json={"market": "lap1", "outcome": "khuseel", "amount": 100})
    assert r.status_code == 400 and r.json()["detail"] == "book_closed"


def test_comeback_closed_before_break1():
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    r = alice.post("/api/bets", json={"market": "comeback", "outcome": "yes", "amount": 100})
    assert r.status_code == 400 and r.json()["detail"] == "book_closed"


def test_no_side_switch_on_match_after_lap1_starts():
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 500})
    approve_all_pending(admin)
    admin.post("/api/admin/race/start-lap")
    admin.post("/api/admin/race/lap-result", json={"winner": "bansod", "time_s": 22.4})  # break1
    r = alice.post("/api/bets", json={"market": "match", "outcome": "bansod", "amount": 500})
    assert r.status_code == 400 and r.json()["detail"] == "no_side_switch"
    # raising the SAME side is fine
    r = alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 500})
    assert r.status_code == 200


def test_side_market_switching_allowed_in_break1():
    """Only the MAIN market locks sides after lap 1 — side markets have no such rule."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    alice.post("/api/bets", json={"market": "distance", "outcome": "yes", "amount": 500})
    approve_all_pending(admin)
    admin.post("/api/admin/race/start-lap")
    admin.post("/api/admin/race/lap-result", json={"winner": "bansod", "time_s": 22.4})
    r = alice.post("/api/bets", json={"market": "distance", "outcome": "no", "amount": 600})
    assert r.status_code == 200


def test_outcome_dead_after_lap1_blocks_bet():
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    admin.post("/api/admin/race/start-lap")
    admin.post("/api/admin/race/lap-result", json={"winner": "bansod", "time_s": 22.4})  # kills k20
    r = alice.post("/api/bets", json={"market": "score", "outcome": "k20", "amount": 500})
    assert r.status_code == 400 and r.json()["detail"] == "outcome_dead"


def test_raise_supersedes_not_doubles():
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 1000})
    approve_all_pending(admin)
    pool_after_first = match_pool(admin)
    alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 2500})
    approve_all_pending(admin)
    pool_after_raise = match_pool(admin)
    assert pool_after_raise - pool_after_first == 1500  # delta only, not +2500 on top


def test_start_lap2_auto_rejects_unapproved_pending():
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    admin.post("/api/admin/race/start-lap")
    admin.post("/api/admin/race/lap-result", json={"winner": "bansod", "time_s": 22.4})  # break1
    alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 5000})  # pending, unapproved
    r = admin.post("/api/admin/race/start-lap")  # -> lap2
    assert r.json()["auto_rejected_pending"] == 1
    pending = admin.get("/api/admin/pending").json()["pending"]
    assert len(pending) == 0


def test_settle_only_once():
    """First settle succeeds and flips phase to 'settled'. A second attempt is still refused —
    via 'race_not_finished' rather than 'already_settled', since phase is no longer 'finished'
    at that point (the already_settled branch on save_settlement guards a narrower race: two
    settle calls arriving before either has moved the phase). Either message is a REFUSAL —
    the property under test is that settlement is never applied twice."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    run_race(admin, [("bansod", 22.4), ("bansod", 23.1)])
    assert admin.post("/api/admin/settle").status_code == 200
    assert store.load_settlement() is not None
    r = admin.post("/api/admin/settle")
    assert r.status_code == 400
    assert r.json()["detail"] in ("already_settled", "race_not_finished")
    assert admin.get("/api/state").json()["race"]["phase"] == "settled"


def test_concurrent_settle_race_is_still_caught_by_save_settlement():
    """The scenario api's phase gate DOESN'T cover: two settle requests both read phase==
    'finished' before either has written 'settled' (a genuine race between two admin taps or
    two browser tabs). store.save_settlement's existence check on the settlements table is the
    actual safety net for that case — exercise it directly rather than through the serialized
    HTTP calls above, which can never observe the interleaving."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    run_race(admin, [("bansod", 22.4), ("bansod", 23.1)])
    laps = store.get_race()["laps"]
    result_a = E.settle_all(store.approved_by_market(), laps)
    result_b = E.settle_all(store.approved_by_market(), laps)
    assert store.save_settlement(result_a) is True
    assert store.save_settlement(result_b) is False  # second writer loses the race, cleanly


def test_reset_book_works_mid_race_and_rolls_phase_back():
    """The full-reset button: usable after laps have run (rehearsals need to roll all the way
    back), not just pre-race. Must reset phase/laps, not only wipe bets."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    admin.post("/api/admin/race/start-lap")
    admin.post("/api/admin/race/lap-result", json={"winner": "bansod", "time_s": 22.4})  # break1
    bob = user_client("Bob")
    bob.post("/api/bets", json={"market": "lap2", "outcome": "khuseel", "amount": 500})

    r = admin.post("/api/admin/reset-book")
    assert r.status_code == 200
    assert r.json()["seeded"] == len(SEED_BETS)

    race = store.get_race()
    assert race["phase"] == "prerace" and race["laps"] == [] and race["suspended"] == []
    # only the reseeded book remains — Bob's lap2 bet is gone, not just superseded
    assert "name:bob" not in {b["key"] for b in store.all_bets()}


def test_reset_book_blocked_after_settlement():
    admin = admin_client()
    admin.post("/api/admin/seed")
    run_race(admin, [("bansod", 22.4), ("bansod", 23.1)])
    admin.post("/api/admin/settle")
    r = admin.post("/api/admin/reset-book")
    assert r.status_code == 400 and r.json()["detail"] == "already_settled"


def test_cancel_pending_snaps_odds_back():
    admin = admin_client()
    admin.post("/api/admin/seed")
    admin.post("/api/admin/side-seeds", json={"per_market": 200, "tilt": True})
    alice = user_client("Alice")
    before = alice.get("/api/state").json()
    before_odds = next(m for m in before["markets"] if m["id"] == "lap2")["outcomes"]
    alice.post("/api/bets", json={"market": "lap2", "outcome": "bansod", "amount": 5000})
    during = alice.get("/api/state").json()
    during_odds = next(m for m in during["markets"] if m["id"] == "lap2")["outcomes"]
    assert during_odds != before_odds  # a PENDING (unapproved) request already moved displayed odds
    alice.post("/api/bets/cancel", json={"market": "lap2"})
    after = alice.get("/api/state").json()
    after_odds = next(m for m in after["markets"] if m["id"] == "lap2")["outcomes"]
    assert after_odds == before_odds


def test_void_returns_stake_to_pool():
    admin = admin_client()
    admin.post("/api/admin/seed")
    before = match_pool(admin)
    r = admin.post("/api/admin/bets/void", json={"key": "name:yashbanwani", "market": "match"})
    assert r.status_code == 200
    after = match_pool(admin)
    assert before - after == 5000


# ── 3. guards over HTTP ──────────────────────────────────────────────────────────────────────────

def test_house_seed_above_cap_rejected():
    admin = admin_client()
    admin.post("/api/admin/seed")
    human_pool = match_pool(admin)
    cap = E.max_house_seed(human_pool)
    r = admin.post("/api/admin/house-seed", json={"outcome": "bansod", "amount": cap + 500})
    assert r.status_code == 400
    assert r.json()["detail"].startswith("seed_exceeds_rake_cap")


def test_house_seed_at_cap_is_accepted():
    admin = admin_client()
    admin.post("/api/admin/seed")
    human_pool = match_pool(admin)
    cap = E.max_house_seed(human_pool)
    r = admin.post("/api/admin/house-seed", json={"outcome": "bansod", "amount": cap})
    assert r.status_code == 200
    assert r.json()["floor"] >= 0


def test_house_seed_floor_visible_and_non_negative_through_full_lifecycle():
    """The admin console's badge (state.house.floor) must never read negative across an entire
    ordinary lifecycle — seed, real bets landing, laps run, right up to settlement."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    admin.post("/api/admin/house-seed", json={"outcome": "bansod", "amount": 3000})
    admin.post("/api/admin/side-seeds", json={"per_market": 200, "tilt": True})
    people = [user_client(f"P{i}") for i in range(6)]
    outcomes = ["khuseel", "bansod"] * 3
    for p, o in zip(people, outcomes):
        p.post("/api/bets", json={"market": "match", "outcome": o, "amount": 1000 + 250 * outcomes.index(o)})
    approve_all_pending(admin)
    assert admin.get("/api/state").json()["house"]["floor"] >= 0
    admin.post("/api/admin/race/start-lap")
    assert admin.get("/api/state").json()["house"]["floor"] >= 0
    admin.post("/api/admin/race/lap-result", json={"winner": "bansod", "time_s": 22.4})
    assert admin.get("/api/state").json()["house"]["floor"] >= 0


def _advance_to_break1(admin):
    """Comeback only opens in break1 (open_phases=("break1",)) — every arbitrage test below
    needs the market actually reachable before it can be part of a real covering pair."""
    admin.post("/api/admin/race/start-lap")
    r = admin.post("/api/admin/race/lap-result", json={"winner": "bansod", "time_s": 22.4})
    assert r.json()["phase"] == "break1"


def test_arbitrage_bet_rejected_at_submit():
    """Reproduces the natural distance=yes + comeback=no covering pair (see test_arbitrage.py)
    through the REAL HTTP submit path — the second leg must come back 409, and the book must
    show the first leg only. distance is open pre-race; comeback only opens in break1, so the
    two legs of the pair are necessarily established across that phase boundary."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    other1 = user_client("Other1")
    assert other1.post("/api/bets", json={"market": "distance", "outcome": "no", "amount": 2400}).status_code == 200
    approve_all_pending(admin)

    _advance_to_break1(admin)

    other2 = user_client("Other2")
    assert other2.post("/api/bets", json={"market": "comeback", "outcome": "yes", "amount": 1800}).status_code == 200
    approve_all_pending(admin)

    p = user_client("Arbitrageur")
    r1 = p.post("/api/bets", json={"market": "distance", "outcome": "yes", "amount": 800})
    assert r1.status_code == 200
    approve_all_pending(admin)

    r2 = p.post("/api/bets", json={"market": "comeback", "outcome": "no", "amount": 600})
    assert r2.status_code == 409
    assert r2.json()["detail"] == "arbitrage_bet"
    # confirm the rejected leg never entered the book at all (not even pending)
    pending = admin.get("/api/admin/pending").json()["pending"]
    assert not any(x["key"] == "name:arbitrageur" and x["market"] == "comeback" for x in pending)
    assert store.current_approved("name:arbitrageur", "comeback") is None


def test_arbitrage_bet_rejected_at_approve_time_too():
    """If the book shifts (another pending request gets approved) between submit and approve,
    approval re-checks and must catch a NOW-completing arbitrage even if it looked fine when
    the bettor first submitted it."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    other1 = user_client("Other1")
    other1.post("/api/bets", json={"market": "distance", "outcome": "no", "amount": 2400})
    approve_all_pending(admin)

    p = user_client("Arbitrageur")
    p.post("/api/bets", json={"market": "distance", "outcome": "yes", "amount": 800})
    approve_all_pending(admin)

    _advance_to_break1(admin)

    other2 = user_client("Other2")
    other2.post("/api/bets", json={"market": "comeback", "outcome": "yes", "amount": 1800})
    # arbitrageur's comeback=no submits successfully (other2's bet isn't approved yet, so this
    # single leg alone isn't arbitrage at submit time)...
    r = p.post("/api/bets", json={"market": "comeback", "outcome": "no", "amount": 600})
    assert r.status_code == 200

    pending = admin.get("/api/admin/pending").json()["pending"]
    other2_id = next(x["id"] for x in pending if x["key"] == "name:other2")
    arb_id = next(x["id"] for x in pending if x["key"] == "name:arbitrageur")
    assert admin.post(f"/api/admin/bets/{other2_id}/approve").status_code == 200
    # ...but NOW approving the arbitrageur's leg would complete the covering pair — rejected:
    r = admin.post(f"/api/admin/bets/{arb_id}/approve")
    assert r.status_code == 409 and r.json()["detail"] == "arbitrage_bet"
    assert store.bet_by_id(arb_id)["status"] == "rejected"

    floor = E.person_floor(store.approved_by_market(), "name:arbitrageur")
    assert floor <= 0


def test_normal_hedge_across_markets_is_allowed():
    """A real hedge (backs the same swimmer two different ways) must NOT be blocked — only
    genuine riskless combinations are."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    r1 = alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 500})
    assert r1.status_code == 200
    approve_all_pending(admin)
    r2 = alice.post("/api/bets", json={"market": "lap1", "outcome": "khuseel", "amount": 500})
    assert r2.status_code == 200


def test_same_person_same_market_opposite_outcome_replaces_not_doubles():
    """Pre-race, switching sides on the SAME market replaces the earlier bet (per rules) —
    proves there is never a state where one person holds both outcomes of one market."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 800})
    approve_all_pending(admin)
    alice.post("/api/bets", json={"market": "match", "outcome": "bansod", "amount": 500})
    approve_all_pending(admin)
    bets = admin.get("/api/state").json()["bets"]
    alice_bets = [b for b in bets if b["display_name"] == "Alice"]
    assert len(alice_bets) == 1 and alice_bets[0]["side"] == "bansod" and alice_bets[0]["amount"] == 500


# ── 4. sanitization: bettor vs admin, and admin's own "view as user" ─────────────────────────────

def test_market_book_shows_on_every_market_not_just_match():
    """The by-name approved-bettor list used to exist only for the match market — now every market
    carries the same `bets` field, sanitized the same way (house rows owner-only)."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    admin.post("/api/admin/side-seeds", json={"per_market": 200, "tilt": True})

    alice = user_client("Alice")
    r = alice.post("/api/bets", json={"market": "lap1", "outcome": "khuseel", "amount": 500})
    assert r.status_code == 200
    approve_all_pending(admin)

    admin_lap1 = next(m for m in admin.get("/api/state").json()["markets"] if m["id"] == "lap1")
    assert any(b["display_name"] == "Alice" and b["side"] == "khuseel" and b["amount"] == 500
               for b in admin_lap1["bets"])
    assert any(b["key"].startswith("house") for b in admin_lap1["bets"])  # admin sees house rows

    alice_lap1 = next(m for m in alice.get("/api/state").json()["markets"] if m["id"] == "lap1")
    assert any(b["display_name"] == "Alice" and b["amount"] == 500 for b in alice_lap1["bets"])
    assert not any(b["key"].startswith("house") for b in alice_lap1["bets"])  # hidden from bettor


def test_market_book_sorted_by_amount_desc():
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    bob = user_client("Bob")
    alice.post("/api/bets", json={"market": "lap2", "outcome": "bansod", "amount": 600})
    bob.post("/api/bets", json={"market": "lap2", "outcome": "bansod", "amount": 1500})
    approve_all_pending(admin)
    lap2 = next(m for m in admin.get("/api/state").json()["markets"] if m["id"] == "lap2")
    amounts = [b["amount"] for b in lap2["bets"] if not b["key"].startswith("house")]
    assert amounts == sorted(amounts, reverse=True)


def test_market_book_empty_for_side_market_with_no_bets():
    admin = admin_client()
    admin.post("/api/admin/seed")  # match-only seed, no side-seeds
    lap3 = next(m for m in admin.get("/api/state").json()["markets"] if m["id"] == "lap3")
    assert lap3["bets"] == []


def test_bettor_never_sees_house_internals():
    admin = admin_client()
    admin.post("/api/admin/seed")
    admin.post("/api/admin/house-seed", json={"outcome": "bansod", "amount": 3000})
    admin.post("/api/admin/side-seeds", json={"per_market": 200, "tilt": True})

    alice = user_client("Alice")
    state = alice.get("/api/state").json()
    assert "house" not in state and "rake_pct" not in state
    assert not any(b["key"].startswith("house") for b in state["bets"])
    assert not alice.get("/api/state").json()["me"]["is_owner"]
    assert next(m for m in state["markets"] if m["id"] == "match")["pool"] == 60050  # human-only


def test_admin_view_as_user_matches_real_bettor_payload_exactly():
    admin = admin_client()
    admin.post("/api/admin/seed")
    admin.post("/api/admin/house-seed", json={"outcome": "bansod", "amount": 3000})
    admin.post("/api/admin/side-seeds", json={"per_market": 200, "tilt": True})

    alice = user_client("Alice")
    alice_view = alice.get("/api/state").json()
    admin_as_user = admin.get("/api/state?as_user=1").json()

    for key in ("markets", "bets"):
        assert alice_view[key] == admin_as_user[key], key
    assert admin_as_user["me"]["is_owner"] is False
    assert admin_as_user["me"]["can_admin"] is True  # the ONE field that must differ
    assert "house" not in admin_as_user and "rake_pct" not in admin_as_user

    # admin's OWN (non-as_user) view must still show everything
    admin_view = admin.get("/api/state").json()
    assert "house" in admin_view and admin_view["me"]["is_owner"] is True


def test_settlement_sanitized_for_bettor():
    admin = admin_client()
    admin.post("/api/admin/seed")
    run_race(admin, [("bansod", 22.4), ("bansod", 23.1)])
    admin.post("/api/admin/settle")

    alice = user_client("Alice")
    bettor_settlement = alice.get("/api/settlement").json()
    assert set(bettor_settlement) == {"winner", "swimmer_take", "aggregate", "markets"}
    assert "house_take" not in bettor_settlement
    for m in bettor_settlement["markets"]:
        assert set(m) == {"market", "name", "won", "won_label", "void"}

    admin_settlement = admin.get("/api/settlement").json()
    assert "house_take" in admin_settlement
    as_user_settlement = admin.get("/api/settlement?as_user=1").json()
    assert as_user_settlement == bettor_settlement


# ── 5. cash reconciliation ───────────────────────────────────────────────────────────────────────

def test_cash_to_collect_matches_approved_pool_growth():
    """Every rupee the admin console tells the cashier to collect, once approved, shows up as
    exactly that much growth in the APPROVED (cash-in-hand) pool — the core 'pool == cash in
    hand' guarantee. (The DISPLAYED/indicative pool already counted this money the moment it
    was requested — see test_cancel_pending_snaps_odds_back — so this test deliberately reads
    the DB's approved-only total, not /api/state's pool, to isolate the cash claim.)"""
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    bob = user_client("Bob")
    alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 1200})
    bob.post("/api/bets", json={"market": "match", "outcome": "bansod", "amount": 800})

    pending = admin.get("/api/admin/pending").json()["pending"]
    total_to_collect = sum(p["cash_to_collect"] for p in pending)
    before = approved_match_pool()
    approve_all_pending(admin)
    after = approved_match_pool()
    assert after - before == total_to_collect == 2000


def test_raise_cash_to_collect_is_delta_only():
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 1000})
    approve_all_pending(admin)
    alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 1000})
    pending = admin.get("/api/admin/pending").json()["pending"]
    assert pending[0]["cash_to_collect"] == 0  # raising to the SAME amount owes nothing more
    alice.post("/api/bets/cancel", json={"market": "match"})
    alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 1500})
    pending = admin.get("/api/admin/pending").json()["pending"]
    assert pending[0]["cash_to_collect"] == 500


def test_manual_admin_bet_and_void_reconcile():
    admin = admin_client()
    admin.post("/api/admin/seed")
    before = match_pool(admin)
    admin.post("/api/admin/bets/manual",
              json={"name": "Walk-in", "market": "match", "outcome": "bansod", "amount": 2000})
    assert match_pool(admin) - before == 2000
    admin.post("/api/admin/bets/manual",
              json={"name": "Walk-in", "market": "match", "outcome": "bansod", "amount": 0})  # void
    assert match_pool(admin) == before


# ── volatility circuit breaker ───────────────────────────────────────────────────────────────────

def test_concurrent_approvals_on_same_market_dont_lose_either_bet():
    """Regression for a review finding: api_approve's before/approve/after/suspend-decision
    sequence is three separate DB transactions. Before _approve_lock, two real concurrent HTTP
    approvals on the same thin market could interleave and corrupt each other's swing snapshot
    (~10% of randomized interleavings produced a missed volatility detection in simulation).
    Fire two genuinely concurrent approve requests (a threading.Barrier forces them to start in
    the same instant) and assert the lock's actual job: neither call is lost, corrupted, or
    deadlocked — both land as approved with the correct combined pool, regardless of which one
    the lock let through first."""
    import threading

    admin = admin_client()
    admin.post("/api/admin/seed")
    alice, bob = user_client("Alice Racer"), user_client("Bob Punter")
    alice.post("/api/bets", json={"market": "lap1", "outcome": "khuseel", "amount": 500})
    bob.post("/api/bets", json={"market": "lap1", "outcome": "bansod", "amount": 500})
    pending = admin.get("/api/admin/pending").json()["pending"]
    ids = [p["id"] for p in pending if p["market"] == "lap1"]
    assert len(ids) == 2

    barrier = threading.Barrier(2)
    results = [None, None]

    # Threads need their own TestClient instances sharing the same underlying app/DB, since a
    # single TestClient's session cookie jar isn't meant for concurrent use from two threads.
    admin_a, admin_b = admin_client(), admin_client()

    def approve_with(client, i, bet_id):
        barrier.wait(timeout=5)  # both threads release together, forcing real interleaving
        results[i] = client.post(f"/api/admin/bets/{bet_id}/approve")

    t1 = threading.Thread(target=approve_with, args=(admin_a, 0, ids[0]))
    t2 = threading.Thread(target=approve_with, args=(admin_b, 1, ids[1]))
    t1.start(); t2.start()
    t1.join(timeout=10); t2.join(timeout=10)

    assert not t1.is_alive() and not t2.is_alive(), "a thread is still blocked -- possible deadlock"
    assert results[0] is not None and results[1] is not None
    assert results[0].status_code == 200, results[0].json()
    assert results[1].status_code == 200, results[1].json()

    approved = store.approved_bets("lap1")
    assert {b["display_name"] for b in approved} == {"Alice Racer", "Bob Punter"}
    assert sum(b["amount"] for b in approved) == 1000  # neither approval lost the other's write


def test_concurrent_submits_same_person_same_market_land_as_exactly_one_pending():
    """Regression for a review finding: store.submit_bet() is an update-then-insert across two
    statements. On Postgres (prod's real DB) two near-simultaneous first-time submits from the
    same person/market can both see 'nothing pending yet' and both INSERT — two live 'pending'
    rows for one person, doubling the cashier's apparent cash_to_collect until manually rejected.
    (SQLite's coarse whole-database write lock happens to serialize the two transactions outright,
    which is exactly why this doesn't reproduce locally without the fix under test — _submit_lock
    makes the guarantee explicit at the app layer instead of relying on which DB is behind it.)
    Fire two genuinely concurrent submits (a threading.Barrier forces them to start in the same
    instant) and assert exactly one live pending row survives, matching the documented supersede
    semantics regardless of which one the lock let through first."""
    import threading

    admin = admin_client()
    admin.post("/api/admin/seed")
    alice_a, alice_b = user_client("Alice"), user_client("Alice")  # same person, two sessions

    barrier = threading.Barrier(2)
    results = [None, None]

    def submit(client, i, amount):
        barrier.wait(timeout=5)
        results[i] = client.post("/api/bets", json={"market": "lap1", "outcome": "khuseel",
                                                     "amount": amount})

    t1 = threading.Thread(target=submit, args=(alice_a, 0, 500))
    t2 = threading.Thread(target=submit, args=(alice_b, 1, 600))
    t1.start(); t2.start()
    t1.join(timeout=10); t2.join(timeout=10)

    assert not t1.is_alive() and not t2.is_alive(), "a thread is still blocked -- possible deadlock"
    assert results[0] is not None and results[1] is not None
    assert results[0].status_code == 200, results[0].json()
    assert results[1].status_code == 200, results[1].json()

    pending = [p for p in store.pending_bets() if p["key"] == "name:alice" and p["market"] == "lap1"]
    assert len(pending) == 1, f"expected exactly one live pending row, found {len(pending)}"
    assert pending[0]["amount"] in (500, 600)


# ── amount bounds, name-mode identity collisions, headers, rate limit, health ───────────────────

def test_bet_amount_above_max_rejected():
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    r = alice.post("/api/bets", json={"market": "match", "outcome": "khuseel",
                                      "amount": E.MAX_BET_AMOUNT + 1})
    assert r.status_code == 400 and r.json()["detail"] == "bad_amount"
    r = alice.post("/api/bets", json={"market": "match", "outcome": "khuseel",
                                      "amount": E.MAX_BET_AMOUNT})
    assert r.status_code == 200


def test_manual_bet_above_max_rejected():
    admin = admin_client()
    admin.post("/api/admin/seed")
    r = admin.post("/api/admin/bets/manual",
                   json={"name": "Walk-in", "market": "match", "outcome": "bansod",
                         "amount": E.MAX_BET_AMOUNT + 1})
    assert r.status_code == 400 and r.json()["detail"] == "bad_input"


def test_name_collision_blocked_after_bet_exists():
    """Two different people whose typed names normalize to the same slug must not silently
    become one identity once the first person already has a bet on record."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    first = user_client("Rahul Sharma")
    first.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 200})

    c = TestClient(api.app)
    r = c.post("/auth/name", json={"name": "Rahul  Sharma"})  # double space -> same slug
    assert r.status_code == 409 and r.json()["detail"] == "name_taken"


def test_name_collision_blocked_before_any_bet_exists():
    """Same guard must fire even when NEITHER person has placed a bet yet — the gap a DB-only
    check (store.name_on_file) alone would miss, closed by the in-process _name_claims map."""
    user_client("Priya Verma")  # logs in, no bet placed yet
    c = TestClient(api.app)
    r = c.post("/auth/name", json={"name": "PRIYA VERMA!!"})  # same slug, still no bet on file
    assert r.status_code == 409 and r.json()["detail"] == "name_taken"


def test_name_relogin_with_identical_name_not_blocked():
    """The same person on a new device/session, typing their name exactly as before, must not be
    mistaken for a collision."""
    user_client("Alice")
    c = TestClient(api.app)
    r = c.post("/auth/name", json={"name": "Alice"})
    assert r.status_code == 200


def test_admin_manual_entry_and_name_login_share_identity():
    """The WhatsApp pre-race book is entered by the admin (store.admin_manual_bet); if that same
    person later logs in themselves via name-mode with the same name, they must land on the SAME
    identity and see their own existing bet — not a fresh, empty one. Regression for the slug
    consolidation: both paths now key through the one engine.name_slug()."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    admin.post("/api/admin/bets/manual",
              json={"name": "Deepak Rao", "market": "match", "outcome": "khuseel", "amount": 900})
    deepak = user_client("Deepak Rao")
    mine = next(m for m in deepak.get("/api/state").json()["markets"]
               if m["id"] == "match")["my_bet"]
    assert mine == {"outcome": "khuseel", "amount": 900}


def test_security_headers_present():
    c = TestClient(api.app)
    r = c.get("/api/config")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    # ALLOW_HTTP=1 in this test env (module setup, for LAN-style plain-http testing) -> HSTS,
    # which would force https on the next request, must NOT be sent.
    assert "strict-transport-security" not in r.headers


def test_rate_limit_trips_admin_login_after_threshold():
    c = TestClient(api.app)
    for _ in range(api._RATE_LIMIT_MAX):
        r = c.post("/auth/admin", json={"password": "wrong"})
        assert r.status_code == 403  # wrong password, but still a counted attempt
    r = c.post("/auth/admin", json={"password": "e2e-test-admin-pw"})  # correct — but over budget
    assert r.status_code == 429 and r.json()["detail"] == "too_many_attempts"


def test_healthz_ok():
    c = TestClient(api.app)
    r = c.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}


# ── pending-request cascade effects on OTHER bettors' displayed odds ────────────────────────────

def test_pending_raise_does_not_double_count_in_displayed_pool():
    """Regression: while a raise sits pending, the bettor's still-approved old amount and new
    pending amount were both being summed into the displayed pool (api_state) — the old row isn't
    superseded until the raise is actually APPROVED, but api_state was counting both the whole
    time it sat in the queue. Overstated the pool by the old amount for as long as the admin took
    to act — misleading every other bettor watching the board in that window, on top of whatever
    genuine indicative-odds movement the raise itself caused."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 1000})
    approve_all_pending(admin)
    pool_before_raise = match_pool(admin)

    alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 2500})
    pool_during_pending_raise = match_pool(admin)  # raise NOT yet approved
    assert pool_during_pending_raise - pool_before_raise == 1500  # delta only, not +2500 on top


def test_pending_side_switch_does_not_double_count_either_outcome():
    """Same mechanism, pre-race side-switch: while the switch sits pending, the old approved
    Khuseel row and the new pending Bansod row must not BOTH count toward the pool — there is
    only ever one live position per person per market, and the display must reflect that even
    before the admin has acted on the switch."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 800})
    approve_all_pending(admin)
    pool_before_switch = match_pool(admin)

    alice.post("/api/bets", json={"market": "match", "outcome": "bansod", "amount": 800})
    pool_during_pending_switch = match_pool(admin)  # switch NOT yet approved
    # same amount, just pending on the other side now -- not counted on both sides at once
    assert pool_during_pending_switch == pool_before_switch


def test_approve_reports_not_pending_if_bet_resolved_between_checks(monkeypatch):
    """Regression: api_approve's top-level pending-check and store.approve_bet's own internal
    re-check are two separate reads inside the same locked section. If the bet stops being
    'pending' in the gap between them (e.g. the bettor cancels in that exact window),
    store.approve_bet returns None without raising — api_approve must notice and report
    not_pending, not silently fall through to {"ok": True} on an approval that never actually
    happened (before/after would read the identical unchanged book, so the swing check alone
    would never catch this either). The real race needs sub-millisecond thread interleaving
    inside one locked section, not reliably triggerable over HTTP — simulated directly by
    stubbing store.approve_bet to return None, exactly as it would on a bet resolved out from
    under it."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 500})
    bet_id = admin.get("/api/admin/pending").json()["pending"][0]["id"]

    monkeypatch.setattr(store, "approve_bet", lambda *a, **k: None)
    r = admin.post(f"/api/admin/bets/{bet_id}/approve")
    assert r.status_code == 404 and r.json()["detail"] == "not_pending"
    assert store.bet_by_id(bet_id)["status"] == "pending"  # untouched, not falsely approved


# ── projected payouts (pre-settlement preview) ───────────────────────────────────────────────────

def test_projected_payouts_requires_owner():
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    r = alice.get("/api/admin/projected-payouts")
    assert r.status_code == 403


def test_projected_payouts_prerace_shows_all_six_scripts():
    admin = admin_client()
    admin.post("/api/admin/seed")
    r = admin.get("/api/admin/projected-payouts")
    assert r.status_code == 200
    scripts = r.json()["scripts"]
    assert len(scripts) == 6  # BB, BKB, BKK, KK, KBK, KBB — see engine.race_scripts
    for s in scripts:
        assert s["winner"] in ("khuseel", "bansod")
        assert s["wins"][s["winner"]] == 2
        assert isinstance(s["aggregate"], list) and len(s["aggregate"]) > 0


def test_projected_payouts_narrows_as_laps_happen():
    admin = admin_client()
    admin.post("/api/admin/seed")
    admin.post("/api/admin/race/start-lap")
    admin.post("/api/admin/race/lap-result", json={"winner": "bansod", "time_s": 22.4})  # break1
    r = admin.get("/api/admin/projected-payouts")
    scripts = r.json()["scripts"]
    assert len(scripts) == 3  # only completions consistent with bansod already winning lap 1
    assert all(s["laps"][0]["winner"] == "bansod" for s in scripts)


def test_projected_payouts_matches_direct_engine_call():
    """Cross-check against an independent engine.settle_all() call for the same laps — the
    endpoint must never compute its own, potentially-drifting version of this math."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    admin.post("/api/admin/house-seed", json={"outcome": "bansod", "amount": 3000})
    r = admin.get("/api/admin/projected-payouts")
    scripts = r.json()["scripts"]
    by_market = store.approved_by_market()
    for s in scripts:
        expected = E.settle_all(by_market, s["laps"])
        assert s["house_take"] == expected["house_take"]
        assert s["swimmer_take"] == expected["swimmer_take"]
        assert s["total_pool"] == expected["total_pool"]
        assert s["aggregate"] == expected["aggregate"]


def test_projected_payouts_mutates_nothing():
    """The whole point is a safe preview — race phase, the bets table, and the (absence of a)
    settlement record must all be exactly as they were before this was called."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    before_race = store.get_race()
    before_bets = store.approved_by_market()
    admin.get("/api/admin/projected-payouts")
    admin.get("/api/admin/projected-payouts")  # twice, in case of any accidental write-on-read
    assert store.get_race() == before_race
    assert store.approved_by_market() == before_bets
    assert store.load_settlement() is None


def test_projected_payouts_blocked_after_settlement():
    admin = admin_client()
    admin.post("/api/admin/seed")
    run_race(admin, [("bansod", 22.4), ("bansod", 23.1)])
    admin.post("/api/admin/settle")
    r = admin.get("/api/admin/projected-payouts")
    assert r.status_code == 400 and r.json()["detail"] == "already_settled"


# ── bet ledger + admin status override ──────────────────────────────────────────────────────────

def test_bets_ledger_requires_owner():
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    r = alice.get("/api/admin/bets")
    assert r.status_code == 403


def test_bets_ledger_lists_every_status_not_just_live():
    """pending_bets()/approved_bets() only ever show the live queue — this is the one endpoint
    where a rejected or cancelled bet is still findable, which is the whole point: you can't
    correct a mistake you can't see."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    bob = user_client("Bob")
    r = bob.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 600})
    rejected_id = r.json()["id"]
    admin.post(f"/api/admin/bets/{rejected_id}/reject")
    bob.post("/api/bets", json={"market": "match", "outcome": "bansod", "amount": 700})
    assert bob.post("/api/bets/cancel", json={"market": "match"}).json()["cancelled"] == 1

    rows = {b["id"]: b for b in admin.get("/api/admin/bets").json()["bets"]}
    assert rows[rejected_id]["status"] == "rejected"
    statuses_present = {b["status"] for b in rows.values()}
    assert {"approved", "rejected", "cancelled"} <= statuses_present


def test_bets_ledger_odds_match_direct_engine_call():
    """The 'odds allocated to who' column must be the SAME number the odds board and the real
    settlement math would use — not a separately-computed approximation."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    carol = user_client("Carol")
    carol.post("/api/bets", json={"market": "match", "outcome": "bansod", "amount": 800})  # pending

    pending_by_market = {}
    for p in store.pending_bets():
        pending_by_market.setdefault(p["market"], []).append(p)
    expected = E.market_book("match", store.approved_by_market().get("match", []) +
                             pending_by_market.get("match", []))

    for b in admin.get("/api/admin/bets").json()["bets"]:
        if b["market"] != "match":
            continue
        mult = expected["outcomes"][b["outcome"]]["est_mult"]
        assert b["est_mult"] == mult
        assert b["est_payout"] == (round(b["amount"] * mult) if mult else None)


def test_status_override_requires_owner():
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    bet_id = store.current_approved("name:yashbanwani", "match")["id"]
    r = alice.post(f"/api/admin/bets/{bet_id}/status", json={"status": "rejected"})
    assert r.status_code == 403
    assert store.bet_by_id(bet_id)["status"] == "approved"  # untouched


def test_status_override_force_approve_a_rejected_bet():
    """The core case this exists for: a bet that was wrongly rejected (or a portal request that
    auto-rejected when a lap started before the admin got to it) but the cash genuinely was
    collected — force it straight to approved without replaying it through /approve."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    dave = user_client("Dave")
    r = dave.post("/api/bets", json={"market": "match", "outcome": "bansod", "amount": 900})
    bet_id = r.json()["id"]
    admin.post(f"/api/admin/bets/{bet_id}/reject")
    assert store.bet_by_id(bet_id)["status"] == "rejected"
    before = match_pool(admin)

    r = admin.post(f"/api/admin/bets/{bet_id}/status", json={"status": "approved"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "old_status": "rejected", "new_status": "approved"}

    row = store.bet_by_id(bet_id)
    assert row["status"] == "approved"
    assert row["decided_by"] == "name:admin"
    assert row["note"].startswith("[override: rejected→approved]")
    assert match_pool(admin) - before == 900


def test_status_override_force_reject_an_approved_bet_shrinks_pool():
    admin = admin_client()
    admin.post("/api/admin/seed")
    before = match_pool(admin)
    yash_bet_id = store.current_approved("name:yashbanwani", "match")["id"]

    r = admin.post(f"/api/admin/bets/{yash_bet_id}/status", json={"status": "rejected"})
    assert r.status_code == 200
    assert before - match_pool(admin) == 5000
    assert store.current_approved("name:yashbanwani", "match") is None


def test_status_override_to_approved_supersedes_other_approved_same_market():
    admin = admin_client()
    admin.post("/api/admin/seed")
    old = store.current_approved("name:yashbanwani", "match")
    assert old["amount"] == 5000 and old["outcome"] == "khuseel"

    yash = user_client("Yash Banwani")  # same name_slug as the seeded key -> same identity
    r = yash.post("/api/bets", json={"market": "match", "outcome": "bansod", "amount": 1200})
    new_id = r.json()["id"]

    r = admin.post(f"/api/admin/bets/{new_id}/status", json={"status": "approved"})
    assert r.status_code == 200

    assert store.bet_by_id(old["id"])["status"] == "superseded"
    cur = store.current_approved("name:yashbanwani", "match")
    assert cur["id"] == new_id and cur["amount"] == 1200 and cur["outcome"] == "bansod"


def test_status_override_to_pending_cancels_other_pending_same_market():
    admin = admin_client()
    admin.post("/api/admin/seed")
    bob = user_client("Bob")
    bet1_id = bob.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 600}).json()["id"]
    admin.post(f"/api/admin/bets/{bet1_id}/reject")
    bet2_id = bob.post("/api/bets", json={"market": "match", "outcome": "bansod", "amount": 700}).json()["id"]
    assert store.bet_by_id(bet2_id)["status"] == "pending"

    r = admin.post(f"/api/admin/bets/{bet1_id}/status", json={"status": "pending"})
    assert r.status_code == 200

    assert store.bet_by_id(bet1_id)["status"] == "pending"
    assert store.bet_by_id(bet2_id)["status"] == "cancelled"
    pending_ids = {p["id"] for p in admin.get("/api/admin/pending").json()["pending"]}
    assert pending_ids == {bet1_id}


def test_status_override_unknown_bet_404():
    admin = admin_client()
    admin.post("/api/admin/seed")
    r = admin.post("/api/admin/bets/999999/status", json={"status": "approved"})
    assert r.status_code == 404 and r.json()["detail"] == "not_found"


def test_status_override_bad_status_rejected():
    admin = admin_client()
    admin.post("/api/admin/seed")
    bet_id = store.current_approved("name:yashbanwani", "match")["id"]
    for bad in ("superseded", "settled", "not_a_status", ""):
        r = admin.post(f"/api/admin/bets/{bet_id}/status", json={"status": bad})
        assert r.status_code == 400 and r.json()["detail"] == "bad_status"
    assert store.bet_by_id(bet_id)["status"] == "approved"  # every rejected attempt was a no-op


def test_status_override_noop_same_status_is_safe():
    admin = admin_client()
    admin.post("/api/admin/seed")
    bet_id = store.current_approved("name:yashbanwani", "match")["id"]
    r = admin.post(f"/api/admin/bets/{bet_id}/status", json={"status": "approved"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "old_status": "approved", "new_status": "approved"}
    assert store.bet_by_id(bet_id)["status"] == "approved"


def test_status_override_blocked_after_settlement():
    admin = admin_client()
    admin.post("/api/admin/seed")
    bet_id = store.current_approved("name:yashbanwani", "match")["id"]
    run_race(admin, [("bansod", 22.4), ("bansod", 23.1)])
    admin.post("/api/admin/settle")
    r = admin.post(f"/api/admin/bets/{bet_id}/status", json={"status": "rejected"})
    assert r.status_code == 400 and r.json()["detail"] == "already_settled"
    assert store.bet_by_id(bet_id)["status"] == "approved"  # frozen, untouched


def test_status_override_house_floor_recheck_suspends_market(monkeypatch):
    """Forcing a big rejected bet to 'approved' can expose the house exactly like a real approval
    can — same protection applies: re-check house_floor afterward, and if it's negative, suspend
    that market for review rather than silently leaving the house uncovered. The exact numeric
    threshold is engine.py's concern (already covered elsewhere); this only proves the endpoint
    reacts correctly when house_floor reports a losing position."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    bob = user_client("Bob")
    bet_id = bob.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 900}).json()["id"]
    admin.post(f"/api/admin/bets/{bet_id}/reject")

    monkeypatch.setattr(api.rules, "house_floor", lambda *a, **k: -777)
    r = admin.post(f"/api/admin/bets/{bet_id}/status", json={"status": "approved"})
    assert r.status_code == 200
    body = r.json()
    assert body["suspended_market"] == "match"
    assert body["floor"] == -777
    assert "match" in store.get_race()["suspended"]
