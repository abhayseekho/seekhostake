import { useCallback, useEffect, useRef, useState } from "react";
import { get, post } from "../api.js";
import { SIDES, LABEL, SIDE_TEXT, REASON_TEXT } from "../lib/constants.js";
import { TONE_TEXT, tone } from "../lib/theme.js";
import { inr } from "../lib/format.js";
import ProjectedPayouts from "./ProjectedPayouts.jsx";
import MarketBook from "./MarketBook.jsx";
import BetLedger from "./BetLedger.jsx";

// The cashier's speed tool during the live window (audit §8) — the information architecture here
// was already right (pending-cash-first, race console, rare tools tucked behind a disclosure) and
// is UNCHANGED below; every handler, every state variable, every API call is identical to the
// pre-revamp version. The one real visual gap: the "COLLECT ₹X" figure is the single most
// important number on this entire surface (literally "how much cash to take from this person,
// right now") and used to carry the same weight as a dozen other small badges elsewhere on the
// page — it's now sized and colored to be unmistakably the answer to "what do I do next."
export default function Admin({ state, refresh }) {
  const [pending, setPending] = useState([]);
  const [lapWinner, setLapWinner] = useState("");
  const [lapTime, setLapTime] = useState("");
  const [manual, setManual] = useState({ name: "", market: "match", outcome: "khuseel", amount: "" });
  const [seedAmt, setSeedAmt] = useState("");
  const [msg, setMsg] = useState("");
  const { race, markets, house } = state;
  const matchPool = markets.find((m) => m.id === "match").pool;

  const pendingJsonRef = useRef("");
  const loadPending = useCallback(async () => {
    const r = await get("/api/admin/pending");
    if (!r.pending) return;
    // Same anti-churn guard as the main state fetch: don't re-render (and don't shift the
    // approve/reject buttons under an in-progress tap) unless the queue actually changed.
    const json = JSON.stringify(r.pending);
    if (json !== pendingJsonRef.current) {
      pendingJsonRef.current = json;
      setPending(r.pending);
    }
  }, []);
  useEffect(() => { loadPending(); }, [loadPending, state]);

  const act = async (fn, failLabel) => {
    const r = await fn();
    const text = r._error ? (REASON_TEXT[r._error] || r._error) : "";
    setMsg(text);
    // Approve/reject failures remove the row from the queue exactly like success does — the
    // small red line below is easy to miss mid-flow, so a failure gets an interrupting alert too.
    if (text && failLabel) alert(`${failLabel} — not done.\n\n${text}`);
    refresh(); loadPending();
  };

  const manualMarket = markets.find((m) => m.id === manual.market);
  const lapInProgress = race.phase.startsWith("lap");
  const canStart = ["prerace", "break1", "break2"].includes(race.phase);
  const suspendedMarkets = markets.filter((m) => m.suspended);

  const approve = async (p) => {
    const r = await post(`/api/admin/bets/${p.id}/approve`);
    if (r._error) {
      setMsg(REASON_TEXT[r._error] || r._error);
      alert(`Approving ${p.display_name}'s ${inr(p.amount)} bet — not done.\n\n${REASON_TEXT[r._error] || r._error}`);
    } else if (r.suspended_market) {
      const mkt = markets.find((m) => m.id === r.suspended_market);
      setMsg("");
      alert(`Approved. But this bet swung "${mkt ? mkt.name : r.suspended_market}" ` +
        `${r.swing.ratio}× on ${LABEL[r.swing.outcome] || r.swing.outcome}, and the house isn't ` +
        `covered on every outcome (worst case ${inr(r.swing.floor)}) — SUSPENDED for review. ` +
        `Resume it from the panel below once you're comfortable.`);
    } else if (r.swing_cleared) {
      // Odds moved a lot but house_floor stayed >= 0 across every possible outcome — provably
      // safe, so it never paused. Quiet note only; nothing needs the admin's attention.
      setMsg(`Note: this bet moved ${LABEL[r.swing_cleared.outcome] || r.swing_cleared.outcome} ` +
        `${r.swing_cleared.ratio}× — checked, house is covered (worst case ${inr(r.swing_cleared.floor)}), stayed live.`);
    } else {
      setMsg("");
    }
    refresh(); loadPending();
  };

  const recheck = async () => {
    const r = await post("/api/admin/markets/recheck");
    if (r._error) { alert(r._error); return; }
    if (r.cleared.length) {
      alert(`House is covered (worst case ${inr(r.floor)}) — resumed: ` +
        r.cleared.map((id) => (markets.find((m) => m.id === id) || {}).name || id).join(", "));
    } else if (r.still_suspended.length) {
      alert(`House is not covered on every outcome right now (worst case ${inr(r.floor)}) — ` +
        `left suspended: ` + r.still_suspended.map((id) => (markets.find((m) => m.id === id) || {}).name || id).join(", "));
    } else {
      alert("Nothing is suspended.");
    }
    refresh();
  };

  return (
    <div className="bg-card border border-gold/50 rounded-2xl p-4 space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-2xs font-extrabold tracking-label uppercase text-gold">Cashier console</h2>
        {pending.length > 0 && (
          <span className="text-2xs font-bold text-gold bg-gold/10 border border-gold/40 rounded-full px-2.5 py-0.5">
            {pending.length} pending
          </span>
        )}
      </div>

      {house && house.fixed_exposure != null && (
        <div className={`flex items-center justify-between gap-2 rounded-xl px-3 py-2.5 border text-sm
          ${house.fixed_exposure < 0 ? "border-bad/40 bg-bad/10" : "border-edge bg-raise"}`}>
          <span className="text-2xs font-bold tracking-label uppercase text-faint">
            Fixed-odds exposure · worst case</span>
          <span className="tabular-nums font-extrabold">
            <span className={house.fixed_exposure < 0 ? "text-bad" : "text-khuseel"}>
              {house.fixed_exposure < 0 ? "−" : "+"}{inr(Math.abs(house.fixed_exposure))}
            </span>
            <span className="text-faint font-normal"> / cap {inr(house.fixed_cap)}</span>
          </span>
        </div>
      )}

      {suspendedMarkets.length > 0 && (
        <div className="bg-gold/10 border border-gold/40 rounded-xl p-3 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-2xs font-bold tracking-label uppercase text-gold">
              Suspended markets — unusual odds swing</h3>
            <button onClick={recheck}
              className="text-2xs font-bold text-gold underline shrink-0 hover:text-gold/80 transition-colors duration-quick">
              Recheck now</button>
          </div>
          {suspendedMarkets.map((m) => (
            <div key={m.id} className="flex items-center justify-between text-sm">
              <span>{m.name}</span>
              <button onClick={() => act(() => post(`/api/admin/markets/${m.id}/resume`))}
                className="bg-gold text-bg font-bold rounded-lg px-3 py-1 text-xs
                  hover:brightness-110 active:scale-[0.99] transition">Resume</button>
            </div>
          ))}
        </div>
      )}

      {/* ── Needs your attention now ─────────────────────────────────────── */}
      <div>
        <h3 className="text-2xs font-bold tracking-label uppercase text-faint mb-2">
          Pending · collect cash first ({pending.length})</h3>
        {pending.length === 0 && <p className="text-faint text-sm">No pending requests.</p>}
        {pending.map((p) => {
          const raise = p.current && p.current.outcome === p.outcome;
          return (
            <div key={p.id} className="flex items-center justify-between bg-raise border border-edge rounded-xl px-3 py-3 mb-2 text-sm">
              <div>
                <b>{p.display_name}</b> · {p.market_name} · <b className={TONE_TEXT[tone(p.outcome)]}>{p.outcome_label}</b>
                <div className="flex items-center gap-2 mt-2 flex-wrap">
                  <span className="inline-flex items-baseline gap-1.5 bg-gold/15 border border-gold/50 rounded-lg px-3 py-1">
                    <span className="text-gold text-3xs font-extrabold tracking-label">COLLECT</span>
                    <span className="text-gold font-extrabold text-lg tabular-nums">{inr(p.cash_to_collect)}</span>
                  </span>
                  <span className="text-2xs text-faint bg-bg rounded-md px-2 py-0.5">
                    {raise ? <>Raise <b className="text-dim tabular-nums">{inr(p.current.amount)} → {inr(p.amount)}</b></>
                      : p.current ? <>Replaces {inr(p.current.amount)} on other outcome</>
                        : "New bet"}
                  </span>
                </div>
              </div>
              <div className="flex gap-2 shrink-0 ml-2">
                <button onClick={() => approve(p)}
                  className="bg-khuseel text-bg font-extrabold rounded-lg px-3 py-1.5 text-xs
                    hover:brightness-110 active:scale-[0.99] transition">Approve</button>
                <button onClick={() => act(() => post(`/api/admin/bets/${p.id}/reject`))}
                  className="border border-edge text-bad rounded-lg px-2.5 py-1.5 text-xs
                    hover:bg-bad/10 transition-colors duration-quick">✕</button>
              </div>
            </div>
          );
        })}
      </div>

      <div>
        <h3 className="text-2xs font-bold tracking-label uppercase text-faint mb-2">Race console</h3>
        <div className="flex flex-wrap gap-2 items-center">
          {canStart && (
            <button onClick={() => {
              // Starting a lap can instantly invalidate a still-pending request (e.g. a Lap 1
              // Winner bet nobody approved yet) -- it then auto-rejects on the next Approve tap,
              // which looks identical to a successful approve unless you're watching closely.
              if (pending.length && !confirm(
                `${pending.length} request${pending.length > 1 ? "s are" : " is"} still pending. ` +
                `Starting this lap may make some of them impossible to approve. Continue?`)) return;
              act(() => post("/api/admin/race/start-lap"));
            }}
              className="bg-bad text-ink font-bold rounded-xl px-4 py-2.5
                hover:brightness-110 active:scale-[0.99] transition">
              ▶ Start lap {race.laps.length + 1}{race.phase === "break1" ? " — closes book" : ""}
            </button>
          )}
          {lapInProgress && (
            <>
              <select value={lapWinner} onChange={(e) => setLapWinner(e.target.value)}
                className="bg-bg border border-edge rounded-xl px-3 py-2.5
                  focus-visible:ring-2 focus-visible:ring-khuseel/50 outline-none">
                <option value="">Lap winner…</option>
                {SIDES.map((s) => <option key={s} value={s}>{LABEL[s]}</option>)}
              </select>
              <input placeholder="Time (s)" value={lapTime}
                onChange={(e) => setLapTime(e.target.value.replace(/[^\d.]/g, ""))}
                className="bg-bg border border-edge rounded-xl px-3 py-2.5 w-24
                  focus-visible:ring-2 focus-visible:ring-khuseel/50 outline-none" />
              <button disabled={!lapWinner}
                onClick={() => act(() => post("/api/admin/race/lap-result",
                  { winner: lapWinner, time_s: lapTime ? parseFloat(lapTime) : null }))
                  .then(() => { setLapWinner(""); setLapTime(""); })}
                className={`font-bold rounded-xl px-4 py-2.5 transition
                  ${lapWinner ? "bg-khuseel text-bg hover:brightness-110 active:scale-[0.99]" : "bg-raise text-faint"}`}>
                Record result
              </button>
            </>
          )}
          {race.phase === "finished" && (
            <button onClick={() => { if (confirm("Settle every market? This is final and freezes the payout sheet.")) act(() => post("/api/admin/settle")); }}
              className="bg-gold text-bg font-extrabold rounded-xl px-4 py-2.5
                hover:brightness-110 active:scale-[0.99] transition">Settle all markets</button>
          )}
          {matchPool === 0 && race.phase === "prerace" && (
            <button onClick={() => act(() => post("/api/admin/seed"))}
              className="bg-raise border border-edge rounded-xl px-4 py-2.5 text-dim
                hover:text-ink transition-colors duration-quick">Load seed book</button>
          )}
          {matchPool > 0 && race.phase !== "settled" && (
            <button onClick={() => { if (confirm(
              (race.phase === "prerace"
                ? "Wipe ALL bets in ALL markets and reload the seed book? "
                : `Wipe ALL bets in ALL markets, DISCARD lap progress (currently ${race.phase}), ` +
                  `and roll the race back to pre-race with the seed book reloaded? `) +
              "This cannot be undone.")) act(() => post("/api/admin/reset-book")); }}
              className="bg-raise border border-edge rounded-xl px-4 py-2.5 text-dim
                hover:text-ink transition-colors duration-quick">
              {race.phase === "prerace" ? "Reset to seed book" : "Full reset — back to pre-race"}
            </button>
          )}
        </div>
        {race.phase === "break1" && (
          <p className="text-2xs text-gold mt-2">Starting lap 2 closes all betting; unapproved requests are rejected.</p>
        )}
      </div>

      <details className="border-t border-edge/60 pt-3" open>
        <summary className="cursor-pointer text-2xs font-bold tracking-label uppercase text-faint
          hover:text-dim select-none transition-colors duration-quick">
          Full book — every approved bet, every market</summary>
        <div className="mt-3 space-y-4">
          {markets.map((m) => <MarketBook key={m.id} market={m} isOwner refresh={refresh} />)}
        </div>
      </details>

      {race.phase !== "settled" && (
        <details className="border-t border-edge/60 pt-3" open>
          <summary className="cursor-pointer text-2xs font-bold tracking-label uppercase text-faint
            hover:text-dim select-none transition-colors duration-quick">
            Projected payouts — who gets what, under every outcome still possible</summary>
          <div className="mt-3">
            <ProjectedPayouts state={state} refresh={refresh} />
          </div>
        </details>
      )}

      <details className="border-t border-edge/60 pt-3">
        <summary className="cursor-pointer text-2xs font-bold tracking-label uppercase text-faint
          hover:text-dim select-none transition-colors duration-quick">
          All bets — find and correct any bet's status</summary>
        <div className="mt-3">
          <BetLedger state={state} refresh={refresh} />
        </div>
      </details>

      {/* ── Setup & rare-use tools — tucked away, one tap to reach ───────── */}
      <details className="border-t border-edge/60 pt-3">
        <summary className="cursor-pointer text-2xs font-bold tracking-label uppercase text-faint
          hover:text-dim select-none transition-colors duration-quick">
          Setup &amp; manual tools</summary>

        <div className="mt-3 space-y-4">
          <div>
            <h3 className="text-2xs font-bold tracking-label uppercase text-faint mb-2">
              Market control</h3>
            <div className="flex flex-wrap gap-1.5">
              {markets.map((m) => (
                <button key={m.id}
                  onClick={() => act(() => post(`/api/admin/markets/${m.id}/${m.suspended ? "resume" : "suspend"}`))}
                  className={`text-2xs rounded-lg px-2.5 py-1 border transition-colors duration-quick ${m.suspended
                    ? "border-gold/40 bg-gold/10 text-gold" : "border-edge text-faint hover:text-dim"}`}>
                  {m.name} {m.suspended ? "· Resume" : "· Pause"}
                </button>
              ))}
            </div>
          </div>

          {house && race.phase !== "settled" && (
            <div>
              <h3 className="text-2xs font-bold tracking-label uppercase text-faint mb-2">
                House seed · cap {inr(house.seed_cap)} ·{" "}
                <span className={house.floor >= 0 ? "text-khuseel" : "text-bad"}>
                  worst case {house.floor >= 0 ? "+" : "−"}{inr(Math.abs(house.floor))}
                </span></h3>
              <div className="flex flex-wrap gap-2 items-center">
                <span className="text-xs text-dim">
                  {house.seed ? <>Current: <b className={TONE_TEXT[tone(house.seed.outcome)]}>
                    {LABEL[house.seed.outcome]} {inr(house.seed.amount)}</b></> : "No seed placed."}
                </span>
                <input placeholder="₹" inputMode="numeric" value={seedAmt}
                  onChange={(e) => setSeedAmt(e.target.value.replace(/\D/g, ""))}
                  className="bg-bg border border-edge rounded-xl px-3 py-2 w-24
                    focus-visible:ring-2 focus-visible:ring-gold/50 outline-none" />
                {SIDES.map((s) => (
                  <button key={s} disabled={seedAmt === ""}
                    onClick={() => act(() => post("/api/admin/house-seed",
                      { outcome: s, amount: parseInt(seedAmt, 10) || 0 })).then(() => setSeedAmt(""))}
                    className={`rounded-xl px-3 py-2 text-xs font-bold border border-edge transition-colors
                      duration-quick hover:border-dim ${SIDE_TEXT[s]}`}>
                    Seed {LABEL[s]}
                  </button>
                ))}
                {house.seed && (
                  <button onClick={() => act(() => post("/api/admin/house-seed", { outcome: house.seed.outcome, amount: 0 }))}
                    className="text-bad text-xs underline hover:text-bad/80 transition-colors duration-quick">Remove seed</button>
                )}
                <button onClick={() => act(() => post("/api/admin/side-seeds", { per_market: 200, tilt: true }))}
                  className="rounded-xl px-3 py-2 text-xs font-bold border border-edge text-gold
                    hover:border-dim transition-colors duration-quick">
                  Seed side odds · ₹200/market · Bansod-tilted
                </button>
                <button onClick={() => act(() => post("/api/admin/side-seeds", { per_market: 0 }))}
                  className="text-faint text-xs underline hover:text-dim transition-colors duration-quick">Clear side liquidity</button>
              </div>
            </div>
          )}

          {race.phase !== "settled" && (
            <div>
              <h3 className="text-2xs font-bold tracking-label uppercase text-faint mb-2">
                Manual bet · amount 0 = void</h3>
              <div className="flex flex-wrap gap-2">
                <input placeholder="Name" value={manual.name}
                  onChange={(e) => setManual({ ...manual, name: e.target.value })}
                  className="bg-bg border border-edge rounded-xl px-3 py-2 w-32
                    focus-visible:ring-2 focus-visible:ring-dim outline-none" />
                <select value={manual.market}
                  onChange={(e) => {
                    const mk = markets.find((m) => m.id === e.target.value);
                    setManual({ ...manual, market: e.target.value, outcome: mk.outcomes[0].id });
                  }}
                  className="bg-bg border border-edge rounded-xl px-3 py-2
                    focus-visible:ring-2 focus-visible:ring-dim outline-none">
                  {markets.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
                </select>
                <select value={manual.outcome} onChange={(e) => setManual({ ...manual, outcome: e.target.value })}
                  className="bg-bg border border-edge rounded-xl px-3 py-2
                    focus-visible:ring-2 focus-visible:ring-dim outline-none">
                  {manualMarket.outcomes.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
                </select>
                <input placeholder="₹" inputMode="numeric" value={manual.amount}
                  onChange={(e) => setManual({ ...manual, amount: e.target.value.replace(/\D/g, "") })}
                  className="bg-bg border border-edge rounded-xl px-3 py-2 w-24
                    focus-visible:ring-2 focus-visible:ring-dim outline-none" />
                <button disabled={!manual.name || manual.amount === ""}
                  onClick={() => act(() => post("/api/admin/bets/manual",
                    { name: manual.name, market: manual.market, outcome: manual.outcome,
                      amount: parseInt(manual.amount, 10) }))
                    .then(() => setManual({ name: "", market: "match", outcome: "khuseel", amount: "" }))}
                  className={`rounded-xl px-4 py-2 font-bold transition
                    ${manual.name && manual.amount !== "" ? "bg-khuseel text-bg hover:brightness-110 active:scale-[0.99]" : "bg-raise text-faint"}`}>
                  Save
                </button>
              </div>
            </div>
          )}
        </div>
      </details>

      {msg && <p className="text-bad text-sm">{msg}</p>}
    </div>
  );
}
