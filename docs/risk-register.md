# SeekhoStake — Risk Register

**Companion to:** [`product-architecture.md`](./product-architecture.md), [`product-requirements.md`](./product-requirements.md)
**As of:** commit `e0c73d2`, 24 Sept 2026 (3 days before the event this system serves)

Severity is scored as **impact if the risk materializes** (Critical/High/Medium/Low), independent of current likelihood — a Critical/currently-mitigated risk still needs its mitigation documented and verified, not dismissed. Priority (P0–P3) reflects urgency of *further* action given current mitigation state.

---

## Update — 24 Sept 2026, second review pass (separate session, same day)

A second, independent review pass landed the following against this exact register, verified by the 1,402-test suite (1,390 existing + 12 new) after each change:

- **R-3 (concurrent-approval race) — now RESOLVED.** The recommended partial unique index (`one_approved_per_person_market`) is live in `store.init()`. **New, adjacent finding also fixed:** `store.submit_bet()` had the SAME class of race one step earlier in the lifecycle — two near-simultaneous first-time *submits* (not approvals) for the same person/market could both land as live `pending` rows on Postgres (SQLite's coarse whole-database locking masks this locally, which is why it was easy to miss). Fixed with an app-level lock (`_submit_lock`, same pattern as the existing `_approve_lock`) plus a `threading.Barrier`-based regression test.
- **R-5 (no rate limiting) — partially mitigated, not closed.** `/auth/admin` and `/auth/test` (the two endpoints that accept a shared secret) now rate-limit at 10 attempts/5 min, keyed on `X-Forwarded-For` with a same-process fallback. General mutating-endpoint rate limiting (e.g. `POST /api/bets`) — the register's original broader recommendation — is still not implemented; deprioritized because `/api/bets` is already bounded by the new `MAX_BET_AMOUNT` guard plus the existing arbitrage/house-floor guards, making the password-guessing surfaces the higher-value target for the time available.
- **R-10 (no idempotency key on `POST /api/bets`) — the specific race is closed, the literal recommendation is not.** The register's fix (a client-supplied idempotency key) was not built. Instead the underlying double-insert race itself is closed by `_submit_lock` above — same outcome (no duplicate pending rows) via a narrower, backend-only mechanism that didn't require a frontend contract change. Worth still doing the idempotency key for Track B (a real API contract, not an internal lock).
- **R-14 (`/docs`/`/openapi.json` unauthenticated) — not addressed this pass.** Still open.
- **Architecture §13 "Health checks: None" — now RESOLVED.** `GET /healthz` added (unauthenticated, checks DB reachability, returns 503 on failure), registered ahead of the SPA catch-all route.
- **Architecture §14 "no structured logging" — partially addressed.** Not the recommended structured-JSON-per-request log (still open) — instead, targeted `logging` calls at the specific safety-critical events: circuit-breaker suspend/clear, manual suspend/resume, settlement, arbitrage rejection at approve-time, rate-limit trips, failed admin-password attempts. Deliberately not a general access log (uvicorn's own stdout log + Railway's capture already covers that).
- **New finding — name-mode identity collision (not previously in this register).** `AUTH_MODE=name` (the OAuth-outage fallback) keyed bettors purely by a normalized slug of their typed name. Two different people typing names that normalize to the same slug (extra space, punctuation, casing — e.g. "Rahul Sharma" vs "Rahul  Sharma!!") would silently share one identity: same session key, same bet slot, same payout row. Fixed with a collision guard (`409 name_taken`) backed by both DB history (`store.name_on_file`) and an in-process claims map (catches the case where neither person has bet yet, which a DB-only check would miss). **Severity was High if it had fired** (misattributed money) **but likelihood was Low** — prod runs `AUTH_MODE=oauth` (confirmed live via `/api/config`), where identity is a globally-unique Google email and this class of collision cannot occur; exposure was real only if the fallback were ever activated with two similarly-named bettors. Also fixed in passing: `store.py`'s admin-manual-entry slug function and `api.py`'s name-mode-login slug function had silently diverged (`str.isalnum()` vs. an ASCII-only regex — the same person could key differently depending on which path recorded them first for any name containing a non-ASCII character). Consolidated into one shared `engine.name_slug()`.
- **New finding — no upper bound on bet amount (not previously in this register).** `BetIn.amount`/`ManualBet.amount` had no ceiling. Not a financial-safety gap (the payout cap and `house_floor` guard already make any single stake safe regardless of size) but a fat-finger/abuse gap — a typo'd extra zero would have been silently accepted. Fixed with `MAX_BET_AMOUNT` (₹10,00,000 — ~16x the entire real pre-race pool, so it can never bind on a legitimate bet).
- **New finding — SSE broadcaster thread-safety (not previously in this register, adjacent to R-8).** `_notify()` called `asyncio.Queue.put_nowait()` directly from sync route handlers, which FastAPI runs in a worker thread, not the event loop thread — `asyncio.Queue` is documented as not thread-safe from outside the loop. Fixed with `loop.call_soon_threadsafe()`, capturing each subscriber's loop at connect time. Low real-world impact given the existing 15s fallback poll and focus/visibility refresh, but a genuine correctness bug, not just a style nit.
- **New finding — `requirements.txt` used unpinned `>=` ranges (not previously in this register).** A fresh `docker build` re-resolves dependencies from scratch on every deploy with no lockfile; an unpinned range could silently pull a newer, untested major version on any future rebuild that changes nothing else in the diff. Pinned to the exact versions the full suite is green against.
- **CI (R-7 / R-18, architecture §15) — the automated test gate now exists.** `.github/workflows/ci.yml` runs the full pytest suite and the frontend build on every push/PR to `main`. This closes the "not automated as a gate" half of R-7; the staging-environment half of R-7 is still open.

None of the above required a database migration beyond the one already in flight (the unique index), and none touch production data — every fix was developed and tested exclusively against local ephemeral SQLite.

---

## Update — 24 Sept 2026, third pass: Slack alerting + docs lockdown

- **R-11 (no automated alerting) — narrowed, not closed.** Added `_alert_slack()`, a fire-and-forget Slack Incoming Webhook post (`SLACK_WEBHOOK_URL` env var; no-op, logs-only, when unset). Wired to three triggers: (1) a market auto-suspending in `api_approve` (event-driven, the exact `house_floor < 0` condition this risk names), (2) any unhandled exception anywhere in the app (global `@app.exception_handler(Exception)`, path-keyed 5-minute dedup so a repeatedly-failing endpoint pings once, not on every hit), and (3) a market that *stays* suspended (the one case needing a poll — a daemon thread checks every 2 min, nudges at most once per 15 min per still-suspended set, closing the "20 minutes with nobody looking" gap this section originally flagged as the top open item). **What this still does not cover, so R-11 stays open at lower priority:** a settlement anomaly with no suspension event, and — the more fundamental gap — the process dying outright rather than throwing a handled exception, since all three triggers above run inside that same process and die with it; only an external uptime check against `/healthz` closes that. Downgraded High → **Medium**, P1 → **P2**.
- **R-14 (`/docs`/`/openapi.json` unauthenticated) — RESOLVED.** `docs_url`/`redoc_url`/`openapi_url` all `None` unless `SWIMBET_DEV=1`. Verified both ways (DEV: reachable; prod-mode env: all three `None`) before landing.
- **R-3 addendum — approve-time constraint violation now handled cleanly.** The `one_approved_per_person_market` DB index from the prior pass had no corresponding application-level handling — a hit would have surfaced as a raw 500. `api_approve` now catches `IntegrityError` specifically and returns `409 already_approved`. Should be unreachable given `_approve_lock`; this is the "belt" to the lock's "suspenders," not a new mitigation layer on its own.

**Update — 24 Sept 2026, fourth pass: `SLACK_WEBHOOK_URL` set and verified live.** Confirmed directly against Railway (`railway variable list`) and by reading `#seekhostake-alerts` back via the Slack API — the test post from webhook setup is actually sitting in the channel, not just accepted with a 200. All three triggers above are now live, not log-only. See `docs/release-checklist.md` for the remaining pre-Sunday action plan (external `/healthz` monitor, R-4 second admin) this pass produced.

---

## Summary table (all risks)

| ID | Category | Risk | Severity | Current mitigation | Priority |
|---|---|---|---|---|---|
| R-1 | Compliance | Real-money betting's legal status in India is unresolved for this product's fact pattern | **Critical** | None — not a technical mitigation, needs counsel | **P0** |
| R-2 | Operational | Postgres backup/restore status unverified | **Critical** | None confirmed | **P0** |
| R-3 | Technical | No DB-level constraint on "one approved bet per person per market" — concurrent approval race | High | App-level transaction logic only | P1 |
| R-4 | Operational | Single point of failure: one admin (`OWNER_EMAILS`), one laptop/session, no backup operator | High | None | P1 |
| R-5 | Security | No rate limiting on bet submission / any mutating endpoint | Medium | None | P1 |
| R-6 | Financial | No segregation of duties — one person holds cash, approves bets, sets liquidity, and settles | High | Mitigated in effect by extensive automated guards (arbitrage guard, house floor, payout cap), not by an independent human check | P2 |
| R-7 | Operational | No CI/staging — every code change (including today's live circuit-breaker patch) deploys straight to production | High | Strong test suite partially substitutes; not automated as a gate | **P0** |
| R-8 | Technical | In-memory SSE subscriber set breaks under >1 process/instance | Medium (N/A at current scale) | Documented; single-instance today | P3 (P0 if scaled horizontally) |
| R-9 | Security | Test-login auth-bypass code path (`/auth/test`) still exists in source, currently dormant | Medium | `TEST_LOGIN_PASSWORD` env var confirmed empty (404s) | P2 |
| R-10 | Technical | No idempotency key on `POST /api/bets` — retry/double-submit risk | Medium | UI disables button after submit (not server-enforced) | P1 |
| R-11 | Operational | Automated alerting exists for suspend/error/stuck-suspended, but nothing external notices if the process itself dies | Medium | Slack alerting live (3 triggers, verified) | P2 |
| R-12 | Technical | Singleton schema (`race.id=1`, `settlements.id=1`) blocks a second event and has no isolation if ever violated | Medium | None — architectural | P1 |
| R-13 | Compliance | No data retention / deletion policy stated anywhere | Low | Minimal PII footprint reduces impact | P2 |
| R-14 | Security | OpenAPI docs (`/docs`, `/openapi.json`) reachable unauthenticated in production | Low-Medium | None | P2 |
| R-15 | Financial | Arbitrage guard checks per-individual key; does not detect collusion across two or more real, distinct people placing complementary bets | Medium | Partial — single-actor arbitrage fully blocked | P2 |
| R-16 | Financial | Manual house-seed/liquidity placement by admin is a human-judgment input to an otherwise-guarded system | Low (now) | Cap + floor check enforced server-side as of today | P3 |
| R-17 | Operational | Concurrent unreviewed direct-to-`main` edits from multiple sessions/humans on the same files, observed repeatedly today | Medium | None — no branch/PR/review process | P2 |
| R-18 | Technical | SSE behavior through Railway's proxy/edge under load not independently verified beyond today's single-event scale | Low | `X-Accel-Buffering: no` header set defensively | P3 |
| R-19 | Operational | Google OAuth is a hard external dependency for login; no tested failover procedure | Medium | `AUTH_MODE=name` fallback exists but requires an env var change + redeploy to activate | P2 |

---

## Detailed write-ups: P0 and highest-impact P1 risks

### R-1 — Legal status of real-money betting (Critical, P0)

**Description.** India's 2025 Online Gaming Act prohibits real-money online games nationally regardless of skill/chance classification. The Public Gambling Act 1867 and state-level statutes add further, untested-against-this-fact-pattern exposure even for a private, closed-group, no-operator-margin, cash-settled pool among colleagues at one company. This has not been reviewed by counsel.

**Impact if it materializes.** Ranges from "this specific activity needs to stop" to more serious exposure depending on facts (frequency, scale, whether it's seen as company-sanctioned) that only a lawyer can assess.

**Current mitigation.** None from an engineering standpoint — engineering controls (guaranteed non-negative house position, zero operator profit margin by design) reduce *financial* risk but do not address *legal* risk, which is a separate axis entirely.

**Recommended action.** Get qualified legal counsel to review the specific fact pattern before running this again, before broadening the participant group, and especially before introducing any digital money movement. See architecture §0.

**Owner.** Abhay (business decision), not resolvable by further engineering.

---

### R-2 — Unverified backups (Critical, P0)

**Description.** The Railway-managed Postgres plugin's backup/point-in-time-recovery configuration was not explicitly checked or configured during today's rapid build-out. Railway does not guarantee automatic backups on every plan tier.

**Impact if it materializes.** Total loss of the bet book, settlement history, and race state with no recovery path — on the day of an actual live financial event, this is the single most damaging *technical* failure mode available (worse than any bug, because a bug can be fixed while data loss cannot be undone).

**Current mitigation.** None confirmed.

**Recommended action (do this before 27 Sept):**
1. Check the Railway dashboard for the Postgres plugin's backup settings.
2. If automatic backups aren't available on the current plan, add a scheduled `pg_dump` (even a simple cron-style export to local storage or cloud storage before and during the event) as a manual stopgap.
3. Test one restore, even into a throwaway database, to confirm the backup is actually usable — an unverified backup is not meaningfully different from no backup.

**Owner.** Whoever has Railway dashboard access (Abhay).

---

### R-3 — Concurrent-approval race condition (High, P1)

**Description.** `approve_bet` supersedes an existing approved row and inserts the new one inside one transaction, but without an explicit row lock or a database-level uniqueness constraint on `(key, market, status='approved')`. Two near-simultaneous approve calls for the same person+market (double-click, or a second admin in the future) could both succeed, producing two "approved" rows for one person in one market — violating the core invariant every odds/settlement calculation assumes.

**Impact if it materializes.** Incorrect odds, incorrect settlement for that person/market, and — because the invariant is assumed rather than checked at read time — the corruption would not be visibly flagged; it would just silently produce a wrong number.

**Current mitigation.** Low collision probability today (single admin, sequential UI clicks); no structural prevention.

**Recommended action.** Add a Postgres partial unique index: `CREATE UNIQUE INDEX one_approved_per_person_market ON bets (key, market) WHERE status = 'approved'`. See architecture §6.1 for the full detail and rollback plan (trivially reversible, additive, no behavior change under normal operation).

**Owner.** Engineering.

---

### R-4 — Single point of failure: one admin (High, P1)

**Description.** `OWNER_EMAILS` contains exactly one address. If Abhay's phone/laptop is unavailable, his session expires at an inconvenient moment, or he's simply not present at the exact moment a lap result needs recording, **no one else can approve bets, record results, or settle** — the entire event stalls.

**Impact if it materializes.** Best case: a delay. Worst case (mid-race, book needs to close at a specific moment, or a market needs urgent suspension): a missed window with financial consequences for bettors.

**Current mitigation.** None — this is a genuine single point of failure by design.

**Recommended action.** Before the event: add at least one trusted second person to `OWNER_EMAILS` (the code already supports a comma-list) purely as a break-glass measure, even without formally defining the narrower "operations" role from architecture §12. Cheap, immediate, zero code change.

**Owner.** Abhay (operational decision, five-minute fix).

---

### R-7 — No CI/staging (High, P0)

**Description.** Every commit today — including the volatility circuit breaker, the payout cap, and the house-floor gate, all designed and shipped **during a live, in-progress betting event** — went from local edit straight to `git push` to Railway auto-deploy to production, with no automated test gate and no staging environment to rehearse against. The 1,390-test suite exists and is genuinely strong, but nothing forces it to run before a deploy; it was only run manually, by discipline, in this session.

**Impact if it materializes.** A change that breaks a test (or breaks something the tests don't cover) ships directly to a live financial event with no safety net beyond "someone happened to run pytest first."

**Current mitigation.** Strong test suite, run manually and consistently in practice today — but that's process discipline, not a system guarantee.

**Recommended action.** Add a GitHub Actions workflow gating every push to `main`: run the full pytest suite and the frontend build; only deploy on green. Add a second Railway environment (staging) with its own Postgres for pre-production smoke testing. See architecture §15.

**Owner.** Engineering.

---

### R-11 — Automated alerting exists, process-liveness monitoring doesn't (Medium, P2)

**Description.** Originally: every incident was caught by a human noticing, not a system signal. **Now resolved for the in-process case:** `_alert_slack()` fires to `#seekhostake-alerts` on market auto-suspend (instant), any unhandled exception (5-min dedup/endpoint), and a market that stays suspended (15-min nudge) — verified live 24 Sept by reading the channel back via the Slack API, not just trusting the webhook's 200. **What remains:** all three triggers run inside the one uvicorn process — if it dies outright (OOM, crash, Railway restart hang) rather than throwing a handled exception, nothing fires, because the alerting code dies with it. A settlement anomaly with no suspension event also has no dedicated check.

**Impact if it materializes.** The process-death gap: total silence during an outage, same as before this pass, just narrowed to that one failure mode. The settlement-anomaly gap: a bad settlement could go unnoticed post-race (lower urgency — race is one-shot, reconciliation happens right after per the runbook, not hours later).

**Current mitigation.** Slack alerting live for the three in-process triggers above (see Update, 24 Sept fourth pass).

**Recommended action.** External uptime monitor (UptimeRobot or Railway's own alerting) polling `/healthz` — the process-death case can only be closed from outside the process itself. ~5 minutes to set up, doesn't require a code change. See `docs/release-checklist.md` for the full prioritized list this pass produced, including why the settlement-anomaly check is lower priority than it looks (race is one-shot, not a recurring exposure window).

**Owner.** Engineering (uptime monitor setup) / Abhay (Railway or UptimeRobot account access).

---

## Notes on risks that are lower priority than they might first appear

- **R-8 (SSE horizontal-scaling limit)** is architecturally real but currently irrelevant — there is exactly one instance and no plan to add a second for this event. It's recorded so it isn't forgotten *if* scaling is ever attempted, not because it needs action now.
- **R-16 (manual house-seed placement)** was the literal subject of today's live incident, and is now the **best-mitigated** risk in this register precisely because of that — the cap+floor guard added today makes a reckless seed placement mathematically rejected rather than merely discouraged. Recorded here for completeness and audit trail, not because it's currently a live concern.
- **R-9 (test-login backdoor)** is confirmed dormant (`TEST_LOGIN_PASSWORD` is set to an empty string in the live environment, which the code treats as "feature disabled, route 404s"). The residual risk is purely "someone sets that env var again without realizing what it re-enables" — worth a P2 cleanup (delete the route entirely post-event) rather than urgent action.

## Notes on risks worth a second read even though they're not P0/P1

- **R-15 (collusion across the arbitrage guard)** is a sharp, easy-to-miss gap: `person_floor` evaluates one bettor's own aggregate position across markets. Two *different*, real people — not a duplicate account, an actual collusion pair — placing complementary bets that together are riskless is invisible to a guard scoped to individual identity. At 19-30 known colleagues betting for fun, the incentive to collude for an economically trivial edge is low, which is why this sits at P2 rather than higher — but it is a genuine limitation of the current guard's scope, not a false alarm, and should be re-evaluated if the stakes or participant count grow.
- **R-17 (unreviewed concurrent editing)** is not hypothetical — it happened repeatedly during today's session: two sources of edits landed in the same files, one test assertion was observed mid-flight in an inconsistent state before settling, and multiple commits bundled unrelated changes because whichever `git commit` ran first captured whatever was on disk at that moment. Nothing broke today, but the absence of branches, PRs, or review is a process gap independent of any single bug, and its likelihood of eventually causing a real conflict grows with every additional contributor or session working the same repository this way.
