"""
store.py — SQLAlchemy Core persistence (same pattern as marketer/dashboard/store.py: Table objects,
no ORM, DATABASE_URL Postgres on Railway with a local SQLite fallback).

Identity: portal bets are keyed by the bettor's OAuth email; admin manual bets by "name:<slug>";
the house seed bet by the literal key "house". Multi-market: every bet row carries (market,
outcome); the bets table is append-mostly — approving a bet supersedes the person's previous
approved bet IN THAT MARKET, so `status='approved'` is one live bet per person per market.
"""
import os
import json
from datetime import datetime, timezone

from sqlalchemy import (create_engine, MetaData, Table, Column, Integer, String, Text,
                        DateTime, select, update, text)

import engine as rules

_HERE = os.path.dirname(os.path.abspath(__file__))
DB_URL = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(_HERE, 'swimbet.db')}")
if DB_URL.startswith("postgres://"):  # Railway sometimes hands out the legacy scheme
    DB_URL = DB_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DB_URL.startswith("postgresql://"):
    DB_URL = DB_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DB_URL, pool_pre_ping=True, future=True)
meta = MetaData()

bets = Table(
    "bets", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("key", String(200), nullable=False),           # email | "name:<slug>" | "house"
    Column("display_name", String(120), nullable=False),
    Column("side", String(20), nullable=False),           # legacy column (= outcome for k/b markets)
    Column("market", String(30), nullable=False, server_default="match"),
    Column("outcome", String(20), nullable=False, server_default=""),
    Column("amount", Integer, nullable=False),
    Column("status", String(20), nullable=False),         # pending|approved|rejected|superseded|cancelled
    Column("source", String(20), nullable=False),         # portal | admin | house
    Column("note", Text, default=""),
    Column("created_at", DateTime, nullable=False),
    Column("decided_at", DateTime),
    Column("decided_by", String(200)),
)

race = Table(
    "race", meta,
    Column("id", Integer, primary_key=True),              # always 1
    Column("phase", String(20), nullable=False),
    Column("laps", Text, nullable=False),                 # JSON [{lap, winner, time_s}]
    Column("suspended", Text, nullable=False, server_default="[]"),  # JSON [market_id, ...]
)

settlements = Table(
    "settlements", meta,
    Column("id", Integer, primary_key=True),              # always 1 — frozen audit record
    Column("payload", Text, nullable=False),
    Column("created_at", DateTime, nullable=False),
)


def _now():
    return datetime.now(timezone.utc)


def init():
    meta.create_all(engine)
    with engine.begin() as cx:
        # In-place migration for pre-multi-market databases (prod Postgres was created without
        # market/outcome). ADD COLUMN IF NOT EXISTS works on Postgres; SQLite needs the try/except.
        for ddl in (
            "ALTER TABLE bets ADD COLUMN market VARCHAR(30) DEFAULT 'match'",
            "ALTER TABLE bets ADD COLUMN outcome VARCHAR(20) DEFAULT ''",
            "ALTER TABLE race ADD COLUMN suspended TEXT DEFAULT '[]'",
        ):
            try:
                cx.execute(text(ddl.replace("ADD COLUMN", "ADD COLUMN IF NOT EXISTS")
                                if engine.dialect.name == "postgresql" else ddl))
            except Exception:  # noqa: BLE001 — column already exists (sqlite)
                pass
        cx.execute(text("UPDATE bets SET market='match' WHERE market IS NULL OR market=''"))
        cx.execute(text("UPDATE bets SET outcome=side WHERE outcome IS NULL OR outcome=''"))
        cx.execute(text("UPDATE race SET suspended='[]' WHERE suspended IS NULL"))
        if cx.execute(select(race.c.id).where(race.c.id == 1)).first() is None:
            cx.execute(race.insert().values(id=1, phase="prerace", laps="[]"))
        # Belt-and-suspenders on top of the app-level _approve_lock (api.py): make "at most one
        # approved bet per person per market" true BY CONSTRUCTION, not just by the lock holding.
        # A partial unique index is valid, portable syntax on both SQLite and Postgres, so no
        # dialect branching is needed here (unlike the ADD COLUMN statements above).
        try:
            cx.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS one_approved_per_person_market "
                "ON bets (key, market) WHERE status = 'approved'"))
        except Exception as e:  # noqa: BLE001 — a pre-existing violation must not block boot
            print(f"WARNING: could not create one_approved_per_person_market index: {e}", flush=True)


# ── race ─────────────────────────────────────────────────────────────────────────────────────────

def get_race():
    with engine.begin() as cx:
        row = cx.execute(select(race).where(race.c.id == 1)).mappings().first()
    return {"phase": row["phase"], "laps": json.loads(row["laps"]),
            "suspended": json.loads(row["suspended"] or "[]")}


def set_race(phase, laps):
    with engine.begin() as cx:
        cx.execute(update(race).where(race.c.id == 1).values(phase=phase, laps=json.dumps(laps)))


def suspend_market(market_id):
    """Circuit breaker trip: block further bets on this one market until an admin resumes it."""
    with engine.begin() as cx:
        row = cx.execute(select(race.c.suspended).where(race.c.id == 1)).first()
        cur = set(json.loads(row[0] or "[]"))
        cur.add(market_id)
        cx.execute(update(race).where(race.c.id == 1).values(suspended=json.dumps(sorted(cur))))


def resume_market(market_id):
    with engine.begin() as cx:
        row = cx.execute(select(race.c.suspended).where(race.c.id == 1)).first()
        cur = set(json.loads(row[0] or "[]"))
        cur.discard(market_id)
        cx.execute(update(race).where(race.c.id == 1).values(suspended=json.dumps(sorted(cur))))


# ── bets ─────────────────────────────────────────────────────────────────────────────────────────

def approved_bets(market=None):
    q = select(bets).where(bets.c.status == "approved").order_by(bets.c.id)
    if market:
        q = q.where(bets.c.market == market)
    with engine.begin() as cx:
        rows = cx.execute(q).mappings().all()
    return [dict(r) for r in rows]


def approved_by_market():
    out = {}
    for b in approved_bets():
        out.setdefault(b["market"], []).append(b)
    return out


def pending_bets():
    with engine.begin() as cx:
        rows = cx.execute(select(bets).where(bets.c.status == "pending")
                          .order_by(bets.c.id)).mappings().all()
    return [dict(r) for r in rows]


def bet_by_id(bet_id):
    with engine.begin() as cx:
        row = cx.execute(select(bets).where(bets.c.id == bet_id)).mappings().first()
    return dict(row) if row else None


def all_bets():
    """Every bet ever recorded, any status, newest first — the full admin ledger. Unlike
    pending_bets()/approved_bets(), this is the only place rejected/cancelled/superseded rows
    are ever surfaced again, which is what makes correcting one of them possible at all."""
    with engine.begin() as cx:
        rows = cx.execute(select(bets).order_by(bets.c.id.desc())).mappings().all()
    return [dict(r) for r in rows]


ADMIN_SETTABLE_STATUSES = ("pending", "approved", "rejected", "cancelled")


def set_status(bet_id, new_status, admin_email):
    """Admin override: force a bet directly to any status, bypassing the normal approve/reject
    flow — for correcting mistakes (wrong tap, cash paid after a reject, an approve that needs
    undoing) on a bet in ANY current status, not just pending. Returns the PRE-change row (or
    None if bet_id doesn't exist), so the caller knows what it moved FROM.

    Moving TO 'approved' still supersedes the person's other live approved bet in the same
    market in the same transaction — exactly like approve_bet — so the one-approved-per-person-
    per-market DB invariant (the partial unique index in init()) holds no matter which status
    this bet is coming from. Moving TO 'pending' likewise cancels any other pending bet the
    person has in that market, mirroring submit_bet's own invariant. Without both of these this
    would just be an UPDATE statement; with them it's safe to point at any row in any state."""
    with engine.begin() as cx:
        row = cx.execute(select(bets).where(bets.c.id == bet_id)).mappings().first()
        if row is None:
            return None
        if row["status"] == new_status:
            return dict(row)  # no-op — nothing to move, caller treats old==new as unchanged
        if new_status == "approved":
            cx.execute(update(bets)
                       .where(bets.c.key == row["key"], bets.c.market == row["market"],
                              bets.c.status == "approved", bets.c.id != bet_id)
                       .values(status="superseded", decided_at=_now(), decided_by=admin_email))
        elif new_status == "pending":
            cx.execute(update(bets)
                       .where(bets.c.key == row["key"], bets.c.market == row["market"],
                              bets.c.status == "pending", bets.c.id != bet_id)
                       .values(status="cancelled", note="replaced by newer request",
                               decided_at=_now(), decided_by=admin_email))
        note = f"[override: {row['status']}→{new_status}] " + (row["note"] or "")
        cx.execute(update(bets).where(bets.c.id == bet_id)
                   .values(status=new_status, note=note.strip(), decided_at=_now(),
                           decided_by=admin_email))
        return dict(row)


def current_approved(key, market="match"):
    with engine.begin() as cx:
        row = cx.execute(select(bets).where(bets.c.key == key, bets.c.status == "approved",
                                            bets.c.market == market)).mappings().first()
    return dict(row) if row else None


def my_approved(key):
    with engine.begin() as cx:
        rows = cx.execute(select(bets).where(bets.c.key == key, bets.c.status == "approved")
                          .order_by(bets.c.id)).mappings().all()
    return [dict(r) for r in rows]


def submit_bet(key, display_name, market, outcome, amount, source="portal", note=""):
    """One live pending request per person PER MARKET: a new submit replaces the older one."""
    with engine.begin() as cx:
        cx.execute(update(bets)
                   .where(bets.c.key == key, bets.c.status == "pending", bets.c.market == market)
                   .values(status="cancelled", note="replaced by newer request", decided_at=_now()))
        res = cx.execute(bets.insert().values(
            key=key, display_name=display_name, market=market, outcome=outcome,
            side=outcome if outcome in ("khuseel", "bansod") else "",
            amount=amount, status="pending", source=source, note=note, created_at=_now()))
    return res.inserted_primary_key[0]


def cancel_pending(key, market=None):
    q = update(bets).where(bets.c.key == key, bets.c.status == "pending")
    if market:
        q = q.where(bets.c.market == market)
    with engine.begin() as cx:
        res = cx.execute(q.values(status="cancelled", note="cancelled by bettor", decided_at=_now()))
    return res.rowcount


def approve_bet(bet_id, admin_email):
    """Approve one pending bet; the person's previous approved bet in the SAME market is
    superseded in the same transaction so no market ever double-counts a person."""
    with engine.begin() as cx:
        row = cx.execute(select(bets).where(bets.c.id == bet_id)).mappings().first()
        if row is None or row["status"] != "pending":
            return None
        cx.execute(update(bets)
                   .where(bets.c.key == row["key"], bets.c.status == "approved",
                          bets.c.market == row["market"])
                   .values(status="superseded", decided_at=_now(), decided_by=admin_email))
        cx.execute(update(bets).where(bets.c.id == bet_id)
                   .values(status="approved", decided_at=_now(), decided_by=admin_email))
        return dict(row)


def reject_bet(bet_id, admin_email, note="rejected by admin"):
    with engine.begin() as cx:
        res = cx.execute(update(bets)
                         .where(bets.c.id == bet_id, bets.c.status == "pending")
                         .values(status="rejected", note=note, decided_at=_now(),
                                 decided_by=admin_email))
    return res.rowcount


def reject_all_pending(admin_email, note):
    with engine.begin() as cx:
        res = cx.execute(update(bets).where(bets.c.status == "pending")
                         .values(status="rejected", note=note, decided_at=_now(),
                                 decided_by=admin_email))
    return res.rowcount


def admin_manual_bet(name, market, outcome, amount, admin_email):
    """Directly place/replace (amount>0) or void (amount=0) a bet on someone's behalf.
    Keyed by name slug — used for the WhatsApp book and race-day cash reconciliation."""
    key = rules.name_slug(name)
    _replace_bet(key, name.strip(), market, outcome, amount, "admin", "admin manual entry", admin_email)
    return key


def set_house_seed(market, outcome, amount, admin_email):
    """The house's visible seed bet (key='house'). amount=0 removes it."""
    _replace_bet("house", "House", market, outcome, amount, "house", "house seed", admin_email)


def _replace_bet(key, display_name, market, outcome, amount, source, note, admin_email):
    with engine.begin() as cx:
        cx.execute(update(bets)
                   .where(bets.c.key == key, bets.c.market == market,
                          bets.c.status.in_(("approved", "pending")))
                   .values(status="superseded", decided_at=_now(), decided_by=admin_email))
        if amount > 0:
            cx.execute(bets.insert().values(
                key=key, display_name=display_name, market=market, outcome=outcome,
                side=outcome if outcome in ("khuseel", "bansod") else "",
                amount=amount, status="approved", source=source, note=note,
                created_at=_now(), decided_at=_now(), decided_by=admin_email))


def name_on_file(key):
    """Most recent display_name ever associated with this key (any status) — lets the API detect
    when a freshly typed name-mode identity collides with a DIFFERENT existing person whose name
    normalizes to the same slug, instead of silently merging the two into one identity."""
    with engine.begin() as cx:
        row = cx.execute(select(bets.c.display_name).where(bets.c.key == key)
                         .order_by(bets.c.id.desc()).limit(1)).first()
    return row[0] if row else None


def house_seed(market="match"):
    return current_approved("house", market)


def seed_side_markets(rows, admin_email):
    """House liquidity on side-market outcomes: rows = [(market, outcome, amount)], amount=0
    clears that outcome. One row per outcome, keyed 'house:<market>:<outcome>'."""
    n = 0
    for mid, oid, amount in rows:
        _replace_bet(f"house:{mid}:{oid}", "House", mid, oid, amount, "house",
                     "house liquidity", admin_email)
        n += 1
    return n


def reset_book(rows, admin_email):
    """Wipe ALL bets, roll the race itself back to pre-race (any lap results are discarded), clear
    circuit-breaker suspensions, and reload the seed — a full reset restarts betting state
    entirely, not just the book. Usable at any point before settlement: rehearsals routinely need
    to roll all the way back after running laps, not just correct a seed before anything's
    happened."""
    with engine.begin() as cx:
        cx.execute(bets.delete())
        cx.execute(update(race).where(race.c.id == 1)
                   .values(phase="prerace", laps="[]", suspended="[]"))
    return seed_bets(rows)


def void_key(key, admin_email, market=None):
    """Void a person's live bet(s) by exact key (all markets unless one is given)."""
    q = update(bets).where(bets.c.key == key, bets.c.status.in_(("approved", "pending")))
    if market:
        q = q.where(bets.c.market == market)
    with engine.begin() as cx:
        res = cx.execute(q.values(status="superseded", note="voided by admin",
                                  decided_at=_now(), decided_by=admin_email))
    return res.rowcount


def seed_bets(rows):
    """Load the pre-race book (match market) once; refuses if any bets already exist."""
    with engine.begin() as cx:
        if cx.execute(select(bets.c.id).limit(1)).first() is not None:
            return 0
        for name, amount, side in rows:
            key = rules.name_slug(name)
            cx.execute(bets.insert().values(
                key=key, display_name=name, market="match", outcome=side, side=side,
                amount=amount, status="approved", source="admin", note="pre-race WhatsApp book",
                created_at=_now(), decided_at=_now(), decided_by="seed"))
    return len(rows)


# ── settlement ───────────────────────────────────────────────────────────────────────────────────

def save_settlement(payload):
    with engine.begin() as cx:
        if cx.execute(select(settlements.c.id).where(settlements.c.id == 1)).first() is not None:
            return False  # immutable once frozen
        cx.execute(settlements.insert().values(id=1, payload=json.dumps(payload), created_at=_now()))
    return True


def load_settlement():
    with engine.begin() as cx:
        row = cx.execute(select(settlements.c.payload).where(settlements.c.id == 1)).first()
    return json.loads(row[0]) if row else None
