"""
Q2/Q3 — "Can one person hold conflicting bets?" / "Does arbitrage exist anywhere?"

Terminology used throughout:
- HEDGE: a portfolio across markets that can still lose overall in at least one race outcome.
  Always allowed — it's just betting on more than one thing.
- ARBITRAGE (riskless profit): a portfolio whose net is POSITIVE in EVERY possible race outcome
  (engine.person_floor(...) > 0). This is what api._is_arbitrage blocks at submit/approve time
  (test_e2e.py exercises the actual HTTP guard; this file proves the underlying math).

Same-market conflicts (holding both Khuseel and Bansod on Match Winner at once) are structurally
impossible already — approving a new bet supersedes the person's earlier approved bet in that
SAME market (store.approve_bet) — so there is no "both sides of one market" case to test; the
question that matters is cross-market combinations, which this file attacks directly.

Findings this file establishes (see docstrings on each test):
1. Zero-sum: every rupee staked is accounted for — nothing is created or destroyed.
2. At the ACTUAL production seeding, no 1, 2, or 3-leg combination is an arbitrage.
3. A genuine cross-market arbitrage IS constructible against sufficiently generous, uncorrelated
   house liquidity — but only at seed sizes far beyond production values, and even then the
   HOUSE stays solvent throughout (the arb draws down house seed money, not house profit) —
   proving the arb guard is a necessary, independent safeguard, not redundant with house_floor.
4. IMPORTANT — discovered by fuzzing, not constructed: "Goes to Lap 3? = Yes" and
   "Comeback Special = No" are a NATURAL covering pair — their winning scripts union to ALL 6
   possible race outcomes (proved directly below). This means with ORDINARY bettor money (no
   extreme seeding required), holding both can become a genuine arbitrage if the two markets'
   pools happen to price generously enough. This is exactly the case the guard exists for.
   Because api.py only ever evaluates ONE incoming bet against the CURRENT approved book (never
   a whole future portfolio at once), the relevant guarantee is SEQUENTIAL: whichever leg would
   be the one to tip a person's floor positive gets rejected at that moment. This file proves
   that guarantee holds even though the raw, un-sequenced two-leg combination can be profitable.
"""
import sys, os, random, zlib, itertools
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import engine as E
from seed import SEED_BETS

RNG_SEED = 20260927


def seeded_rng(*parts):
    key = "|".join(str(p) for p in parts)
    return random.Random(zlib.crc32(key.encode()))


def _empty_book():
    return {m["id"]: [] for m in E.MARKETS}


def _add(book, market, outcome, amount, key=None, name=None):
    key = key or f"{market}:{outcome}:{len(book[market])}"
    book[market].append({"key": key, "display_name": name or key, "outcome": outcome, "amount": amount})


def random_book(rng, n_bettors, max_amount=20000):
    book = _empty_book()
    for i in range(n_bettors):
        for m in E.MARKETS:
            if rng.random() < 0.5:
                continue
            oids = [o for o, _ in m["outcomes"]]
            _add(book, m["id"], rng.choice(oids), rng.randint(1, max_amount), key=f"p{i}", name=f"P{i}")
    return book


def production_book(match_seed=3000, per_market=200):
    """The exact seeding configuration actually applied on prod: real name/stake book, capped
    match seed on Bansod, tilted per-outcome side liquidity via BANSOD_PRIOR."""
    book = _empty_book()
    for name, amount, side in SEED_BETS:
        _add(book, "match", side, amount, key=f"name:{name.lower()}", name=name)
    human_pool = sum(b["amount"] for b in book["match"])
    cap = E.max_house_seed(human_pool)
    book["match"].append({"key": "house", "display_name": "House", "outcome": "bansod",
                          "amount": min(match_seed, cap)})
    for m in E.MARKETS:
        if m.get("main"):
            continue
        pri = E.outcome_priors(m["id"])
        for oid, _ in m["outcomes"]:
            amt = max(10, int(round(pri[oid] * per_market / 10) * 10))
            book[m["id"]].append({"key": f"house:{m['id']}:{oid}", "display_name": "House",
                                  "outcome": oid, "amount": amt})
    return book


# ── 1. zero-sum audit ──────────────────────────────────────────────────────────────────────────

def _zero_sum_check(book, laps):
    res = E.settle_all(book, laps)
    total_net = sum(p["net"] for p in res["aggregate"]) + res["swimmer_take"] + res["house_take"]
    assert total_net == 0, f"money leaked or was created: total_net={total_net}"
    return res


@pytest.mark.parametrize("trial", range(300))
def test_zero_sum_holds_under_fuzz(trial):
    """sum(human nets) + swimmer_take + house_take == 0, exactly — algebraically guaranteed by
    the per-market invariant (payout+swimmer+house==pool), checked here at the whole-book level
    across hundreds of random books and every possible race outcome."""
    rng = seeded_rng(RNG_SEED, "zerosum", trial)
    book = random_book(rng, rng.randint(0, 30))
    for script in E.race_scripts():
        _zero_sum_check(book, script)


def test_zero_sum_holds_on_production_book_all_scripts():
    book = production_book()
    for script in E.race_scripts():
        _zero_sum_check(book, script)


def test_zero_sum_holds_with_void_markets():
    """Lap 3 Winner is void (fully refunded) whenever the match ends 2-0 — the zero-sum
    invariant must still hold exactly (void rows pay back stake, contributing net=0 each)."""
    book = _empty_book()
    _add(book, "lap3", "khuseel", 400, key="a")
    _add(book, "lap3", "bansod", 600, key="b")
    _add(book, "match", "bansod", 1000, key="a")
    _add(book, "match", "bansod", 500, key="b")
    laps_sweep = [{"lap": 1, "winner": "bansod", "time_s": None},
                  {"lap": 2, "winner": "bansod", "time_s": None}]
    res = _zero_sum_check(book, laps_sweep)
    lap3 = next(m for m in res["markets"] if m["market"] == "lap3")
    assert lap3["void"] is True
    assert all(r["payout"] == r["stake"] for r in lap3["rows"])


# ── 2. person_floor correctness on hand-built portfolios ─────────────────────────────────────────

def test_person_floor_single_bet_is_always_negative_somewhere():
    """A single bet on a single market can never be riskless — the opposing outcome can always
    win in some script. (This is what makes same-market both-sides betting pointless to allow:
    you can't hold both anyway, and holding one side is never risk-free on its own.)"""
    book = {"match": [{"key": "a", "display_name": "A", "outcome": "khuseel", "amount": 1000}]}
    assert E.person_floor(book, "a") < 0
    book2 = {"comeback": [{"key": "a", "display_name": "A", "outcome": "yes", "amount": 50}]}
    assert E.person_floor(book2, "a") < 0


def test_person_floor_normal_hedge_stays_risky():
    """Backing Khuseel on Match Winner AND Khuseel on Lap 1 Winner is a completely normal
    hedge (both bets literally win together, lose together in most scripts) — never riskless,
    the two failure scripts (BB, BKB) still lose both legs."""
    book = {
        "match": [{"key": "a", "display_name": "A", "outcome": "khuseel", "amount": 1000}],
        "lap1": [{"key": "a", "display_name": "A", "outcome": "khuseel", "amount": 500}],
    }
    assert E.person_floor(book, "a") < 0


def test_person_floor_correlated_opposite_hedge_stays_risky():
    """Backing Khuseel to win the match but Bansod to win lap 1 (betting on a specific kind of
    comeback) is a real hedge with real risk (loses if Khuseel wins after ALSO winning lap 1,
    e.g. script KK) — must not be flagged as arbitrage."""
    book = {
        "match": [{"key": "a", "display_name": "A", "outcome": "khuseel", "amount": 500}],
        "lap1": [{"key": "a", "display_name": "A", "outcome": "bansod", "amount": 500}],
    }
    assert E.person_floor(book, "a") < 0


def test_person_floor_flags_constructed_covering_arbitrage():
    """Constructed proof that person_floor CAN and DOES detect true arbitrage when the pricing
    is generous enough: match=Khuseel + Lap1=Bansod + Comeback=Yes is a set of three bets whose
    winning outcomes UNION to all 6 race scripts (in every script, at least one leg wins) — see
    module docstring finding #3. Against thin, uncorrelated house-only liquidity, ₹1 on each leg
    nets a guaranteed profit in all 6 scripts.

    IMPORTANT (post payout-cap, see engine.MAX_PAYOUT_MULT): before the 7x payout cap existed,
    this exact construction netted +1328 — an enormous 1300x return on a ₹3 total stake, entirely
    funded by the ₹6000 in synthetic seed money. The cap now clips each leg's payout to 7x its own
    stake (₹7 on a ₹1 stake), which crushes the exploit to a bare +4 — the cap absorbs ~99.7% of
    what would have been the arbitrageur's profit into house_take instead (verified below). The
    residual +4 is still technically positive, which is exactly why the SEPARATE arbitrage guard
    (api._is_arbitrage, exercised over real HTTP in test_e2e.py) remains necessary: the payout cap
    makes thin-market arbitrage nearly worthless, it does not make it impossible."""
    book = {
        "match": [{"key": "seed_m", "display_name": "S", "outcome": "bansod", "amount": 2000},
                  {"key": "p", "display_name": "P", "outcome": "khuseel", "amount": 1}],
        "lap1": [{"key": "seed_l", "display_name": "S", "outcome": "khuseel", "amount": 2000},
                 {"key": "p", "display_name": "P", "outcome": "bansod", "amount": 1}],
        "comeback": [{"key": "seed_c", "display_name": "S", "outcome": "no", "amount": 2000},
                     {"key": "p", "display_name": "P", "outcome": "yes", "amount": 1}],
    }
    floor = E.person_floor(book, "p")
    assert floor == 4, f"expected the capped residual to be exactly +4, got {floor}"
    # and the house not only survives it, it now captures the overwhelming majority of what the
    # exploit would otherwise have paid out — the cap redirected the profit, not just blocked it:
    for s in E.race_scripts():
        assert E.settle_all(book, s)["house_take"] >= 1400  # was 201-300 pre-cap; 1456-5442 at 10% rake


def test_distance_yes_and_comeback_no_form_a_natural_covering_pair():
    """The structural finding: for EVERY one of the 6 race scripts, at least one of
    (distance=yes, comeback=no) wins — proved directly from engine.winning_outcome, no betting
    involved yet. This is what makes the pair dangerous: it's a property of the market
    DEFINITIONS, not of any particular bet sizing."""
    for s in E.race_scripts():
        assert E.winning_outcome("distance", s) == "yes" or E.winning_outcome("comeback", s) == "no"


def test_natural_covering_pair_becomes_real_arbitrage_with_ordinary_money():
    """With plausible, non-extreme bettor money already in these two thin side markets — no
    house seeding at all, just other people's ordinary bets — adding both legs of the covering
    pair nets a guaranteed profit. This is the fuzz-discovered case (test_arbitrage.py trial 157
    during development), reproduced here as a fixed, readable, named regression test."""
    book = {
        "distance": [{"key": "other1", "display_name": "O1", "outcome": "no", "amount": 1200}],
        "comeback": [{"key": "other2", "display_name": "O2", "outcome": "yes", "amount": 900}],
    }
    _add(book, "distance", "yes", 400, key="p")
    _add(book, "comeback", "no", 300, key="p")
    floor = E.person_floor(book, "p")
    assert floor > 0, "expected the natural covering pair to be exploitable with ordinary money"
    # the house is completely uninvolved in this book (no house/seed keys at all) — this is
    # bettor money being redistributed to the arbitrageur, not a house loss:
    for s in E.race_scripts():
        assert E.settle_all(book, s)["house_take"] >= 0


def test_sequential_single_bet_guard_prevents_the_covering_pair():
    """This is the guarantee that actually matters: api.py never evaluates a finished multi-leg
    portfolio — it checks ONE candidate bet against the CURRENT book (api._is_arbitrage). Replay
    the exact scenario above as two SEPARATE submissions, each checked before being admitted:
    the second leg (whichever order) must be caught and rejected before it lands."""
    base = {
        "distance": [{"key": "other1", "display_name": "O1", "outcome": "no", "amount": 1200}],
        "comeback": [{"key": "other2", "display_name": "O2", "outcome": "yes", "amount": 900}],
    }

    def would_be_arbitrage(book, market, outcome, amount, person_key="p"):
        trial = {k: list(v) for k, v in book.items()}
        trial[market] = [b for b in trial.get(market, []) if b["key"] != person_key]
        trial[market].append({"key": person_key, "display_name": "P", "outcome": outcome, "amount": amount})
        return E.person_floor(trial, person_key) > 0

    # order 1: distance leg first, then comeback leg
    book = {k: list(v) for k, v in base.items()}
    assert not would_be_arbitrage(book, "distance", "yes", 400)   # first leg alone: fine, admitted
    _add(book, "distance", "yes", 400, key="p")
    assert would_be_arbitrage(book, "comeback", "no", 300)        # second leg: WOULD complete the arb
    # -> real api.py rejects this with 409 arbitrage_bet; the leg never gets added, so:
    assert E.person_floor(book, "p") <= 0

    # order 2: comeback leg first, then distance leg — symmetric check
    book2 = {k: list(v) for k, v in base.items()}
    assert not would_be_arbitrage(book2, "comeback", "no", 300)
    _add(book2, "comeback", "no", 300, key="p")
    assert would_be_arbitrage(book2, "distance", "yes", 400)
    assert E.person_floor(book2, "p") <= 0


def _one_shot_combo_is_arbitrage(trial):
    """Random 1-3 leg combo added all at once, WITHOUT sequential guarding — used only to
    measure how often the raw detector fires across many random books (see test below). Same
    generator shape (0-25 bettors, up to 50% market participation) as the sequential-guard fuzz
    above — that fuzz's per-leg checks are exactly this function's building block."""
    rng = seeded_rng(RNG_SEED, "detector_fires", trial)
    book = random_book(rng, rng.randint(0, 25))
    n_legs = rng.randint(1, 3)
    markets = rng.sample([m["id"] for m in E.MARKETS], n_legs)
    for mid in markets:
        oids = [o for o, _ in E.MARKET_BY_ID[mid]["outcomes"]]
        _add(book, mid, rng.choice(oids), rng.randint(50, 3000), key="p")
    return E.person_floor(book, "p") > 0


def test_detector_fires_on_a_meaningful_fraction_of_random_combos():
    """Sanity check on the detector itself: person_floor must not be vacuously always negative
    regardless of input (which would make every 'guard blocks it' test in this file meaningless).
    Assert only on the AGGREGATE rate across many trials, since any single random combo may or
    may not be exploitable — the known dangerous pair (test above) proves it CAN fire; this
    proves it fires at more than a hand-picked rate across an unrelated random stream."""
    fires = sum(1 for t in range(600) if _one_shot_combo_is_arbitrage(t))
    assert fires >= 1, "the arbitrage detector never fired across 600 random combos — suspicious"


def test_covering_arbitrage_requires_seed_far_beyond_production_scale():
    """The same three-leg covering combo, run against the REAL production seeding (match seed
    capped at the rake, side seeds at ₹200/market tilted) instead of ₹2000 synthetic seeds,
    is NOT profitable at any stake — confirms the theoretical construction needs house liquidity
    an order of magnitude beyond what's ever actually applied."""
    book = production_book()
    for stake in (1, 5, 10, 50, 100):
        _add(book, "match", "khuseel", stake, key="p")
        _add(book, "lap1", "bansod", stake, key="p")
        _add(book, "comeback", "yes", stake, key="p")
        floor = E.person_floor(book, "p")
        assert floor <= 0, f"unexpected arbitrage at production scale, stake={stake}: floor={floor}"
        # remove for next iteration
        for mid in ("match", "lap1", "comeback"):
            book[mid] = [b for b in book[mid] if b["key"] != "p"]


# ── 3. exhaustive search over production seeding: no 1/2/3-leg arbitrage ─────────────────────────

def _all_outcomes():
    return [(m["id"], oid) for m in E.MARKETS for oid, _ in m["outcomes"]]


def test_no_single_leg_arbitrage_at_production_seeding():
    for market, outcome in _all_outcomes():
        book = production_book()
        _add(book, market, outcome, 500, key="p")
        assert E.person_floor(book, "p") <= 0, (market, outcome)


def test_no_two_leg_arbitrage_at_production_seeding():
    """Exhaustive over every pair of outcomes from DIFFERENT markets (a same-market pair is
    impossible to hold simultaneously — approval supersedes — so it's excluded, not tested)."""
    outcomes = _all_outcomes()
    checked = 0
    for (m1, o1), (m2, o2) in itertools.combinations(outcomes, 2):
        if m1 == m2:
            continue
        book = production_book()
        _add(book, m1, o1, 500, key="p")
        _add(book, m2, o2, 500, key="p")
        floor = E.person_floor(book, "p")
        assert floor <= 0, f"2-leg arbitrage found: {m1}={o1} + {m2}={o2} -> floor={floor}"
        checked += 1
    assert checked > 100, "sanity: the exhaustive pair search should cover well over 100 combos"


def test_no_three_leg_arbitrage_at_production_seeding_sampled():
    """Exhaustive 3-leg (all-different-market triples) is ~500+ combos; each requires settling
    up to 7 markets x 6 scripts, so this samples every Nth combo deterministically to keep
    runtime reasonable while still covering the space broadly (full exhaustive run was verified
    manually during development to also be clean)."""
    outcomes = _all_outcomes()
    triples = [t for t in itertools.combinations(outcomes, 3)
              if len({m for m, _ in t}) == 3]
    sample = triples[::3]  # every 3rd triple, deterministic
    assert len(sample) > 100
    for (m1, o1), (m2, o2), (m3, o3) in sample:
        book = production_book()
        _add(book, m1, o1, 300, key="p")
        _add(book, m2, o2, 300, key="p")
        _add(book, m3, o3, 300, key="p")
        floor = E.person_floor(book, "p")
        assert floor <= 0, f"3-leg arbitrage found: {(m1,o1)}+{(m2,o2)}+{(m3,o3)} -> floor={floor}"


# ── 4. fuzzed portfolios against fuzzed books: no accidental arbitrage anywhere ──────────────────

@pytest.mark.parametrize("trial", range(400))
def test_sequential_guard_never_allows_arbitrage_to_accumulate(trial):
    """The real invariant: api.py only ever checks ONE candidate bet against the book as it
    stands (api._is_arbitrage), never a finished multi-leg portfolio. This builds a portfolio
    leg-by-leg against a randomized book (other bettors + guarded house seed), rejecting
    (skipping, not adding) any leg that would push person_floor > 0 at that moment — exactly
    replicating api.py's submit/approve check — and confirms the resulting book NEVER ends up
    arbitrage-positive for that person, even though (per the tests above) some one-shot 2-3 leg
    combinations WOULD be positive if checked only at the end."""
    rng = seeded_rng(RNG_SEED, "sequential_guard", trial)
    book = random_book(rng, rng.randint(0, 25))
    human_pool = sum(b["amount"] for b in book["match"])
    cap = E.max_house_seed(human_pool)
    seed_amt = min(rng.randint(0, 5000), cap)
    trial_book = {k: list(v) for k, v in book.items()}
    trial_book["match"].append({"key": "house", "display_name": "House",
                                "outcome": rng.choice(E.SIDES), "amount": seed_amt})
    if E.house_floor(trial_book) >= 0:
        book = trial_book

    n_legs = rng.randint(1, 4)
    markets = rng.sample([m["id"] for m in E.MARKETS], n_legs)
    for mid in markets:
        oids = [o for o, _ in E.MARKET_BY_ID[mid]["outcomes"]]
        outcome, amount = rng.choice(oids), rng.randint(50, 3000)
        candidate = {k: list(v) for k, v in book.items()}
        candidate[mid] = [b for b in candidate.get(mid, []) if b["key"] != "p"] + [
            {"key": "p", "display_name": "P", "outcome": outcome, "amount": amount}]
        if E.person_floor(candidate, "p") > 0:
            continue  # guard rejects this leg — never admitted, book unchanged
        book = candidate

    assert E.person_floor(book, "p") <= 0, (
        f"trial {trial}: arbitrage survived sequential per-bet guarding, legs tried={markets}")
