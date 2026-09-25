import { useEffect, useState } from "react";
import { post } from "../api.js";
import { REASON_TEXT } from "../lib/constants.js";
import { inr } from "../lib/format.js";

// The highest-stakes interaction in the app — real cash changes hands off the back of this
// panel. Audit §5: functionally correct already (verified live end-to-end); the two real gaps
// were a success message that lingers forever, including after the bet is actually approved
// (fixed below: it's a transient confirmation, not a status — the permanent status lives on
// MyBets/MarketCard's "IN POOL" tag), and mobile placement, which App.jsx now handles by making
// this panel a fixed bottom sheet on small screens once an outcome is picked, so placing a bet
// never requires scrolling away from the market you just tapped.
export default function BetSlip({ picked, refresh, onClear, fixed }) {
  const [amount, setAmount] = useState("");
  const [msg, setMsg] = useState(null);
  const amt = parseInt(amount, 10) || 0;

  useEffect(() => {
    if (msg?.ok) {
      const t = setTimeout(() => setMsg(null), 5000);
      return () => clearTimeout(t);
    }
  }, [msg]);

  // A fresh pick means a stale confirmation/error from a previous slip no longer applies.
  useEffect(() => { setMsg(null); }, [picked?.market, picked?.outcome]);

  const submit = async () => {
    setMsg(null);
    const r = await post("/api/bets", { market: picked.market, outcome: picked.outcome, amount: amt });
    if (r._error) setMsg({ ok: false, text: REASON_TEXT[r._error] || r._error });
    else {
      setMsg({ ok: true, text: `${inr(amt)} on ${picked.label} — submitted. Pay cash to confirm.` });
      setAmount("");
    }
    refresh();
  };

  return (
    <div className="bg-raise border border-edge rounded-2xl p-4 space-y-3 shadow-xl shadow-black/20">
      <div className="flex justify-between items-center">
        <h2 className="text-2xs font-bold tracking-label text-faint uppercase">Bet slip</h2>
        {picked && <button onClick={onClear}
          className="text-faint text-2xs underline hover:text-dim transition-colors duration-quick">Clear</button>}
      </div>
      {!picked ? (
        <p className="text-dim text-sm">Select an outcome to place a bet.</p>
      ) : (
        <>
          <p className="text-sm text-dim">
            {picked.name} — <b className="text-ink">{picked.label}</b>
            {picked.est && <span className="tabular-nums"> @ {picked.est.toFixed(2)}×</span>}
          </p>
          <div className="flex gap-2">
            <input inputMode="numeric" placeholder="Amount ₹" value={amount}
              onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))}
              className="flex-1 min-w-0 bg-bg border border-edge rounded-xl px-4 py-3 font-bold tabular-nums
                outline-none focus-visible:ring-2 focus-visible:ring-gold/50 focus:border-gold
                transition-colors duration-quick" />
            {[500, 1000, 2000].map((v) => (
              <button key={v} onClick={() => setAmount(String(v))}
                className="bg-bg border border-edge rounded-xl px-3 text-sm font-semibold text-dim
                  hover:text-ink hover:border-dim transition-colors duration-quick">
                {v >= 1000 ? v / 1000 + "k" : v}</button>
            ))}
          </div>
          {amt > 0 && (picked.est ? (
            <div className="px-0.5">
              <div className="flex justify-between items-baseline text-xs text-dim">
                <span>{fixed ? "Locked payout" : "Indicative payout"}</span>
                <b className="text-ink text-base tabular-nums">{inr(Math.floor(amt * picked.est))}</b>
              </div>
              {fixed && (
                <p className="text-2xs text-faint mt-1">
                  Odds lock at the moment you bet — a larger stake may lock a touch shorter; you’ll see
                  your exact locked odds under “My bets”.
                </p>
              )}
            </div>
          ) : (
            <p className="text-2xs text-faint px-0.5">
              {fixed ? "This outcome is closed." : "Odds form once bets are placed on this outcome."}
            </p>
          ))}
          <button disabled={amt < 1} onClick={submit}
            className={`w-full font-extrabold rounded-xl py-3.5 transition-all duration-quick
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-raise
              ${amt >= 1 ? "bg-khuseel text-bg hover:brightness-110 active:scale-[0.99] focus-visible:ring-khuseel/50"
                : "bg-card text-faint"}`}>
            {amt >= 1 ? `Bet ${inr(amt)} on ${picked.label}` : "Enter amount"}
          </button>
        </>
      )}
      {msg && <p className={`text-sm ${msg.ok ? "text-khuseel" : "text-bad"}`}>{msg.text}</p>}
    </div>
  );
}
