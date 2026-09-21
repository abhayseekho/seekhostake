"""
store.py — SQLAlchemy Core persistence (same pattern as marketer/dashboard/store.py: Table objects,
no ORM, DATABASE_URL Postgres on Railway with a local SQLite fallback).

Identity: portal bets are keyed by the bettor's OAuth email; admin manual bets by "name:<slug>".
The bets table is append-mostly — approving a bet marks the person's previous approved bet
'superseded', so `status='approved'` is always exactly one live bet per person.
"""
import os
import json
from datetime import datetime, timezone

from sqlalchemy import (create_engine, MetaData, Table, Column, Integer, String, Text,
                        DateTime, select, update)

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
    Column("key", String(200), nullable=False),          # email or "name:<slug>"
    Column("display_name", String(120), nullable=False),
    Column("side", String(20), nullable=False),           # khuseel | bansod
    Column("amount", Integer, nullable=False),
    Column("status", String(20), nullable=False),         # pending|approved|rejected|superseded|cancelled
    Column("source", String(20), nullable=False),         # portal | admin
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

def approved_bets():
    with engine.begin() as cx:
        rows = cx.execute(select(bets).where(bets.c.status == "approved")
                          .order_by(bets.c.id)).mappings().all()
    return [dict(r) for r in rows]


def pending_bets():
    with engine.begin() as cx:
        rows = cx.execute(select(bets).where(bets.c.status == "pending")
                          .order_by(bets.c.id)).mappings().all()
    return [dict(r) for r in rows]


def bet_by_id(bet_id):
    with engine.begin() as cx:
        row = cx.execute(select(bets).where(bets.c.id == bet_id)).mappings().first()
    return dict(row) if row else None


def my_bets(key):
    with engine.begin() as cx:
        rows = cx.execute(select(bets).where(bets.c.key == key).order_by(bets.c.id)).mappings().all()
    return [dict(r) for r in rows]


def current_approved(key):
    for b in approved_bets():
        if b["key"] == key:
            return b
    return None


def submit_bet(key, display_name, side, amount, source="portal", note=""):
    """One live pending request per person: a new submit replaces (cancels) an older pending one."""
    with engine.begin() as cx:
        cx.execute(update(bets)
                   .where(bets.c.key == key, bets.c.status == "pending")
                   .values(status="cancelled", note="replaced by newer request", decided_at=_now()))
        res = cx.execute(bets.insert().values(
            key=key, display_name=display_name, side=side, amount=amount,
            status="pending", source=source, note=note, created_at=_now()))
    return res.inserted_primary_key[0]


def cancel_pending(key):
    with engine.begin() as cx:
        res = cx.execute(update(bets)
                         .where(bets.c.key == key, bets.c.status == "pending")
                         .values(status="cancelled", note="cancelled by bettor", decided_at=_now()))
    return res.rowcount


def approve_bet(bet_id, admin_email):
    """Approve one pending bet; the person's previous approved bet (if any) is superseded
    in the same transaction so the book never double-counts."""
    with engine.begin() as cx:
        row = cx.execute(select(bets).where(bets.c.id == bet_id)).mappings().first()
        if row is None or row["status"] != "pending":
            return None
        cx.execute(update(bets)
                   .where(bets.c.key == row["key"], bets.c.status == "approved")
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


def admin_manual_bet(name, side, amount, admin_email):
    """Directly place/replace (amount>0) or void (amount=0) a bet on someone's behalf.
    Keyed by name slug — used for the WhatsApp book and race-day cash reconciliation."""
    key = "name:" + "".join(ch for ch in name.lower() if ch.isalnum())
    with engine.begin() as cx:
        cx.execute(update(bets)
                   .where(bets.c.key == key, bets.c.status.in_(("approved", "pending")))
                   .values(status="superseded", decided_at=_now(), decided_by=admin_email))
        if amount > 0:
            cx.execute(bets.insert().values(
                key=key, display_name=name.strip(), side=side, amount=amount,
                status="approved", source="admin", note="admin manual entry",
                created_at=_now(), decided_at=_now(), decided_by=admin_email))
    return key


def reset_book(rows, admin_email):
    """Pre-race only (enforced at the API): wipe ALL bets and reload the seed. Used to refresh
    the live book after seed corrections (full names, merged bettors) without hand-voiding."""
    with engine.begin() as cx:
        cx.execute(bets.delete())
    return seed_bets(rows)


def void_key(key, admin_email):
    """Void a person's live bet by exact key (works for portal email keys too, unlike
    admin_manual_bet which only reaches name-keyed entries)."""
    with engine.begin() as cx:
        res = cx.execute(update(bets)
                         .where(bets.c.key == key, bets.c.status.in_(("approved", "pending")))
                         .values(status="superseded", note="voided by admin",
                                 decided_at=_now(), decided_by=admin_email))
    return res.rowcount


def seed_bets(rows):
    """Load the pre-race book once; refuses if any bets already exist."""
    with engine.begin() as cx:
        if cx.execute(select(bets.c.id).limit(1)).first() is not None:
            return 0
        for name, amount, side in rows:
            key = "name:" + "".join(ch for ch in name.lower() if ch.isalnum())
            cx.execute(bets.insert().values(
                key=key, display_name=name, side=side, amount=amount,
                status="approved", source="admin", note="pre-race WhatsApp book",
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
