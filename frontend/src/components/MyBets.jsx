import { post } from "../api.js";
import { tone, TONE_TEXT } from "../lib/theme.js";
import { inr } from "../lib/format.js";

const labelOf = (market, oid) => {
  const o = market.outcomes.find((x) => x.id === oid);
  return o ? o.label : oid;
};

// Audit §6: returned null outright with no bets — a first-time bettor saw nothing where this
// section would be, no confirmation the page loaded correctly. Now matches the "No pending
// requests." pattern the Admin panel already uses elsewhere in this same app. Each row also gets
// a left status stripe (gold=pending, khuseel=in pool) so the two states are visually distinct
// beyond a small colored word, matching how status reads everywhere else in the product.
export default function MyBets({ markets, refresh }) {
  const rows = [];
  for (const m of markets) {
    if (m.my_bet) rows.push({ m, ...m.my_bet, status: "APPROVED" });
    if (m.my_pending) rows.push({ m, ...m.my_pending, status: "PENDING" });
  }
  const cancel = async (market) => { await post("/api/bets/cancel", { market }); refresh(); };
  return (
    <div className="bg-card border border-edge rounded-2xl p-4">
      <h2 className="text-2xs font-bold tracking-label text-faint uppercase mb-2">My bets</h2>
      {!rows.length && <p className="text-faint text-sm">No bets placed yet.</p>}
      {rows.map((r, i) => (
        <div key={i} className={`flex justify-between items-center text-sm py-2 pl-3 -ml-px border-l-2
          ${r.status === "PENDING" ? "border-gold" : "border-khuseel"}
          ${i < rows.length - 1 ? "border-b border-b-edge/50 mb-0.5" : ""}`}>
          <span>{r.m.name} · <b className={TONE_TEXT[tone(r.outcome)]}>{labelOf(r.m, r.outcome)}</b> <span className="tabular-nums">{inr(r.amount)}</span></span>
          {r.status === "PENDING" ? (
            <span className="text-gold text-2xs font-bold tracking-label uppercase shrink-0 ml-2">
              Pending <button onClick={() => cancel(r.m.id)}
                className="text-bad underline font-normal normal-case tracking-normal ml-1
                  hover:text-bad/80 transition-colors duration-quick">Cancel</button>
            </span>
          ) : (
            <span className="text-khuseel text-2xs font-bold tracking-label uppercase shrink-0 ml-2">In pool</span>
          )}
        </div>
      ))}
    </div>
  );
}
