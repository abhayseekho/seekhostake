"""Multi-market settlement + rules invariants. The seeded WhatsApp book (₹60,050) is the main
fixture; every market must sum payouts + swimmer + house exactly to its pool."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import engine
from seed import SEED_BETS

LAPS_B20 = [{"lap": 1, "winner": "bansod", "time_s": 22.4},
            {"lap": 2, "winner": "bansod", "time_s": 23.0}]
LAPS_K21 = [{"lap": 1, "winner": "bansod", "time_s": 22.4},
            {"lap": 2, "winner": "khuseel", "time_s": 22.1},
            {"lap": 3, "winner": "khuseel", "time_s": 22.9}]


def _match_bets(house_seed=0, seed_side="bansod"):
    rows = [{"key": n.lower(), "display_name": n, "outcome": s, "amount": a}
            for n, a, s in SEED_BETS]
    if house_seed:
        rows.append({"key": "house", "display_name": "House", "outcome": seed_side,
                     "amount": house_seed})
    return rows


def _mk(outcomes_amounts):
    return [{"key": f"p{i}", "display_name": f"P{i}", "outcome": o, "amount": a}
            for i, (o, a) in enumerate(outcomes_amounts)]


def test_seeded_match_book():
    book = engine.market_book("match", _match_bets())
    assert book["pool"] == 60050
    assert book["outcomes"]["khuseel"]["total"] == 28050
    assert book["outcomes"]["bansod"]["total"] == 32000
    # est_mult reflects 5% rake + 30% swimmer cut on the losing pot
    rake = int(0.05 * 60050)
    assert book["outcomes"]["khuseel"]["est_mult"] == round(1 + 0.7 * (32000 - rake) / 28050, 3)


@pytest.mark.parametrize("laps,winner", [(LAPS_B20, "bansod"), (LAPS_K21, "khuseel")])
def test_match_settlement_sums_to_pool(laps, winner):
    res = engine.settle_market("match", _match_bets(), laps)
    assert res["won"] == winner
    paid = sum(r["payout"] for r in res["rows"])
    assert paid + res["swimmer"] + res["house"] == res["pool"] == 60050
    assert res["house"] >= int(0.05 * 60050)  # rake + rounding remainders
    for r in res["rows"]:
        if r["outcome"] == winner:
            assert r["payout"] >= r["stake"]
        else:
            assert r["payout"] == 0


def test_house_seed_never_negative():
    """Seed capped at the rake → organiser net (rake + seed result) >= 0 for both outcomes."""
    human_pool = 60050
    cap = engine.max_house_seed(human_pool)
    assert cap == 3002
    for laps in (LAPS_B20, LAPS_K21):
        res = engine.settle_market("match", _match_bets(house_seed=cap), laps)
        seed_net = next(r["net"] for r in res["rows"] if r["key"] == "house")
        organiser_net = res["house"] + seed_net
        assert organiser_net >= 0, laps
        paid = sum(r["payout"] for r in res["rows"])
        assert paid + res["swimmer"] + res["house"] == res["pool"]


def test_house_seed_sweetens_khuseel():
    plain = engine.market_book("match", _match_bets())
    seeded = engine.market_book("match", _match_bets(house_seed=3000))
    assert seeded["outcomes"]["khuseel"]["est_mult"] > plain["outcomes"]["khuseel"]["est_mult"]


def test_side_market_rake_and_sums():
    bets = _mk([("yes", 1400), ("no", 1800), ("yes", 600)])
    res = engine.settle_market("distance", bets, LAPS_K21)  # 3 laps → yes
    assert res["won"] == "yes"
    paid = sum(r["payout"] for r in res["rows"])
    assert paid + res["house"] == res["pool"] == 3800
    assert res["house"] >= int(0.05 * 3800)
    assert res["swimmer"] == 0  # swimmer cut is main-market only


def test_score_market():
    bets = _mk([("b20", 1900), ("k21", 850), ("b21", 1850), ("k20", 500)])
    res = engine.settle_market("score", bets, LAPS_K21)
    assert res["won"] == "k21"
    winner_row = next(r for r in res["rows"] if r["outcome"] == "k21")
    assert winner_row["payout"] == 850 + (850 * (5100 - int(0.05 * 5100) - 850)) // 850
    # dead outcome (k20 after bansod takes lap 1) is unbettable but its money stays in the pool
    assert not engine.outcome_alive("score", "k20", LAPS_K21[:1])
    assert engine.outcome_alive("score", "k21", LAPS_K21[:1])


def test_lap3_void_refunds():
    bets = _mk([("khuseel", 700), ("bansod", 300)])
    res = engine.settle_market("lap3", bets, LAPS_B20)  # 2-0 → lap 3 never swum
    assert res["void"] is True and res["house"] == 0
    assert all(r["payout"] == r["stake"] for r in res["rows"])


def test_comeback_market():
    bets = _mk([("yes", 600), ("no", 1300)])
    assert engine.settle_market("comeback", bets, LAPS_K21)["won"] == "yes"
    assert engine.settle_market("comeback", bets, LAPS_B20)["won"] == "no"


def test_no_winner_backers():
    bets = _mk([("no", 1000)])
    res = engine.settle_market("distance", bets, LAPS_K21)  # yes wins, nobody on it
    assert res["rows"][0]["payout"] == 950  # 95% refund, house keeps the rake
    assert res["house"] == 50


def test_settle_all_aggregate():
    by_market = {
        "match": _match_bets(house_seed=3000),
        "distance": _mk([("yes", 500), ("no", 500)]),
        "lap1": _mk([("bansod", 200), ("khuseel", 200)]),
        "lap3": _mk([("khuseel", 300)]),
    }
    s = engine.settle_all(by_market, LAPS_B20)
    assert s["winner"] == "bansod"
    # every rupee that entered any pool is accounted for
    total_pool = sum(m["pool"] for m in s["markets"])
    paid = sum(p["payout"] for p in s["aggregate"])
    seed = 3000
    house_abs = s["house_take"] + seed  # house_take nets the seed stake
    assert paid + s["swimmer_take"] + house_abs == total_pool
    assert s["house_take"] >= 0
    assert not any(p["key"] == "house" for p in s["aggregate"])


def test_house_floor_enumeration():
    assert len(engine.race_scripts()) == 6           # BB, BKB, BKK, KK, KBK, KBB
    assert len(engine.race_scripts(LAPS_B20[:1])) == 3
    # match seed alone, capped at rake → floor >= 0 in every script
    floor = engine.house_floor({"match": _match_bets(house_seed=3000)})
    assert floor >= 0
    # a reckless one-sided side seed can create a losing scenario the floor must catch:
    # house 500 on 'no', humans 500 on 'yes', a 3-lap race makes 'yes' win and house lose
    risky = {"match": _match_bets(house_seed=3000),
             "distance": _mk([("yes", 500)]) + [{"key": "house:distance:no",
                                                 "display_name": "House", "outcome": "no",
                                                 "amount": 500}]}
    assert engine.house_floor(risky) < engine.house_floor({"match": _match_bets(house_seed=3000)})


def test_can_submit_rules():
    ok, _ = engine.can_submit("match", "prerace", "khuseel", 500)
    assert ok
    assert engine.can_submit("match", "prerace", "khuseel", 500, current_outcome="bansod")[0]
    assert engine.can_submit("match", "break1", "khuseel", 500,
                             current_outcome="bansod") == (False, "no_side_switch")
    assert engine.can_submit("match", "break1", "khuseel", 500, current_outcome="khuseel")[0]
    for phase in ("lap1", "lap2", "break2", "lap3", "finished", "settled"):
        assert engine.can_submit("match", phase, "khuseel", 500) == (False, "book_closed")
    assert engine.can_submit("match", "prerace", "khuseel", 0) == (False, "bad_amount")
    # market-specific windows
    assert engine.can_submit("lap1", "break1", "khuseel", 100) == (False, "book_closed")
    assert engine.can_submit("comeback", "prerace", "yes", 100) == (False, "book_closed")
    assert engine.can_submit("comeback", "break1", "yes", 100)[0]
    # dead outcome after lap 1
    assert engine.can_submit("score", "break1", "k20", 100,
                             laps=LAPS_K21[:1]) == (False, "outcome_dead")
    # side-switch freedom on side markets
    assert engine.can_submit("distance", "break1", "yes", 100, current_outcome="no")[0]


def test_phase_machine_best_of_3():
    assert engine.next_phase_on_start_lap("prerace") == "lap1"
    laps = [LAPS_B20[0]]
    assert engine.next_phase_on_lap_result("lap1", laps) == "break1"
    assert engine.next_phase_on_lap_result("lap2", LAPS_B20) == "finished"
    assert engine.race_winner(LAPS_B20) == "bansod"
    assert engine.next_phase_on_lap_result("lap2", LAPS_K21[:2]) == "break2"
    assert engine.race_winner(LAPS_K21) == "khuseel"
    with pytest.raises(ValueError):
        engine.next_phase_on_start_lap("lap1")
    with pytest.raises(ValueError):
        engine.next_phase_on_lap_result("break1", laps)


def test_odds_swing_flags_thin_market_moves():
    # Thin market: house seed only ₹80/₹120. One ₹500 bet on khuseel should swing bansod's
    # multiplier by several times — exactly the real production scenario this guards against.
    seed = _mk([("khuseel", 80), ("bansod", 120)])
    before = engine.market_book("lap1", seed)
    after = engine.market_book("lap1", seed + _mk([("khuseel", 500)]))
    ratio, oid = engine.odds_swing("lap1", before, after)
    assert ratio > engine.VOLATILITY_SUSPEND_RATIO
    assert oid == "bansod"  # bansod's price is what moved (khuseel's own side barely changes)


def test_odds_swing_ignores_normal_growth():
    # A deep market (like the real match book) absorbs a normal-sized bet without tripping.
    seed = _mk([("khuseel", 28050), ("bansod", 32000)])
    before = engine.market_book("match", seed)
    after = engine.market_book("match", seed + _mk([("khuseel", 500)]))
    ratio, _ = engine.odds_swing("match", before, after)
    assert ratio < engine.VOLATILITY_SUSPEND_RATIO


def test_odds_swing_no_prior_price_is_not_volatility():
    # First-ever bet on a previously dead/untouched outcome has nothing to compare against —
    # that's demand showing up, not a "swing", so it must not trip the breaker.
    before = engine.market_book("distance", [])
    after = engine.market_book("distance", _mk([("yes", 500)]))
    ratio, oid = engine.odds_swing("distance", before, after)
    assert ratio == 1.0 and oid is None


def test_odds_swing_ignores_dead_outcome_drift():
    # Regression: after lap 1, one score outcome (the loser's 2-0 line) is permanently dead —
    # its multiplier still drifts as a pure side effect whenever the pool grows on a LIVE
    # outcome, since every outcome in a market shares the same pool. That drift is arithmetic,
    # not demand, and nobody can ever bet on the dead line to "correct" it — so it must never
    # trip the breaker, no matter how large the ratio looks in isolation.
    laps_after_lap1 = [{"lap": 1, "winner": "bansod", "time_s": 22.4}]
    seed = _mk([("k20", 81), ("k21", 96), ("b20", 23), ("b21", 22)])
    before = engine.market_book("score", seed)
    after = engine.market_book("score", seed + _mk([("k21", 267)]))  # ordinary bet on a live line
    # Sanity: k20 (dead) swings hard as a pure side effect, and would wrongly trip if not excluded.
    naive_ratio, naive_oid = engine.odds_swing("score", before, after)  # laps=() -> nothing excluded
    assert naive_ratio > engine.VOLATILITY_SUSPEND_RATIO and naive_oid == "k20"
    # With the actual lap history supplied, the dead outcome is skipped entirely.
    ratio, oid = engine.odds_swing("score", before, after, laps=laps_after_lap1)
    assert oid != "k20"
    assert ratio <= engine.VOLATILITY_SUSPEND_RATIO  # the live k21 bet alone doesn't trip it


def test_can_submit_respects_suspension():
    assert engine.can_submit("lap1", "prerace", "khuseel", 100, suspended=True) == \
        (False, "market_suspended")
    assert engine.can_submit("lap1", "prerace", "khuseel", 100, suspended=False)[0]
