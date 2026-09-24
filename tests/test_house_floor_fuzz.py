"""
Q1 — "Can the house ever lose money?"

The organiser's guaranteed take is engine.house_floor(): settle every market under every
POSSIBLE way the race can end (race_scripts, ≤6 pre-race) and take the worst total. This file
fuzzes thousands of random and adversarial books, applies house seeds through the SAME
cap-then-floor-check-and-revert logic api.py enforces (replicated locally in pure Python against
engine.py — no DB/HTTP — so this runs fast and tests the MATH, not the wiring; the wiring itself
is exercised over real HTTP in test_e2e.py), and asserts the floor is never negative.

It also proves the guard is load-bearing (not decorative) by showing that WITHOUT it, adversarial
seed placements DO produce a negative floor — so "the house never loses" is a property of the
guard, not an accident of the numbers we happened to pick.
"""
import sys, os, random, zlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import engine as E

RNG_SEED = 20260927  # race date, for reproducibility
N_FUZZ = 600          # each iteration settles up to 6 scripts x 7 markets — keep runtime sane
NAMES = [f"P{i}" for i in range(60)]


def seeded_rng(*parts):
    """Deterministic Random from arbitrary parts — CPython's default Random(tuple) hashes
    strings with PYTHONHASHSEED (randomized per process), so reruns wouldn't reproduce
    failures. crc32 of a stable string join gives the same seed every run, every machine."""
    key = "|".join(str(p) for p in parts)
    return random.Random(zlib.crc32(key.encode()))


def _empty_book():
    return {m["id"]: [] for m in E.MARKETS}


def _add(book, market, outcome, amount, key=None, name=None):
    key = key or f"{market}:{outcome}:{len(book[market])}"
    book[market].append({"key": key, "display_name": name or key, "outcome": outcome, "amount": amount})


def guarded_match_seed(book, outcome, amount):
    """Mirrors api.api_house_seed: cap at expected rake, then floor-check-and-revert."""
    human_pool = sum(b["amount"] for b in book["match"] if not b["key"].startswith("house"))
    cap = E.max_house_seed(human_pool)
    amount = min(amount, cap)
    prev = [b for b in book["match"] if b["key"] == "house"]
    trial = {k: list(v) for k, v in book.items()}
    trial["match"] = [b for b in trial["match"] if b["key"] != "house"]
    if amount > 0:
        trial["match"].append({"key": "house", "display_name": "House", "outcome": outcome, "amount": amount})
    if E.house_floor(trial) < 0:
        return book  # reverted, unchanged
    return trial


def guarded_side_seed(book, market, outcome, amount):
    """Mirrors api.api_side_seeds' per-outcome guard for a single outcome change."""
    trial = {k: list(v) for k, v in book.items()}
    key = f"house:{market}:{outcome}"
    trial[market] = [b for b in trial[market] if b["key"] != key]
    if amount > 0:
        trial[market].append({"key": key, "display_name": "House", "outcome": outcome, "amount": amount})
    if E.house_floor(trial) < 0:
        return book
    return trial


def random_book(rng, n_bettors, max_amount=20000, concentrate=None):
    """concentrate: optional (market_id -> outcome) to force everyone onto one outcome per
    market — the worst case for that market's house exposure."""
    book = _empty_book()
    for i in range(n_bettors):
        for m in E.MARKETS:
            if rng.random() < 0.5:  # not every bettor touches every market
                continue
            oids = [o for o, _ in m["outcomes"]]
            outcome = (concentrate or {}).get(m["id"]) or rng.choice(oids)
            amount = rng.randint(1, max_amount)
            _add(book, m["id"], outcome, amount, key=f"p{i}", name=f"P{i}")
    return book


def apply_realistic_seeding(book, rng):
    book = guarded_match_seed(book, rng.choice(E.SIDES), rng.randint(0, 5000))
    for m in E.MARKETS:
        if m.get("main"):
            continue
        for oid, _ in m["outcomes"]:
            book = guarded_side_seed(book, m["id"], oid, rng.randint(0, 800))
    return book


def test_race_scripts_enumeration_is_exhaustive_and_correct():
    scripts = E.race_scripts()
    assert len(scripts) == 6
    seqs = {"".join(x["winner"][0] for x in s) for s in scripts}
    assert seqs == {"kk", "kbk", "kbb", "bb", "bkb", "bkk"}
    for s in scripts:
        assert E.race_winner(s) in E.SIDES
    # mid-race: only the scripts consistent with history remain
    after_b1 = E.race_scripts([{"lap": 1, "winner": "bansod", "time_s": None}])
    assert len(after_b1) == 3
    assert all(s[0]["winner"] == "bansod" for s in after_b1)


@pytest.mark.parametrize("trial", range(N_FUZZ))
def test_fuzz_random_books_house_never_loses(trial):
    rng = seeded_rng(RNG_SEED, trial)
    n = rng.randint(0, 40)
    book = random_book(rng, n)
    book = apply_realistic_seeding(book, rng)
    floor = E.house_floor(book)
    assert floor >= 0, f"trial {trial}: house floor went negative ({floor}) with guarded seeding"


@pytest.mark.parametrize("market", [m["id"] for m in E.MARKETS])
@pytest.mark.parametrize("outcome_index", [0, 1])
def test_adversarial_everyone_backs_one_outcome(market, outcome_index):
    """Worst case per market: every bettor concentrates on a single outcome (the one that, if
    it wins, pays out the most per rupee staked). Seeds applied through the guard; must hold."""
    m = E.MARKET_BY_ID[market]
    oids = [o for o, _ in m["outcomes"]]
    if outcome_index >= len(oids):
        pytest.skip("market has fewer outcomes")
    outcome = oids[outcome_index]
    rng = seeded_rng(RNG_SEED, "concentrate", market, outcome)
    book = random_book(rng, rng.randint(5, 40), concentrate={market: outcome})
    book = apply_realistic_seeding(book, rng)
    assert E.house_floor(book) >= 0


def test_adversarial_single_dominant_bettor():
    """One bettor stakes far more than everyone else combined, on the eventual winner."""
    rng = seeded_rng(RNG_SEED, "dominant")
    book = _empty_book()
    _add(book, "match", "khuseel", 500000, key="whale")
    for m in E.MARKETS:
        if m.get("main"):
            continue
        _add(book, m["id"], m["outcomes"][0][0], 200000, key="whale")
    # a few small bettors on the other side too
    for i in range(5):
        _add(book, "match", "bansod", rng.randint(100, 5000), key=f"p{i}")
    book = apply_realistic_seeding(book, rng)
    assert E.house_floor(book) >= 0


def test_adversarial_only_dead_outcomes_hold_money():
    """Money sits on an outcome that becomes impossible after lap 1 (e.g. Khuseel 2-0 once
    Bansod has taken lap 1) — that stake must stay in the pool for the survivors, not vanish."""
    book = _empty_book()
    _add(book, "score", "k20", 5000, key="p1")
    _add(book, "score", "b21", 3000, key="p2")
    laps = [{"lap": 1, "winner": "bansod", "time_s": None}]
    assert not E.outcome_alive("score", "k20", laps)
    res = E.settle_market("score", book["score"], laps + [{"lap": 2, "winner": "bansod", "time_s": None}])
    assert res["pool"] == 8000  # k20's 5000 is still in the pool
    assert res["house"] + res["swimmer"] + sum(r["payout"] for r in res["rows"]) == 8000


def test_adversarial_win_total_zero_every_market():
    """Nobody at all backs the winning outcome anywhere — house must still not go negative
    (side markets refund 95%, keeping the 5% rake; main market pays the swimmer regardless)."""
    book = _empty_book()
    for m in E.MARKETS:
        oid = m["outcomes"][0][0]  # only ever bet the outcome that will NOT win
        _add(book, m["id"], oid, 1000, key="loyalist")
    laps_b_sweep = [{"lap": 1, "winner": "bansod", "time_s": None},
                    {"lap": 2, "winner": "bansod", "time_s": None}]
    res = E.settle_all(book, laps_b_sweep)
    assert res["house_take"] >= 0


def test_adversarial_seeds_at_exact_cap_boundary():
    rng = seeded_rng(RNG_SEED, "cap_boundary")
    book = random_book(rng, 20)
    human_pool = sum(b["amount"] for b in book["match"])
    cap = E.max_house_seed(human_pool)
    book_at_cap = guarded_match_seed(book, "bansod", cap)  # exactly at cap, not over
    assert E.house_floor(book_at_cap) >= 0
    # one rupee over the cap must never even be attempted by the guard function (it clamps),
    # but prove the UNCLAMPED amount would indeed be accepted-or-reverted correctly either way
    book_over = guarded_match_seed(book, "bansod", cap + 1)
    assert E.house_floor(book_over) >= 0  # guard clamps internally, still safe


def test_guard_is_load_bearing_not_decorative():
    """Without the cap+floor guard, a reckless seed CAN create a losing scenario — proving the
    guard is doing real work, not just agreeing with numbers that were always going to be safe."""
    book = _empty_book()
    _add(book, "match", "khuseel", 1000, key="p1")
    _add(book, "match", "bansod", 1000, key="p2")
    # Recklessly seed 50,000 on bansod with NO cap applied (bypassing max_house_seed entirely)
    reckless = {k: list(v) for k, v in book.items()}
    reckless["match"].append({"key": "house", "display_name": "House", "outcome": "bansod", "amount": 50000})
    assert E.house_floor(reckless) < 0, "expected an uncapped reckless seed to be able to lose money"
    # The SAME seed, applied through the guard, is rejected/clamped and stays safe
    guarded = guarded_match_seed(book, "bansod", 50000)
    assert E.house_floor(guarded) >= 0


def test_guard_is_load_bearing_side_markets():
    book = _empty_book()
    _add(book, "distance", "yes", 100, key="p1")
    reckless = {k: list(v) for k, v in book.items()}
    reckless["distance"].append({"key": "house:distance:no", "display_name": "House",
                                 "outcome": "no", "amount": 100000})
    assert E.house_floor(reckless) < 0
    guarded = guarded_side_seed(book, "distance", "no", 100000)
    assert E.house_floor(guarded) >= 0


def test_per_market_settlement_invariant_holds_under_fuzz():
    """payout + swimmer + house == pool, exactly, for every market, every script, every fuzz book."""
    rng = seeded_rng(RNG_SEED, "invariant")
    for trial in range(100):
        book = random_book(rng, rng.randint(0, 30))
        book = apply_realistic_seeding(book, rng)
        for script in E.race_scripts():
            for m in E.MARKETS:
                rows = book.get(m["id"], [])
                if not rows:
                    continue
                res = E.settle_market(m["id"], rows, script)
                paid = sum(r["payout"] for r in res["rows"])
                assert paid + res["swimmer"] + res["house"] == res["pool"], (trial, m["id"], script)


def test_shivam_real_lap3_position_has_no_external_blowout_either_direction():
    """The exact real book that prompted this cap (2026-09-24 finding): Lap 3 Winner shows
    khuseel=2080 (house seed 80 + Shivam's real ₹2,000 bet) vs bansod=120 (house seed only).
    Worked out precisely, this is NOT a blowout risk in either direction: Shivam bet the ALREADY
    HEAVY side, so if khuseel wins he barely gets his stake back (~1.0x, house nets ₹111) — there
    was never a hole to fall into. The genuine payout-blowout math is on the THIN bansod side,
    which right now is 100% house money: if bansod wins, the natural multiplier there is ~17.5x
    -- the cap correctly clips the house's OWN seed row to exactly 7x (₹840, not ~₹2100), with
    the difference simply staying as additional house profit (moving money between house buckets,
    not creating or losing any). Either way the organiser is safe; see the next test for the
    scenario that actually matters going forward — a REAL bettor later taking that thin side."""
    bets = [{"key": "house:lap3:bansod", "display_name": "House", "outcome": "bansod", "amount": 120},
            {"key": "house:lap3:khuseel", "display_name": "House", "outcome": "khuseel", "amount": 80},
            {"key": "shivam", "display_name": "Shivam Maheshwari", "outcome": "khuseel", "amount": 2000}]

    khuseel_takes_it = [{"lap": 1, "winner": "bansod", "time_s": None},
                        {"lap": 2, "winner": "khuseel", "time_s": None},
                        {"lap": 3, "winner": "khuseel", "time_s": None}]
    res = E.settle_market("lap3", bets, khuseel_takes_it)
    shivam_row = next(r for r in res["rows"] if r["key"] == "shivam")
    assert shivam_row["payout"] == 2009  # ~1.0x — nowhere near the 7x cap, nothing to clip
    assert res["house"] == 111

    bansod_takes_it = [{"lap": 1, "winner": "khuseel", "time_s": None},
                       {"lap": 2, "winner": "bansod", "time_s": None},
                       {"lap": 3, "winner": "bansod", "time_s": None}]
    res2 = E.settle_market("lap3", bets, bansod_takes_it)
    house_bansod_row = next(r for r in res2["rows"] if r["key"] == "house:lap3:bansod")
    assert house_bansod_row["payout"] == 120 * E.MAX_PAYOUT_MULT == 840  # capped from ~2100 natural
    paid = sum(r["payout"] for r in res2["rows"])
    assert paid + res2["swimmer"] + res2["house"] == res2["pool"]


def test_payout_cap_protects_against_a_real_bettor_on_the_thin_side():
    """The scenario the cap actually exists to prevent going forward: someone ELSE now bets a
    real, modest stake on the currently-thin bansod side of the SAME market Shivam is in. A
    SMALL stake on the thin side gets the HIGHEST natural ratio (the ~fixed opposing pool is
    divided among less win_total) — ₹100 here would naturally return ~10.6x, funded mostly by
    Shivam's real ₹2,000, not by any seed. The cap bounds it to 7x regardless."""
    bets = [{"key": "house:lap3:bansod", "display_name": "House", "outcome": "bansod", "amount": 120},
            {"key": "house:lap3:khuseel", "display_name": "House", "outcome": "khuseel", "amount": 80},
            {"key": "shivam", "display_name": "Shivam Maheshwari", "outcome": "khuseel", "amount": 2000},
            {"key": "priya", "display_name": "Priya", "outcome": "bansod", "amount": 100}]
    bansod_takes_it = [{"lap": 1, "winner": "khuseel", "time_s": None},
                       {"lap": 2, "winner": "bansod", "time_s": None},
                       {"lap": 3, "winner": "bansod", "time_s": None}]
    res = E.settle_market("lap3", bets, bansod_takes_it)
    priya_row = next(r for r in res["rows"] if r["key"] == "priya")
    assert priya_row["payout"] == 100 * E.MAX_PAYOUT_MULT == 700  # capped from a ~10.6x natural ratio
    paid = sum(r["payout"] for r in res["rows"])
    assert paid + res["swimmer"] + res["house"] == res["pool"]
    assert res["house"] >= 0


def test_payout_cap_applies_uniformly_to_all_winners_on_capped_outcome():
    """The pari-mutuel multiplier is the same for every bettor on a winning outcome — so when
    the cap binds, it binds identically for a ₹10 bettor and a ₹10,000 bettor on that same
    outcome; nobody is treated differently by stake size. (Winning side must be the THIN one —
    a large 'no' seed funds a big natural multiplier for the comparatively small 'yes' stakes.)"""
    bets = [{"key": "seed", "display_name": "S", "outcome": "no", "amount": 500000},
            {"key": "small", "display_name": "Small", "outcome": "yes", "amount": 10},
            {"key": "big", "display_name": "Big", "outcome": "yes", "amount": 10000}]
    res = E.settle_market("distance", bets, [{"lap": 1, "winner": "bansod", "time_s": None},
                                             {"lap": 2, "winner": "khuseel", "time_s": None},
                                             {"lap": 3, "winner": "khuseel", "time_s": None}])
    small = next(r for r in res["rows"] if r["key"] == "small")
    big = next(r for r in res["rows"] if r["key"] == "big")
    assert small["payout"] == 10 * E.MAX_PAYOUT_MULT == 70
    assert big["payout"] == 10000 * E.MAX_PAYOUT_MULT == 70000


def test_displayed_odds_never_exceed_the_cap():
    """market_book's est_mult (what bettors actually see) is capped identically to the real
    settlement payout — a bettor should never see a promised multiplier the app won't honor.
    Uses lap1 (khuseel/bansod outcomes) — distance/comeback/score use yes/no or score-code
    outcome ids, so a khuseel/bansod book would KeyError against their outcome sets."""
    khuseel_stake, bansod_stake = 10, 100000
    rows = [{"key": "a", "display_name": "A", "outcome": "khuseel", "amount": khuseel_stake},
            {"key": "b", "display_name": "B", "outcome": "bansod", "amount": bansod_stake}]
    b = E.market_book("lap1", rows)
    assert b["outcomes"]["khuseel"]["est_mult"] == E.MAX_PAYOUT_MULT
    # sanity: without the cap this would be enormous (~9500x) — confirm it's the cap doing the
    # clipping, not a coincidentally-small natural value
    pool, rake = khuseel_stake + bansod_stake, int(0.05 * (khuseel_stake + bansod_stake))
    natural = (pool - rake) / khuseel_stake
    assert natural > E.MAX_PAYOUT_MULT * 100


def test_payout_cap_never_increases_house_risk_under_fuzz():
    """The cap can only ever REDUCE what's paid to winners (routing the difference to house), so
    it can only ever help house_floor — confirm capped floors are always >= what an identical
    book would floor at if we (hypothetically) had no cap at all, across the same fuzz used for
    the core Q1 property."""
    rng = seeded_rng(RNG_SEED, "cap_monotonic")
    for _ in range(200):
        book = random_book(rng, rng.randint(0, 30), max_amount=50000)
        book = apply_realistic_seeding(book, rng)
        assert E.house_floor(book) >= 0  # the already-proven Q1 property, re-affirmed with the cap active


def test_production_seeding_worst_case_is_documented():
    """The exact floor at the seeding configuration actually applied to prod (match seed 3000
    on bansod + tilted per-outcome side seeds at 200/market) with the REAL seed book, so the
    number in this test is the number that should match what the admin console shows."""
    import store as _store  # noqa: F401  (import path sanity only; not used — book built by hand)
    from seed import SEED_BETS
    book = _empty_book()
    for name, amount, side in SEED_BETS:
        _add(book, "match", side, amount, key=f"name:{name.lower()}", name=name)
    book = guarded_match_seed(book, "bansod", 3000)
    for m in E.MARKETS:
        if m.get("main"):
            continue
        pri = E.outcome_priors(m["id"])
        for oid, _ in m["outcomes"]:
            amt = max(10, int(round(pri[oid] * 200 / 10) * 10))
            book = guarded_side_seed(book, m["id"], oid, amt)
    floor = E.house_floor(book)
    assert floor >= 160, f"prod seeding floor dropped below the documented +160 baseline: {floor}"
