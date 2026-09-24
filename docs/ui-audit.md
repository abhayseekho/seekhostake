# SeekhoStake — Phase 1 UX Audit

**Scope:** `frontend/src/App.jsx` as of this branch's base (`origin/main` @ `c217b77`). Walked live
at 375px and desktop against a realistically seeded book (18 bettors, ₹63,050+ pool, house seed +
tilted side liquidity) via `SWIMBET_DEV=1` locally. Verified directly in-browser: Login (name-mode),
main odds board, BetSlip full lifecycle (idle → picked → amount → submitted → approved, live via
SSE), Admin cashier console + race console + setup tools, Match-winner book, Settlement. Read
directly from source (not independently re-screenshotted this pass, findings below are code-level):
MyBets, Rules modal content, empty/loading states.

**How to read this:** each finding is stated as a concrete problem, not a vague impression — file/
component named, what's wrong, why it matters for a live cash event. Findings feed directly into
Phase 2 (design system) and Phase 3 (component work); this doc doesn't prescribe the fix, just
names the gap precisely.

---

## 1. Global / cross-cutting

- **No type scale.** Every heading-ish element is `font-extrabold` or `font-bold` with an ad hoc
  size class (`text-[11px]`, `text-xs`, `text-sm`, `text-lg`, `text-xl`, `text-2xl`, `text-4xl`
  variously) chosen per-instance, not from a named scale. Result: section labels ("CASHIER
  CONSOLE", "BET SLIP", "MY BETS") and the actual odds numbers compete for attention at a glance —
  everything is bold, so nothing reads as *more* important. This is the single biggest reason the
  app reads "prototype, not product": real trading/betting UIs (Stake, Kalshi, Robinhood) use
  weight and size very deliberately so the eye lands on the number that matters first.
- **No spacing scale.** `space-y-4`, `p-4`, `px-3 py-2.5`, `gap-1.5`, `mt-2.5` etc. are chosen per
  component with no consistent rhythm. Nothing is broken, but nothing feels composed either.
- **Elevation is binary, not a system.** Tokens exist (`bg → card → raise → edge`) but are used
  almost interchangeably — e.g. `MarketCard` is `bg-card` with `bg-raise` outcome buttons inside,
  while `BetSlip` is `bg-raise` directly on `bg-card`'s sibling level. No consistent rule for "this
  is a surface, this is one level up, this is interactive."
- **Khuseel vs Bansod is a color, not a system.** The rivalry is real (green vs blue, it's the
  whole premise of the product) but today it's expressed only as a text/border color on whatever
  element happens to reference that outcome. There's no shared visual language (e.g. a consistent
  side-indicator, a paired treatment when both appear together) that makes "this is a two-sided
  contest" legible at a glance the way, say, a sports book's home/away color bar does.
- **Focus states: absent.** Grep confirms no `focus-visible:` anywhere in `App.jsx`; inputs get a
  `focus:border-khuseel`/`focus:border-gold` border change but buttons — including every bet
  outcome button, Approve/Reject, Settle — have no visible keyboard-focus ring at all. Real gap for
  keyboard users, and free to fix (Tailwind's `focus-visible:ring` utilities).
- **Contrast spot-check:** `text-faint` (`#5c6d7d`) on `bg-card`/`bg-raise` (`#17222e`/`#1e2b3a`) is
  close to WCAG AA-fail for normal-size text (~3.6:1 against `#17222e`, needs 4.5:1) — used for
  market sub-labels, timestamps, the "Setup & manual tools" disclosure. Not illegible, but thin
  margin for a screen used poolside in bright daylight.
- **Tap targets:** most buttons clear 44px on mobile (odds cards, Approve/Reject), but the
  `BookTable` void "✕" and the `MarketCard`'s outcome buttons at dense screen widths run close to
  the minimum — worth an explicit pass in Phase 3, not just an assumption it's fine.

## 2. Login (`Login`) — first impression

Verified live (name-mode). **This is the biggest gap between current state and the brief's stated
bar.** Concretely:
- A single small card (`max-w-sm`) centered in a completely empty viewport — on desktop this is
  roughly 25% of the screen's real estate used, 75% flat background. Nothing else on the page
  earns any of that space (no imagery, no motion, no secondary content).
- The 🏊 emoji as the entire brand mark reads casual/placeholder, not "a real product with real
  money on the line" — the exact opposite of the brief's "trustworthy-feeling" goal.
- Typographically flat: title, subtitle, and deadline notice are all competent on their own but
  don't build toward a single focal point — nothing tells the eye "look here first." The OAuth
  variant and the name-mode fallback share this same structural gap; the latter just has fewer
  fields below the fold.
- Functionally correct and not confusing (name field autofocus-worthy, clear CTA, admin/test login
  tucked behind secondary links appropriately) — this is a visual-polish gap, not a UX-flow gap.

## 3. RaceStrip — the glance header

Verified across `prerace`, `finished`, `settled` phases (not `lap*`/`break*` live-in-progress,
since that requires a real race — reasoned from code + the `border-bad animate-pulse` treatment).
- Phase label + KHU/BAN win counter are on one line, roughly equal visual weight — fine at rest,
  but there's no distinct "this is LIVE right now, pay attention" state beyond a red border and a
  pulsing 7px dot. During an actual live lap, this is the single most important status on the
  screen and currently has the same footprint as "pre-race, nothing happening yet."
- Lap history chips (`L1 Bansod 22.4s`) are correct and clear once present, but tiny (`text-xs` in
  a `px-2.5 py-0.5` pill) relative to their importance as the running record of the match.

## 4. OddsBoard / MarketCard / PoolBar — the core surface

Verified live, including a real submit → approve → live-odds-move cycle via SSE.
- **The odds numbers themselves are good** — `text-4xl font-extrabold tracking-tight` on the main
  board is genuinely legible at a glance, and `tabular-nums` (global, via `index.css`) keeps digit
  widths stable as numbers change. This is the one area already close to the bar.
- **The flash animation is too subtle to trust.** `animate-flashup`/`flashdn` is a 900ms background
  tint pulse plus an 11px ▲/▼ badge in the card's top-right corner. In a live capture where a real
  bet moved the odds by a full 0.01× tick, the flash was already gone by the time two sequential
  screenshots were taken roughly a second apart — i.e., a bettor glancing at their phone at almost
  any moment has a real chance of missing that a number just moved. For a page whose entire value
  proposition is "the price is live," this deserves stronger, more deliberate motion.
- **Side `MarketCard`s are visually undifferentiated from each other.** Six cards (Correct Score,
  Goes to Lap 3?, Lap 1/2/3 Winner, Comeback Special) all use the identical card chrome and layout
  — on mobile this becomes six near-identical full-width blocks stacked in a long column with
  nothing but the heading text to tell them apart at a scroll-past glance.
- **`PoolBar`'s split bar is a good idea, underweighted.** A 2px-tall bar (`h-2`) carrying the
  entire "which side has the money" signal is easy to miss; the number next to it (`text-sm`) is
  smaller than plenty of less important numbers elsewhere on the same screen.
- **Dead-outcome state (`opacity-40`) reads as "disabled/broken," not "no longer possible."** No
  copy, icon, or strikethrough — just a dimmed button. Someone landing mid-race (not having read
  the Rules modal) has no in-context explanation for why one score line is greyed out.

## 5. BetSlip — the highest-stakes interaction

Verified the full lifecycle live: idle → outcome picked → amount entered (typed + quick-buttons) →
submitted → shows in Admin's pending queue in real time → approved → odds move live.
- **Works correctly end to end** — no functional complaints. The specific findings are about
  confidence/feedback quality:
- **Stale success message.** After `Bet ₹X on Y — submitted. Pay cash to confirm.` appears, it
  persists indefinitely — including after the admin approves the bet moments later. There's no
  transition to an "approved, you're in" state; the bettor's last signal stays frozen on "pending"
  even once it's actually live in the pool (they'd only know from `MyBets` showing "IN POOL"
  elsewhere on the page).
- **Mobile placement actively fights the scroll flow.** On mobile the slip renders inline
  (`lg:hidden`) directly after `PoolBar`, *before* all six side-market cards and `MyBets`. Picking
  an outcome on, say, "Lap 3 Winner" — which is six card-heights below the slip — requires
  scrolling back *up* past everything to find the slip that just populated. On desktop this is a
  non-issue (`sticky top-4` in the right rail); on mobile, which the brief explicitly calls the
  dominant device, it's a real friction point on the single most important interaction in the app.
- **The quick-amount buttons (₹500/1k/2k) are a good, undersold idea** — small, same visual weight
  as everything else, easy to miss as the fastest path to a bet.
- **No inline validation feedback while typing** — errors (e.g. below the new ₹500 minimum) only
  surface after a failed submit, not as the amount is entered.

## 6. MyBets / BookTable — dense data views

Read from source (structure verified, not independently re-screenshotted this pass — straightforward
enough to assess from JSX + the live book I did view).
- `MyBets` is a plain `flex justify-between` row list — functional, no table typography problems
  because it isn't really a table, but also no visual distinction between an approved position and
  a pending one beyond a color-coded status word.
- `BookTable` (Match-winner book, verified live with the full 18-row seed) is genuinely serviceable
  already: two-column K/B split, colored side-dot, right-aligned amounts. The one real gap —
  **the House row (`key === "house"`) is styled identically to every other bettor** except for a
  gold display-name color; on a screen an admin is scanning quickly during a live event, the
  organiser's own seed position should be visually set apart more decisively (it's a fundamentally
  different kind of row — not a bettor's cash — not just a differently-colored bettor).
- Neither table has an explicit empty state beyond `MyBets` returning `null` outright (verified in
  code) — a first-time bettor with no positions sees *nothing* where the section would be, not an
  affirmative "you haven't bet yet."

## 7. Settlement — the payout moment

**Verified live** by fast-forwarding a real 2–0 sweep to settlement. This is explicitly "the screen
people screenshot" per the brief, and today it undersells the moment:
- "BANSOD WINS 2–0" renders as a modest `text-2xl` headline in a subtly-tinted bordered box — correct
  information, low ceremony. For the single most emotionally-loaded screen in the product (money
  has just definitively changed hands), the visual weight is closer to a form-submission confirmation
  than a result.
- Swimmer/House take are two small pills of equal visual weight — the swimmer's payout (the whole
  point of the prize-money mechanic) doesn't stand out as the "human interest" number it is.
- **The payout sheet itself is the strongest part of this screen already** — clean tabular data,
  right-aligned numbers, color-coded net (green/red), scannable. Worth preserving almost as-is,
  just given a more considered frame around it.

## 8. Admin (Cashier Console) — the speed tool

Verified live: pending queue with a real submission, Approve action, Race Console phase
transitions, Settle, and the collapsed "Setup & manual tools" (house seed, side liquidity, manual
bet, market pause) all present and correctly wired.
- **The information architecture here is already good** — pending-cash-first at the top (correctly
  prioritized: collecting real money is the most urgent recurring task), race console next, rare
  tools tucked behind a `<details>` disclosure. This is the one component that already reflects
  "optimize for speed under pressure" thinking. Phase 3 should mostly *preserve* this hierarchy,
  not redesign it, and focus on typography/spacing polish plus the mobile header problem below.
- **The "COLLECT ₹X" chip is the single most important number on the entire admin surface** (it's
  literally "how much cash to physically take from this person") and today it's the same visual
  weight class as a dozen other small gold badges elsewhere in the app (house floor, seed cap,
  suspended-market pills) — nothing marks it as *the* number that matters most in this exact
  moment.
- Confirm-via-native-`confirm()` dialogs (Settle, Reset book, Start-lap-with-pending-requests) are
  functionally fine but visually jarring against the otherwise-custom UI — a modal in the app's own
  design language would read as far more "product," though this is a smaller-priority item given
  it's a rare, deliberately-interrupting action.

## 9. Rules modal

Read from source; copy is **frozen per the guardrails** (verified live in prod per
`docs/release-checklist.md` — do not alter wording, restyle only). Structurally: 8 numbered
sections in one scrolling modal, each `<h3>` + `<p>` — plain, readable, no hierarchy problems
beyond the global type-scale issue above. Section 8 ("Play responsibly") currently reads
identically to every rules-of-the-game section above it; worth a subtler visual treatment that
still doesn't touch the words.

## 10. Mobile-specific findings (375px) — beyond what's already noted per-component above

- **Header overflow is a real, visible bug, not a nitpick.** At 375px, `Seekho`/`Stake` wraps to
  two lines, `View as user` wraps to three, and `Logout` is clipped at the viewport edge —
  confirmed by direct screenshot. This is the top nav on every single screen in the app; it's
  broken on the brief's own stated dominant device today.
- Side-market cards collapsing to one-per-row (`sm:grid-cols-2` → single column below `sm`) is
  correct and legible individually, but produces a very long single-column scroll (six full cards)
  before `MyBets`/`BookTable` — reinforces the BetSlip-placement problem from §5.

## 11. Empty / loading / error states (from code, not independently screenshotted)

- Initial load: plain `Loading…` text, no skeleton — acceptable given the load is typically
  sub-second on this connection, but worth a brief skeleton state if easy to add without touching
  data-fetching logic.
- 401/unauth mid-session: falls straight back to `Login` — reasonable, no dead-end.
- `MyBets` empty: renders nothing (see §6) — the one real "missing state" worth an explicit fix.
- Network/API failures beyond `_error` reason codes (i.e. the fetch itself failing, not a 4xx) are
  swallowed silently in `api.js`'s `req()` — `refresh()` just returns without updating state. Not a
  visual finding, flagging since it's adjacent (a genuinely offline bettor sees stale data with no
  "you're offline" signal, matching what the architecture review's own frontend section already
  flagged as untested).

---

## Summary: where Phase 3 effort should go, in priority order

1. **Type scale + spacing tokens (Phase 2 foundation)** — every other finding compounds without this.
2. **Mobile header** — an actual bug at the stated primary viewport, fix first.
3. **BetSlip mobile placement** — the highest-stakes interaction shouldn't require scrolling away
   from itself.
4. **Login** — biggest gap vs. the stated bar, first thing every user sees.
5. **Settlement** — "the screenshot moment" deserves more ceremony; payout sheet itself is already good.
6. **Odds-move motion** — make a live number change actually land with the viewer.
7. **Admin COLLECT chip + House row distinction** — small, high-value, speed-tool-specific polish.
8. Focus states + contrast pass — cheap, systematic, do alongside the token work in Phase 2.
