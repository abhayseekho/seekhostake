import { useCallback, useEffect, useRef, useState } from "react";
import { get } from "../api.js";
import { LABEL, SIDE_TEXT } from "../lib/constants.js";
import { inr } from "../lib/format.js";

// "How much do I owe everyone" — answered for every outcome that's still possible from here, not
// just the one that eventually happens. Pulls from the SAME settle_all()/race_scripts() the real
// settlement uses (api.py's /api/admin/projected-payouts is a pure read of that math, nothing
// duplicated here), so this can never show a number real settlement wouldn't also produce.
//
// Two scripts can share a headline (e.g. two different "Khuseel 2–1" paths, depending on which
// lap Bansod won) but differ underneath — Correct Score and Comeback Special settle differently
// depending on WHICH lap was lost, not just the final score. Colliding labels get the deciding
// lap appended so it's never ambiguous which tab you're looking at.
function scriptLabel(script, collides) {
  const loser = script.winner === "khuseel" ? "bansod" : "khuseel";
  const base = `${LABEL[script.winner]} ${script.wins[script.winner]}–${script.wins[loser]}`;
  if (!collides) return base;
  const loserLap = script.laps.find((l) => l.winner === loser);
  return `${base} (L${loserLap.lap} ${LABEL[loser]})`;
}

export default function ProjectedPayouts({ state, refresh: parentRefresh }) {
  const [scripts, setScripts] = useState(null);
  const [active, setActive] = useState(0);
  const scriptsJsonRef = useRef("");

  const load = useCallback(async () => {
    const r = await get("/api/admin/projected-payouts");
    if (!r.scripts) return;  // already settled, or a transient error — just don't update
    const json = JSON.stringify(r.scripts);
    if (json !== scriptsJsonRef.current) {
      scriptsJsonRef.current = json;
      setScripts(r.scripts);
      setActive((a) => Math.min(a, r.scripts.length - 1));
    }
  }, []);
  useEffect(() => { load(); }, [load, state]);

  if (!scripts || !scripts.length) return <p className="text-faint text-sm">Loading projections…</p>;

  const labelCounts = {};
  for (const s of scripts) {
    const b = `${LABEL[s.winner]} ${s.wins[s.winner]}–${s.wins[s.winner === "khuseel" ? "bansod" : "khuseel"]}`;
    labelCounts[b] = (labelCounts[b] || 0) + 1;
  }
  const labels = scripts.map((s) => scriptLabel(s, labelCounts[
    `${LABEL[s.winner]} ${s.wins[s.winner]}–${s.wins[s.winner === "khuseel" ? "bansod" : "khuseel"]}`] > 1));
  const sel = scripts[active];

  return (
    <div className="space-y-3">
      <p className="text-2xs text-faint">
        {scripts.length === 1
          ? "The race outcome is decided — this is the only payout scenario left."
          : `${scripts.length} outcomes are still possible from here. Pick one to see who gets what.`}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {scripts.map((s, i) => (
          <button key={i} onClick={() => setActive(i)}
            className={`text-2xs font-bold rounded-lg px-2.5 py-1.5 border transition-colors duration-quick
              ${i === active
                ? `${SIDE_TEXT[s.winner]} border-current bg-current/10`
                : "border-edge text-faint hover:text-dim"}`}>
            {labels[i]}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        <span className="bg-gold/15 text-gold font-extrabold text-sm rounded-xl px-3.5 py-1.5 tabular-nums">
          🏆 Swimmer gets {inr(sel.swimmer_take)}
        </span>
        <span className="bg-raise border border-edge text-dim font-bold text-xs rounded-xl px-3 py-1.5 tabular-nums">
          House keeps {inr(sel.house_take)}
        </span>
      </div>

      <div className="overflow-x-auto -mx-1">
        <table className="w-full text-sm">
          <thead><tr className="text-faint text-3xs uppercase tracking-label text-left">
            <th className="pb-2 font-semibold px-1">Bettor</th>
            <th className="pb-2 font-semibold text-right px-1">Staked</th>
            <th className="pb-2 font-semibold text-right px-1">Pay them</th>
            <th className="pb-2 font-semibold text-right px-1">Net for them</th></tr></thead>
          <tbody>
            {sel.aggregate.map((r, i) => (
              <tr key={r.key} className={`border-t border-edge/50 ${i % 2 ? "bg-bg/40" : ""}`}>
                <td className="py-1.5 px-1">{r.display_name}</td>
                <td className="text-right text-dim tabular-nums px-1">{inr(r.stake)}</td>
                <td className="text-right font-bold tabular-nums px-1">{inr(r.payout)}</td>
                <td className={`text-right tabular-nums px-1 ${r.net >= 0 ? "text-khuseel" : "text-bad"}`}>
                  {r.net >= 0 ? "+" : "−"}{inr(Math.abs(r.net))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
