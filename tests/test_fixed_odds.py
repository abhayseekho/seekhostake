"""Fixed-odds mode: quotes are probability-priced and UNCAPPED (Abhay, 2026-09-25), the fixed book
accounts for every rupee, and it never disturbs the parimutuel (pool) book. The old liability cap
shortened a longshot's price until it collapsed to 1.00× — a bet with zero upside quoted beneath a
1.13× favourite — so pricing is now a function of probability alone; the house carries the exposure
and reads it live off fixed_house_floor."""
import random
import pytest
import engine as E

MARKETS_OUTCOMES = {m["id"]: [o for o, _ in m["outcomes"]] for m in E.MARKETS}


def _replay_fixed(seq):
    """Turn a sequence of (market, outcome, stake) into locked fixed bets exactly the way the store
    does: each bet is priced by fixed_offer_odds against the fixed book accumulated so far."""
    by_market = {}
    pool = {}
    liab = {}
    for i, (mid, outcome, stake) in enumerate(seq):
        p0 = pool.get(mid, 0)
        l0 = liab.get((mid, outcome), 0.0)
        odds = E.fixed_offer_odds(mid, outcome, stake, p0, l0)
        by_market.setdefault(mid, []).append(
            {"key": f"p{i}", "display_name": f"P{i}", "outcome": outcome,
             "amount": stake, "locked_odds": odds})
        pool[mid] = p0 + stake
        liab[(mid, outcome)] = l0 + stake * odds
    return by_market


@pytest.mark.parametrize("seed", range(60))
def test_fixed_book_conserves_and_never_quotes_a_dead_price(seed):
    rng = random.Random(seed)
    n = rng.randint(0, 25)
    seq = []
    for _ in range(n):
        mid = rng.choice(list(MARKETS_OUTCOMES))
        outcome = rng.choice(MARKETS_OUTCOMES[mid])
        stake = rng.choice([500, 1000, 2500, 5000, 20000, 100000])
        seq.append((mid, outcome, stake))
    book = _replay_fixed(seq)

    # No matter how lopsided the book gets, every locked price is a real one: a winning bet always
    # returns more than its stake. This is what the capped pricer violated (it could lock 1.00×).
    for bets in book.values():
        for b in bets:
            assert b["locked_odds"] >= 1.05, (seed, b)

    for script in E.race_scripts():
        for mid, bets in book.items():
            f = E.settle_market_fixed(mid, bets, script)
            # conservation on the fixed book: every rupee is a payout or house take, exactly.
            paid = sum(r["payout"] for r in f["rows"])
            assert paid + f["house"] == f["pool"]


@pytest.mark.parametrize("seed", range(30))
def test_settle_all_conserves_with_mixed_books(seed):
    """A market holding BOTH pool bets and fixed bets still accounts for every rupee, and the pool
    sub-book's house stays >= 0 (its own guarantee) while only the fixed sub-book may go negative."""
    rng = random.Random(seed)

    def rand_leg():
        mid = rng.choice(list(MARKETS_OUTCOMES))
        return (mid, rng.choice(MARKETS_OUTCOMES[mid]), rng.choice([500, 5000, 20000]))

    book = _replay_fixed([rand_leg() for _ in range(rng.randint(0, 10))])
    # add plain pool bets (no locked_odds) into some of the same markets
    for _ in range(rng.randint(1, 12)):
        mid, outcome, stake = rand_leg()
        book.setdefault(mid, []).append(
            {"key": f"pool{rng.random()}", "display_name": "Pool", "outcome": outcome, "amount": stake})
    if not book:
        return

    for script in E.race_scripts():
        res = E.settle_all(book, script)
        # global conservation (same identity settle_all already asserts internally, re-checked here)
        total_pool = sum(m["pool"] for m in res["markets"])
        paid = sum(p["payout"] for p in res["aggregate"])
        assert paid + res["swimmer_take"] + res["house_take"] == total_pool


def test_fixed_bets_do_not_disturb_pool_settlement():
    """Pool bettors are paid identically whether or not fixed bets share their market — the two
    books are independent, so adding a fixed book can never change a pool bettor's payout."""
    laps = [{"lap": 1, "winner": "khuseel", "time_s": None},
            {"lap": 2, "winner": "khuseel", "time_s": None}]
    pool_only = {"match": [
        {"key": "a", "display_name": "A", "outcome": "khuseel", "amount": 3000},
        {"key": "b", "display_name": "B", "outcome": "bansod", "amount": 5000}]}
    mixed = {"match": pool_only["match"] + [
        {"key": "f1", "display_name": "F1", "outcome": "khuseel", "amount": 2000, "locked_odds": 2.5},
        {"key": "f2", "display_name": "F2", "outcome": "bansod", "amount": 1000, "locked_odds": 1.3}]}

    a_pool = next(r for r in E.settle_all(pool_only, laps)["markets"][0]["rows"] if r["key"] == "a")
    a_mixed = next(r for r in E.settle_all(mixed, laps)["markets"][0]["rows"] if r["key"] == "a")
    assert a_pool["payout"] == a_mixed["payout"]  # fixed book is invisible to the pool bettor


def test_pool_house_floor_ignores_fixed_bets():
    """house_floor (the seed-guard / breaker number) must count pool bets only, so the presence of
    fixed bets — which can legitimately push the house negative — never trips those pool guards."""
    laps = ()
    fixed_heavy = {"match": [
        {"key": "seed", "display_name": "S", "outcome": "bansod", "amount": 3000},  # pool
        {"key": "f", "display_name": "F", "outcome": "khuseel", "amount": 5000, "locked_odds": 6.0}]}
    # pool floor sees only the ₹3000 pool bet → cannot be negative
    assert E.house_floor(fixed_heavy, laps) >= 0
    # fixed floor sees the exposed fixed bet → negative (unbounded, by design)
    assert E.fixed_house_floor(fixed_heavy, laps) <= 0


def test_board_is_bansod_tilted():
    """Sanity on the priced board: Bansod (the favourite) is short, Khuseel (the dog) is long."""
    assert E.fixed_base_odds("match", "bansod") < 1.3
    assert E.fixed_base_odds("match", "khuseel") > 4.0
    assert E.fixed_base_odds("match", "bansod") < E.fixed_base_odds("match", "khuseel")


def test_demand_weighting_blends_read_with_money():
    """80% the organiser's read, 20% the money. With money piled on Bansod, Bansod's blended prob
    rises above the 80% read → its odds shorten; Khuseel's lengthen. No money → pure read."""
    # pure read (no money) — anchored to the 80% call
    assert E.fixed_base_odds("match", "bansod") == E.fixed_base_odds("match", "bansod", None)
    read_bansod = E.fixed_base_odds("match", "bansod")
    # money almost entirely on Bansod pulls the blend toward Bansod → shorter Bansod odds
    heavy_bansod = {"bansod": 90000, "khuseel": 10000}
    assert E.fixed_base_odds("match", "bansod", heavy_bansod) < read_bansod
    assert E.fixed_base_odds("match", "khuseel", heavy_bansod) > E.fixed_base_odds("match", "khuseel")
    # the blend is exactly FIXED_PRIOR_WEIGHT·read + (1-w)·moneyshare
    p = E.fixed_blended_prob("match", "bansod", heavy_bansod)
    assert abs(p - (E.FIXED_PRIOR_WEIGHT * 0.80 + (1 - E.FIXED_PRIOR_WEIGHT) * 0.90)) < 1e-9


def test_long_shots_differentiate_under_the_higher_fixed_cap():
    """The two Khuseel scores used to both flatten at the 7x parimutuel cap; under FIXED_MAX_ODDS
    they price distinctly (2–0 rarer than 2–1, so it pays more)."""
    k20 = E.fixed_base_odds("score", "k20")
    k21 = E.fixed_base_odds("score", "k21")
    assert k20 > k21 > 1.0
    assert k20 <= E.FIXED_MAX_ODDS


def test_offer_odds_are_stable_as_a_side_fills():
    """Uncapped pricing: a loaded outcome is quoted exactly like an empty one. The regression this
    locks down is the live board showing Khuseel (a 20% shot) at 1.00× while Bansod (80%) sat at
    1.13× — the favourite quoted LONGER than the underdog, purely because Khuseel's side had
    filled and the old cap shortened his price into the floor."""
    empty = E.fixed_offer_odds("match", "khuseel", 5000, 0, 0)
    loaded = E.fixed_offer_odds("match", "khuseel", 5000, 5000, 20000)
    swamped = E.fixed_offer_odds("match", "khuseel", 5000, 500_000, 2_000_000)
    assert empty == loaded == swamped == E.fixed_base_odds("match", "khuseel")
    # the ordering that was inverted on the live board now always holds
    assert E.fixed_offer_odds("match", "bansod", 5000, 500_000, 0) < loaded


def test_favourite_is_never_quoted_longer_than_the_underdog():
    """The live symptom, asserted directly across every two-way market and any money split: the
    side the read favours must always be the shorter price."""
    for mid in ("match", "lap1", "lap2", "lap3"):
        for money in (None, {"khuseel": 31050, "bansod": 32000},
                      {"khuseel": 100000, "bansod": 500}, {"khuseel": 500, "bansod": 100000}):
            k = E.fixed_offer_odds(mid, "khuseel", 500, 999_999, 9_999_999, money_by_outcome=money)
            b = E.fixed_offer_odds(mid, "bansod", 500, 999_999, 0, money_by_outcome=money)
            assert b < k, (mid, money, b, k)
            assert min(b, k) >= 1.05
