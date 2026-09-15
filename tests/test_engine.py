"""Settlement + rules invariants. The seeded WhatsApp book is the fixture because its expected
numbers were hand-computed and agreed with Abhay in chat (Bansod 1.53x / swimmer 8415;
Khuseel 1.92x / swimmer 11100 before rounding drift)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import engine
from seed import SEED_BETS


def _bets():
    return [{"key": n.lower(), "display_name": n, "side": s, "amount": a} for n, a, s in SEED_BETS]


def test_seeded_book_totals():
    book = engine.effective_book(_bets())
    assert book["pool"] == 65050
    assert book["sides"]["khuseel"]["total"] == 28050
    assert book["sides"]["bansod"]["total"] == 37000
    assert book["sides"]["bansod"]["implied_pct"] == 56.9


@pytest.mark.parametrize("winner", engine.SIDES)
def test_settlement_sums_to_pool(winner):
    s = engine.settle(_bets(), winner)
    assert s["paid_to_bettors"] + s["swimmer_take"] == 65050
    # every winner at least gets their stake back; every loser pays exactly their stake
    for r in s["rows"]:
        if r["side"] == winner:
            assert r["payout"] >= r["stake"]
        else:
            assert r["payout"] == 0 and r["net"] == -r["stake"]


def test_swimmer_take_is_30pct_plus_rounding():
    s = engine.settle(_bets(), "bansod")
    base = int(0.30 * 28050)  # 8415
    assert base <= s["swimmer_take"] < base + len(s["rows"])  # remainder < 1 rupee per winner
    s2 = engine.settle(_bets(), "khuseel")
    assert int(0.30 * 37000) <= s2["swimmer_take"] < 11100 + len(s2["rows"])


def test_known_payouts():
    s = engine.settle(_bets(), "khuseel")
    by = {r["display_name"]: r for r in s["rows"]}
    assert by["Yash"]["payout"] == 5000 + (5000 * 25900) // 28050   # 9616
    assert by["Sarash"]["payout"] == 50 + (50 * 25900) // 28050     # 96
    assert by["Shivam"]["net"] == -5000


def test_no_winner_backers_refunds_70pct():
    bets = [{"key": "a", "display_name": "A", "side": "bansod", "amount": 1000}]
    s = engine.settle(bets, "khuseel")
    assert s["rows"][0]["payout"] == 700
    assert s["swimmer_take"] == 300
    assert s["paid_to_bettors"] + s["swimmer_take"] == 1000


def test_can_submit_rules():
    ok, _ = engine.can_submit("prerace", "khuseel", 500)
    assert ok
    # switching sides allowed pre-race, blocked once racing
    assert engine.can_submit("prerace", "khuseel", 500, current_side="bansod")[0]
    assert engine.can_submit("break1", "khuseel", 500, current_side="bansod") == (False, "no_side_switch")
    # raises on same side fine in break1
    assert engine.can_submit("break1", "khuseel", 500, current_side="khuseel")[0]
    # book closed everywhere else
    for phase in ("lap1", "lap2", "break2", "lap3", "finished", "settled"):
        assert engine.can_submit(phase, "khuseel", 500) == (False, "book_closed")
    assert engine.can_submit("prerace", "khuseel", 0) == (False, "bad_amount")
    assert engine.can_submit("prerace", "khuseel", "5000") == (False, "bad_amount")


def test_phase_machine_best_of_3():
    assert engine.next_phase_on_start_lap("prerace") == "lap1"
    laps = [{"lap": 1, "winner": "bansod", "time_s": 22.4}]
    assert engine.next_phase_on_lap_result("lap1", laps) == "break1"
    # 2-0 sweep ends it at lap 2
    laps2 = laps + [{"lap": 2, "winner": "bansod", "time_s": 23.0}]
    assert engine.next_phase_on_lap_result("lap2", laps2) == "finished"
    assert engine.race_winner(laps2) == "bansod"
    # 1-1 goes to a decider
    laps_split = laps + [{"lap": 2, "winner": "khuseel", "time_s": 22.1}]
    assert engine.next_phase_on_lap_result("lap2", laps_split) == "break2"
    assert engine.race_winner(laps_split) is None
    laps3 = laps_split + [{"lap": 3, "winner": "khuseel", "time_s": 22.9}]
    assert engine.next_phase_on_lap_result("lap3", laps3) == "finished"
    assert engine.race_winner(laps3) == "khuseel"
    with pytest.raises(ValueError):
        engine.next_phase_on_start_lap("lap1")
    with pytest.raises(ValueError):
        engine.next_phase_on_lap_result("break1", laps)
