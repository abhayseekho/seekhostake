"""
engine.py — pure betting logic for the Khuseel vs Bansod parimutuel pools. No I/O, no DB.

House rules (ratified with Abhay, 2026-09-15):
- Multiple parimutuel MARKETS, each its own pool. 5% house rake on every market.
- MAIN market (match winner) additionally: 30% of the post-rake losing pot to the winning
  swimmer, 70% to winning bettors; and the house may hold a visible seed bet ("House"),
  capped at the expected rake so the organiser can never go net negative.
- Side markets: winners share the post-rake pool pro-rata. Voided markets refund in full.
- Latest APPROVED bet per person PER MARKET is binding.
- All betting closes when lap 2 starts. Match-winner side-switching is pre-race only.
- Settlement asserts every market's payouts + house take sum exactly to its pool.
"""

SIDES = ("khuseel", "bansod")
SWIMMER_CUT = 0.30
HOUSE_RAKE = 0.05

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
        out[oid] = {"label": label, "total": w, "bettors": counts[oid],
                    "est_mult": round(est, 3) if est else None}
    return {"pool": pool, "outcomes": out}


# ── bet validation ───────────────────────────────────────────────────────────────────────────────

def can_submit(market_id, phase, outcome, amount, laps=(), current_outcome=None):
    """Returns (ok, reason)."""
    m = MARKET_BY_ID.get(market_id)
    if not m:
        return False, "bad_market"
    if phase not in m["open_phases"]:
        return False, "book_closed"
    if outcome not in {oid for oid, _ in m["outcomes"]}:
        return False, "bad_outcome"
    if not isinstance(amount, int) or amount < 1:
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
        winners_pot = pool - rake - win_total      # winners also get stakes back below

    paid = 0
    for b in approved_bets:
        stake = int(b["amount"])
        if b["outcome"] == won:
            profit = (stake * winners_pot) // win_total
            payout = stake + profit
            result = "won"
        else:
            payout, result = 0, "lost"
        paid += payout
        rows.append({**_row(b), "payout": payout, "result": result})

    house = pool - paid - swimmer  # rake + rounding remainders (+/- house seed rows are in `rows`)
    assert house >= 0 and paid + swimmer + house == pool, f"{market_id}: settlement must sum to pool"
    return {"market": market_id, "name": m["name"], "won": won, "won_label": labels[won],
            "void": False, "pool": pool, "house": house, "swimmer": swimmer, "rows": _net(rows)}


def settle_all(bets_by_market, laps):
    """Settle every market. Returns per-market results + a per-person aggregate (the cashier's
    payout sheet) + the house line (rakes + remainders + seed result; seed rows use key 'house')."""
    winner = race_winner(laps)
    if not winner:
        raise ValueError("race not decided")
    markets = [settle_market(mid, bets_by_market.get(mid, []), laps)
               for mid in MARKET_IDS if bets_by_market.get(mid)]

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
