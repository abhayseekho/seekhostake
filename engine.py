"""
engine.py — pure betting logic for the Khuseel vs Bansod parimutuel pools. No I/O, no DB.

House rules (ratified with Abhay, 2026-09-15):
- Multiple parimutuel MARKETS, each its own pool. 10% house rake on every market.
- MAIN market (match winner) additionally: 30% of the post-rake losing pot to the winning
  swimmer, 70% to winning bettors; and the house may hold a visible seed bet ("House"),
  capped at the expected rake so the organiser can never go net negative.
- Side markets: winners share the post-rake pool pro-rata. Voided markets refund in full.
- Latest APPROVED bet per person PER MARKET is binding.
- All betting closes when lap 2 starts. Match-winner side-switching is pre-race only.
- Settlement asserts every market's payouts + house take sum exactly to its pool.
"""

import re

SIDES = ("khuseel", "bansod")
SWIMMER_CUT = 0.30
HOUSE_RAKE = 0.10  # organiser's cut on the parimutuel (pool) book; odds/payouts derive from this

# Payout cap: a thin market (a few hundred rupees on one side) can hand a single winning bet a
# huge multiplier if the OTHER side is imbalanced enough (e.g. one large bet lands against thin
# opposing liquidity). No single stake may return more than this multiple of itself; whatever
# the uncapped parimutuel math would have paid beyond the cap becomes house profit instead —
# it falls out of the existing `house = pool - paid - swimmer` formula automatically, so the
# per-market sum-to-pool invariant holds without any extra bookkeeping. Applied identically to
# the live indicative odds (market_book) and the final settlement (settle_market) so a bettor
# never sees a displayed multiplier the actual payout won't honor.
MAX_PAYOUT_MULT = 7

# Circuit breaker: a thin market (a few hundred rupees of liquidity) can have its odds swung
# 5-10x by a single realistically-sized bet — correct parimutuel math, but too volatile to leave
# unattended. If one approval moves ANY outcome's multiplier by more than this ratio (in either
# direction), the market auto-suspends for admin review; the triggering bet still goes through.
VOLATILITY_SUSPEND_RATIO = 2.0

# Fat-finger/abuse guard, not a financial-safety mechanism — the payout cap and house_floor guard
# already make any single stake financially safe regardless of size. This just stops a typo'd
# extra zero (or a malicious huge number) from ever reaching the pool: ~16x the entire real
# pre-race book (₹60,050), so it can never bind on a legitimate bet.
MAX_BET_AMOUNT = 1_000_000

# Business rule (Abhay): ₹500 minimum per portal bet — keeps cash collection worth the organiser's
# time and each request meaningfully sized. Applies to bettor self-service submission only (the
# admin's manual-entry/reconciliation tool has its own, separate validation — amount=0 there means
# "void", not "too small", and cash-reconciliation corrections shouldn't be blocked by this floor).
MIN_BET_AMOUNT = 500

# ── Fixed-odds mode ────────────────────────────────────────────────────────────────────────────
# Optional per-bet FIXED odds that live ALONGSIDE the parimutuel pool (see settle_all): a bet is
# "fixed" iff it carries a locked_odds value; every other bet stays a pool bet and settles exactly
# as before. Fixed bets are priced from win-probability (Bansod-tilted, the organiser's read) with
# a house margin. Unlike the parimutuel book (house strictly ≥ 0), the fixed book lets the house
# lose, and since 2026-09-25 (Abhay) that loss is UNCAPPED: every bet is quoted at the board price
# regardless of how much money has already loaded the outcome.
#
# The previous liability cap shortened the offered odds as a side filled, which on a longshot hit a
# wall almost immediately: Khuseel prices at 4.50×, so ~₹2,800 of Khuseel money exhausted a ₹10,000
# cap and the pricer collapsed his quote to 1.00× — a bet with zero upside and full downside, shown
# on the board underneath a favourite quoted at 1.13×. Uncapped pricing is the organiser's deliberate
# choice to run a real book: the underdog stays honestly priced, and the house carries the exposure.
# `fixed_house_floor` reports that exposure live on the admin panel; it is now unbounded, so watch it.
FIXED_ODDS_MARGIN = 0.10       # house edge (overround) baked into every quoted price — the house's 10% cut
MATCH_BANSOD_PRIOR = 0.80      # organiser's read: Bansod wins the MATCH 80% of the time
FIXED_PER_LAP_BANSOD = 0.715   # per-lap Bansod prob that yields ≈80% match (p²·(3−2p) ≈ 0.80),
                               # used to price the lap / score / distance / comeback markets coherently
# Odds = a blend of the organiser's probability read and the crowd's money: FIXED_PRIOR_WEIGHT to the
# read, the rest to the observed money split on that market. So the board mostly reflects the 80%
# call but drifts toward whichever side the money actually lands on.
FIXED_PRIOR_WEIGHT = 0.80      # 80% the read, 20% the money placed
# Display/offer ceiling for fixed odds. Higher than the parimutuel MAX_PAYOUT_MULT so genuine
# long-shots (e.g. Khuseel 2–0) price distinctly instead of all flattening at the cap. Nothing
# protects the house behind this now — this ceiling IS the per-bet risk limit, so a winning fixed
# bet can cost at most 15× its stake.
FIXED_MAX_ODDS = 15

PHASES = ("prerace", "lap1", "break1", "lap2", "break2", "lap3", "finished", "settled")
OPEN_PHASES = ("prerace", "break1")  # any betting at all

YES_NO = (("yes", "Yes"), ("no", "No"))
K_B = (("khuseel", "Khuseel"), ("bansod", "Bansod"))

# Ordered market definitions. `open_phases` = when bets may be placed; every market is closed
# for good once lap 2 starts (the global rule). `main` marks the swimmer-cut + house-seed market.
MARKETS = (
    {"id": "match",    "name": "Match Winner",   "outcomes": K_B, "open_phases": ("prerace", "break1"),
     "main": True,     "sub": "Best of 3 · first to 2 laps"},
    {"id": "score",    "name": "Correct Score",  "outcomes": (("k20", "Khuseel 2–0"), ("k21", "Khuseel 2–1"),
                                                              ("b20", "Bansod 2–0"), ("b21", "Bansod 2–1")),
     "open_phases": ("prerace", "break1"), "sub": "Final lap score of the match"},
    {"id": "distance", "name": "Goes to Lap 3?", "outcomes": YES_NO, "open_phases": ("prerace", "break1"),
     "sub": "Does the match reach a decider?"},
    {"id": "lap1",     "name": "Lap 1 Winner",   "outcomes": K_B, "open_phases": ("prerace",),
     "sub": "Closes when lap 1 starts"},
    {"id": "lap2",     "name": "Lap 2 Winner",   "outcomes": K_B, "open_phases": ("prerace", "break1"),
     "sub": None},
    {"id": "lap3",     "name": "Lap 3 Winner",   "outcomes": K_B, "open_phases": ("prerace", "break1"),
     "sub": "Refunded if the match ends 2–0"},
    {"id": "comeback", "name": "Comeback Special", "outcomes": YES_NO, "open_phases": ("break1",),
     "sub": "Lap-1 loser wins the match?"},
)
MARKET_IDS = tuple(m["id"] for m in MARKETS)
MARKET_BY_ID = {m["id"]: m for m in MARKETS}


def name_slug(name: str) -> str:
    """Canonical identity key for a typed name: lowercase, everything but a-z0-9 stripped. The
    ONE definition — shared by name-mode login (api.py) and admin manual entry / seed load
    (store.py) — so the same person always keys to the same identity no matter which path
    records them first. (Previously duplicated with a subtly different rule per module: the
    admin/seed path used str.isalnum(), which is also true for non-ASCII letters and digits, so a
    name containing one could have keyed differently there than through name-mode login.)"""
    return "name:" + re.sub(r"[^a-z0-9]", "", name.lower())


# ── race facts ───────────────────────────────────────────────────────────────────────────────────

def lap_wins(laps):
    wins = {s: 0 for s in SIDES}
    for lap in laps:
        wins[lap["winner"]] += 1
    return wins


def race_winner(laps):
    wins = lap_wins(laps)
    for s in SIDES:
        if wins[s] >= 2:
            return s
    return None


def next_phase_on_start_lap(phase):
    transitions = {"prerace": "lap1", "break1": "lap2", "break2": "lap3"}
    if phase not in transitions:
        raise ValueError(f"cannot start a lap from phase {phase!r}")
    return transitions[phase]


def next_phase_on_lap_result(phase, laps_after):
    if phase not in ("lap1", "lap2", "lap3"):
        raise ValueError(f"no lap in progress (phase {phase!r})")
    if race_winner(laps_after):
        return "finished"
    return {"lap1": "break1", "lap2": "break2"}[phase]


def outcome_alive(market_id, outcome, laps):
    """False once the race so far has made this outcome impossible (dead outcomes are
    unbettable; their money stays in the pool for the survivors)."""
    if not laps:
        return True
    if market_id == "score":
        return _score_alive(outcome, laps[0]["winner"])
    if market_id == "lap1":
        return False  # already decided
    return True


def _score_alive(outcome, lap1_winner):
    # after lap 1: the side that lost lap 1 can no longer win 2–0
    dead = "k20" if lap1_winner == "bansod" else "b20"
    return outcome != dead


# ── books & odds ─────────────────────────────────────────────────────────────────────────────────

def market_book(market_id, approved_bets):
    """approved_bets: this market's live rows {"key","display_name","outcome","amount"}.
    Returns per-outcome totals + estimated net-payout multiple per ₹ at the current pool
    (rake and, for the main market, the swimmer cut already reflected)."""
    m = MARKET_BY_ID[market_id]
    totals = {oid: 0 for oid, _ in m["outcomes"]}
    counts = {oid: 0 for oid, _ in m["outcomes"]}
    for b in approved_bets:
        totals[b["outcome"]] += int(b["amount"])
        counts[b["outcome"]] += 1
    pool = sum(totals.values())
    rake = int(HOUSE_RAKE * pool)
    out = {}
    for oid, label in m["outcomes"]:
        w = totals[oid]
        est = None
        if w:
            if m.get("main"):
                lose = pool - w
                est = 1 + (1 - SWIMMER_CUT) * max(lose - rake, 0) / w
            else:
                est = max(pool - rake, w) / w
            est = min(est, MAX_PAYOUT_MULT)
        out[oid] = {"label": label, "total": w, "bettors": counts[oid],
                    "est_mult": round(est, 3) if est else None}
    return {"pool": pool, "outcomes": out}


def odds_swing(market_id, before_book, after_book, laps=()):
    """Largest single-outcome multiplier ratio between two market_book() snapshots of the SAME
    market (before vs after applying one approval). None if either side of an outcome has no
    price yet (nothing to compare — a fresh bet on a previously dead outcome isn't 'volatility').
    Dead outcomes (e.g. the score market's losing-2-0 line after lap 1) are skipped entirely:
    their multiplier drifts as a pure side effect of the pool growing on OTHER outcomes — nobody
    can bet on them to correct it, so that drift is not volatility, it's arithmetic.
    Returns (ratio, outcome_id) for the worst offender, or (1.0, None) if nothing moved."""
    worst, worst_oid = 1.0, None
    for oid, after in after_book["outcomes"].items():
        if not outcome_alive(market_id, oid, list(laps)):
            continue
        before = before_book["outcomes"].get(oid)
        b, a = before and before["est_mult"], after["est_mult"]
        if not b or not a:
            continue
        ratio = max(a / b, b / a)
        if ratio > worst:
            worst, worst_oid = ratio, oid
    return worst, worst_oid


# ── bet validation ───────────────────────────────────────────────────────────────────────────────

def can_submit(market_id, phase, outcome, amount, laps=(), current_outcome=None, suspended=False):
    """Returns (ok, reason)."""
    m = MARKET_BY_ID.get(market_id)
    if not m:
        return False, "bad_market"
    if suspended:
        return False, "market_suspended"
    if phase not in m["open_phases"]:
        return False, "book_closed"
    if outcome not in {oid for oid, _ in m["outcomes"]}:
        return False, "bad_outcome"
    if not isinstance(amount, int) or amount < MIN_BET_AMOUNT or amount > MAX_BET_AMOUNT:
        return False, "bad_amount"
    if not outcome_alive(market_id, outcome, list(laps)):
        return False, "outcome_dead"
    if m.get("main") and current_outcome and current_outcome != outcome and phase != "prerace":
        return False, "no_side_switch"
    return True, ""


# ── settlement ───────────────────────────────────────────────────────────────────────────────────

def winning_outcome(market_id, laps):
    """The market's winning outcome id, or None → market VOID (full refund)."""
    winner = race_winner(laps)
    if market_id == "match":
        return winner
    if market_id == "score":
        loser_laps = len(laps) - 2
        return ("k" if winner == "khuseel" else "b") + f"2{loser_laps}"
    if market_id == "distance":
        return "yes" if len(laps) == 3 else "no"
    if market_id in ("lap1", "lap2", "lap3"):
        n = int(market_id[-1])
        if len(laps) < n:
            return None  # lap never swum → void
        return laps[n - 1]["winner"]
    if market_id == "comeback":
        return "yes" if winner != laps[0]["winner"] else "no"
    raise ValueError(market_id)


def settle_market(market_id, approved_bets, laps):
    """One market's payout rows. House take = rake + rounding remainders (+ seed result on the
    main market, where the house seed is just a bet row with key 'house'). Invariant: payouts
    + swimmer + house == pool, exactly."""
    m = MARKET_BY_ID[market_id]
    pool = sum(int(b["amount"]) for b in approved_bets)
    won = winning_outcome(market_id, laps)
    rows, house, swimmer = [], 0, 0

    labels = dict(m["outcomes"])
    if won is None:  # void → full refund, no rake
        for b in approved_bets:
            rows.append({**_row(b), "payout": int(b["amount"]), "result": "void"})
        return {"market": market_id, "name": m["name"], "won": None, "won_label": None,
                "void": True, "pool": pool, "house": 0, "swimmer": 0, "rows": _net(rows)}

    win_total = sum(int(b["amount"]) for b in approved_bets if b["outcome"] == won)
    lose_total = pool - win_total
    rake = int(HOUSE_RAKE * pool)

    if win_total == 0:
        # nobody backed the winner: rake stays with the house, losers get the rest back pro-rata
        paid = 0
        for b in approved_bets:
            payout = (int(b["amount"]) * (pool - rake)) // pool if pool else 0
            paid += payout
            rows.append({**_row(b), "payout": payout, "result": "refund"})
        house = pool - paid
        return {"market": market_id, "name": m["name"], "won": won, "won_label": labels[won],
                "void": False, "pool": pool, "house": house, "swimmer": 0, "rows": _net(rows)}

    if m.get("main"):
        distributable = lose_total - rake          # losers fund rake first
        swimmer = int(SWIMMER_CUT * max(distributable, 0))
        winners_pot = max(distributable, 0) - swimmer
    else:
        # Floor at 0 so a winner never receives LESS than their stake. On a very lopsided market
        # the losing side may not cover a full rake (pool - win_total < rake); the house then simply
        # takes the smaller rake it can, rather than clawing it out of winners' stakes. This mirrors
        # market_book's displayed est_mult, which already floors at 1.0x via max(pool-rake, w)/w — so
        # settlement can never pay under a multiplier the board showed. (At the old 5% rake this was
        # masked; the 10% rake surfaces it on the thin-opposing-side markets.)
        winners_pot = max(pool - rake - win_total, 0)  # winners also get stakes back below

    paid = 0
    for b in approved_bets:
        stake = int(b["amount"])
        if b["outcome"] == won:
            profit = (stake * winners_pot) // win_total
            payout = min(stake + profit, stake * MAX_PAYOUT_MULT)  # overflow -> house, see top
            result = "won"
        else:
            payout, result = 0, "lost"
        paid += payout
        rows.append({**_row(b), "payout": payout, "result": result})

    house = pool - paid - swimmer  # rake + rounding remainders (+/- house seed rows are in `rows`)
    assert house >= 0 and paid + swimmer + house == pool, f"{market_id}: settlement must sum to pool"
    return {"market": market_id, "name": m["name"], "won": won, "won_label": labels[won],
            "void": False, "pool": pool, "house": house, "swimmer": swimmer, "rows": _net(rows)}


# ── fixed-odds pricing & settlement ──────────────────────────────────────────────────────────────

def fixed_prob(market_id, outcome):
    """Win probability used to PRICE a fixed-odds bet, Bansod-tilted per the organiser's read."""
    if market_id == "match":
        return MATCH_BANSOD_PRIOR if outcome == "bansod" else 1 - MATCH_BANSOD_PRIOR
    return outcome_priors(market_id, FIXED_PER_LAP_BANSOD)[outcome]


def fixed_blended_prob(market_id, outcome, money_by_outcome=None):
    """The probability the price is built on: FIXED_PRIOR_WEIGHT on the organiser's read, the rest
    on the crowd's money split for this market. money_by_outcome = {outcome: ₹ backed} (human money;
    None or all-zero → pure read). This is what makes the board 'give weightage to what people put
    money on' while still anchoring to the 80% call."""
    p_read = fixed_prob(market_id, outcome)
    if not money_by_outcome:
        return p_read
    total = sum(money_by_outcome.values())
    if total <= 0:
        return p_read
    p_money = money_by_outcome.get(outcome, 0) / total
    return FIXED_PRIOR_WEIGHT * p_read + (1 - FIXED_PRIOR_WEIGHT) * p_money


def fixed_base_odds(market_id, outcome, money_by_outcome=None):
    """The board price for an outcome: fair odds from the blended probability with the house
    margin, clamped to [1.05, FIXED_MAX_ODDS]."""
    p = fixed_blended_prob(market_id, outcome, money_by_outcome)
    if p <= 0:
        return FIXED_MAX_ODDS
    return round(max(1.05, min(FIXED_MAX_ODDS, (1 - FIXED_ODDS_MARGIN) / p)), 3)


def fixed_offer_odds(market_id, outcome, stake, fixed_pool_before=0, outcome_liability_before=0,
                     money_by_outcome=None):
    """Odds to LOCK for a new fixed bet of `stake` on `outcome`. Uncapped (see the module header):
    every bet gets the blended board price no matter how the book is loaded, so a quote moves only
    with the organiser's read and the crowd's money — never with the house's own liability, which
    is what inverted the board. The fixed-book arguments are retained so callers need not change
    and so exposure-aware pricing can return later; they do not affect the quote."""
    if stake <= 0:
        return None
    return fixed_base_odds(market_id, outcome, money_by_outcome)


def settle_market_fixed(market_id, fixed_bets, laps):
    """Settle the FIXED sub-book of one market: each winner is paid stake × its own locked_odds;
    losers get nothing; a void market refunds in full. House take = pool − paid (may be NEGATIVE —
    that is the house covering a locked payout, and since pricing is uncapped it is unbounded).
    No rake and no swimmer cut here: the house's edge on fixed bets is the margin already priced in."""
    m = MARKET_BY_ID[market_id]
    pool = sum(int(b["amount"]) for b in fixed_bets)
    won = winning_outcome(market_id, laps)
    rows, paid = [], 0
    if won is None:  # void → full refund
        for b in fixed_bets:
            rows.append({**_row(b), "payout": int(b["amount"]), "result": "void"})
        return {"pool": pool, "house": 0, "rows": _net(rows)}
    for b in fixed_bets:
        stake = int(b["amount"])
        if b["outcome"] == won:
            payout = int(round(stake * float(b["locked_odds"])))
            result = "won"
        else:
            payout, result = 0, "lost"
        paid += payout
        rows.append({**_row(b), "payout": payout, "result": result})
    return {"pool": pool, "house": pool - paid, "rows": _net(rows)}


def _is_fixed(b):
    return b.get("locked_odds") not in (None, "", 0)


def _split_book(bets):
    """Partition one market's bets into (pool_bets, fixed_bets). Fixed = carries locked_odds."""
    pool_bets, fixed_bets = [], []
    for b in bets:
        (fixed_bets if _is_fixed(b) else pool_bets).append(b)
    return pool_bets, fixed_bets


def settle_all(bets_by_market, laps):
    """Settle every market. Returns per-market results + a per-person aggregate (the cashier's
    payout sheet) + the house line. Each market may hold BOTH a parimutuel pool book (old bets, the
    house never loses) and a fixed-odds book (new bets, house loss ≤ cap); they settle independently
    and are merged into one market result. Seed rows use key 'house'."""
    winner = race_winner(laps)
    if not winner:
        raise ValueError("race not decided")
    markets = []
    for mid in MARKET_IDS:
        bets = bets_by_market.get(mid)
        if not bets:
            continue
        pool_bets, fixed_bets = _split_book(bets)
        res = settle_market(mid, pool_bets, laps)  # unchanged parimutuel path (house ≥ 0)
        if fixed_bets:
            f = settle_market_fixed(mid, fixed_bets, laps)
            res["rows"] = res["rows"] + f["rows"]
            res["house"] = res["house"] + f["house"]   # fixed house may be negative (bounded by cap)
            res["pool"] = res["pool"] + f["pool"]
            res["fixed_house"] = f["house"]
            res["fixed_pool"] = f["pool"]
        markets.append(res)

    people = {}
    house_from_seed = 0
    for res in markets:
        for r in res["rows"]:
            if r["key"].startswith("house"):  # 'house' (match seed) or 'house:<market>:<outcome>'
                house_from_seed += r["net"]
                continue
            p = people.setdefault(r["key"], {"key": r["key"], "display_name": r["display_name"],
                                             "stake": 0, "payout": 0, "net": 0})
            p["stake"] += r["stake"]
            p["payout"] += r["payout"]
            p["net"] += r["net"]
    aggregate = sorted(people.values(), key=lambda p: -p["net"])
    house_total = sum(res["house"] for res in markets) + house_from_seed
    swimmer_total = sum(res["swimmer"] for res in markets)

    total_pool = sum(res["pool"] for res in markets)
    paid_people = sum(p["payout"] for p in aggregate)
    seed_stake = sum(r["stake"] for res in markets for r in res["rows"]
                     if r["key"].startswith("house"))
    # humans put in (total_pool - seed_stake); every rupee of it goes to people, swimmer, or the
    # organiser's net take (rakes + seed result) — the organiser can never leak or absorb extra.
    assert paid_people + swimmer_total + house_total == total_pool - seed_stake

    return {"winner": winner, "markets": markets, "aggregate": aggregate,
            "swimmer_take": swimmer_total, "house_take": house_total, "total_pool": total_pool}


def race_scripts(laps=()):
    """Every possible completion of the current lap history into a decided match (≤6 pre-race)."""
    out = []

    def rec(seq):
        if race_winner(seq):
            out.append(seq)
            return
        if len(seq) >= 3:
            return
        for s in SIDES:
            rec(seq + [{"lap": len(seq) + 1, "winner": s, "time_s": None}])

    rec(list(laps))
    return out


def house_floor(bets_by_market, laps=()):
    """The organiser's GUARANTEED minimum take on the PARIMUTUEL (pool) book: settle every market
    under every possible race outcome and take the worst total, counting pool bets only. Seed
    changes must keep this >= 0 — the literal 'house never loses' invariant for the pool book,
    enforced at the API. Fixed-odds bets are excluded here on purpose: they carry their own
    exposure (see fixed_house_floor), and folding them in would make this go negative and wrongly
    trip the seed guards / volatility breaker that this number drives."""
    scripts = race_scripts(laps)
    if not scripts:
        return 0
    pool_only = {mid: [b for b in bets if not _is_fixed(b)] for mid, bets in bets_by_market.items()}
    return min(settle_all(pool_only, s)["house_take"] for s in scripts)


def fixed_house_floor(bets_by_market, laps=()):
    """Worst-case house P&L on the FIXED book across every remaining race outcome. Negative = the
    house is exposed, and since pricing is uncapped that exposure is unbounded — this is the number
    to watch. For the admin's live exposure view — not a guard, since fixed exposure is expected."""
    scripts = race_scripts(laps)
    if not scripts:
        return 0
    worst = None
    for s in scripts:
        total = 0
        for mid, bets in bets_by_market.items():
            _, fixed_bets = _split_book(bets)
            if fixed_bets:
                total += settle_market_fixed(mid, fixed_bets, s)["house"]
        worst = total if worst is None else min(worst, total)
    return worst or 0


def person_floor(bets_by_market, key, laps=()):
    """Min over race scripts of this person's aggregate net across all markets.
    > 0 ⇒ they profit in EVERY possible outcome ⇒ riskless (arbitrage) portfolio."""
    scripts = race_scripts(laps)
    if not scripts:
        return 0
    floors = []
    for s in scripts:
        res = settle_all(bets_by_market, s)
        floors.append(sum(r["net"] for m in res["markets"] for r in m["rows"] if r["key"] == key))
    return min(floors)


def max_house_seed(match_pool_human):
    """The seed cap that keeps the organiser net-non-negative: expected rake on the main market."""
    return int(HOUSE_RAKE * match_pool_human)


BANSOD_PRIOR = 0.60  # organiser's estimate that Bansod wins any given lap (skill edge)


def outcome_priors(market_id, p=BANSOD_PRIOR):
    """Opening probabilities per outcome under an i.i.d. per-lap win prob p for Bansod.
    Used to tilt house liquidity so boards open at informed odds instead of even money."""
    q = 1 - p
    if market_id in ("lap1", "lap2", "lap3"):
        return {"khuseel": q, "bansod": p}
    if market_id == "score":
        return {"k20": q * q, "k21": 2 * p * q * q, "b20": p * p, "b21": 2 * p * p * q}
    if market_id == "distance":
        return {"yes": 2 * p * q, "no": p * p + q * q}
    if market_id == "comeback":
        return {"yes": p * q, "no": 1 - p * q}
    raise ValueError(market_id)


def _row(b):
    return {"key": b["key"], "display_name": b["display_name"],
            "outcome": b["outcome"], "stake": int(b["amount"])}


def _net(rows):
    for r in rows:
        r["net"] = r["payout"] - r["stake"]
    return rows
