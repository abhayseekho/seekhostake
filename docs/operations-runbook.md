# SeekhoStake — Operations Runbook

**Companion to:** [`risk-register.md`](./risk-register.md), [`product-architecture.md`](./product-architecture.md)
**Audience:** whoever holds admin access on event day (today: Abhay only — see R-4, fix this first)

---

## 1. Environment overview

| Item | Value |
|---|---|
| Production URL | `https://seekhostake-production.up.railway.app` |
| Railway workspace / project | Seekho Projects / `gracious-renewal` |
| Railway service | `seekhostake` |
| Database | Railway-managed Postgres plugin, single volume (`postgres-volume`) |
| Repo | `github.com/abhayseekho/seekhostake`, single branch `main`, auto-deploys on push |
| Auth | Google OAuth (`@seekhoapp.com` domain), fallback `AUTH_MODE=name` + `ADMIN_PASSWORD` |
| Admin identity | `OWNER_EMAILS` env var (currently one address) |

**Access needed to operate this runbook:** Railway CLI logged in with access to the `seekhostake` service (`railway link`), `git` push access to the repo, and the Google account listed in `OWNER_EMAILS`.

---

## 2. Deployment procedure (normal path)

This is exactly the procedure exercised successfully many times during development — it works, and it's fast (typically 60-120 seconds from push to live).

```bash
cd swim-bet
git add -A && git commit -m "…"
git push origin main
```

Railway auto-builds the committed `Dockerfile` and replaces the running container. To confirm the new build is actually live (don't assume — verify):

```bash
# Watch for the new backend surface to appear (adjust the grep target to whatever
# the change actually adds — a new route, a new field in /api/config, etc.)
until curl -s https://seekhostake-production.up.railway.app/openapi.json | grep -q '"/api/your-new-route"'; do sleep 15; done

# Confirm the frontend bundle hash actually changed (index.html references a
# content-hashed JS file; if it's the same hash as before the deploy, the SPA
# didn't actually rebuild — check the Railway build logs)
curl -s https://seekhostake-production.up.railway.app/ | grep -o 'index-[A-Za-z0-9_-]*\.js'
```

**Known gotcha (hit today):** a rolling deploy can briefly serve a stale `index.html` referencing an asset hash from the *previous* build (edge-cache propagation lag), returning a 404 for the new hash for a few seconds. If the bundle-hash check above fails once, wait 5-10 seconds and retry before concluding the deploy failed.

**Before every deploy that touches auth, secrets, or the DB schema:** re-read the diff once specifically for anything that could 500 on boot — `store.init()` runs migrations synchronously at process start, and a bad migration statement takes the whole service down, not just one feature.

---

## 3. Rollback procedure

Exercised today under real pressure, and it works cleanly because there is no other rollback mechanism (no feature flags, no blue/green — see architecture §15):

```bash
git log --oneline -10                 # find the last known-good commit
git revert <bad-commit-sha>           # NEVER git reset --hard on a shared/pushed branch
git push origin main
# then re-run the deploy verification steps in §2
```

If the bad commit already caused data corruption (not just a code bug), a code rollback alone is **not** sufficient — see §6 (Disaster Recovery) for the data side.

---

## 4. Monitoring & health checks

**What exists today:**
- `GET /healthz` — unauthenticated, checks DB reachability, returns `{"ok": true}`/200 or `{"ok": false}`/503. Added in the second review pass; suitable for Railway's own health checking and any future external uptime monitor (e.g. UptimeRobot hitting this URL every minute is a five-minute setup and a real improvement over "nothing," complementary to the Slack alerting below, not a substitute for it — `/healthz` only tells you the process is up, not that it's a process that would ever fire an alert if something inside it broke).
- **Slack alerting (third review pass, live once `SLACK_WEBHOOK_URL` is set — see §8):** three triggers, all event-driven rather than a polling loop for the two that can be, since the moment of concern is already computed synchronously where it happens —
  1. A market auto-suspends (`api_approve`'s circuit breaker) — fires the instant it happens.
  2. Any unhandled server exception, anywhere — a global FastAPI exception handler, deduped per-endpoint-path to one alert per 5 minutes so a repeatedly-failing endpoint pings once, not on every request.
  3. A market that's *stayed* suspended — the one case that genuinely needs polling, since nothing else re-triggers on it: a background thread checks every 2 minutes and nudges Slack at most once per 15 minutes per still-suspended set.
  All three no-op to log-only (no exception, no crash) if `SLACK_WEBHOOK_URL` isn't set — safe to have shipped ahead of the webhook existing.
- Targeted application logs (`logging`, stdout — see Railway's raw logs) at safety-critical events: circuit-breaker suspend/clear, manual suspend/resume, settlement, arbitrage rejection at approve-time, rate-limit trips, failed admin-password attempts. Not a general access log — still no per-request structured logging (§14's fuller recommendation is still open).
- Manually fetching `/api/state` as admin and reading `house.floor`, `pending_count`, and each market's `suspended` flag.
- A human watching the live site.

**Manual health check to run at the start of every session working on this system, and periodically during a live event:**

```bash
curl -s https://seekhostake-production.up.railway.app/healthz
# expect: {"ok":true}

curl -s https://seekhostake-production.up.railway.app/api/config
# expect: {"auth_mode":"oauth","test_login":false, ...}
# test_login MUST be false in production — if it's ever true, the auth-bypass
# endpoint is live; see risk register R-9.
```

Then, as an authenticated admin (via the app, not curl, since it needs a session cookie):
- `house.floor` should be `>= 0`. If negative, see the incident playbook below immediately.
- No market should show `suspended: true` for longer than the admin intends — a forgotten suspended market silently blocks all bets on it.

**Remaining gap (P2, downgraded from P1 now that the above is live):** nothing external watches `/healthz` itself yet — if the process dies outright rather than throwing a handled exception, none of the three Slack triggers above fire, since they all run inside the same process. An external uptime monitor (UptimeRobot or Railway's own alerting, pointed at `/healthz`) closes that specific gap and is a five-minute setup whenever it's prioritized.

---

## 5. Incident response

### 5.1 General playbook

1. **Read-only diagnosis first.** `GET /api/state` as admin, check Railway logs. Do not mutate anything until you understand what's happening.
2. **If money/settlement is at risk:** use the market-level pause, not a full outage — `POST /api/admin/markets/{id}/suspend` stops new bets on exactly the affected market while everything else keeps running. There is no "pause the whole platform" button by design; a single-market pause is almost always the right scope.
3. **If it's a code bug:** fix locally, run the full test suite (`SWIMBET_DEV=1 .venv/bin/python -m pytest tests/ -q`), deploy per §2, verify.
4. **If it's a data/config issue** (e.g., a bad manual bet entry, a house seed placed in error): use the existing admin tools (void-by-key, manual-bet-amount-zero, house-seed-amount-zero) rather than direct database edits — every one of these already goes through `_notify()` and keeps the audit trail (`note`, `decided_by`) intact. Only touch the database directly as an absolute last resort, and never during a live event without a backup taken immediately first.
5. **After resolution:** run `POST /api/admin/markets/recheck` to auto-clear any suspension the fix has made safe, and write down what happened (see the worked example below — this runbook should grow one entry per real incident).

### 5.2 Worked example: the odds-sensitivity incident (24 Sept 2026)

This actually happened during development and is kept here verbatim as the runbook's first real case study.

**Symptom.** Abhay observed (via a screenshot) that after a single real bettor placed one bet, Lap 1/2 Winner odds swung to Khuseel 8.31× / Bansod 1.07×, and Lap 3 Winner swung the opposite way to Khuseel 1.05× / Bansod 9.93×.

**Diagnosis.** Fetched `/api/state` as admin, read the exact per-market pool and per-outcome totals. Confirmed: these side markets had only ~₹200 of seeded liquidity each; a single ₹500 real bet against a ~₹120 pool mechanically produces a 3-5× swing under correct parimutuel math (`market_book`'s formula: `pool_after_rake / stake_on_outcome`). Not a bug — a genuine thin-liquidity exposure.

**Resolution (in order, each deployed and verified before the next):**
1. `MAX_PAYOUT_MULT = 7` — hard cap on any single stake's payout multiple, applied identically to displayed odds and actual settlement.
2. `VOLATILITY_SUSPEND_RATIO = 2.0` — any approval that swings a market's odds past 2× triggers a check.
3. That check was refined from "always suspend on a big swing" to "suspend **only if** `house_floor` (the exact worst-case-across-every-outcome number) would actually go negative — otherwise clear instantly and stay live," because the odds-ratio was only ever a *proxy* for risk, and the real invariant (`house_floor`) was already computed elsewhere in the codebase and trusted.
4. Manual pause/resume and a `recheck` endpoint were added so the admin has full override in both directions, independent of the automatic logic.
5. The three affected markets, which had swung *before* the breaker existed and so weren't automatically caught, were rechecked against the new logic and cleared (`house_floor` was `+₹2,418` — genuinely safe) via `POST /api/admin/markets/recheck`.

**Follow-up captured in this review:** the underlying cause (side markets seeded with liquidity far thinner than realistic bet sizes) is a liquidity-provisioning decision, not a bug — worth revisiting the seed amounts before the next event now that real bet-size distribution is observed.

---

## 6. Reconciliation

### 6.1 Pre-race (cash-in-hand check)

Run this before lap 1 starts, every event:

- For every row in the admin's "Match-winner book" and every side-market book, confirm physical cash collected matches the displayed `amount` — the admin console's pending queue already shows "cash to collect" per request at approval time, so if approvals were done correctly in the moment, this should already reconcile. Treat any mismatch as a stop-the-clock issue, not a "reconcile later" one.
- Confirm `house.seed_cap` and any placed house seed amount make sense against the current human pool — the system will refuse to let a seed exceed the cap, but sanity-check the *displayed* number matches intent.

### 6.2 Post-settlement (payout check)

- The settlement payload is mathematically guaranteed to sum to the pool (asserted in code, fuzz-tested). The manual check that still matters is **process, not math**: confirm every bettor listed in the payout sheet actually receives the exact cash amount shown, and get a lightweight acknowledgment (even a verbal "got it" or a tick on a paper list) — the system cannot verify that the *physical handoff* happened, only that the *number* is correct.

---

## 7. Disaster recovery

**Current status: unverified — do this before the next event, not after a loss (risk register R-2).**

1. Open the Railway dashboard → the Postgres plugin for this project → check backup/PITR settings.
2. If backups exist: note the retention window and the exact restore procedure, and **test one restore into a throwaway database** to confirm it actually works.
3. If backups do not exist on the current plan: set up a scheduled export as a stopgap —
   ```bash
   railway run --service seekhostake pg_dump "$DATABASE_URL" > backup-$(date +%Y%m%d-%H%M).sql
   ```
   Run this manually before and periodically during a live event at minimum, until an automated schedule exists.
4. **Restore procedure (once a backup format is confirmed):**
   ```bash
   railway run --service seekhostake psql "$DATABASE_URL" < backup-YYYYMMDD-HHMM.sql
   ```
   Never run this against the live database without first taking a *fresh* backup of the current (possibly-corrupted) state — you may need to reconcile the two afterward.

---

## 8. Credentials & access

| Secret | Where it lives | Rotation status |
|---|---|---|
| `SESSION_SECRET` | Railway env var | Set once at initial deploy; no rotation schedule |
| `GOOGLE_CLIENT_ID` / `_SECRET` | Railway env var, from a GCP OAuth client in a dedicated `seekhostake` GCP project | No rotation schedule |
| `ADMIN_PASSWORD` | Railway env var (name-mode fallback — currently dormant while `AUTH_MODE=oauth`) | Stale credential — consider rotating or removing if name-mode is never used again |
| `TEST_LOGIN_PASSWORD` | Railway env var, **currently empty** (feature dormant) | Confirmed empty as of this review — recheck before every event per §4 |
| `OWNER_EMAILS` | Railway env var, currently one address | See R-4 — add a second trusted admin before the event as a break-glass measure |
| `SLACK_WEBHOOK_URL` | Railway env var, **not yet set** | Slack Incoming Webhook URL for the alerting channel (risk R-11). App runs fine without it — alerts just stay log-only until it's added. Create at `api.slack.com/apps` → an app → Incoming Webhooks → Add New Webhook to Workspace. |

**Nothing above should ever be committed to the repository.** This has held so far — verify it continues to hold on every commit touching `api.py` or deployment config.
