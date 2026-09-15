import React, { useEffect, useState, useCallback } from "react";
import { get, post } from "./api.js";

const SIDES = ["khuseel", "bansod"];
const LABEL = { khuseel: "Khuseel", bansod: "Bansod" };
const SIDE_TEXT = { khuseel: "text-khuseel", bansod: "text-bansod" };
const SIDE_BORDER = { khuseel: "border-khuseel", bansod: "border-bansod" };
const inr = (n) => "₹" + Number(n || 0).toLocaleString("en-IN");

const PHASE_LABEL = {
  prerace: "Pre-race — betting open",
  lap1: "🔴 Live — lap 1 in progress",
  break1: "Break 1 — betting open (last window)",
  lap2: "🔴 Live — lap 2 in progress · book closed",
  break2: "Break 2 — book closed, decider next",
  lap3: "🔴 Live — lap 3, the decider",
  finished: "Race finished — awaiting settlement",
  settled: "Settled",
};

const REASON_TEXT = {
  book_closed: "Book is closed — no more bets.",
  no_side_switch: "You can't switch sides after lap 1 — raises on your side only.",
  bad_amount: "Enter a whole-rupee amount of at least ₹1.",
  not_pending: "That request was already handled.",
};

// ── login ────────────────────────────────────────────────────────────────────────────────────────
function Login({ authMode, onNamed }) {
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [showRules, setShowRules] = useState(false);
  const [showAdmin, setShowAdmin] = useState(false);
  const [pw, setPw] = useState("");
  const submitName = async () => {
    const r = await post("/auth/name", { name });
    if (r._error) setErr(r._error === "bad_name" ? "Enter your real name (2–40 chars)." : r._error);
    else onNamed();
  };
  const submitAdmin = async () => {
    const r = await post("/auth/admin", { password: pw });
    if (r._error) setErr("Wrong admin password.");
    else onNamed();
  };
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="bg-card border border-edge rounded-2xl p-8 max-w-sm w-full text-center">
        <div className="text-5xl mb-3">🏊</div>
        <h1 className="text-2xl font-extrabold mb-1">Khuseel vs Bansod</h1>
        <p className="text-dim mb-2">Live betting · best of 3 laps · 16 Sept</p>
        <button onClick={() => setShowRules(true)} className="text-dim text-sm underline mb-6">📜 Read the rules</button>
        {showRules && <Rules onClose={() => setShowRules(false)} />}
        {authMode === "name" ? (
          <div className="space-y-3">
            <input
              className="w-full bg-bg border border-edge rounded-xl px-4 py-3 outline-none focus:border-khuseel"
              placeholder="Your name" value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submitName()} />
            <button onClick={submitName}
              className="w-full bg-khuseel text-bg font-bold rounded-xl py-3">Enter</button>
            {err && <p className="text-bad text-sm">{err}</p>}
            {showAdmin ? (
              <div className="flex gap-2">
                <input type="password" placeholder="Admin password" value={pw}
                  onChange={(e) => setPw(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && submitAdmin()}
                  className="flex-1 bg-bg border border-edge rounded-xl px-4 py-2 outline-none" />
                <button onClick={submitAdmin} className="bg-gold text-bg font-bold rounded-xl px-4">Go</button>
              </div>
            ) : (
              <button onClick={() => setShowAdmin(true)} className="text-dim text-xs underline">Admin login</button>
            )}
          </div>
        ) : (
          <a href="/auth/login"
            className="block w-full bg-khuseel text-bg font-bold rounded-xl py-3">
            Sign in with Google (@seekhoapp.com)
          </a>
        )}
      </div>
    </div>
  );
}

// ── race status ──────────────────────────────────────────────────────────────────────────────────
function RaceStrip({ race }) {
  const live = race.phase.startsWith("lap");
  return (
    <div className={`bg-card border ${live ? "border-bad" : "border-edge"} rounded-2xl p-4`}>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <span className={`font-bold ${live ? "text-bad animate-pulse" : "text-dim"}`}>
          {PHASE_LABEL[race.phase] || race.phase}
        </span>
        <span className="font-extrabold text-lg">
          <span className={SIDE_TEXT.khuseel}>{LABEL.khuseel} {race.wins.khuseel}</span>
          <span className="text-dim mx-2">–</span>
          <span className={SIDE_TEXT.bansod}>{race.wins.bansod} {LABEL.bansod}</span>
        </span>
      </div>
      {race.laps.length > 0 && (
        <div className="flex gap-2 mt-3 flex-wrap">
          {race.laps.map((l) => (
            <span key={l.lap} className="bg-bg border border-edge rounded-lg px-3 py-1 text-sm">
              Lap {l.lap}: <b className={SIDE_TEXT[l.winner]}>{LABEL[l.winner]}</b>
              {l.time_s != null && <span className="text-dim"> · {l.time_s}s</span>}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── odds board ───────────────────────────────────────────────────────────────────────────────────
function OddsBoard({ book, picked, onPick, bookOpen }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {SIDES.map((s) => {
        const d = book.sides[s];
        const sel = picked === s;
        return (
          <button key={s} disabled={!bookOpen} onClick={() => onPick(s)}
            className={`bg-card rounded-2xl p-4 text-left border-2 transition
              ${sel ? SIDE_BORDER[s] : "border-edge"} ${bookOpen ? "hover:border-dim" : "opacity-90"}`}>
            <div className={`font-extrabold text-lg ${SIDE_TEXT[s]}`}>{LABEL[s]}</div>
            <div className="text-3xl font-extrabold mt-1">
              {d.multiplier ? d.multiplier.toFixed(2) + "×" : "—"}
            </div>
            <div className="text-dim text-sm mt-1">
              {d.implied_pct != null ? d.implied_pct + "% implied" : "No money yet"}
            </div>
            <div className="text-dim text-xs mt-2">{inr(d.total)} · {d.bettors} bettors</div>
          </button>
        );
      })}
    </div>
  );
}

// ── bet slip ─────────────────────────────────────────────────────────────────────────────────────
function BetSlip({ state, picked, refresh }) {
  const [amount, setAmount] = useState("");
  const [msg, setMsg] = useState(null); // {ok, text}
  const { race, book, my_bet, my_pending } = state;
  const mult = picked && book.sides[picked].multiplier;
  const amt = parseInt(amount, 10) || 0;

  const blocked = !race.book_open
    ? "Book is closed."
    : my_bet && picked && my_bet.side !== picked && race.phase !== "prerace"
      ? REASON_TEXT.no_side_switch
      : null;

  const submit = async () => {
    setMsg(null);
    const r = await post("/api/bets", { side: picked, amount: amt });
    if (r._error) setMsg({ ok: false, text: REASON_TEXT[r._error] || r._error });
    else setMsg({ ok: true, text: "Request sent — pay cash to Abhay to get it approved." });
    refresh();
  };
  const cancel = async () => { await post("/api/bets/cancel"); refresh(); };

  return (
    <div className="bg-card border border-edge rounded-2xl p-4 space-y-3">
      <h2 className="font-bold">Bet slip</h2>
      {my_bet && (
        <div className="text-sm bg-bg rounded-xl px-3 py-2 border border-edge">
          Your bet: <b className={SIDE_TEXT[my_bet.side]}>{LABEL[my_bet.side]}</b> · {inr(my_bet.amount)}
          <span className="text-dim"> (approved — betting again replaces it)</span>
        </div>
      )}
      {my_pending && (
        <div className="text-sm bg-bg rounded-xl px-3 py-2 border border-gold flex justify-between items-center">
          <span>Pending: <b className={SIDE_TEXT[my_pending.side]}>{LABEL[my_pending.side]}</b> · {inr(my_pending.amount)}
            <span className="text-gold"> — pay cash to confirm</span></span>
          <button onClick={cancel} className="text-bad text-xs underline">Cancel</button>
        </div>
      )}
      {blocked ? (
        <p className="text-dim text-sm">{blocked}</p>
      ) : (
        <>
          <div className="flex gap-2">
            <input inputMode="numeric" placeholder="Amount ₹" value={amount}
              onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))}
              className="flex-1 bg-bg border border-edge rounded-xl px-4 py-3 outline-none focus:border-khuseel" />
            {[500, 1000, 5000].map((v) => (
              <button key={v} onClick={() => setAmount(String(v))}
                className="bg-bg border border-edge rounded-xl px-3 text-sm text-dim">{v}</button>
            ))}
          </div>
          {picked && amt > 0 && mult && (
            <p className="text-sm text-dim">
              Indicative payout if {LABEL[picked]} wins: <b className="text-ink">{inr(Math.floor(amt * (1 + 0.7 * (mult - 1))))}</b>
              <span> (final payout depends on the closing pool; 30% of the profit pot goes to the winning swimmer)</span>
            </p>
          )}
          <button disabled={!picked || amt < 1} onClick={submit}
            className={`w-full font-bold rounded-xl py-3 ${picked && amt >= 1
              ? "bg-khuseel text-bg" : "bg-edge text-dim"}`}>
            {picked ? `Bet ${inr(amt)} on ${LABEL[picked]}` : "Pick a swimmer above"}
          </button>
        </>
      )}
      {msg && <p className={`text-sm ${msg.ok ? "text-khuseel" : "text-bad"}`}>{msg.text}</p>}
    </div>
  );
}

// ── book table ───────────────────────────────────────────────────────────────────────────────────
function BookTable({ bets, pool, isOwner, refresh }) {
  const voidBet = async (b) => {
    if (!confirm(`Void ${b.display_name}'s ${inr(b.amount)} bet? (Return their cash.)`)) return;
    await post("/api/admin/bets/void", { key: b.key });
    refresh();
  };
  return (
    <div className="bg-card border border-edge rounded-2xl p-4">
      <div className="flex justify-between items-baseline mb-2">
        <h2 className="font-bold">Approved book</h2>
        <span className="text-dim text-sm">Pool <b className="text-gold">{inr(pool)}</b></span>
      </div>
      <div className="grid grid-cols-2 gap-4">
        {SIDES.map((s) => (
          <div key={s}>
            <div className={`text-sm font-bold mb-1 ${SIDE_TEXT[s]}`}>{LABEL[s]}</div>
            {bets.filter((b) => b.side === s).map((b) => (
              <div key={b.key} className="flex justify-between text-sm py-0.5 border-b border-edge/50">
                <span>{b.display_name}</span>
                <span className="text-dim">
                  {inr(b.amount)}
                  {isOwner && (
                    <button onClick={() => voidBet(b)} title="Void (cash returned)"
                      className="text-bad ml-2">✕</button>
                  )}
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── settlement ───────────────────────────────────────────────────────────────────────────────────
function Settlement({ s }) {
  return (
    <div className="bg-card border border-gold rounded-2xl p-4">
      <h2 className="font-extrabold text-lg mb-1">
        🏆 <span className={SIDE_TEXT[s.winner]}>{LABEL[s.winner]}</span> wins — final settlement
      </h2>
      <p className="text-sm text-dim mb-3">
        Pool {inr(s.pool)} · Swimmer's cut <b className="text-gold">{inr(s.swimmer_take)}</b> ·
        Paid to bettors {inr(s.paid_to_bettors)} · Sum check {inr(s.paid_to_bettors + s.swimmer_take)} ✓
      </p>
      <table className="w-full text-sm">
        <thead><tr className="text-dim text-left">
          <th className="py-1">Bettor</th><th>Side</th><th className="text-right">Stake</th>
          <th className="text-right">Payout</th><th className="text-right">Net</th></tr></thead>
        <tbody>
          {s.rows.map((r) => (
            <tr key={r.key} className="border-t border-edge/50">
              <td className="py-1">{r.display_name}</td>
              <td className={SIDE_TEXT[r.side]}>{LABEL[r.side]}</td>
              <td className="text-right text-dim">{inr(r.stake)}</td>
              <td className="text-right">{inr(r.payout)}</td>
              <td className={`text-right font-bold ${r.net >= 0 ? "text-khuseel" : "text-bad"}`}>
                {r.net >= 0 ? "+" : "−"}{inr(Math.abs(r.net))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── admin ────────────────────────────────────────────────────────────────────────────────────────
function Admin({ state, refresh }) {
  const [pending, setPending] = useState([]);
  const [lapWinner, setLapWinner] = useState("");
  const [lapTime, setLapTime] = useState("");
  const [manual, setManual] = useState({ name: "", side: "khuseel", amount: "" });
  const [msg, setMsg] = useState("");
  const { race, book } = state;

  const loadPending = useCallback(async () => {
    const r = await get("/api/admin/pending");
    if (r.pending) setPending(r.pending);
  }, []);
  useEffect(() => { loadPending(); }, [loadPending, state]);

  const act = async (fn) => {
    const r = await fn();
    setMsg(r._error ? (REASON_TEXT[r._error] || r._error) : "");
    refresh(); loadPending();
  };

  const lapInProgress = race.phase.startsWith("lap");
  const canStart = ["prerace", "break1", "break2"].includes(race.phase);

  return (
    <div className="bg-card border-2 border-gold rounded-2xl p-4 space-y-4">
      <h2 className="font-extrabold text-gold">Admin · Cashier console</h2>

      <div>
        <h3 className="font-bold text-sm mb-2">Pending requests ({pending.length})</h3>
        {pending.length === 0 && <p className="text-dim text-sm">Queue empty.</p>}
        {pending.map((p) => (
          <div key={p.id} className="flex items-center justify-between bg-bg border border-edge rounded-xl px-3 py-2 mb-2 text-sm">
            <div>
              <b>{p.display_name}</b> → <b className={SIDE_TEXT[p.side]}>{LABEL[p.side]}</b> {inr(p.amount)}
              {p.current && <span className="text-dim"> (current: {LABEL[p.current.side]} {inr(p.current.amount)})</span>}
              <div className="text-gold text-xs">Collect {inr(p.cash_to_collect)} cash</div>
            </div>
            <div className="flex gap-2">
              <button onClick={() => act(() => post(`/api/admin/bets/${p.id}/approve`))}
                className="bg-khuseel text-bg font-bold rounded-lg px-3 py-1">✓ Cash received</button>
              <button onClick={() => act(() => post(`/api/admin/bets/${p.id}/reject`))}
                className="bg-bad/20 text-bad rounded-lg px-3 py-1">✕</button>
            </div>
          </div>
        ))}
      </div>

      <div>
        <h3 className="font-bold text-sm mb-2">Race console</h3>
        <div className="flex flex-wrap gap-2 items-center">
          {canStart && (
            <button onClick={() => act(() => post("/api/admin/race/start-lap"))}
              className="bg-bad text-ink font-bold rounded-xl px-4 py-2">
              ▶ Start lap {race.laps.length + 1}{race.phase === "break1" ? " (closes book!)" : ""}
            </button>
          )}
          {lapInProgress && (
            <>
              <select value={lapWinner} onChange={(e) => setLapWinner(e.target.value)}
                className="bg-bg border border-edge rounded-xl px-3 py-2">
                <option value="">Lap winner…</option>
                {SIDES.map((s) => <option key={s} value={s}>{LABEL[s]}</option>)}
              </select>
              <input placeholder="Time (s)" value={lapTime}
                onChange={(e) => setLapTime(e.target.value.replace(/[^\d.]/g, ""))}
                className="bg-bg border border-edge rounded-xl px-3 py-2 w-24" />
              <button disabled={!lapWinner}
                onClick={() => act(() => post("/api/admin/race/lap-result",
                  { winner: lapWinner, time_s: lapTime ? parseFloat(lapTime) : null }))
                  .then(() => { setLapWinner(""); setLapTime(""); })}
                className={`font-bold rounded-xl px-4 py-2 ${lapWinner ? "bg-khuseel text-bg" : "bg-edge text-dim"}`}>
                Record result
              </button>
            </>
          )}
          {race.phase === "finished" && (
            <button onClick={() => { if (confirm("Settle the pool? This is final and freezes the payout table.")) act(() => post("/api/admin/settle")); }}
              className="bg-gold text-bg font-extrabold rounded-xl px-4 py-2">💰 Settle pool</button>
          )}
          {book.pool === 0 && race.phase === "prerace" && (
            <button onClick={() => act(() => post("/api/admin/seed"))}
              className="bg-edge rounded-xl px-4 py-2">Load the WhatsApp book</button>
          )}
        </div>
      </div>

      {race.phase !== "settled" && (
        <div>
          <h3 className="font-bold text-sm mb-2">Manual bet — cash already in hand (amount 0 = void)</h3>
          <div className="flex flex-wrap gap-2">
            <input placeholder="Name" value={manual.name}
              onChange={(e) => setManual({ ...manual, name: e.target.value })}
              className="bg-bg border border-edge rounded-xl px-3 py-2 w-32" />
            <select value={manual.side} onChange={(e) => setManual({ ...manual, side: e.target.value })}
              className="bg-bg border border-edge rounded-xl px-3 py-2">
              {SIDES.map((s) => <option key={s} value={s}>{LABEL[s]}</option>)}
            </select>
            <input placeholder="₹ (0 = void)" inputMode="numeric" value={manual.amount}
              onChange={(e) => setManual({ ...manual, amount: e.target.value.replace(/\D/g, "") })}
              className="bg-bg border border-edge rounded-xl px-3 py-2 w-28" />
            <button disabled={!manual.name || manual.amount === ""}
              onClick={() => act(() => post("/api/admin/bets/manual",
                { name: manual.name, side: manual.side, amount: parseInt(manual.amount, 10) }))
                .then(() => setManual({ name: "", side: "khuseel", amount: "" }))}
              className={`rounded-xl px-4 py-2 font-bold ${manual.name && manual.amount !== "" ? "bg-khuseel text-bg" : "bg-edge text-dim"}`}>
              Save
            </button>
          </div>
        </div>
      )}
      {msg && <p className="text-bad text-sm">{msg}</p>}
    </div>
  );
}

// ── rulebook ─────────────────────────────────────────────────────────────────────────────────────
function Rules({ onClose }) {
  const S = ({ n, title, children }) => (
    <div className="mb-4">
      <h3 className="font-bold mb-1">{n}. {title}</h3>
      <div className="text-sm text-dim space-y-1">{children}</div>
    </div>
  );
  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-start justify-center overflow-y-auto p-4"
      onClick={onClose}>
      <div className="bg-card border border-edge rounded-2xl p-6 max-w-lg w-full my-8"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-extrabold">📜 Rulebook</h2>
          <button onClick={onClose} className="text-dim text-2xl leading-none">×</button>
        </div>

        <S n={1} title="The race">
          <p>Khuseel vs Bansod, best of 3 laps of 25m each. First to win 2 laps wins the match —
            if someone takes the first two, there is no lap 3. ~15-minute break between laps.</p>
        </S>
        <S n={2} title="How to bet — cash first">
          <p>① Pay your stake in <b className="text-ink">cash to Abhay</b>. ② Submit the same bet
            here (pick a swimmer, enter the amount). ③ Your bet shows as <b className="text-gold">pending</b> until
            Abhay confirms the cash and approves it. Only approved bets are in the pool — no cash, no bet.</p>
        </S>
        <S n={3} title="One live bet per person">
          <p>Your <b className="text-ink">latest approved bet</b> is your bet. Betting again replaces the
            old one (e.g. a raise). Whole rupees only, minimum ₹1.</p>
        </S>
        <S n={4} title="When you can bet">
          <p>Before the race and during <b className="text-ink">break 1</b> only.
            Once lap 1 starts you <b className="text-ink">cannot switch sides</b> — raises on your own swimmer only.
            The book <b className="text-ink">closes for good when lap 2 starts</b>. Pending requests not approved
            by then are auto-rejected (cash returned).</p>
        </S>
        <S n={5} title="How payouts work (pool betting)">
          <p>All stakes form one pool. If your swimmer <b className="text-ink">loses</b>, your stake is gone.
            If your swimmer <b className="text-ink">wins</b>: you get your stake back <b className="text-ink">plus</b> a
            share of 70% of the losing side's money, in proportion to your stake.</p>
          <p>The remaining <b className="text-gold">30% of the losing pot goes to the winning swimmer</b> —
            the man in the water gets paid too.</p>
          <p>Payouts round down to the rupee; leftover paise go to the swimmer. Every rupee collected
            is paid out — the organiser keeps nothing.</p>
        </S>
        <S n={6} title="Odds are live">
          <p>The multiplier shown is <b className="text-ink">indicative</b> — it moves as money comes in and is
            final only when the book closes. More money on your side = smaller multiplier.</p>
        </S>
        <S n={7} title="Disputes">
          <p>This portal's record is final. Lap results are entered by the organiser at the pool.
            Abhay is cashier and referee — his call stands.</p>
        </S>
        <button onClick={onClose} className="w-full bg-khuseel text-bg font-bold rounded-xl py-3 mt-2">
          Got it
        </button>
      </div>
    </div>
  );
}

// ── app shell ────────────────────────────────────────────────────────────────────────────────────
export default function App() {
  const [state, setState] = useState(null);
  const [unauth, setUnauth] = useState(false);
  const [authMode, setAuthMode] = useState("oauth");
  const [picked, setPicked] = useState(null);
  const [settlement, setSettlement] = useState(null);
  const [showRules, setShowRules] = useState(false);

  const refresh = useCallback(async () => {
    const r = await get("/api/state");
    if (r._unauth) { setUnauth(true); return; }
    if (r._error) return;
    setUnauth(false);
    setState(r);
    if (r.auth_mode) setAuthMode(r.auth_mode);
    if (r.settled && !settlement) {
      const s = await get("/api/settlement");
      if (!s._error) setSettlement(s);
    }
  }, [settlement]);

  useEffect(() => {
    get("/api/config").then((c) => c && c.auth_mode && setAuthMode(c.auth_mode));
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [refresh]);

  if (unauth) return <Login authMode={authMode} onNamed={refresh} />;
  if (!state) return <div className="min-h-screen flex items-center justify-center text-dim">Loading…</div>;

  return (
    <div className="max-w-3xl mx-auto p-4 space-y-4 pb-16">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-extrabold">🏊 Khuseel <span className="text-dim">vs</span> Bansod</h1>
        <div className="text-sm text-dim">
          <button onClick={() => setShowRules(true)} className="underline mr-3">📜 Rules</button>
          {state.me.name}{state.me.is_owner && <span className="text-gold"> · Admin</span>}
          <a href="/auth/logout" className="ml-3 underline">Log out</a>
        </div>
      </header>
      {showRules && <Rules onClose={() => setShowRules(false)} />}

      <RaceStrip race={state.race} />
      {settlement && <Settlement s={settlement} />}
      {state.me.is_owner && <Admin state={state} refresh={refresh} />}
      {!settlement && (
        <>
          <OddsBoard book={state.book} picked={picked} onPick={setPicked} bookOpen={state.race.book_open} />
          <BetSlip state={state} picked={picked} refresh={refresh} />
        </>
      )}
      <BookTable bets={state.bets} pool={state.book.pool}
        isOwner={state.me.is_owner && !settlement} refresh={refresh} />
      <p className="text-center text-xs text-dim">
        Parimutuel pool · Winners split 70% of the losing pot pro-rata · 30% goes to the winning swimmer ·
        Cash first: bets count only after Abhay confirms cash.
      </p>
    </div>
  );
}
