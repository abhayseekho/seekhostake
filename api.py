#!/usr/bin/env python3
"""
api.py — FastAPI backend for the Khuseel vs Bansod live betting portal.

Serves the React SPA (frontend/dist) + a small JSON API. Auth follows the marketer dashboard
pattern: Google OAuth (Authlib) gating everything to @seekhoapp.com, OWNER_EMAILS = admin
(Abhay, the cashier). Cash-first flow: portal bets land 'pending' and enter the pool only when
the admin approves after receiving cash — so the pool always equals cash in hand.

Env: GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET, AUTH_REDIRECT_URI (…/auth/callback), SESSION_SECRET,
ALLOWED_DOMAIN/ALLOWED_EMAILS, OWNER_EMAILS, DATABASE_URL.
SWIMBET_DEV=1 bypasses auth (local dev).
AUTH_MODE=name is the race-morning fallback: bettors identify by typed name (no OAuth),
admin unlocks with ADMIN_PASSWORD via POST /auth/admin.
"""
import os
import re
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel

import engine as rules
import store
from seed import SEED_BETS

DEV = os.environ.get("SWIMBET_DEV", "").lower() in ("1", "true", "yes")
AUTH_MODE = os.environ.get("AUTH_MODE", "oauth").lower()  # oauth | name
_HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(_HERE, "frontend", "dist")

_DEV_SESSION_SECRET = "dev-insecure-secret"
_MIN_SESSION_SECRET_LENGTH = 32


def _session_secret() -> str:
    """Return a session secret, refusing unsafe production configuration at startup."""
    secret = os.environ.get("SESSION_SECRET", "")
    if DEV:
        return secret or _DEV_SESSION_SECRET
    if not secret:
        raise RuntimeError("SESSION_SECRET must be configured when SWIMBET_DEV is not enabled")
    if secret == _DEV_SESSION_SECRET:
        raise RuntimeError("SESSION_SECRET must not use the development default in production")
    if len(secret) < _MIN_SESSION_SECRET_LENGTH:
        raise RuntimeError(f"SESSION_SECRET must be at least {_MIN_SESSION_SECRET_LENGTH} characters")
    return secret


# ALLOW_HTTP=1: session cookie sent over plain http — needed for LAN mode (phones hitting
# http://<mac-ip>:port are not a secure context, so a Secure cookie would be silently dropped
# and login would never stick). Never set it on Railway (https there).
_ALLOW_HTTP = os.environ.get("ALLOW_HTTP", "").lower() in ("1", "true", "yes")

app = FastAPI(title="Swim Bet — Khuseel vs Bansod")
app.add_middleware(SessionMiddleware, secret_key=_session_secret(),
                   same_site="lax", https_only=not (DEV or _ALLOW_HTTP))

# ── Google OAuth (Authlib) ────────────────────────────────────────────────────────────────────────
_oauth = None
if os.environ.get("GOOGLE_CLIENT_ID"):
    from authlib.integrations.starlette_client import OAuth
    _oauth = OAuth()
    _oauth.register(
        name="google",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


def _allowed(email: str) -> bool:
    email = (email or "").lower().strip()
    allow = {e.strip().lower() for e in os.environ.get("ALLOWED_EMAILS", "").split(",") if e.strip()}
    domain = os.environ.get("ALLOWED_DOMAIN", "").lower().strip().lstrip("@")
    if allow and email in allow:
        return True
    if domain and email.endswith("@" + domain):
        return True
    return False


def _name_slug(name: str) -> str:
    return "name:" + re.sub(r"[^a-z0-9]", "", name.lower())


def _current_user(request: Request):
    """Returns {key, name} or None. key is the canonical bettor identity: OAuth email,
    or 'name:<slug>' in name-mode (matching admin manual entries for the same person)."""
    if DEV:
        return {"key": "dev@local", "name": "Dev"}
    u = request.session.get("user")
    if not u:
        return None
    return {"key": u["key"], "name": u.get("name") or u["key"]}


def _require(request: Request):
    u = _current_user(request)
    if not u:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return u


def _is_owner(request: Request) -> bool:
    if DEV:
        return True
    if AUTH_MODE == "name":
        return bool(request.session.get("admin"))
    u = request.session.get("user") or {}
    owners = {e.strip().lower() for e in
              os.environ.get("OWNER_EMAILS", "abhay@seekhoapp.com").split(",") if e.strip()}
    return (u.get("key") or "").lower() in owners


def _require_owner(request: Request):
    u = _require(request)
    if not _is_owner(request):
        raise HTTPException(status_code=403, detail="owner_only")
    return u


@app.get("/auth/login")
async def auth_login(request: Request):
    if AUTH_MODE == "name":
        raise HTTPException(400, "name-mode: POST /auth/name instead")
    if not _oauth:
        raise HTTPException(500, "OAuth not configured (GOOGLE_CLIENT_ID missing)")
    redirect_uri = os.environ.get("AUTH_REDIRECT_URI") or str(request.url_for("auth_callback"))
    return await _oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    if not _oauth:
        raise HTTPException(500, "OAuth not configured")
    try:
        token = await _oauth.google.authorize_access_token(request)
    except Exception:  # noqa: BLE001
        return RedirectResponse("/?error=oauth")
    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower()
    if not _allowed(email):
        return RedirectResponse("/?error=denied")
    request.session["user"] = {"key": email, "name": info.get("name")}
    return RedirectResponse("/")


class NameLogin(BaseModel):
    name: str


@app.post("/auth/name")
def auth_name(request: Request, body: NameLogin):
    """Race-morning fallback identity: first name = identity. Only active in AUTH_MODE=name."""
    if AUTH_MODE != "name":
        raise HTTPException(400, "oauth mode: use /auth/login")
    name = body.name.strip()
    if not (2 <= len(name) <= 40):
        raise HTTPException(400, "bad_name")
    request.session["user"] = {"key": _name_slug(name), "name": name}
    return {"ok": True}


class TestLogin(BaseModel):
    email: str
    password: str


@app.post("/auth/test")
def auth_test(request: Request, body: TestLogin):
    """Env-gated test login (TEST_LOGIN_PASSWORD): sign in as any allowed-domain email without
    Google — for pre-race admin/user-side checks. Unset the env var to disable. Invisible when off."""
    expected = os.environ.get("TEST_LOGIN_PASSWORD", "")
    if not expected:
        raise HTTPException(404)
    if body.password != expected:
        raise HTTPException(403, "wrong_password")
    email = body.email.lower().strip()
    if not _allowed(email):
        raise HTTPException(403, "not_allowed")
    request.session["user"] = {"key": email, "name": email.split("@")[0].replace(".", " ").title()}
    return {"ok": True}


class AdminLogin(BaseModel):
    password: str


@app.post("/auth/admin")
def auth_admin(request: Request, body: AdminLogin):
    """Admin unlock for name-mode (in oauth mode admin = OWNER_EMAILS, no password)."""
    expected = os.environ.get("ADMIN_PASSWORD", "")
    if not expected:
        raise HTTPException(404)
    if body.password != expected:
        raise HTTPException(403, "wrong_password")
    request.session["admin"] = True
    if not request.session.get("user"):
        request.session["user"] = {"key": "name:admin", "name": "Admin"}
    return {"ok": True}


@app.get("/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────

def _close_book(admin_key: str):
    n = store.reject_all_pending(admin_key, "book closed at lap 2")
    return n


# ── public API ───────────────────────────────────────────────────────────────────────────────────

@app.get("/api/config")
def api_config():
    """Unauthenticated: the login screen needs to know which auth mode to render."""
    return {"auth_mode": AUTH_MODE,
            "test_login": bool(os.environ.get("TEST_LOGIN_PASSWORD"))}


@app.get("/api/state")
def api_state(request: Request):
    """The one endpoint the UI polls: race, every market's live book/odds, the caller's positions."""
    u = _require(request)
    owner = _is_owner(request)
    r = store.get_race()
    by_market = store.approved_by_market()
    my_pendings = {p["market"]: p for p in store.pending_bets() if p["key"] == u["key"]}
    mine_all = {b["market"]: b for b in store.my_approved(u["key"])}

    markets = []
    for m in rules.MARKETS:
        mid = m["id"]
        rows = by_market.get(mid, [])
        book = rules.market_book(mid, rows)
        # Bettors see quoted odds only — the house position is priced into est_mult but never
        # itemized for them: displayed totals/pool exclude house rows for non-admins.
        shown_totals = {}
        for oid, _label in m["outcomes"]:
            o = book["outcomes"][oid]
            if owner:
                shown_totals[oid] = (o["total"], o["bettors"])
            else:
                house_amt = sum(int(b["amount"]) for b in rows
                                if b["key"] == "house" and b["outcome"] == oid)
                house_n = sum(1 for b in rows if b["key"] == "house" and b["outcome"] == oid)
                shown_totals[oid] = (o["total"] - house_amt, o["bettors"] - house_n)
        my = mine_all.get(mid)
        pend = my_pendings.get(mid)
        markets.append({
            "id": mid, "name": m["name"], "main": bool(m.get("main")),
            "open": r["phase"] in m["open_phases"],
            "pool": sum(t for t, _ in shown_totals.values()),
            "outcomes": [{"id": oid, "label": book["outcomes"][oid]["label"],
                          "est_mult": book["outcomes"][oid]["est_mult"],
                          "total": shown_totals[oid][0], "bettors": shown_totals[oid][1],
                          "alive": rules.outcome_alive(mid, oid, r["laps"])}
                         for oid, _ in m["outcomes"]],
            "my_bet": my and {"outcome": my["outcome"], "amount": my["amount"]},
            "my_pending": pend and {"id": pend["id"], "outcome": pend["outcome"],
                                    "amount": pend["amount"]},
        })

    match_rows = by_market.get("match", [])
    out = {
        "auth_mode": AUTH_MODE,
        "me": {"key": u["key"], "name": u["name"], "is_owner": owner},
        "race": {"phase": r["phase"], "laps": r["laps"],
                 "wins": rules.lap_wins(r["laps"]),
                 "book_open": r["phase"] in rules.OPEN_PHASES},
        "markets": markets,
        "bets": sorted(({"key": b["key"], "display_name": b["display_name"],
                         "side": b["outcome"], "amount": b["amount"]}
                        for b in match_rows if owner or b["key"] != "house"),
                       key=lambda b: -b["amount"]),
        "settled": store.load_settlement() is not None,
    }
    if owner:
        human_pool = sum(b["amount"] for b in match_rows if b["key"] != "house")
        seed = store.house_seed()
        out["rake_pct"] = int(rules.HOUSE_RAKE * 100)
        out["pending_count"] = len(store.pending_bets())
        out["house"] = {"seed": seed and {"outcome": seed["outcome"], "amount": seed["amount"]},
                        "seed_cap": rules.max_house_seed(human_pool)}
    return out


class BetIn(BaseModel):
    market: str = "match"
    outcome: str
    amount: int


@app.post("/api/bets")
def api_submit_bet(request: Request, body: BetIn):
    u = _require(request)
    r = store.get_race()
    mine = store.current_approved(u["key"], body.market)
    ok, reason = rules.can_submit(body.market, r["phase"], body.outcome, body.amount,
                                  laps=r["laps"], current_outcome=mine and mine["outcome"])
    if not ok:
        raise HTTPException(400, reason)
    bet_id = store.submit_bet(u["key"], u["name"], body.market, body.outcome, body.amount)
    return {"ok": True, "id": bet_id, "status": "pending"}


class CancelIn(BaseModel):
    market: Optional[str] = None


@app.post("/api/bets/cancel")
def api_cancel_bet(request: Request, body: CancelIn = CancelIn()):
    u = _require(request)
    n = store.cancel_pending(u["key"], body.market)
    return {"ok": True, "cancelled": n}


@app.get("/api/settlement")
def api_settlement(request: Request):
    _require(request)
    s = store.load_settlement()
    if s is None:
        raise HTTPException(404, "not_settled")
    if _is_owner(request):
        return s
    # Bettor view: winner, swimmer's cut, market results, and the per-person payout sheet —
    # house internals (rake, seed rows, per-market house lines) stay admin-only.
    return {
        "winner": s["winner"],
        "swimmer_take": s["swimmer_take"],
        "aggregate": s["aggregate"],
        "markets": [{"market": m["market"], "name": m["name"], "won": m["won"], "void": m["void"]}
                    for m in s["markets"]],
    }


# ── admin API ────────────────────────────────────────────────────────────────────────────────────

@app.get("/api/admin/pending")
def api_pending(request: Request):
    _require_owner(request)
    out = []
    for p in store.pending_bets():
        cur = store.current_approved(p["key"], p["market"])
        # cash the admin must collect: full stake for a new bet; only the delta on a same-outcome
        # raise (the old cash is already in the pool)
        delta = p["amount"] - (cur["amount"] if cur and cur["outcome"] == p["outcome"] else 0)
        out.append({"id": p["id"], "key": p["key"], "display_name": p["display_name"],
                    "market": p["market"], "market_name": rules.MARKET_BY_ID[p["market"]]["name"],
                    "outcome": p["outcome"],
                    "outcome_label": dict(rules.MARKET_BY_ID[p["market"]]["outcomes"])[p["outcome"]],
                    "amount": p["amount"],
                    "current": cur and {"outcome": cur["outcome"], "amount": cur["amount"]},
                    "cash_to_collect": max(delta, 0)})
    return {"pending": out}


@app.post("/api/admin/bets/{bet_id}/approve")
def api_approve(request: Request, bet_id: int):
    u = _require_owner(request)
    r = store.get_race()
    p = store.bet_by_id(bet_id)
    if not p or p["status"] != "pending":
        raise HTTPException(404, "not_pending")
    mine = store.current_approved(p["key"], p["market"])
    ok, reason = rules.can_submit(p["market"], r["phase"], p["outcome"], p["amount"],
                                  laps=r["laps"], current_outcome=mine and mine["outcome"])
    if not ok:  # book may have closed / race moved on since the request was submitted
        store.reject_bet(bet_id, u["key"], note=f"auto-rejected on approve: {reason}")
        raise HTTPException(400, reason)
    store.approve_bet(bet_id, u["key"])
    return {"ok": True}


@app.post("/api/admin/bets/{bet_id}/reject")
def api_reject(request: Request, bet_id: int):
    u = _require_owner(request)
    if not store.reject_bet(bet_id, u["key"]):
        raise HTTPException(404, "not_pending")
    return {"ok": True}


class ManualBet(BaseModel):
    name: str
    outcome: str
    amount: int  # 0 voids the person's bet (e.g. never paid cash)
    market: str = "match"


@app.post("/api/admin/bets/manual")
def api_manual(request: Request, body: ManualBet):
    u = _require_owner(request)
    m = rules.MARKET_BY_ID.get(body.market)
    if not m:
        raise HTTPException(400, "bad_market")
    if body.amount > 0 and body.outcome not in {o for o, _ in m["outcomes"]}:
        raise HTTPException(400, "bad_outcome")
    if body.amount < 0 or not (2 <= len(body.name.strip()) <= 40):
        raise HTTPException(400, "bad_input")
    if store.load_settlement() is not None:
        raise HTTPException(400, "already_settled")
    key = store.admin_manual_bet(body.name, body.market,
                                 body.outcome or m["outcomes"][0][0], body.amount, u["key"])
    return {"ok": True, "key": key}


class HouseSeed(BaseModel):
    outcome: str
    amount: int  # 0 removes the seed


@app.post("/api/admin/house-seed")
def api_house_seed(request: Request, body: HouseSeed):
    """The house's visible position on the match market, hard-capped at the expected rake so
    the organiser can never end up net negative."""
    u = _require_owner(request)
    if body.amount > 0 and body.outcome not in rules.SIDES:
        raise HTTPException(400, "bad_outcome")
    if store.load_settlement() is not None:
        raise HTTPException(400, "already_settled")
    if store.get_race()["phase"] not in rules.OPEN_PHASES:
        raise HTTPException(400, "book_closed")
    human_pool = sum(b["amount"] for b in store.approved_bets("match") if b["key"] != "house")
    cap = rules.max_house_seed(human_pool)
    if body.amount > cap:
        raise HTTPException(400, f"seed_exceeds_rake_cap:{cap}")
    store.set_house_seed("match", body.outcome, body.amount, u["key"])
    return {"ok": True, "cap": cap}


class VoidBet(BaseModel):
    key: str
    market: Optional[str] = None


@app.post("/api/admin/bets/void")
def api_void(request: Request, body: VoidBet):
    u = _require_owner(request)
    if store.load_settlement() is not None:
        raise HTTPException(400, "already_settled")
    n = store.void_key(body.key, u["key"], body.market)
    if not n:
        raise HTTPException(404, "no_live_bet")
    return {"ok": True, "voided": n}


@app.post("/api/admin/race/start-lap")
def api_start_lap(request: Request):
    u = _require_owner(request)
    r = store.get_race()
    try:
        phase = rules.next_phase_on_start_lap(r["phase"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.set_race(phase, r["laps"])
    closed = 0
    if phase == "lap2":  # the book closes for good the moment lap 2 starts
        closed = _close_book(u["key"])
    return {"ok": True, "phase": phase, "auto_rejected_pending": closed}


class LapResult(BaseModel):
    winner: str
    time_s: Optional[float] = None


@app.post("/api/admin/race/lap-result")
def api_lap_result(request: Request, body: LapResult):
    _require_owner(request)
    if body.winner not in rules.SIDES:
        raise HTTPException(400, "bad_winner")
    r = store.get_race()
    laps = r["laps"] + [{"lap": len(r["laps"]) + 1, "winner": body.winner, "time_s": body.time_s}]
    try:
        phase = rules.next_phase_on_lap_result(r["phase"], laps)
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.set_race(phase, laps)
    return {"ok": True, "phase": phase, "race_winner": rules.race_winner(laps)}


@app.post("/api/admin/settle")
def api_settle(request: Request):
    u = _require_owner(request)
    r = store.get_race()
    winner = rules.race_winner(r["laps"])
    if r["phase"] != "finished" or not winner:
        raise HTTPException(400, "race_not_finished")
    store.reject_all_pending(u["key"], "race settled")
    result = rules.settle_all(store.approved_by_market(), r["laps"])
    if not store.save_settlement(result):
        raise HTTPException(400, "already_settled")
    store.set_race("settled", r["laps"])
    return result


@app.post("/api/admin/seed")
def api_seed(request: Request):
    _require_owner(request)
    n = store.seed_bets(SEED_BETS)
    return {"ok": True, "seeded": n}


@app.post("/api/admin/reset-book")
def api_reset_book(request: Request):
    """Wipe every bet and reload the current seed. Only while the race hasn't started —
    the escape hatch for seed corrections (e.g. full names) on an already-seeded book."""
    u = _require_owner(request)
    if store.get_race()["phase"] != "prerace":
        raise HTTPException(400, "race_started")
    n = store.reset_book(SEED_BETS, u["key"])
    return {"ok": True, "seeded": n}


# ── static SPA (marketer dashboard pattern: immutable hashed assets, no-cache index.html) ─────────
class _ImmutableStatic(StaticFiles):
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


if os.path.isdir(os.path.join(DIST, "assets")):
    app.mount("/assets", _ImmutableStatic(directory=os.path.join(DIST, "assets")), name="assets")


@app.get("/{full_path:path}")
def spa(full_path: str):
    if full_path.startswith(("api/", "auth/")):
        raise HTTPException(404)
    index = os.path.join(DIST, "index.html")
    if os.path.isfile(index):
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"error": "frontend not built"}, status_code=503)


store.init()
