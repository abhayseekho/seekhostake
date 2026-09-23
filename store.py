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
        ):
            try:
                cx.execute(text(ddl.replace("ADD COLUMN", "ADD COLUMN IF NOT EXISTS")
                                if engine.dialect.name == "postgresql" else ddl))
            except Exception:  # noqa: BLE001 — column already exists (sqlite)
                pass
        cx.execute(text("UPDATE bets SET market='match' WHERE market IS NULL OR market=''"))
        cx.execute(text("UPDATE bets SET outcome=side WHERE outcome IS NULL OR outcome=''"))
        if cx.execute(select(race.c.id).where(race.c.id == 1)).first() is None:
            cx.execute(race.insert().values(id=1, phase="prerace", laps="[]"))


# ── race ─────────────────────────────────────────────────────────────────────────────────────────

def get_race():
    with engine.begin() as cx:
        row = cx.execute(select(race).where(race.c.id == 1)).mappings().first()
    return {"phase": row["phase"], "laps": json.loads(row["laps"])}


def set_race(phase, laps):
    with engine.begin() as cx:
        cx.execute(update(race).where(race.c.id == 1).values(phase=phase, laps=json.dumps(laps)))


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
    key = "name:" + "".join(ch for ch in name.lower() if ch.isalnum())
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


def house_seed(market="match"):
    return current_approved("house", market)


def seed_side_markets(markets_outcomes, amount, admin_email):
    """Symmetric house liquidity on every side-market outcome (amount=0 clears) so boards open
    with real odds instead of '—'. One row per outcome, keyed 'house:<market>:<outcome>'."""
    n = 0
    for mid, oid in markets_outcomes:
        _replace_bet(f"house:{mid}:{oid}", "House", mid, oid, amount, "house",
                     "house liquidity", admin_email)
        n += 1
    return n


def reset_book(rows, admin_email):
    """Pre-race only (enforced at the API): wipe ALL bets and reload the seed."""
    with engine.begin() as cx:
        cx.execute(bets.delete())
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
            key = "name:" + "".join(ch for ch in name.lower() if ch.isalnum())
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
