import { LABEL, SIDE_TEXT } from "../lib/constants.js";
import { inr } from "../lib/format.js";

// "The screen people screenshot" per the brief (audit §7) — verified live by settling a real
// race. The headline now gets the same display-weight treatment as the main odds (the biggest
// number on the busiest screen deserves the biggest number here too), a winner-tinted glow
// instead of a flat 10%-opacity wash, and a reveal animation. The payout sheet below was already
// the strongest part of this screen — kept close to as-is, just on the new tokens.
export default function Settlement({ s, race }) {
  const wins = race?.wins;
  const winnerGlow = s.winner === "khuseel" ? "bg-khuseel" : "bg-bansod";
  return (
    <div className="space-y-4">
      <div className={`animate-rise-in relative overflow-hidden rounded-2xl border p-6 sm:p-8 text-center
        ${s.winner === "khuseel" ? "border-khuseel/60 bg-khuseel/[0.07]" : "border-bansod/60 bg-bansod/[0.07]"}`}>
        <div className={`pointer-events-none absolute -top-20 left-1/2 -translate-x-1/2 w-64 h-64
          rounded-full ${winnerGlow} opacity-[0.12] blur-[80px]`} />
        <div className="relative text-3xs font-bold tracking-label uppercase text-faint mb-2">Match settled</div>
        <div className="relative text-display-sm sm:text-display font-extrabold tracking-tight">
          <span className={SIDE_TEXT[s.winner]}>{LABEL[s.winner].toUpperCase()}</span>
          <span className="text-ink"> WINS</span>
          {wins && <span className="tabular-nums text-ink">
            {" "}{Math.max(wins.khuseel, wins.bansod)}–{Math.min(wins.khuseel, wins.bansod)}</span>}
        </div>
        <div className="relative flex justify-center gap-2.5 mt-5 flex-wrap">
          <span className="bg-gold/15 text-gold font-extrabold text-base rounded-xl px-5 py-2 tabular-nums">
            🏆 Swimmer {inr(s.swimmer_take)}
          </span>
          {s.house_take != null && (
            <span className="bg-raise border border-edge text-dim font-bold text-sm rounded-xl px-4 py-2 tabular-nums">
              House {inr(s.house_take)}
            </span>
          )}
        </div>
      </div>

      <div className="bg-card border border-edge rounded-2xl p-4">
        <h2 className="text-2xs font-bold tracking-label text-faint uppercase mb-2">Markets</h2>
        <div className="flex flex-wrap gap-2">
          {s.markets.map((m) => (
            <span key={m.market} className="bg-raise border border-edge rounded-lg px-2.5 py-1.5 text-xs text-dim">
              {m.name}: <b className="text-ink">{m.void ? "Void — refunded" : (m.won_label || m.won)}</b>
            </span>
          ))}
        </div>
      </div>

      <div className="bg-card border border-edge rounded-2xl p-4 overflow-x-auto">
        <h2 className="text-2xs font-bold tracking-label text-faint uppercase mb-2">
          Payout sheet</h2>
        <table className="w-full text-sm">
          <thead><tr className="text-faint text-3xs uppercase tracking-label text-left">
            <th className="pb-2 font-semibold">Bettor</th>
            <th className="pb-2 font-semibold text-right">Staked</th>
            <th className="pb-2 font-semibold text-right">Gets back</th>
            <th className="pb-2 font-semibold text-right">Net</th></tr></thead>
          <tbody>
            {s.aggregate.map((r, i) => (
              <tr key={r.key} className={`border-t border-edge/50 ${i % 2 ? "bg-bg/40" : ""}`}>
                <td className="py-2 px-1">{r.display_name}</td>
                <td className="text-right text-dim tabular-nums px-1">{inr(r.stake)}</td>
                <td className="text-right tabular-nums px-1">{inr(r.payout)}</td>
                <td className={`text-right font-bold tabular-nums px-1 ${r.net >= 0 ? "text-khuseel" : "text-bad"}`}>
                  {r.net >= 0 ? "+" : "−"}{inr(Math.abs(r.net))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
