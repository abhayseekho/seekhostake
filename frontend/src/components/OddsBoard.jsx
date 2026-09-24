import { useEffect, useRef, useState } from "react";
import { tone, TONE_TEXT, TONE_SEL_STRONG } from "../lib/theme.js";

// The core surface — audit §4: numbers were already legible (kept: text-display is even larger
// now), but a live price move was easy to miss entirely (a 900ms background tint, gone before a
// second screenshot). Every outcome now gets BOTH the background wash (a lingering "something
// changed here" cue) and a scale+color pop directly on the number (an instant, hard-to-miss
// signal) — the pop never delays the number being readable, it animates the number that's
// already there.
export default function OddsBoard({ market, picked, onPick }) {
  const prev = useRef({});
  const [flash, setFlash] = useState({});
  useEffect(() => {
    const f = {};
    for (const o of market.outcomes) {
      const m = o.est_mult, p = prev.current[o.id];
      if (p != null && m != null && m !== p) f[o.id] = m > p ? "up" : "down";
      prev.current[o.id] = m;
    }
    if (Object.keys(f).length) {
      setFlash(f);
      const t = setTimeout(() => setFlash({}), 900);
      return () => clearTimeout(t);
    }
  }, [market]);

  return (
    <div className="space-y-2">
      {market.suspended && (
        <p className="flex items-center gap-2 text-sm text-gold bg-gold/10 border border-gold/40 rounded-xl px-3 py-2.5">
          <span className="text-base leading-none">⏸</span>
          Suspended for review after an unusual odds swing — new bets are paused until the organiser resumes it.
        </p>
      )}
      <div className="grid grid-cols-2 gap-3">
      {market.outcomes.map((o) => {
        const sel = picked && picked.market === market.id && picked.outcome === o.id;
        return (
          <button key={o.id} disabled={!market.open}
            onClick={() => onPick({ market: market.id, outcome: o.id, label: o.label, name: market.name, est: o.est_mult })}
            className={`relative rounded-2xl p-4 sm:p-5 text-left border-2 transition-all duration-quick bg-card
              ${sel ? TONE_SEL_STRONG[tone(o.id)] : "border-edge"} ${market.open ? "hover:border-dim" : "opacity-90"}
              ${flash[o.id] === "up" ? "animate-flashup" : flash[o.id] === "down" ? "animate-flashdn" : ""}
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2
              focus-visible:ring-offset-bg ${flash[o.id] ? "" : "focus-visible:ring-dim"}`}>
            {flash[o.id] && (
              <span className={`absolute top-3 right-3 inline-flex items-center gap-0.5 text-2xs font-extrabold
                rounded-full px-2 py-0.5 ${flash[o.id] === "up" ? "text-khuseel bg-khuseel/15" : "text-bad bg-bad/15"}`}>
                {flash[o.id] === "up" ? "▲" : "▼"}
              </span>
            )}
            <div className={`font-extrabold uppercase tracking-wide text-sm ${TONE_TEXT[tone(o.id)]}`}>{o.label}</div>
            <div className={`text-display-sm sm:text-display font-extrabold tabular-nums mt-1
              ${flash[o.id] === "up" ? "animate-price-pulse-up" : flash[o.id] === "down" ? "animate-price-pulse-dn" : ""}`}>
              {o.est_mult ? o.est_mult.toFixed(2) + "×" : "—"}
            </div>
          </button>
        );
      })}
      </div>
    </div>
  );
}
