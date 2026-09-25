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
import time
import asyncio
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

import engine as rules
import store
from seed import SEED_BETS

# Deliberately minimal: not a general request/access log (uvicorn already emits one to stdout,
# which Railway captures) — just the handful of safety-critical, irreversible, or security-
# relevant events that are otherwise invisible between requests. Bet-level audit trail already
# lives in the DB itself (bets.decided_by/decided_at/note on every mutation).
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("swimbet")

# ── Slack alerting ───────────────────────────────────────────────────────────────────────────────
# Fire-and-forget notification for the two kinds of event that mean "a human should look at this
# right now": a market auto-suspending (real financial risk, see odds_swing/house_floor below) and
# an unhandled server error (a bug). Silently a no-op when unset — same "invisible until
# configured" pattern as TEST_LOGIN_PASSWORD — so this is safe to ship ahead of the webhook existing.
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "").strip()


def _alert_slack(text: str) -> None:
    if not SLACK_WEBHOOK_URL:
        return
    try:
        httpx.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=5)
    except Exception:
        log.exception("Slack alert failed to send")


DEV = os.environ.get("SWIMBET_DEV", "").lower() in ("1", "true", "yes")
AUTH_MODE = os.environ.get("AUTH_MODE", "oauth").lower()  # oauth | name
_HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(_HERE, "frontend", "dist")

# Betting closes ahead of the race itself (Sunday 27 Sept), independent of race phase — a fixed
# UTC+5:30 offset rather than a zoneinfo tz name, since python:3.11-slim has no guarantee of
# tzdata being installed and India never observes DST, so the offset is always exactly this.
_IST = timezone(timedelta(hours=5, minutes=30))
BETTING_DEADLINE = datetime(2026, 9, 27, 13, 0, 0, tzinfo=_IST)
BETTING_DEADLINE_LABEL = "1:00 PM, Sunday 27 Sept (IST)"


def _betting_closed_by_deadline() -> bool:
    return datetime.now(timezone.utc) >= BETTING_DEADLINE

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

# /docs, /redoc and the raw /openapi.json schema are a reconnaissance gift to anyone who finds the
# URL — every route, param, and model shape laid out for free. No auth benefit to hiding them (the
# routes still enforce their own checks), but no reason to publish the map either. Kept in DEV only.
app = FastAPI(
    title="Swim Bet — Khuseel vs Bansod",
    docs_url="/docs" if DEV else None,
    redoc_url="/redoc" if DEV else None,
    openapi_url="/openapi.json" if DEV else None,
)
app.add_middleware(SessionMiddleware, secret_key=_session_secret(),
                   same_site="lax", https_only=not (DEV or _ALLOW_HTTP))

# Same-origin app (SPA served from this process, API on the same origin, no third-party embeds).
# style-src needs 'unsafe-inline' for exactly one thing: the two pool-bar width indicators in
# App.jsx (`style={{width: ...}}`), locally computed numbers, not attacker-reachable — every other
# directive stays closed. HSTS only when the connection is actually HTTPS-only (mirrors
# https_only above); on plain-http LAN dev mode it would wrongly force https on the next request.
_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'")


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Content-Security-Policy"] = _CSP
    if not (DEV or _ALLOW_HTTP):
        resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return resp


# Registering a handler for the base Exception class does not steal HTTPException's own handler —
# Starlette resolves by most-specific-registered-class, so the deliberate HTTPException(...) calls
# all over this file (404/400/409/…) are untouched. This only ever fires for genuine bugs.
_last_error_alert: dict[str, float] = {}  # path -> unix ts, so a repeatedly-failing endpoint pings once
_ERROR_ALERT_COOLDOWN_S = 300  # every occurrence is still logged; only the Slack ping is throttled


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled exception on %s %s", request.method, request.url.path)
    path = request.url.path
    now = time.time()
    if now - _last_error_alert.get(path, 0.0) > _ERROR_ALERT_COOLDOWN_S:
        _last_error_alert[path] = now
        _alert_slack(
            f":boom: *Unhandled server error* on `{request.method} {path}`\n"
            f"`{type(exc).__name__}: {exc}`\nCheck Railway logs for the full traceback."
        )
    return JSONResponse(status_code=500, content={"detail": "internal_error"})


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


# In-memory limiter for the two password-gated endpoints (/auth/admin, /auth/test). Per-process
# state — consistent with the SSE broadcaster's existing single-process assumption (no --workers
# in the Dockerfile CMD). Keyed on X-Forwarded-For (Railway's edge sets this; request.client.host
# alone would be Railway's internal proxy address for every visitor, collapsing all callers into
# one bucket) with a same-process fallback — a best-effort deterrent against scripted guessing,
# not a hard security boundary (the header is client-influenceable if a proxy doesn't overwrite it).
_login_attempts: "dict[str, list[float]]" = {}
_RATE_LIMIT_WINDOW_S = 300
_RATE_LIMIT_MAX = 10


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(request: Request, bucket: str):
    key = f"{bucket}:{_client_ip(request)}"
    now = time.monotonic()
    hits = [t for t in _login_attempts.get(key, []) if now - t < _RATE_LIMIT_WINDOW_S]
    if len(hits) >= _RATE_LIMIT_MAX:
        log.warning("rate limit tripped: bucket=%s ip=%s", bucket, _client_ip(request))
        raise HTTPException(429, "too_many_attempts")
    hits.append(now)
    _login_attempts[key] = hits


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


# Name-mode has no password, no email — just whatever the bettor types, normalized to a slug
# (rules.name_slug). Two different people can type names that normalize to the same slug (extra
# space, punctuation, casing) and would otherwise silently become the SAME identity: same session
# key, same bet slot, same payout row. store.name_on_file() catches this once a bet exists under
# the key, but two people who both log in before either has bet yet would slip past a DB-only
# check — so also track the first name seen per key in-process. Same single-process assumption as
# the SSE broadcaster and the rate limiter (no --workers in the Dockerfile CMD); resets on a
# restart, which only means a stale claim is forgotten, never that an active session breaks.
_name_claims: "dict[str, str]" = {}


@app.post("/auth/name")
def auth_name(request: Request, body: NameLogin):
    """Race-morning fallback identity: first name = identity. Only active in AUTH_MODE=name."""
    if AUTH_MODE != "name":
        raise HTTPException(400, "oauth mode: use /auth/login")
    name = body.name.strip()
    if not (2 <= len(name) <= 40):
        raise HTTPException(400, "bad_name")
    key = rules.name_slug(name)
    on_file = store.name_on_file(key) or _name_claims.get(key)
    if on_file is not None and on_file.strip().lower() != name.lower():
        # Same normalized slug, different typed name (e.g. "Rahul Sharma" vs "Rahul  Sharma!!"
        # both -> name:rahulsharma) — plausibly a DIFFERENT person, not the same one logging in
        # again. Refuse rather than silently handing this session someone else's identity, bets,
        # and payout; the bettor retypes with a distinguishing detail (surname, initial) instead.
        raise HTTPException(409, "name_taken")
    _name_claims.setdefault(key, name)
    request.session["user"] = {"key": key, "name": name}
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
    _check_rate_limit(request, "test")
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
    _check_rate_limit(request, "admin")
    if body.password != expected:
        log.warning("admin login: wrong password from %s", _client_ip(request))
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


def _is_arbitrage(key, market, outcome, amount, laps):
    """Would approving this bet (on top of the person's OTHER already-approved positions) give
    them a guaranteed profit in every possible race outcome? Simulates the post-approval book:
    the candidate replaces any existing approved bet the person holds in the same market
    (mirroring real supersede semantics), then checks person_floor > 0 across all race scripts."""
    by_market = store.approved_by_market()
    rows = list(by_market.get(market, []))
    by_market[market] = [b for b in rows if b["key"] != key] + [
        {"key": key, "display_name": "candidate", "outcome": outcome, "amount": amount}]
    return rules.person_floor(by_market, key, laps) > 0


# ── live updates (SSE) ──────────────────────────────────────────────────────────────────────────
# One in-process broadcaster: every mutating endpoint calls _notify() after it commits, which
# wakes every connected client's queue. Clients then re-fetch /api/state themselves — the stream
# carries no payload, just a "something changed" ping, so sanitization stays exactly where it
# already lives (api_state/api_settlement) with no duplicate logic to keep in sync. Requires a
# single uvicorn process (true here — no --workers flag in the Dockerfile CMD); multiple workers
# would each hold their own subscriber set and miss each other's events.
#
# Each entry pairs a subscriber's queue with the event loop it was created on. Mutating routes are
# sync `def`s that FastAPI runs in a worker thread, not the event loop thread — asyncio.Queue is
# documented as NOT thread-safe, so calling q.put_nowait() directly from _notify() (a non-loop
# thread) is a data race on the queue's internal state. loop.call_soon_threadsafe() is the
# sanctioned way to schedule loop-affecting work from another thread.
_subscribers: "set[tuple[asyncio.Queue, asyncio.AbstractEventLoop]]" = set()

# api_approve's before/approve/after/suspend-decision sequence is three separate DB transactions,
# not one atomic unit. Sync routes run in FastAPI's threadpool, so two concurrent Approve calls on
# the SAME market can genuinely interleave and corrupt each other's before/after swing snapshot —
# found by review, confirmed by simulation: ~10% of randomized concurrent-approval interleavings
# produced a missed volatility detection. Serializing all approvals behind one lock costs nothing
# at this app's scale (one admin, clicking buttons) and removes the race entirely.
_approve_lock = threading.Lock()

# store.submit_bet() is an UPDATE-then-INSERT (cancel any existing pending row, then insert the
# new one) across two statements in one transaction — safe on SQLite (whole-database write lock
# serializes the two transactions outright) but NOT on Postgres (prod): under READ COMMITTED, an
# UPDATE that matches zero rows takes no lock, so two near-simultaneous first-time submits from
# the same person in the same market (double-tap, retried request) can both see "nothing pending
# yet" and both INSERT, leaving two live 'pending' rows for one person. Settlement is never at
# risk (approve_bet supersedes on approval regardless), but the admin's pending queue and cash-to-
# collect math would double-count until the duplicate is manually rejected. Same fix shape as
# _approve_lock, kept as a separate lock since it guards an unrelated statement pair.
_submit_lock = threading.Lock()


def _put_nowait_safe(q: asyncio.Queue):
    try:
        q.put_nowait(1)
    except asyncio.QueueFull:
        pass  # a ping is already queued for this client — coalesces fine, next fetch is fresh


def _notify():
    for q, loop in list(_subscribers):
        try:
            loop.call_soon_threadsafe(_put_nowait_safe, q)
        except RuntimeError:
            pass  # loop already closed (shutdown) — subscriber is gone anyway


@app.get("/api/stream")
async def api_stream(request: Request):
    _require(request)
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    loop = asyncio.get_running_loop()
    entry = (q, loop)
    _subscribers.add(entry)

    async def gen():
        try:
            yield "retry: 2000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    await asyncio.wait_for(q.get(), timeout=20)
                    yield "data: update\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # comment ping — holds the connection through proxies
        finally:
            _subscribers.discard(entry)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── public API ───────────────────────────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    """Unauthenticated liveness/readiness probe — process up AND database reachable. For
    Railway's own health checks and any external uptime monitor. Must stay registered ahead of
    the SPA catch-all route below (route order matters: the catch-all matches any path)."""
    try:
        store.get_race()
    except Exception:  # noqa: BLE001 — any DB failure means "not ready", detail is irrelevant here
        return JSONResponse({"ok": False}, status_code=503)
    return {"ok": True}


@app.get("/api/config")
def api_config():
    """Unauthenticated: the login screen needs to know which auth mode to render, and shows the
    betting deadline so it's visible before anyone even signs in."""
    return {"auth_mode": AUTH_MODE,
            "test_login": bool(os.environ.get("TEST_LOGIN_PASSWORD")),
            "betting_deadline": BETTING_DEADLINE.isoformat(),
            "betting_deadline_label": BETTING_DEADLINE_LABEL,
            "betting_closed": _betting_closed_by_deadline()}


@app.get("/api/state")
def api_state(request: Request, as_user: bool = False):
    """The one endpoint the UI polls: race, every market's live book/odds, the caller's positions.
    as_user=1 lets the admin preview the exact bettor-sanitized payload."""
    u = _require(request)
    can_admin = _is_owner(request)
    owner = can_admin and not as_user
    r = store.get_race()
    by_market = store.approved_by_market()
    all_pending = store.pending_bets()
    pending_by_market = {}
    for p in all_pending:
        pending_by_market.setdefault(p["market"], []).append(p)
    my_pendings = {p["market"]: p for p in all_pending if p["key"] == u["key"]}
    mine_all = {b["market"]: b for b in store.my_approved(u["key"])}
    deadline_passed = _betting_closed_by_deadline()

    markets = []
    for m in rules.MARKETS:
        mid = m["id"]
        # Displayed (indicative) odds include pending requests so the market reflects demand the
        # moment it's submitted; settlement always uses approved cash only.
        #
        # A bettor's pending request (a raise, or a pre-race side-switch) represents their CURRENT
        # intent and will supersede their existing approved row in this market if/when it's
        # approved — so while it's pending, count only the pending amount here, not both. Without
        # this exclusion the display double-counts them (old approved + new pending) for as long
        # as the request sits in the queue: e.g. an approved ₹1,000 bet raised to ₹2,500 would
        # show the pool as +₹3,500, not the correct +₹2,500, until the admin acts on it.
        pending_here = pending_by_market.get(mid, [])
        pending_keys_here = {p["key"] for p in pending_here}
        approved_here = [b for b in by_market.get(mid, []) if b["key"] not in pending_keys_here]
        rows = approved_here + pending_here
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
                                if b["key"].startswith("house") and b["outcome"] == oid)
                house_n = sum(1 for b in rows if b["key"].startswith("house") and b["outcome"] == oid)
                shown_totals[oid] = (o["total"] - house_amt, o["bettors"] - house_n)
        my = mine_all.get(mid)
        pend = my_pendings.get(mid)
        suspended = mid in r["suspended"]
        # Same per-bettor visibility already shipped for the match market (house rows are the
        # organiser's own liquidity, not a bettor's cash, so they're owner-only) — generalized here
        # to every market so admin and bettors alike can see who's actually in each side book, not
        # just the match book. Approved rows only (mirrors match: a pending raise doesn't replace
        # the row here until it's actually approved).
        market_bets = sorted(
            ({"key": b["key"], "display_name": b["display_name"], "side": b["outcome"], "amount": b["amount"]}
             for b in by_market.get(mid, []) if owner or not b["key"].startswith("house")),
            key=lambda b: -b["amount"])
        markets.append({
            "id": mid, "name": m["name"], "sub": m.get("sub"), "main": bool(m.get("main")),
            "open": r["phase"] in m["open_phases"] and not suspended and not deadline_passed,
            "suspended": suspended,
            "pool": sum(t for t, _ in shown_totals.values()),
            "outcomes": [{"id": oid, "label": book["outcomes"][oid]["label"],
                          "est_mult": book["outcomes"][oid]["est_mult"],
                          "total": shown_totals[oid][0], "bettors": shown_totals[oid][1],
                          "alive": rules.outcome_alive(mid, oid, r["laps"])}
                         for oid, _ in m["outcomes"]],
            "my_bet": my and {"outcome": my["outcome"], "amount": my["amount"]},
            "my_pending": pend and {"id": pend["id"], "outcome": pend["outcome"],
                                    "amount": pend["amount"]},
            "bets": market_bets,
        })

    match_rows = by_market.get("match", [])
    out = {
        "auth_mode": AUTH_MODE,
        "me": {"key": u["key"], "name": u["name"], "is_owner": owner, "can_admin": can_admin},
        "race": {"phase": r["phase"], "laps": r["laps"],
                 "wins": rules.lap_wins(r["laps"]),
                 "book_open": r["phase"] in rules.OPEN_PHASES and not deadline_passed},
        "markets": markets,
        "betting_deadline_label": BETTING_DEADLINE_LABEL,
        "betting_closed": deadline_passed,
        "bets": sorted(({"key": b["key"], "display_name": b["display_name"],
                         "side": b["outcome"], "amount": b["amount"]}
                        for b in match_rows if owner or not b["key"].startswith("house")),
                       key=lambda b: -b["amount"]),
        "settled": store.load_settlement() is not None,
    }
    if owner:
        human_pool = sum(b["amount"] for b in match_rows if not b["key"].startswith("house"))
        seed = store.house_seed()
        out["rake_pct"] = int(rules.HOUSE_RAKE * 100)
        out["pending_count"] = len(store.pending_bets())
        out["house"] = {"seed": seed and {"outcome": seed["outcome"], "amount": seed["amount"]},
                        "seed_cap": rules.max_house_seed(human_pool),
                        "floor": rules.house_floor(by_market, r["laps"])}
    return out


class BetIn(BaseModel):
    market: str = "match"
    outcome: str
    amount: int


@app.post("/api/bets")
def api_submit_bet(request: Request, body: BetIn):
    u = _require(request)
    if _betting_closed_by_deadline():
        raise HTTPException(400, "betting_closed")
    # See _submit_lock docstring: serializes the read-then-cancel-then-insert so two concurrent
    # submits from the same person/market can never both land as live 'pending' rows.
    with _submit_lock:
        r = store.get_race()
        mine = store.current_approved(u["key"], body.market)
        ok, reason = rules.can_submit(body.market, r["phase"], body.outcome, body.amount,
                                      laps=r["laps"], current_outcome=mine and mine["outcome"],
                                      suspended=body.market in r["suspended"])
        if not ok:
            raise HTTPException(400, reason)
        if _is_arbitrage(u["key"], body.market, body.outcome, body.amount, r["laps"]):
            raise HTTPException(409, "arbitrage_bet")
        bet_id = store.submit_bet(u["key"], u["name"], body.market, body.outcome, body.amount)
    _notify()
    return {"ok": True, "id": bet_id, "status": "pending"}


class CancelIn(BaseModel):
    market: Optional[str] = None


@app.post("/api/bets/cancel")
def api_cancel_bet(request: Request, body: CancelIn = CancelIn()):
    u = _require(request)
    n = store.cancel_pending(u["key"], body.market)
    if n:
        _notify()
    return {"ok": True, "cancelled": n}


@app.get("/api/settlement")
def api_settlement(request: Request, as_user: bool = False):
    _require(request)
    s = store.load_settlement()
    if s is None:
        raise HTTPException(404, "not_settled")
    if _is_owner(request) and not as_user:
        return s
    # Bettor view: winner, swimmer's cut, market results, and the per-person payout sheet —
    # house internals (rake, seed rows, per-market house lines) stay admin-only.
    return {
        "winner": s["winner"],
        "swimmer_take": s["swimmer_take"],
        "aggregate": s["aggregate"],
        "markets": [{"market": m["market"], "name": m["name"], "won": m["won"],
                     "won_label": m.get("won_label"), "void": m["void"]}
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


@app.get("/api/admin/bets")
def api_all_bets(request: Request):
    """Full bet ledger — every request ever made, any status, across all markets — so the admin
    can find and correct one that isn't pending or approved (already rejected, cancelled, or
    superseded), not just act on what's currently in the queue. Each row carries the CURRENT
    estimated odds for its own (market, outcome), computed on the same approved+pending basis
    as /api/state's owner view, so "what's allocated to who" is one glance, not a cross-reference
    against the odds board."""
    _require_owner(request)
    by_market = store.approved_by_market()
    pending_by_market = {}
    for p in store.pending_bets():
        pending_by_market.setdefault(p["market"], []).append(p)
    books = {}
    for m in rules.MARKETS:
        mid = m["id"]
        rows = by_market.get(mid, []) + pending_by_market.get(mid, [])
        books[mid] = rules.market_book(mid, rows)

    out = []
    for b in store.all_bets():
        m = rules.MARKET_BY_ID.get(b["market"])
        outcome_book = books.get(b["market"], {}).get("outcomes", {}).get(b["outcome"])
        est_mult = outcome_book["est_mult"] if outcome_book else None
        out.append({
            "id": b["id"], "key": b["key"], "display_name": b["display_name"],
            "market": b["market"], "market_name": m["name"] if m else b["market"],
            "outcome": b["outcome"],
            "outcome_label": dict(m["outcomes"]).get(b["outcome"], b["outcome"]) if m else b["outcome"],
            "amount": b["amount"], "status": b["status"], "source": b["source"],
            "est_mult": est_mult,
            "est_payout": round(b["amount"] * est_mult) if est_mult else None,
            "created_at": b["created_at"].isoformat(),
            "decided_at": b["decided_at"].isoformat() if b["decided_at"] else None,
        })
    return {"bets": out}


class StatusChange(BaseModel):
    status: str


@app.post("/api/admin/bets/{bet_id}/status")
def api_set_status(request: Request, bet_id: int, body: StatusChange):
    """Admin override: force any bet directly to a new status, regardless of its current one —
    for correcting mistakes (wrong tap, cash paid after a reject, an approve that needs undoing).
    Distinct from /approve and /reject (the normal cash-collection flow, which stays the primary
    path and keeps its own arbitrage/circuit-breaker checks on the INCOMING bet); this is the
    blunt escape hatch for a bet that's already been decided, so like admin_manual_bet it skips
    those bettor-facing checks — but it still can't break the one-approved/one-pending-per-
    person-per-market invariants (store.set_status supersedes in the same transaction), and a
    move that newly approves a bet still gets the house re-checked afterward, same protection
    the real approve flow gives the house."""
    u = _require_owner(request)
    if body.status not in store.ADMIN_SETTABLE_STATUSES:
        raise HTTPException(400, "bad_status")
    if store.load_settlement() is not None:
        raise HTTPException(400, "already_settled")
    with _approve_lock:
        try:
            old = store.set_status(bet_id, body.status, u["key"])
        except IntegrityError:
            # Belt-and-suspenders, same as api_approve: the one_approved_per_person_market index
            # is the last line of defense if this handler's own supersede-then-set is ever raced.
            log.error("set_status hit one_approved_per_person_market constraint: bet_id=%s status=%s",
                      bet_id, body.status)
            raise HTTPException(409, "already_approved")
        if old is None:
            raise HTTPException(404, "not_found")
        out = {"ok": True, "old_status": old["status"], "new_status": body.status}
        if body.status == "approved" and old["status"] != "approved":
            floor = rules.house_floor(store.approved_by_market(), store.get_race()["laps"])
            if floor < 0:
                store.suspend_market(old["market"])
                out["suspended_market"] = old["market"]
                out["floor"] = floor
                log.warning("market AUTO-SUSPENDED on status override: market=%s bet_id=%s floor=%d",
                           old["market"], bet_id, floor)
                _alert_slack(
                    f":rotating_light: *Market auto-suspended* — `{old['market']}`\n"
                    f"Status override on bet #{bet_id} left the house uncovered on some outcome "
                    f"(worst case {floor:+d}). Betting paused on this market only — review and "
                    f"resume from the admin panel."
                )
    if old["status"] != body.status:
        log.info("bet status overridden: bet_id=%s %s->%s by=%s", bet_id, old["status"], body.status, u["key"])
        _notify()
    return out


@app.post("/api/admin/bets/{bet_id}/approve")
def api_approve(request: Request, bet_id: int):
    u = _require_owner(request)
    # Whole handler serialized: see _approve_lock docstring. Cheap at this app's real call volume,
    # and removes any interleaving between this approval's before/after swing snapshot and another
    # concurrent one on the same market (or a second approval racing the same pending bet).
    with _approve_lock:
        r = store.get_race()
        p = store.bet_by_id(bet_id)
        if not p or p["status"] != "pending":
            raise HTTPException(404, "not_pending")
        mine = store.current_approved(p["key"], p["market"])
        ok, reason = rules.can_submit(p["market"], r["phase"], p["outcome"], p["amount"],
                                      laps=r["laps"], current_outcome=mine and mine["outcome"],
                                      suspended=p["market"] in r["suspended"])
        if not ok:  # book may have closed / race moved on since the request was submitted
            store.reject_bet(bet_id, u["key"], note=f"auto-rejected on approve: {reason}")
            _notify()
            raise HTTPException(400, reason)
        if _is_arbitrage(p["key"], p["market"], p["outcome"], p["amount"], r["laps"]):
            store.reject_bet(bet_id, u["key"], note="auto-rejected on approve: arbitrage_bet")
            log.warning("arbitrage bet auto-rejected AT APPROVE: key=%s market=%s bet_id=%s",
                       p["key"], p["market"], bet_id)
            _notify()
            raise HTTPException(409, "arbitrage_bet")
        # Circuit breaker: a thin market can be swung 5-10x by one realistically-sized bet. Compare
        # this market's odds before vs after approving — a big swing is a PROXY for risk, not risk
        # itself, so before acting on it we check the actual invariant the whole engine is built on:
        # house_floor (worst-case organiser take across every possible race outcome, right now, with
        # this bet included). If the house is provably safe regardless, there is nothing to protect —
        # clear it instantly and stay live. Only a swing that ALSO leaves the house exposed suspends
        # the market for a human. One synchronous check, no polling: this is as fast as it gets — a
        # background loop would only add latency for a number we already have in hand.
        before = rules.market_book(p["market"], store.approved_bets(p["market"]))
        try:
            approved = store.approve_bet(bet_id, u["key"])
        except IntegrityError:
            # Belt-and-suspenders: the one_approved_per_person_market DB index (store.init) is the
            # last line of defense if _approve_lock is ever bypassed or a second process exists —
            # should be unreachable in normal operation, but a clean 409 beats a raw 500 either way.
            log.error("approve_bet hit one_approved_per_person_market constraint: bet_id=%s key=%s market=%s",
                      bet_id, p["key"], p["market"])
            raise HTTPException(409, "already_approved")
        if approved is None:
            # store.approve_bet's own fresh check found the row no longer 'pending' — the bettor
            # cancelled (or it was otherwise resolved) in the narrow window between this handler's
            # top-level check and approve_bet's internal one. Nothing was approved; report that
            # honestly instead of falling through to a false {"ok": True} (before/after would both
            # read the unchanged book, so the swing check alone would never have caught this).
            raise HTTPException(404, "not_pending")
        after = rules.market_book(p["market"], store.approved_bets(p["market"]))
        swing_ratio, swing_outcome = rules.odds_swing(p["market"], before, after, laps=r["laps"])
        suspended_now = False
        swing_cleared = False
        floor = None
        if swing_ratio > rules.VOLATILITY_SUSPEND_RATIO:
            floor = rules.house_floor(store.approved_by_market(), r["laps"])
            if floor >= 0:
                swing_cleared = True  # house safe regardless of outcome — nothing to protect
                log.info("swing cleared: market=%s outcome=%s ratio=%.2f floor=%d",
                         p["market"], swing_outcome, swing_ratio, floor)
            else:
                store.suspend_market(p["market"])
                suspended_now = True
                log.warning("market AUTO-SUSPENDED: market=%s outcome=%s ratio=%.2f floor=%d bet_id=%s",
                           p["market"], swing_outcome, swing_ratio, floor, bet_id)
                _alert_slack(
                    f":rotating_light: *Market auto-suspended* — `{p['market']}`\n"
                    f"Outcome `{swing_outcome}` swung {swing_ratio:.2f}x on bet #{bet_id}, "
                    f"projected house floor {floor:+d}. Betting paused on this market only — "
                    f"review and resume from the admin panel."
                )
        _notify()
        out = {"ok": True}
        if suspended_now:
            out["suspended_market"] = p["market"]
            out["swing"] = {"outcome": swing_outcome, "ratio": round(swing_ratio, 2), "floor": floor}
        elif swing_cleared:
            out["swing_cleared"] = {"outcome": swing_outcome, "ratio": round(swing_ratio, 2), "floor": floor}
        return out


@app.post("/api/admin/bets/{bet_id}/reject")
def api_reject(request: Request, bet_id: int):
    u = _require_owner(request)
    if not store.reject_bet(bet_id, u["key"]):
        raise HTTPException(404, "not_pending")
    _notify()
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
    if body.amount < 0 or body.amount > rules.MAX_BET_AMOUNT or not (2 <= len(body.name.strip()) <= 40):
        raise HTTPException(400, "bad_input")
    if store.load_settlement() is not None:
        raise HTTPException(400, "already_settled")
    key = store.admin_manual_bet(body.name, body.market,
                                 body.outcome or m["outcomes"][0][0], body.amount, u["key"])
    _notify()
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
    human_pool = sum(b["amount"] for b in store.approved_bets("match") if not b["key"].startswith("house"))
    cap = rules.max_house_seed(human_pool)
    if body.amount > cap:
        raise HTTPException(400, f"seed_exceeds_rake_cap:{cap}")
    prev = store.house_seed()
    store.set_house_seed("match", body.outcome, body.amount, u["key"])
    floor = rules.house_floor(store.approved_by_market(), store.get_race()["laps"])
    if floor < 0:  # would create a losing scenario — revert and refuse
        store.set_house_seed("match", prev["outcome"] if prev else "bansod",
                             prev["amount"] if prev else 0, u["key"])
        raise HTTPException(400, f"floor_negative:{floor}")
    _notify()
    return {"ok": True, "cap": cap, "floor": floor}


class SideSeeds(BaseModel):
    per_market: int = 200  # total house liquidity per market; 0 clears
    tilt: bool = True      # split by outcome priors (Bansod skill edge) vs evenly


def _side_seed_rows(per_market, tilt):
    rows = []
    for m in rules.MARKETS:
        if m.get("main"):
            continue
        oids = [oid for oid, _ in m["outcomes"]]
        if per_market == 0:
            rows += [(m["id"], oid, 0) for oid in oids]
            continue
        if tilt:
            pri = rules.outcome_priors(m["id"])
            amts = {oid: max(10, int(round(pri[oid] * per_market / 10) * 10)) for oid in oids}
        else:
            amts = {oid: per_market // len(oids) for oid in oids}
        rows += [(m["id"], oid, amts[oid]) for oid in oids]
    return rows


def _apply_side_seeds(per_market, tilt, admin_email):
    """House liquidity on every side-market outcome so boards open with informed odds instead of
    a blank dash (no bettor, no odds to quote). tilt=true splits each market's liquidity by
    outcome priors (BANSOD_PRIOR), so likelier outcomes open short and long shots open
    attractive. Shared by the manual /api/admin/side-seeds endpoint AND the auto-seed-on-book-
    load hook (api_seed/api_reset_book) — same money-safety net either way: verify house_floor
    afterward and revert immediately if this would ever leave the house exposed. Never raises;
    callers that must fail loudly on a bad floor (the manual endpoint) check r["ok"] themselves,
    callers that must not let this block a bigger action (the auto-seed hooks) just log it."""
    rows = _side_seed_rows(per_market, tilt)
    prev = {(b["market"], b["outcome"]): b["amount"]
            for b in store.approved_bets() if b["key"].startswith("house:")}
    n = store.seed_side_markets(rows, admin_email)
    floor = rules.house_floor(store.approved_by_market(), store.get_race()["laps"])
    if floor < 0:  # would create a losing scenario — restore previous liquidity and refuse
        restore = [(mid, oid, prev.get((mid, oid), 0)) for mid, oid, _ in rows]
        store.seed_side_markets(restore, admin_email)
        return {"ok": False, "floor": floor, "outcomes_seeded": 0}
    return {"ok": True, "floor": floor, "outcomes_seeded": n}


@app.post("/api/admin/side-seeds")
def api_side_seeds(request: Request, body: SideSeeds):
    u = _require_owner(request)
    if body.per_market < 0 or body.per_market > 2000:
        raise HTTPException(400, "bad_amount")
    if store.load_settlement() is not None:
        raise HTTPException(400, "already_settled")
    r = _apply_side_seeds(body.per_market, body.tilt, u["key"])
    if not r["ok"]:
        raise HTTPException(400, f"floor_negative:{r['floor']}")
    _notify()
    return {"ok": True, "outcomes_seeded": r["outcomes_seeded"], "per_market": body.per_market,
            "tilt": body.tilt, "floor": r["floor"]}


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
    _notify()
    return {"ok": True, "voided": n}


@app.post("/api/admin/markets/{market_id}/resume")
def api_resume_market(request: Request, market_id: str):
    """Clears a circuit-breaker suspension so the market accepts bets again."""
    u = _require_owner(request)
    if market_id not in rules.MARKET_BY_ID:
        raise HTTPException(400, "bad_market")
    store.resume_market(market_id)
    log.info("market manually resumed: market=%s by=%s", market_id, u["key"])
    _notify()
    return {"ok": True}


@app.post("/api/admin/markets/{market_id}/suspend")
def api_suspend_market(request: Request, market_id: str):
    """Manual override: the automatic breaker only trips on a NEW approval that crosses the
    ratio, so it can't retroactively flag a market that already swung before this check existed
    (or before liquidity was topped up). This lets the organiser pause one by hand."""
    u = _require_owner(request)
    if market_id not in rules.MARKET_BY_ID:
        raise HTTPException(400, "bad_market")
    store.suspend_market(market_id)
    log.warning("market manually suspended: market=%s by=%s", market_id, u["key"])
    _notify()
    return {"ok": True}


@app.post("/api/admin/markets/recheck")
def api_recheck_markets(request: Request):
    """Re-runs the real safety check (house_floor, not the odds-swing proxy) and, if the house is
    provably safe regardless of outcome, clears EVERY currently suspended market — including ones
    paused by hand — e.g. after liquidity was topped up, or for markets suspended before this
    check existed. One-shot, synchronous, no polling: if you want a market to stay paused for a
    reason unrelated to money (e.g. reviewing something), don't call this while it matters."""
    _require_owner(request)
    r = store.get_race()
    floor = rules.house_floor(store.approved_by_market(), r["laps"])
    cleared = []
    if floor >= 0:
        for mid in r["suspended"]:
            store.resume_market(mid)
            cleared.append(mid)
        if cleared:
            _notify()
    return {"ok": True, "floor": floor, "cleared": cleared,
            "still_suspended": [m for m in r["suspended"] if m not in cleared]}


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
    _notify()
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
    _notify()
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
    log.info("RACE SETTLED: winner=%s house_take=%d swimmer_take=%d total_pool=%d by=%s",
             result["winner"], result["house_take"], result["swimmer_take"],
             result["total_pool"], u["key"])
    _notify()
    return result


@app.get("/api/admin/projected-payouts")
def api_projected_payouts(request: Request):
    """Read-only preview: 'how much do I owe everyone' under every race outcome that's still
    possible from here — before the race, or mid-race with some laps already decided. Reuses
    rules.settle_all() and rules.race_scripts() exactly as real settlement does (see api_settle
    above), so a projection can never drift from what /api/admin/settle would actually produce
    for that same outcome. Never writes anything — no settlement is created, nothing is mutated;
    it's the same math the house_floor/arbitrage guards already run internally, just surfaced."""
    _require_owner(request)
    if store.load_settlement() is not None:
        raise HTTPException(400, "already_settled")
    r = store.get_race()
    by_market = store.approved_by_market()
    scripts = []
    for laps in rules.race_scripts(r["laps"]):
        result = rules.settle_all(by_market, laps)
        scripts.append({
            "laps": laps,
            "winner": result["winner"],
            "wins": rules.lap_wins(laps),
            "aggregate": result["aggregate"],
            "swimmer_take": result["swimmer_take"],
            "house_take": result["house_take"],
            "total_pool": result["total_pool"],
        })
    return {"scripts": scripts}


@app.post("/api/admin/seed")
def api_seed(request: Request):
    u = _require_owner(request)
    n = store.seed_bets(SEED_BETS)
    if n:
        # Side markets used to sit at a blank "no odds yet" until someone remembered to press
        # the separate "Seed side odds" button — easy to forget, and a market with zero house
        # liquidity shows nothing to bet against until a human happens to bet both sides. Folding
        # it into the book load makes every side market start with a real (floor-guarded) price
        # the moment the main book does, with no extra step.
        r = _apply_side_seeds(200, True, u["key"])
        if not r["ok"]:
            log.warning("auto side-seed on /seed skipped: floor would go negative (%d)", r["floor"])
        _notify()
    return {"ok": True, "seeded": n}


@app.post("/api/admin/reset-book")
def api_reset_book(request: Request):
    """Wipe every bet and reload the current seed. Only while the race hasn't started —
    the escape hatch for seed corrections (e.g. full names) on an already-seeded book."""
    u = _require_owner(request)
    if store.get_race()["phase"] != "prerace":
        raise HTTPException(400, "race_started")
    n = store.reset_book(SEED_BETS, u["key"])
    if n:
        r = _apply_side_seeds(200, True, u["key"])
        if not r["ok"]:
            log.warning("auto side-seed on /reset-book skipped: floor would go negative (%d)", r["floor"])
    _notify()
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


# ── Suspended-market watchdog ────────────────────────────────────────────────────────────────────
# api_approve already alerts the instant a market auto-suspends (event-driven, zero latency). What
# that can't catch: a market that's SAT suspended for the last 20 minutes because everyone's
# attention moved on. This is the other half — a periodic nudge, cheap and simple since there's
# only ever one process (R-8): a plain daemon thread, no scheduler/cron dependency needed. Fires at
# most once per _SUSPENDED_NUDGE_INTERVAL_S per still-suspended set, not every poll, so it reminds
# rather than spams.
_SUSPENDED_WATCHDOG_POLL_S = 120
_SUSPENDED_NUDGE_INTERVAL_S = 900
_last_suspended_nudge = 0.0


def _suspended_watchdog() -> None:
    global _last_suspended_nudge
    while True:
        time.sleep(_SUSPENDED_WATCHDOG_POLL_S)
        try:
            suspended = store.get_race()["suspended"]
        except Exception:
            log.exception("suspended-market watchdog: could not read race state")
            continue
        if not suspended:
            continue
        now = time.time()
        if now - _last_suspended_nudge > _SUSPENDED_NUDGE_INTERVAL_S:
            _last_suspended_nudge = now
            log.warning("suspended-market watchdog nudge: still suspended=%s", suspended)
            _alert_slack(
                f":warning: *Still suspended*: `{', '.join(suspended)}` — no admin action yet "
                f"(checked every {_SUSPENDED_WATCHDOG_POLL_S // 60} min). Resume from the admin "
                f"panel once reviewed, or leave paused if still investigating."
            )


threading.Thread(target=_suspended_watchdog, daemon=True, name="suspended-watchdog").start()
