import { inr } from "../lib/format.js";

// Audit §4: a 2px bar plus a text-sm total tried to carry "which side has the money" — a real
// signal — at less visual weight than several less important numbers on the same screen. The
// total is now a headline-weight number; the split bar is taller with a soft inner highlight so
// the lead side actually reads as "ahead," not just "a slightly longer green bit."
export default function PoolBar({ market }) {
  const k = market.outcomes.find((o) => o.id === "khuseel");
  const b = market.outcomes.find((o) => o.id === "bansod");
  const kw = market.pool ? (100 * k.total) / market.pool : 50;
  return (
    <div className="bg-card border border-edge rounded-2xl px-4 py-3.5">
      <div className="flex justify-between items-baseline">
        <span className="text-2xs font-bold tracking-label uppercase text-faint">Pool</span>
        <b className="text-gold text-lg font-extrabold tabular-nums">{inr(market.pool)}</b>
      </div>
      <div className="relative flex h-2.5 rounded-full overflow-hidden mt-2.5 bg-raise">
        <span className="relative bg-khuseel transition-[width] duration-settle" style={{ width: kw + "%" }}>
          <span className="absolute inset-0 bg-gradient-to-t from-transparent to-white/15" />
        </span>
        <span className="relative bg-bansod transition-[width] duration-settle" style={{ width: 100 - kw + "%" }}>
          <span className="absolute inset-0 bg-gradient-to-t from-transparent to-white/15" />
        </span>
      </div>
      <div className="flex justify-between text-2xs text-faint mt-2 tabular-nums">
        <span className="inline-flex items-center gap-1.5">
          <i className="w-1.5 h-1.5 rounded-full bg-khuseel" />{inr(k.total)} · {k.bettors}
        </span>
        <span className="inline-flex items-center gap-1.5">
          {inr(b.total)} · {b.bettors}<i className="w-1.5 h-1.5 rounded-full bg-bansod" />
        </span>
      </div>
    </div>
  );
}
