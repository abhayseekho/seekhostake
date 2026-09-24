/**
 * SeekhoStake design system — Stake-inspired deep blue-slate, locked down per the Phase 2 UI
 * revamp (see docs/ui-audit.md for the findings this responds to). Core palette hues are
 * unchanged from the approved prototype; the additions below are the actual "system" — named
 * roles instead of the ad hoc bracket values (`text-[11px]`, `tracking-[.13em]`, ...) the audit
 * found scattered through the old App.jsx. Components should never need an arbitrary `[...]`
 * value for type, tracking, or the small dot sizes — if one seems necessary, it belongs here
 * instead so every screen stays consistent by construction, not by discipline.
 */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0e1621",
        card: "#17222e",     // surface
        raise: "#1e2b3a",    // one level up (nested controls, the bet slip)
        edge: "#26344a",     // borders
        overlay: "rgba(6, 10, 16, 0.78)",  // modal backdrop — was an inline bg-black/70 one-off
        ink: "#eaf1f7",
        dim: "#8fa2b3",
        // Was #5c6d7d — measured 3.02:1 on `card` / 2.69:1 on `raise`, both well under WCAG AA's
        // 4.5:1 for normal text (audit §1). This value clears both surfaces (5.24:1 / 4.68:1)
        // while staying visibly more muted than `dim`.
        faint: "#8595a5",
        khuseel: "#21c065",
        bansod: "#3aa8f0",
        gold: "#f2b83b",
        bad: "#f56262",
      },
      fontFamily: { sans: ["-apple-system", "SF Pro Text", "Segoe UI", "system-ui", "sans-serif"] },

      // ── Type scale ───────────────────────────────────────────────────────────────────────────
      // Default Tailwind xs/sm/base/lg/xl/2xl cover body/heading roles and stay in use as-is.
      // These fill the two roles the default scale has no named size for:
      fontSize: {
        // The category-label size used everywhere (CASHIER CONSOLE, BET SLIP, PENDING ·  ...).
        // Was a bare `text-[11px]` at 24 call sites in the old App.jsx — one role, one name now.
        "2xs": ["0.6875rem", { lineHeight: "1.4" }],
        // A couple of places even 2xs reads too loud (timestamps inside a lap chip, etc).
        "3xs": ["0.625rem", { lineHeight: "1.35" }],
        // The "this is the number on this screen" role: main odds, settlement headline. Nothing
        // in the default scale goes this big with this tight a tracking.
        display: ["2.75rem", { lineHeight: "1.05", letterSpacing: "-0.02em" }],
        "display-sm": ["2rem", { lineHeight: "1.1", letterSpacing: "-0.02em" }],
      },
      letterSpacing: {
        // The uppercase tracked label treatment — was drifting between .1em/.12em/.13em across
        // 40+ call sites with no apparent intent behind the differences. One value now.
        label: "0.12em",
      },

      // ── Spacing / sizing additions ───────────────────────────────────────────────────────────
      spacing: {
        // Status-indicator dot (RaceStrip's live pulse, the header LIVE badge) — was w-[7px] in
        // one place and w-[6px] in the other, no reason for the difference.
        dot: "0.4375rem",
      },

      // ── Motion ───────────────────────────────────────────────────────────────────────────────
      // Durations named by INTENT, not value, so a component picks the right feel instead of a
      // number: instant taps, quick hovers, a settle-in for panels/modals, and the slower ceremony
      // reserved for the settlement reveal (the one screen allowed to take its time).
      transitionDuration: {
        instant: "100ms",
        quick: "200ms",
        settle: "400ms",
      },
      transitionTimingFunction: {
        // A slight overshoot-free "confident" ease — snappier out than Tailwind's default ease-out.
        confident: "cubic-bezier(0.16, 1, 0.3, 1)",
      },
      keyframes: {
        // Existing background-tint pulse — kept for places a quieter move-signal is right (e.g.
        // dense list rows) but no longer the ONLY odds-move signal on the primary board; see
        // price-pulse below.
        flashup: { "0%": { backgroundColor: "rgba(33,192,101,.25)" }, "100%": { backgroundColor: "#17222e" } },
        flashdn: { "0%": { backgroundColor: "rgba(245,98,98,.25)" }, "100%": { backgroundColor: "#17222e" } },
        // Audit §4: the old flash was easy to miss entirely — background tint only, gone in under
        // a second. This adds a real scale pop on the number itself so a live price move actually
        // registers even on a mid-blink glance, without ever delaying the number from being readable.
        "price-pulse-up": {
          "0%": { transform: "scale(1)" },
          "30%": { transform: "scale(1.08)", color: "#21c065" },
          "100%": { transform: "scale(1)" },
        },
        "price-pulse-dn": {
          "0%": { transform: "scale(1)" },
          "30%": { transform: "scale(1.08)", color: "#f56262" },
          "100%": { transform: "scale(1)" },
        },
        // Settlement reveal — the one screen the brief asks to feel like a moment, not a form
        // submission (audit §7).
        "rise-in": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        flashup: "flashup .9s",
        flashdn: "flashdn .9s",
        "price-pulse-up": "price-pulse-up .6s cubic-bezier(0.16, 1, 0.3, 1)",
        "price-pulse-dn": "price-pulse-dn .6s cubic-bezier(0.16, 1, 0.3, 1)",
        "rise-in": "rise-in .5s cubic-bezier(0.16, 1, 0.3, 1) both",
      },
    },
  },
  plugins: [],
};
