import { post } from "../api.js";
import { inr } from "../lib/format.js";

// Generalizes the match market's original by-name book to every market (2-way K/B, Yes/No, or
// the 4-way Correct Score) — one visual language, so admin and bettors alike can see exactly who
// holds an approved position anywhere, not just on the match. Renders nothing for a market with no
// approved rows to show, so empty side markets don't clutter the page.
export default function MarketBook({ market, isOwner, refresh }) {
  const bets = market.bets || [];
  if (!bets.length) return null;

  const voidBet = async (b) => {
    if (!confirm(`Void ${b.display_name}'s ${inr(b.amount)} bet on ${market.name}? (Return their cash.)`)) return;
    await post("/api/admin/bets/void", { key: b.key, market: market.id });
    refresh();
  };

  const cols = market.outcomes.length > 2 ? "grid-cols-2 sm:grid-cols-4" : "grid-cols-2";
  return (
    <div>
      <h3 className="text-2xs font-bold tracking-label uppercase text-faint mb-2">{market.name}</h3>
      <div className={`grid ${cols} gap-4`}>
        {market.outcomes.map((o) => {
          const rows = bets.filter((b) => b.side === o.id);
          return (
            <div key={o.id} className="min-w-0">
              <p className="text-3xs text-faint uppercase tracking-label mb-1 truncate">{o.label}</p>
              {rows.length === 0 && <p className="text-2xs text-faint">—</p>}
              {rows.map((b) => {
                const house = b.key.startsWith("house");
                return (
                  <div key={b.key} className={`flex justify-between items-center text-sm py-1.5 px-2 -mx-2 rounded-lg
                    border-b border-edge/50 ${house ? "bg-gold/[0.06]" : ""}`}>
                    <span className="flex items-center gap-1.5 min-w-0">
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
          );
        })}
      </div>
    </div>
  );
}
