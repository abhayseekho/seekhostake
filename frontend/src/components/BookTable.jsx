import { post } from "../api.js";
import { SIDES } from "../lib/constants.js";
import { inr } from "../lib/format.js";

// Audit §6: this table itself was already the strongest data view in the app (kept close to
// as-is). The one real gap — the house's own seed row read as just a differently-colored
// bettor — now gets a tinted row + an explicit tag, since it's a fundamentally different kind of
// line (the organiser's liquidity, not a bettor's cash) and an admin scanning quickly during a
// live event should never mistake one for the other.
export default function BookTable({ bets, isOwner, refresh }) {
  const voidBet = async (b) => {
    if (!confirm(`Void ${b.display_name}'s ${inr(b.amount)} bet? (Return their cash.)`)) return;
    await post("/api/admin/bets/void", { key: b.key, market: "match" });
    refresh();
  };
  return (
    <div className="bg-card border border-edge rounded-2xl p-4">
      <h2 className="text-2xs font-bold tracking-label text-faint uppercase mb-2">Match-winner book</h2>
      <div className="grid grid-cols-2 gap-4">
        {SIDES.map((s) => (
          <div key={s}>
            {bets.filter((b) => b.side === s).map((b) => {
              const house = b.key === "house";
              return (
                <div key={b.key} className={`flex justify-between items-center text-sm py-1.5 px-2 -mx-2 rounded-lg
                  border-b border-edge/50 ${house ? "bg-gold/[0.06]" : ""}`}>
                  <span className="flex items-center gap-2 min-w-0">
                    <i className={`w-2 h-2 rounded-full shrink-0 ${s === "khuseel" ? "bg-khuseel" : "bg-bansod"}`} />
                    <span className={`truncate ${house ? "text-gold font-bold" : ""}`}>{b.display_name}</span>
                    {house && (
                      <span className="text-3xs font-extrabold tracking-label uppercase text-gold
                        bg-gold/15 rounded px-1 py-0.5 shrink-0">House</span>
                    )}
                  </span>
                  <span className="text-dim shrink-0 ml-2 tabular-nums">
                    {inr(b.amount)}
                    {isOwner && (
                      <button onClick={() => voidBet(b)} title="Void (cash returned)"
                        className="text-bad ml-2 hover:text-bad/80 transition-colors duration-quick
                          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bad/50 rounded">✕</button>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
