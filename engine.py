"""
engine.py — pure betting logic for the Khuseel vs Bansod parimutuel pool. No I/O, no DB:
every function takes plain dicts/lists and returns plain dicts, so the whole rulebook is
unit-testable without a server.

House rules (ratified with Abhay, 2026-09-15):
- Parimutuel: one pool; winners get stake back + 70% of the losing side's pot pro-rata.
- The winning SWIMMER takes 30% of the losing pot (plus rounding paise — see settle()).
- Latest APPROVED bet per person is the binding one (approval supersedes earlier bets).
- Book is open pre-race and during break 1 only; NO side-switching once lap 1 starts.
- Best of 3 laps: race finishes at 2-0 or after lap 3.
- Organiser must stay net-zero: settle() asserts payouts sum exactly to the pool.
"""

SIDES = ("khuseel", "bansod")
SWIMMER_CUT = 0.30

# Phase machine. "breakN" is the 15-min gap after lap N; betting is legal only in OPEN_PHASES.
PHASES = ("prerace", "lap1", "break1", "lap2", "break2", "lap3", "finished", "settled")
OPEN_PHASES = ("prerace", "break1")


# ── book ─────────────────────────────────────────────────────────────────────────────────────────

def effective_book(approved_bets):
    """approved_bets: one row per person (the DB supersedes older approvals), each
    {"key", "display_name", "side", "amount"}. Returns totals, pool, and per-side
    multiplier/implied% (None while a side has no money)."""
    totals = {s: 0 for s in SIDES}
    for b in approved_bets:
        totals[b["side"]] += int(b["amount"])
    pool = sum(totals.values())
    sides = {}
    for s in SIDES:
        t = totals[s]
        sides[s] = {
            "total": t,
            "bettors": sum(1 for b in approved_bets if b["side"] == s),
            "multiplier": round(pool / t, 3) if t else None,
            "implied_pct": round(100.0 * t / pool, 1) if pool and t else None,
        }
    return {"pool": pool, "sides": sides}


# ── bet validation ───────────────────────────────────────────────────────────────────────────────

def can_submit(phase, side, amount, current_side=None):
    """Returns (ok, reason). current_side = the person's live approved side, if any.
    Side-switching is only legal pre-race (latest-bet-wins was a pre-race rule)."""
    if phase not in OPEN_PHASES:
        return False, "book_closed"
    if side not in SIDES:
        return False, "bad_side"
    if not isinstance(amount, int) or amount < 1:
        return False, "bad_amount"
    if current_side and current_side != side and phase != "prerace":
        return False, "no_side_switch"
    return True, ""


# ── race phase machine ───────────────────────────────────────────────────────────────────────────

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
    """Admin presses 'Start lap N'. Starting lap 2 is the moment the book closes for good."""
    transitions = {"prerace": "lap1", "break1": "lap2", "break2": "lap3"}
    if phase not in transitions:
        raise ValueError(f"cannot start a lap from phase {phase!r}")
    return transitions[phase]


def next_phase_on_lap_result(phase, laps_after):
    """Admin records who won the lap just swum. laps_after includes the new result."""
    if phase not in ("lap1", "lap2", "lap3"):
        raise ValueError(f"no lap in progress (phase {phase!r})")
    if race_winner(laps_after):
        return "finished"
    return {"lap1": "break1", "lap2": "break2"}[phase]  # lap3 without a 2-win is impossible


# ── settlement ───────────────────────────────────────────────────────────────────────────────────

def settle(approved_bets, winner_side):
    """Final payout table. Losers forfeit their stake; each winner gets
    stake + floor(stake/win_total * 70% of losing pot); the winning swimmer gets
    30% of the losing pot + every rounding remainder, so the table sums EXACTLY
    to the pool and the organiser is net-zero by construction.

    Degenerate case (nobody backed the winner): swimmer still gets 30%, and the
    backers of the loser get 70% of their own stakes back pro-rata — money never
    sticks to the organiser."""
    if winner_side not in SIDES:
        raise ValueError(f"bad winner {winner_side!r}")
    loser_side = SIDES[0] if winner_side == SIDES[1] else SIDES[1]
    book = effective_book(approved_bets)
    pool = book["pool"]
    win_total = book["sides"][winner_side]["total"]
    lose_total = book["sides"][loser_side]["total"]
    profit_pot = int((1 - SWIMMER_CUT) * lose_total)  # 70% of losing pot, whole ₹

    rows = []
    paid_to_bettors = 0
    for b in approved_bets:
        stake = int(b["amount"])
        if b["side"] == winner_side:
            profit = (stake * profit_pot) // win_total if win_total else 0
            payout = stake + profit
        elif win_total == 0:
            payout = (stake * profit_pot) // lose_total if lose_total else 0  # 70% refund
        else:
            payout = 0
        paid_to_bettors += payout
        rows.append({
            "key": b["key"], "display_name": b["display_name"], "side": b["side"],
            "stake": stake, "payout": payout, "net": payout - stake,
        })
    swimmer_take = pool - paid_to_bettors  # 30% of losing pot + rounding remainders
    assert swimmer_take >= 0
    assert paid_to_bettors + swimmer_take == pool, "settlement must sum to the pool"
    rows.sort(key=lambda r: -r["net"])
    return {
        "winner": winner_side,
        "pool": pool,
        "win_total": win_total,
        "lose_total": lose_total,
        "swimmer_take": swimmer_take,
        "paid_to_bettors": paid_to_bettors,
        "rows": rows,
    }
