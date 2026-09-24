# SeekhoStake — Release Checklist

**Companion to:** all other documents in `docs/`. Every item below cites the section/risk it comes from.

This checklist has two parts. **Use Part A now.** Part B is a reference for a hypothetical future a lawyer has not yet cleared (see [`product-architecture.md`](./product-architecture.md#0-the-gate-that-comes-before-every-other-recommendation)) — do not treat it as a near-term to-do list.

---

## Part A — Before running this system again for a real event (Track A)

### Legal & responsible framing
- [ ] Confirm the operating fact pattern with counsel or, at minimum, document Abhay's explicit, informed decision to proceed within it: closed employee group, no operator profit margin, cash settled in person, one-off or infrequent recurrence. *(architecture §0, risk R-1)*
- [ ] Rules page bettors read before betting states plainly: this is a private pool among colleagues, not a licensed gambling product, and includes a one-line responsible-gambling note ("bet only what you're comfortable losing"). *(requirements §3.1)*

### Data safety
- [ ] Postgres backup/PITR status checked in the Railway dashboard; if unavailable on the current plan, a manual `pg_dump` export taken before and during the event. *(risk R-2, runbook §7)*
- [ ] One test restore performed into a throwaway database to confirm backups are actually usable. *(runbook §7)*

### Access & operational resilience
- [ ] At least one additional trusted person added to `OWNER_EMAILS` as a break-glass measure. *(risk R-4)*
- [ ] `TEST_LOGIN_PASSWORD` confirmed empty in production (`/api/config` → `test_login: false`). *(risk R-9, runbook §4)*
- [ ] `AUTH_MODE=oauth` confirmed as the live value (not accidentally left on `name` fallback from testing). *(runbook §8)*
- [ ] `SESSION_SECRET` confirmed strong (32+ chars, not the dev default) — the app already refuses to boot otherwise, but confirm the boot actually succeeded after any redeploy.

### Financial integrity
- [ ] `house.seed_cap` and any placed house seed reviewed and sane for the current book. *(runbook §6.1)*
- [ ] No market left in an unintended `suspended` state from prior testing — run `POST /api/admin/markets/recheck` and review the result. *(architecture §11, today's incident)*
- [ ] Full test suite green immediately before the event: `SWIMBET_DEV=1 .venv/bin/python -m pytest tests/ -q`. *(test-strategy §1)*
- [ ] Pre-race cash reconciliation performed: every approved bet's cash physically confirmed in hand. *(runbook §6.1)*

### Change management
- [ ] No untested code change deployed within the final hour before betting opens, unless it's a genuine incident fix — the system has no staging environment, so "untested" and "unverified in production" are the same thing today. *(risk R-7)*
- [ ] Anyone with deploy access in the final run-up is aware of the rollback procedure (`runbook §3`) before they need it, not after.
- [ ] CI (`.github/workflows/ci.yml`, added in the second review pass) is green on the commit about to be deployed — it runs the full pytest suite and the frontend build, but only ON PUSH; it does not block Railway's auto-deploy from proceeding on a red run, since there's no branch-protection/required-check wired up yet. Check the Actions tab, don't assume. *(risk R-7 — closes the "not automated as a gate" half; the staging-environment half is still open)*

### Monitoring during the live window
- [ ] `SLACK_WEBHOOK_URL` set in Railway — without it, auto-suspend / unhandled-error / stuck-suspended alerts stay log-only. *(risk R-11, runbook §4/§8)*
- [ ] A human (not necessarily the admin) is still watching `house.floor` and the suspended-markets panel throughout every live betting window — Slack alerting narrows this risk, it doesn't remove the need for a human in the loop (nothing watches the process itself if it dies outright; see runbook §4). *(risk R-11)*

---

## Part B — Before any real-money, multi-event, licensed platform (Track B, not currently in scope)

This section exists because the original review scope asked for "mandatory pre-release checks for a real-money launch." It is included for completeness and to make the size of the gap explicit — **none of these should be started without legal clearance first**, and several require inputs (a licensed jurisdiction, a payment processor relationship, a compliance officer) that don't exist yet.

### Legal & licensing
- [ ] Jurisdiction(s) of operation identified and licensing obtained.
- [ ] Terms of service, privacy policy, and responsible-gambling policy drafted by counsel and version-controlled with an acceptance audit trail per user.
- [ ] KYC/AML program designed and implemented (identity verification, sanctions screening, suspicious-activity reporting).
- [ ] Age and geolocation verification enforced at signup and, where required, at bet time.

### Financial architecture
- [ ] Double-entry ledger implemented and independently reconciled against actual custodied funds on a defined schedule. *(architecture §2, §10.2)*
- [ ] Payment gateway integration for deposits/withdrawals, PCI-DSS scope assessed if card data is ever touched directly.
- [ ] Segregation of duties enforced in the org chart, not just in software: no single person can both approve a bet and authorize its settlement without an independent check. *(risk R-6)*
- [ ] Responsible-gambling controls live: deposit/stake/loss limits, self-exclusion, cooling-off periods, all enforced server-side, not by policy alone.

### Engineering
- [ ] Multi-event schema in place (no hardcoded singleton row IDs). *(architecture §6.2, risk R-12)*
- [ ] RBAC with the roles defined in `product-requirements.md` §2, each with its own audit trail.
- [ ] DB-level uniqueness constraint on one-approved-bet-per-person-per-market (or the multi-event equivalent). *(architecture §6.1, risk R-3)*
- [ ] Idempotency keys on every money-moving endpoint. *(architecture §2.2, risk R-10)*
- [ ] Rate limiting on every mutating endpoint. *(architecture §5, risk R-5)*
- [ ] Horizontal scaling verified: SSE broadcaster moved off in-process state, load-tested at target concurrency. *(architecture §3.1/§13, risk R-8)*
- [ ] `/docs` and `/openapi.json` gated or disabled in production. *(architecture §5, risk R-14)*
- [ ] Collusion/multi-account arbitrage detection beyond single-identity `person_floor`. *(risk R-15)*

### Operations & compliance evidence
- [ ] CI/CD with mandatory test gates and a staging environment mirroring production. *(architecture §15, risk R-7)*
- [ ] Automated alerting on every financial-safety invariant (`house_floor`, reconciliation drift). *(architecture §14, risk R-11)*
- [ ] Structured audit-event log, independently exportable for a regulator. *(architecture §2.1)*
- [ ] Data retention and deletion policy implemented and enforced, not just documented. *(architecture §6.2, risk R-13)*
- [ ] Disaster recovery plan tested end-to-end (not just backups — a full restore-and-resume drill). *(runbook §7)*
- [ ] Independent security review / penetration test completed.
- [ ] Load test at target concurrency completed, with results documented against defined SLOs.

**None of Part B is a near-term backlog.** It's the honest answer to "what would 'real-money launch ready' require," provided so the gap between today's private pool and that bar is visible rather than assumed away.
