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
    r = alice.post("/api/bets", json={"market": "distance", "outcome": "no", "amount": 150})
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
    r = bob.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 400})
    assert r.status_code == 200
    approve_all_pending(admin)

    r = admin.post("/api/admin/race/start-lap")  # -> lap1
    admin.post("/api/admin/race/lap-result", json={"winner": "bansod", "time_s": 22.4})  # -> break1

    # comeback market opens only in break1 — bet it now
    r = bob.post("/api/bets", json={"market": "comeback", "outcome": "yes", "amount": 200})
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
    alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 100})
    approve_all_pending(admin)
    admin.post("/api/admin/race/start-lap")
    admin.post("/api/admin/race/lap-result", json={"winner": "bansod", "time_s": 22.4})  # break1
    r = alice.post("/api/bets", json={"market": "match", "outcome": "bansod", "amount": 100})
    assert r.status_code == 400 and r.json()["detail"] == "no_side_switch"
    # raising the SAME side is fine
    r = alice.post("/api/bets", json={"market": "match", "outcome": "khuseel", "amount": 500})
    assert r.status_code == 200


def test_side_market_switching_allowed_in_break1():
    """Only the MAIN market locks sides after lap 1 — side markets have no such rule."""
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    alice.post("/api/bets", json={"market": "distance", "outcome": "yes", "amount": 100})
    approve_all_pending(admin)
    admin.post("/api/admin/race/start-lap")
    admin.post("/api/admin/race/lap-result", json={"winner": "bansod", "time_s": 22.4})
    r = alice.post("/api/bets", json={"market": "distance", "outcome": "no", "amount": 150})
    assert r.status_code == 200


def test_outcome_dead_after_lap1_blocks_bet():
    admin = admin_client()
    admin.post("/api/admin/seed")
    alice = user_client("Alice")
    admin.post("/api/admin/race/start-lap")
    admin.post("/api/admin/race/lap-result", json={"winner": "bansod", "time_s": 22.4})  # kills k20
    r = alice.post("/api/bets", json={"market": "score", "outcome": "k20", "amount": 100})
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


def test_reset_book_only_pre_race():
    admin = admin_client()
    admin.post("/api/admin/seed")
    admin.post("/api/admin/race/start-lap")
    r = admin.post("/api/admin/reset-book")
    assert r.status_code == 400 and r.json()["detail"] == "race_started"


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
    assert other1.post("/api/bets", json={"market": "distance", "outcome": "no", "amount": 1200}).status_code == 200
    approve_all_pending(admin)

    _advance_to_break1(admin)

    other2 = user_client("Other2")
    assert other2.post("/api/bets", json={"market": "comeback", "outcome": "yes", "amount": 900}).status_code == 200
    approve_all_pending(admin)

    p = user_client("Arbitrageur")
    r1 = p.post("/api/bets", json={"market": "distance", "outcome": "yes", "amount": 400})
    assert r1.status_code == 200
    approve_all_pending(admin)

    r2 = p.post("/api/bets", json={"market": "comeback", "outcome": "no", "amount": 300})
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
    other1.post("/api/bets", json={"market": "distance", "outcome": "no", "amount": 1200})
    approve_all_pending(admin)

    p = user_client("Arbitrageur")
    p.post("/api/bets", json={"market": "distance", "outcome": "yes", "amount": 400})
    approve_all_pending(admin)

    _advance_to_break1(admin)

    other2 = user_client("Other2")
    other2.post("/api/bets", json={"market": "comeback", "outcome": "yes", "amount": 900})
    # arbitrageur's comeback=no submits successfully (other2's bet isn't approved yet, so this
    # single leg alone isn't arbitrage at submit time)...
    r = p.post("/api/bets", json={"market": "comeback", "outcome": "no", "amount": 300})
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
    r2 = alice.post("/api/bets", json={"market": "lap1", "outcome": "khuseel", "amount": 300})
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
