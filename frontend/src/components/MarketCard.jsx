import { tone, TONE_TEXT, TONE_SEL } from "../lib/theme.js";
import { inr } from "../lib/format.js";

const labelOf = (market, oid) => {
  const o = market.outcomes.find((x) => x.id === oid);
  return o ? o.label : oid;
};

// Audit §4: six of these render as visually near-identical stacked blocks, differentiated only
// by heading text — worst on mobile, where it's a long single-column scroll. Status is now a
// real pill (was plain colored text) so "which of these can I still bet on" scans without
// reading every label, and a dead outcome gets an explicit "OUT" tag instead of just a dimmed
// button, which previously read as broken rather than "no longer possible" (a bettor arriving
// mid-race has no other in-context explanation for a greyed-out line).
export default function MarketCard({ market, picked, onPick }) {
  const my = market.my_bet, pend = market.my_pending;
  return (
    <div className={`bg-card border rounded-2xl p-4 transition-colors duration-settle
      ${market.suspended ? "border-gold/50" : "border-edge"}`}>
      <div className="flex justify-between items-center gap-2 mb-0.5">
        <h2 className="font-bold text-sm">{market.name}</h2>
        <span className={`shrink-0 text-3xs font-extrabold tracking-label uppercase rounded-full px-2 py-0.5
          ${market.suspended ? "text-gold bg-gold/10"
            : market.open ? "text-khuseel bg-khuseel/10" : "text-faint bg-raise"}`}>
          {market.suspended ? "Suspended" : market.open ? "Open" : "Closed"}
        </span>
      </div>
      <p className="text-2xs text-faint mb-3 min-h-[1.4em]">
        {market.suspended ? "Paused for review after an unusual odds swing." : (market.sub || "")}
      </p>
      <div className="grid grid-cols-2 gap-2">
        {market.outcomes.map((o) => {
          const sel = picked && picked.market === market.id && picked.outcome === o.id;
          const dead = !o.alive;
          return (
            <button key={o.id} disabled={!market.open || dead}
              onClick={() => onPick({ market: market.id, outcome: o.id, label: o.label, name: market.name, est: o.est_mult })}
              className={`relative rounded-xl px-3 py-2.5 text-left border-2 transition-all duration-quick bg-raise
                ${sel ? TONE_SEL[tone(o.id)] : "border-edge"}
                ${dead ? "opacity-50" : market.open ? "hover:border-dim" : "opacity-80"}
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-dim focus-visible:ring-offset-2
                focus-visible:ring-offset-card`}>
              {dead && (
                <span className="absolute top-1.5 right-1.5 text-[9px] font-extrabold tracking-label
                  text-faint bg-bg rounded px-1 py-0.5">OUT</span>
              )}
              <div className={`text-xs font-semibold ${TONE_TEXT[tone(o.id)]}`}>{o.label}</div>
              <div className="text-xl font-extrabold tabular-nums">
                {dead ? "—" : o.est_mult ? o.est_mult.toFixed(2) + "×" : "—"}
              </div>
            </button>
          );
        })}
      </div>
      {(my || pend) && (
        <p className="text-2xs mt-2.5 text-dim">
          {my && <>Your bet: <b className="text-ink">{labelOf(market, my.outcome)} {inr(my.amount)}</b></>}
          {my && pend && " · "}
          {pend && <span className="text-gold">Pending: {labelOf(market, pend.outcome)} {inr(pend.amount)}</span>}
        </p>
      )}
    </div>
  );
}
