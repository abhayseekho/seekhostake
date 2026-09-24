# SeekhoStake — Product Requirements

**Companion to:** [`product-architecture.md`](./product-architecture.md) — read that document's Track A/Track B framing first; every requirement below is tagged the same way.

---

## 1. Product statement

**Today (Track A):** a coordination and settlement-calculation tool for a private, closed-group parimutuel pool among Seekho colleagues, for a single swim race event (27 Sept 2026). The platform never custodies money — cash changes hands in person between bettors and the organiser; the software computes odds, validates bets, and computes who owes whom.

**Aspirational (Track B):** a licensed, multi-event, real-money betting platform. **Not started, and gated on legal clearance** (see architecture doc §0). Requirements below marked "Track B" describe target state only.

---

## 2. User roles

| Role | Defined today? | Summary |
|---|---|---|
| **Bettor** | Yes, fully implemented | Any person with a @seekhoapp.com Google account (or, in `AUTH_MODE=name` fallback, anyone who types a name). Views markets, submits bet requests, tracks own positions, views settlement. |
| **Admin / Organiser** | Yes, fully implemented (one person: Abhay, via `OWNER_EMAILS`) | Confirms cash and approves/rejects bets, runs the race console (lap results), manages market liquidity and suspensions, triggers settlement. |
| **Operations** | No — collapsed into Admin | Track B: day-to-day cash confirmation and market monitoring without settlement authority. |
| **Support** | No — handled ad hoc, in person / over chat | Track B: read-only access to a bettor's bet history to resolve a dispute, no money-moving capability. |
| **Trading / Risk** | No — collapsed into Admin (the person who set `VOLATILITY_SUSPEND_RATIO`, `MAX_PAYOUT_MULT`, seed liquidity, and who resumes suspended markets) | Track B: distinct role that owns pricing/liquidity parameters and market-suspension decisions, with its own audit trail separate from cash-handling. |
| **Compliance** | Does not exist | Track B: KYC/AML review, self-exclusion administration, regulator audit export. Blocked on legal clearance regardless. |
| **Finance** | Does not exist | Track B: independent reconciliation and reporting, structurally separated from whoever can approve bets (segregation of duties — see Risk Register R-6). |

---

## 3. User journeys

### 3.1 Onboarding

**Today:**
1. Bettor receives the site URL (shared informally, e.g. WhatsApp).
2. Signs in with Google OAuth (`@seekhoapp.com` domain-gated) — or types a name in the `AUTH_MODE=name` fallback.
3. Sees the Rules modal (race format, betting windows, payout math) — **not gated**, i.e. a bettor can place a bet without ever opening it.
4. No explicit consent/terms-acceptance step. No age check beyond implicit company employment. No stated minimum age.

**Gaps:**
- No mandatory "I have read and accept the rules" checkpoint before first bet.
- No responsible-gambling messaging at all (Track A: low-stakes/low-frequency context makes this lower-severity, but "low severity" is not "zero," and a one-line "bet only what you can afford to lose, this is for fun" costs nothing to add).

**Track B additions:** identity verification (KYC), explicit age/jurisdiction attestation, deposit method setup, documented consent flow with a timestamped record.

### 3.2 Betting

**Today (fully built, this is the strongest journey):**
1. Bettor reviews live odds across 7 markets (Match Winner + 6 side markets).
2. Selects an outcome → bet slip shows indicative payout.
3. Enters amount, submits → request goes **pending**.
4. Pays the organiser in cash.
5. Organiser approves in the admin console (cash confirmed) → bet is **live**, odds update for everyone via SSE within roughly one round trip.
6. Bettor can raise (same market, `break1` window) or cancel a still-pending request; cannot switch sides on the main market post-lap-1.

**Acceptance criteria (met today, verified via `tests/test_e2e.py` + manual production verification during this session):**
- A bet never enters a pool without an approved (cash-confirmed) status.
- Latest approved bet per person per market is the only one counted (superseded bets are excluded from settlement).
- Displayed odds reflect pending demand instantly; settlement uses approved cash only.
- A bet that would guarantee the bettor risk-free profit across every possible race outcome is rejected (409 `arbitrage_bet`).
- A single approval that swings a market's odds beyond a 2× threshold is checked against `house_floor`; if the house remains covered on every outcome, the market stays open — otherwise it auto-suspends for review.

### 3.3 Settlement

**Today:**
1. Admin records each lap's winner (and optionally time) as the race progresses.
2. Race auto-transitions phases (`prerace → lap1 → break1 → lap2 → …`); the book closes for good the moment `lap2` starts, auto-rejecting any still-pending requests.
3. Once a winner is decided (2 laps won), admin taps "Settle all markets."
4. System computes and freezes a payout sheet: per-market results, per-person aggregate stake/payout/net, swimmer's cut, house's take — asserted to sum exactly to the pool.
5. Bettors see their own settlement view (sanitized — house/rake figures hidden); admin sees full detail.

**Acceptance criteria (met, fuzz-tested):** every market's `paid + swimmer + house == pool`, exactly, for every possible race outcome and every tested bet-book construction (~2,000 fuzzed cases).

### 3.4 Withdrawal

**Today:** there is no digital withdrawal. Settlement produces a payout sheet; the organiser hands out physical cash matching it, in person, off-platform. This is a **feature, not a gap**, for Track A — it's what keeps the platform out of the business of moving money.

**Track B:** would require a full payment-gateway withdrawal flow, KYC-gated, with its own fraud controls (see architecture §10.2).

### 3.5 Support

**Today:** entirely ad hoc — a bettor with a dispute talks to Abhay directly (in person or chat). No in-app dispute mechanism, no ticket log, no SLA.

**Gap worth closing even for Track A:** a lightweight, low-cost improvement — log every admin action (`decided_by`, `decided_at`, `note` already exist on every `bets` row) into a bettor-visible "history" so a dispute can be resolved by pointing at the record rather than relying on memory. The data already exists; it's just not surfaced.

### 3.6 Account closure

**Today:** does not exist as a concept. There is no user profile to delete, no data-retention policy, no way for a bettor to ask "remove my data." Given the minimal PII footprint (name + email only, per architecture §6.2), the practical risk is low, but the **absence of a stated policy** is itself the gap — a one-paragraph data-handling statement in the Rules page costs little and closes it.

---

## 4. Functional requirements

| ID | Requirement | Status | Track |
|---|---|---|---|
| FR-1 | System supports N parimutuel markets per event with independent pools, odds, and open/close windows. | ✅ Done (7 markets) | A |
| FR-2 | A bet enters a market's pool only after admin confirmation of cash received. | ✅ Done | A |
| FR-3 | Latest approved bet per bettor per market supersedes earlier ones; at most one live position per bettor per market. | ✅ Done (app-enforced; **not yet DB-enforced**, see architecture §6.1) | A |
| FR-4 | Displayed odds update live (sub-few-seconds) across all connected clients on any approval, submission, cancellation, or market-state change. | ✅ Done (SSE + anti-churn re-render guard) | A |
| FR-5 | System prevents any bet or combination of bets that would guarantee a bettor risk-free profit. | ✅ Done (`person_floor` guard, `409 arbitrage_bet`) | A |
| FR-6 | System guarantees the organiser ("house") cannot end an event net-negative under any possible race outcome, given guarded liquidity seeding. | ✅ Done (`house_floor`, exhaustively fuzz-tested) | A |
| FR-7 | A market whose odds move beyond a defined volatility threshold from a single approval is checked against real house risk; auto-suspends only if genuinely unsafe. | ✅ Done (today's build) | A |
| FR-8 | Admin can manually pause/resume any market regardless of automatic triggers. | ✅ Done | A |
| FR-9 | Settlement is computed once, is immutable once frozen, and is mathematically asserted to distribute exactly the pool (no leakage, no shortfall). | ✅ Done | A |
| FR-10 | Bettors see a sanitized view (no house/rake internals); admin sees full detail. Admin can preview the exact bettor-facing view. | ✅ Done (`?as_user=1` / "View as user") | A |
| FR-11 | Betting closes hard at a defined deadline independent of race phase. | ✅ Done (server-enforced, 27 Sept 1:00 PM IST) | A |
| FR-12 | System supports multiple concurrent or sequential events with independent books. | ❌ Not built (singleton schema, architecture §6.2) | A/B |
| FR-13 | System supports role-based access beyond bettor/admin binary. | ❌ Not built | B |
| FR-14 | System supports digital deposits and withdrawals via a payment gateway. | ❌ Not built | B |
| FR-15 | System enforces KYC/age/jurisdiction gates before allowing a bet. | ❌ Not built | B |
| FR-16 | System supports bettor-configurable deposit/stake/loss limits and self-exclusion. | ❌ Not built | B |
| FR-17 | System maintains an immutable, independently-queryable ledger of every money-relevant event. | ❌ Not built (architecture §2.1) | A (recommended), B (required) |

---

## 5. Non-functional requirements

| ID | Requirement | Current state | Target |
|---|---|---|---|
| NFR-1 (Correctness) | Settlement math must be exact to the rupee, every time, under adversarial input. | ✅ Met — 2,000+ fuzz cases, zero known violations | Maintain via CI gate on every change (currently not automated — architecture §15) |
| NFR-2 (Latency) | A live odds change should reach all connected clients within a few seconds. | ✅ Met — SSE push, typically sub-second; 15s worst-case fallback poll | Maintain |
| NFR-3 (Availability) | The platform should be reachable throughout a live event window. | Single-instance, single-region, no redundancy; acceptable for a single closed-group event, actively monitored. | Add a `/healthz` + basic uptime monitoring (P1, architecture §13) |
| NFR-4 (Auditability) | Every money-relevant decision must be traceable to who/when/why. | Partially met — `bets.decided_by/decided_at/note` exist; no independent ledger, no structured audit-event stream | Add immutable ledger (architecture §2.1) |
| NFR-5 (Security) | No unauthenticated access to admin actions; secrets never in source control. | ✅ Met | Add rate limiting, restrict `/docs` in prod, RBAC granularity (Track B) |
| NFR-6 (Data integrity) | Financial invariants must hold under concurrent access, not just sequential testing. | Partially met — correct sequentially; race window exists under true concurrency (architecture §6.1) | Add DB-level unique constraint |
| NFR-7 (Recoverability) | The platform must be restorable after data loss. | **Unverified** — backup status not confirmed | Verify and document now (P0, see risk register R-2) |
| NFR-8 (Usability) | A first-time bettor should be able to place a bet without assistance. | Reasonably met (bet slip flow is simple); no formal usability testing performed | Optional: a 5-minute usability pass with a non-technical colleague |
| NFR-9 (Accessibility) | Usable via keyboard and screen reader for core flows. | Not evaluated | Automated axe pass + manual keyboard test (architecture §7) |

---

## 6. Acceptance criteria for "ready for event #2" (the next concrete milestone)

This is the practical, near-term bar — more useful than a generic "production-ready" checklist, because it's the actual next decision point for this team.

- [ ] Multi-event schema in place (`events` table, `event_id` threaded through `bets`/`race`/`settlements`) — FR-12.
- [ ] Postgres backup verified and a restore has been test-run at least once — NFR-7.
- [ ] Partial unique index enforcing one-approved-bet-per-person-per-market at the DB level — FR-3/NFR-6.
- [ ] Automated CI run of the existing 1,390-test suite gating every deploy — architecture §15.
- [ ] A staging environment exists and the previous point's CI run is exercised against it before promoting to prod — architecture §15.
- [ ] `house_floor`/suspension alerting wired to Slack (or equivalent) instead of relying on an admin noticing — architecture §14.
- [ ] Legal sign-off obtained (or a documented decision to continue operating strictly within the closed-group/no-operator-margin/cash-settled fact pattern with an explicit accepted-risk statement from Abhay) — architecture §0.

Everything else in the architecture review (RBAC, ledger, frontend split, etc.) is valuable but not gating for a second run of the same low-stakes format.
