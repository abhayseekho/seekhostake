# SeekhoStake — Test Strategy

**Companion to:** [`product-architecture.md`](./product-architecture.md), [`risk-register.md`](./risk-register.md) (R-7)

---

## 1. What exists today (and it's genuinely good)

| File | Lines | What it tests | Style |
|---|---|---|---|
| `tests/test_engine.py` | ~236 | Core settlement math per market, phase machine, `can_submit` rule enforcement, house-floor enumeration basics. | Deterministic unit tests against hand-built bet books. |
| `tests/test_house_floor_fuzz.py` | ~349 | Property-based: the house cannot end an event net-negative under any of ~6 possible race outcomes, across randomized and deliberately adversarial bet-book constructions (everyone on one outcome, single huge bettor, seeds placed exactly at the cap, dead-outcome-only pools). Also proves the guard is *load-bearing* by constructing an unguarded case that *does* lose money, then showing the guard rejects it. Also covers the payout cap (`MAX_PAYOUT_MULT`) under fuzz. | Property/fuzz testing with fixed (deterministic) seeds. |
| `tests/test_arbitrage.py` | ~382 | Zero-sum audit (every rupee is accounted for across bettors + swimmer + house, exactly), `person_floor` correctness on hand-built portfolios, the arbitrage guard's actual blocking behavior, cross-market consistency of tilted seed liquidity. | Mix of deterministic and fuzzed cases. |
| `tests/test_e2e.py` | ~607 | Full-stack lifecycle via FastAPI's `TestClient` against the real `api.py` module and a temp SQLite DB: happy path (seed → house seed → tilted liquidity → bet → approve → lap flow → settle), rule enforcement over real HTTP (`book_closed`, `no_side_switch`, `outcome_dead`, raise-supersede, cancel, auto-reject at lap 2, settle-once), guard enforcement over HTTP (seed-above-cap → 400, seed-pushing-floor-negative → 400 + revert, arbitrage bet → 409), sanitization parity (admin vs bettor payloads), cash-reconciliation arithmetic at every step. | Integration, real HTTP layer, real (temp) database. |

**Total: 1,390+ tests, run in under 10 seconds, fully deterministic (fuzz seeds are fixed, not wall-clock-random).**

This is a genuinely strong foundation — stronger, in the settlement/risk domain specifically, than most production betting systems' test suites, because it was built adversarially from day one (the explicit goal was "can the house lose, can a person arbitrage, is it zero-sum" rather than just "does the happy path work"). The gap is not depth in this domain; it's **breadth outside it**.

---

## 2. What's missing

| Area | Current coverage | Gap | Priority |
|---|---|---|---|
| Engine / settlement math | Excellent (fuzz + deterministic) | None significant | — |
| API integration (HTTP layer) | Good (`test_e2e.py`) | No explicit test of the SSE stream itself (connect, receive a ping, disconnect cleanly) | P2 |
| Frontend components | **None** | Zero component tests on `BetSlip`, `Admin`, `OddsBoard`, etc. | P1 |
| Frontend E2E (real browser) | **None automated** — today's verification was manual (this session, via browser automation tools, repeatedly, including against production) | No Playwright/Cypress suite | P2 |
| Security / authz | **None automated** — manually verified today (owner vs bettor payload sanitization, test-login gating) | No test asserting a bettor session gets 403 on every `/api/admin/*` route | **P1** |
| Load / performance | **None** | No test of concurrent bet submission, no measurement of `/api/state` latency under N simultaneous pollers | P2 |
| Chaos / failure injection | **None** | No test of "DB connection drops mid-transaction," "SSE broadcaster queue full," etc. | P3 |
| Concurrency / race conditions | **None** | The exact race described in architecture §6.1 (concurrent approve) has no regression test — cannot, until the DB constraint exists to make the "before" state observable as a bug | P1 (write once the constraint lands) |
| Migration testing | **None** | The `ALTER TABLE ADD COLUMN IF NOT EXISTS` migrations have never been tested against a database that already has real production data and a different starting schema version | P2 |
| Reconciliation (as a running check, not a unit test) | Asserted inside settlement (`sum == pool`), not run as a standing job against live state | Promote to a scheduled production check (see Ops Runbook) | P1 |

---

## 3. Target test matrix

| Layer | Tool / approach | Runs when | Status |
|---|---|---|---|
| **Unit** (pure functions, `engine.py`) | pytest | Every commit (locally today; should be CI-gated) | ✅ Strong |
| **Property / fuzz** (adversarial bet books) | pytest + fixed-seed randomization | Every commit | ✅ Strong |
| **Integration** (API + real DB, `TestClient`) | pytest + FastAPI `TestClient` + temp SQLite | Every commit | ✅ Good |
| **Contract** (API schema stability) | Not present — recommend a snapshot test of `/openapi.json` that fails on an unintentional breaking change | Every commit | ❌ Missing (P3 — low urgency, single consumer) |
| **Frontend component** | React Testing Library, focused on `BetSlip` and `Admin` approve flow | Every commit | ❌ Missing (P1) |
| **Frontend E2E** | Manual today; recommend Playwright for the golden path (login → bet → approve → settle) as a smoke test | Before each deploy (once CI exists) | ❌ Missing (P2) |
| **Security / authz matrix** | pytest — every `/api/admin/*` route asserted to 403 for a non-owner session, every `/api/*` route asserted to 401 for no session | Every commit | ❌ Missing (P1) |
| **Load** | k6 or locust — simulate 30-50 concurrent pollers + a burst of simultaneous bet submissions around a lap-result moment | Before a scale-up decision, not routinely needed at current size | ❌ Missing (P2, low urgency at current scale) |
| **Reconciliation** (production) | Scheduled job comparing `sum(approved bets)` to admin-confirmed cash, and `house_floor` sign | Continuously during a live event | ❌ Missing (P1 — see Ops Runbook) |
| **Manual exploratory** | Human clicking through the real UI | Every significant feature, done consistently well today | ✅ Practiced, not written down until now |

---

## 4. Production-safe testing approach

This is the section that matters most given the actual operating reality: **there is one production environment, no staging, and testing against it has repeatedly meant testing against a live, real-money event** (this happened multiple times today, including the circuit-breaker work being verified against the actual production odds board mid-race-week). That is a real constraint, not a hypothetical one, and pretending a textbook "always test in staging" answer solves it would be dishonest — staging doesn't exist yet (architecture §15, R-7). Given that, here is what's actually safe to do **today**, and what should exist **before the next event**:

### 4.1 Safe today (already in use, formalize as documented practice)

- **`?as_user=1` / "View as user" preview.** Already built specifically as a safe way for the admin to see the exact sanitized bettor payload without needing a second real account. This is a legitimate production-testing tool and should be used before every UI change that touches bettor-facing sanitization.
- **`SWIMBET_DEV=1` local mode + local SQLite.** Fully isolated from production; every engine/API change was (and should continue to be) exercised here first, seeded via `seed.py`, before touching prod.
- **Read-only production probes.** Fetching `/api/state` as the authenticated admin to inspect real numbers (pool, odds, `house_floor`) is safe — it's a `GET`, it mutates nothing. This was used extensively today to *diagnose* the odds-sensitivity incident before writing a single line of the fix.
- **Manual endpoint tests with immediate reversal.** When a production mutation genuinely needed verifying live (e.g., confirming the circuit breaker actually suspends a market), the pattern used today was: perform the smallest possible real mutation, verify, then immediately reverse it (resume the market, void the test bet) — acceptable **only** because it was done by the admin, with real understanding of the reversal, not as a general practice to extend to anyone else.

### 4.2 Not safe today, and should not be repeated (documented honestly, not to assign blame — to fix the gap)

- **Testing a new circuit-breaker/guard change by triggering it against the real production book during a live event window**, as happened today. It worked, and the test suite backing the change was strong, but the *only* thing standing between "worked" and "a live financial event was disrupted by a bug in a same-day patch" was the quality of manual verification in the moment. That is not a repeatable safety margin.

### 4.3 What to build before next relying on "test in prod" again

1. **A staging environment** (second Railway environment + Postgres, same Dockerfile) — the single highest-leverage fix, already called out in architecture §15/R-7. Every "let's verify this against real-shaped data" instinct from today should go here instead of production.
2. **Synthetic/seeded bettor fixtures for staging** — the existing `seed.py` book is a perfect starting point; extend it with a couple of deliberately adversarial synthetic bettors (a thin-market whale, a rapid-fire submitter) so staging can reproduce today's exact incident on demand as a regression test.
3. **A CI gate** (GitHub Actions running the full pytest suite + frontend build) so "did I break anything" is answered before merge, not after a live probe.
4. **Feature flags for risk-sensitive logic** — even a simple env-var toggle (`ENABLE_VOLATILITY_BREAKER=1`) would have let today's circuit-breaker ship "dark" (deployed but inert) to production, then be flipped on deliberately at a chosen moment rather than going live the instant the deploy finished.

---

## 5. Reviewing this test suite itself

One meta-recommendation: the existing 1,390 tests are excellent at their job but concentrated in one file family (`engine.py`'s domain). As the codebase grows (ledger, RBAC, multi-event), resist the temptation to let test *count* substitute for test *coverage breadth* — a thousand more fuzz cases against the same settlement function add diminishing value compared to the first test of, say, the authz matrix (currently zero tests) or the SSE stream itself (currently zero tests). Track coverage by *area*, not by raw test count, going forward.
