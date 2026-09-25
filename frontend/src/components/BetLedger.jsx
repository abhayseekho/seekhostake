import { useCallback, useEffect, useRef, useState } from "react";
import { get, post } from "../api.js";
import { REASON_TEXT } from "../lib/constants.js";
import { inr } from "../lib/format.js";

const STATUS_LABEL = {
  pending: "Pending", approved: "Approved", rejected: "Rejected",
  cancelled: "Cancelled", superseded: "Superseded",
};
const STATUS_TEXT = {
  pending: "text-gold", approved: "text-khuseel", rejected: "text-bad",
  cancelled: "text-faint", superseded: "text-faint",
};
const SETTABLE = ["pending", "approved", "rejected", "cancelled"];
const FILTERS = ["all", ...SETTABLE, "superseded"];

// The correction tool for everything /approve, /reject and Void don't cover: the moment a bet
// leaves the live queue (rejected, cancelled, superseded) it's invisible to every other admin
// view — this is the one place it's still findable and fixable. Each row also carries the
// CURRENT odds on its own outcome (api.py computes it, not this component — same book the odds
// board reads), so "what's allocated to who" is read straight off the row.
//
// Status changes go through a two-step select-then-Save, not an instant-fire onChange: a
// misclick on a <select> is one accidental event away from moving real money, and this keeps
// the select a plain controlled input (value always driven by state) with no native-DOM-vs-React
// revert edge case to fight if a confirm() gets cancelled.
export default function BetLedger({ state, refresh: parentRefresh }) {
  const [bets, setBets] = useState(null);
  const [filter, setFilter] = useState("all");
  const [edits, setEdits] = useState({});
  const [busy, setBusy] = useState(null);
  const betsJsonRef = useRef("");

  const load = useCallback(async () => {
    const r = await get("/api/admin/bets");
    if (!r.bets) return;
    const json = JSON.stringify(r.bets);
    if (json !== betsJsonRef.current) {
      betsJsonRef.current = json;
      setBets(r.bets);
    }
  }, []);
  useEffect(() => { load(); }, [load, state]);

  if (!bets) return <p className="text-faint text-sm">Loading ledger…</p>;

  const shown = filter === "all" ? bets : bets.filter((b) => b.status === filter);

  const save = async (b) => {
    const next = edits[b.id];
    if (!next || next === b.status) return;
    if (!confirm(`Set ${b.display_name}'s ${inr(b.amount)} ${b.market_name} bet to ` +
      `"${STATUS_LABEL[next]}"? (currently "${STATUS_LABEL[b.status]}")`)) return;
    setBusy(b.id);
    const r = await post(`/api/admin/bets/${b.id}/status`, { status: next });
    setBusy(null);
    setEdits((cur) => { const c = { ...cur }; delete c[b.id]; return c; });
    if (r._error) {
      alert(`Status change failed.\n\n${REASON_TEXT[r._error] || r._error}`);
    } else if (r.suspended_market) {
      alert(`Done. But this left the house uncovered on some outcome in "${r.suspended_market}" ` +
        `(worst case ${inr(r.floor)}) — that market is now SUSPENDED for review.`);
    }
    load(); parentRefresh();
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map((f) => {
          const n = f === "all" ? bets.length : bets.filter((b) => b.status === f).length;
          return (
            <button key={f} onClick={() => setFilter(f)}
              className={`text-2xs font-bold rounded-lg px-2.5 py-1.5 border transition-colors duration-quick
                ${f === filter ? "border-dim bg-raise text-ink" : "border-edge text-faint hover:text-dim"}`}>
              {f === "all" ? "All" : STATUS_LABEL[f]} ({n})
            </button>
          );
        })}
      </div>

      <div className="overflow-x-auto -mx-1">
        <table className="w-full text-sm">
          <thead><tr className="text-faint text-3xs uppercase tracking-label text-left">
            <th className="pb-2 font-semibold px-1">Bettor</th>
            <th className="pb-2 font-semibold px-1">Market · outcome</th>
            <th className="pb-2 font-semibold text-right px-1">Amount</th>
            <th className="pb-2 font-semibold text-right px-1">Odds</th>
            <th className="pb-2 font-semibold px-1">Status</th>
            <th className="pb-2 font-semibold px-1"></th></tr></thead>
          <tbody>
            {shown.map((b, i) => {
              const picked = edits[b.id];
              const dirty = picked && picked !== b.status;
              return (
                <tr key={b.id} className={`border-t border-edge/50 ${i % 2 ? "bg-bg/40" : ""}`}>
                  <td className="py-1.5 px-1 truncate max-w-[9rem]">{b.display_name}</td>
                  <td className="py-1.5 px-1 text-dim whitespace-nowrap">{b.market_name} · {b.outcome_label}</td>
                  <td className="text-right tabular-nums px-1">{inr(b.amount)}</td>
                  <td className="text-right tabular-nums px-1 text-dim">
                    {b.est_mult ? b.est_mult.toFixed(2) + "×" : "—"}
                  </td>
                  <td className={`px-1 font-bold whitespace-nowrap ${STATUS_TEXT[b.status]}`}>
                    {STATUS_LABEL[b.status]}
                  </td>
                  <td className="px-1">
                    <div className="flex items-center gap-1.5">
                      <select value={picked ?? b.status} disabled={busy === b.id}
                        onChange={(e) => setEdits((cur) => ({ ...cur, [b.id]: e.target.value }))}
                        className="bg-bg border border-edge rounded-lg px-1.5 py-1 text-2xs
                          focus-visible:ring-2 focus-visible:ring-dim outline-none">
                        {SETTABLE.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
                        {b.status === "superseded" &&
                          <option value="superseded" disabled>Superseded</option>}
                      </select>
                      {dirty && (
                        <button onClick={() => save(b)} disabled={busy === b.id}
                          className="bg-khuseel text-bg font-extrabold rounded-lg px-2 py-1 text-2xs
                            hover:brightness-110 active:scale-[0.99] transition disabled:opacity-50 shrink-0">
                          {busy === b.id ? "…" : "Save"}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {shown.length === 0 && <p className="text-faint text-sm">No bets in this filter.</p>}
    </div>
  );
}
