import React, { useEffect, useState, useCallback, useRef } from "react";
import { get, post } from "./api.js";

const SIDES = ["khuseel", "bansod"];
const LABEL = { khuseel: "Khuseel", bansod: "Bansod" };
const SIDE_TEXT = { khuseel: "text-khuseel", bansod: "text-bansod" };
const inr = (n) => "₹" + Number(n || 0).toLocaleString("en-IN");

const PHASE_LABEL = {
  prerace: "Pre-race · bets open",
  lap1: "Lap 1 in progress",
  break1: "Break 1 · bets open",
  lap2: "Lap 2 · book closed",
  break2: "Break 2 · book closed",
  lap3: "Lap 3 · decider",
  finished: "Race finished",
  settled: "Settled",
};

const REASON_TEXT = {
  book_closed: "Book is closed — no more bets.",
  no_side_switch: "Side locked after lap 1 — raise on your swimmer only.",
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
      <div className="bg-card border border-edge rounded-3xl p-8 max-w-sm w-full text-center shadow-2xl">
        <div className="text-5xl mb-3">🏊</div>
        <h1 className="text-2xl font-extrabold tracking-tight mb-1">
          Seekho<span className="text-gold">Stake</span>
        </h1>
        <p className="text-dim mb-2">Khuseel vs Bansod · best of 3 · 16 Sept</p>
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
              className="w-full bg-khuseel text-bg font-extrabold rounded-xl py-3">Enter</button>
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
              <button onClick={() => setShowAdmin(true)} className="text-faint text-xs underline">Admin login</button>
            )}
          </div>
        ) : (
          <a href="/auth/login"
            className="block w-full bg-khuseel text-bg font-extrabold rounded-xl py-3">
            Sign in with Google (@seekhoapp.com)
          </a>
        )}
      </div>
    </div>
  );
}

// ── race strip ───────────────────────────────────────────────────────────────────────────────────
function RaceStrip({ race }) {
  const live = race.phase.startsWith("lap");
  const open = race.book_open;
  return (
    <div className={`bg-card border ${live ? "border-bad" : "border-edge"} rounded-2xl px-4 py-3`}>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <span className={`inline-flex items-center gap-2 text-[11px] font-extrabold tracking-[.12em] uppercase
          ${live ? "text-bad" : open ? "text-khuseel" : "text-dim"}`}>
          <i className={`w-[7px] h-[7px] rounded-full ${live ? "bg-bad animate-pulse" : open ? "bg-khuseel" : "bg-faint"}`} />
          {PHASE_LABEL[race.phase] || race.phase}
        </span>
        <span className="font-extrabold">
          <span className={SIDE_TEXT.khuseel}>KHU {race.wins.khuseel}</span>
          <span className="text-dim mx-1.5">·</span>
          <span className={SIDE_TEXT.bansod}>{race.wins.bansod} BAN</span>
        </span>
      </div>
      {race.laps.length > 0 && (
        <div className="flex gap-1.5 mt-2.5 flex-wrap">
          {race.laps.map((l) => (
            <span key={l.lap} className="bg-raise rounded-lg px-2.5 py-0.5 text-xs text-dim">
              L{l.lap} <b className={SIDE_TEXT[l.winner]}>{LABEL[l.winner]}</b>
              {l.time_s != null && ` ${l.time_s}s`}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── odds board (flashes on movement) ─────────────────────────────────────────────────────────────
function OddsBoard({ book, picked, onPick, bookOpen }) {
  const prev = useRef({});
  const [flash, setFlash] = useState({});
  useEffect(() => {
    const f = {};
    for (const s of SIDES) {
      const m = book.sides[s].multiplier;
      const p = prev.current[s];
      if (p != null && m != null && m !== p) f[s] = m > p ? "up" : "down";
      prev.current[s] = m;
    }
    if (Object.keys(f).length) {
      setFlash(f);
      const t = setTimeout(() => setFlash({}), 900);
      return () => clearTimeout(t);
    }
  }, [book]);

  return (
    <div className="grid grid-cols-2 gap-3">
      {SIDES.map((s) => {
        const d = book.sides[s];
        const sel = picked === s;
        const selCls = s === "khuseel"
          ? "border-khuseel bg-khuseel/10" : "border-bansod bg-bansod/10";
        return (
          <button key={s} disabled={!bookOpen} onClick={() => onPick(s)}
            className={`relative rounded-2xl p-4 text-left border-2 transition bg-card
              ${sel ? selCls : "border-edge"} ${bookOpen ? "hover:border-dim" : "opacity-90"}
              ${flash[s] === "up" ? "animate-flashup" : flash[s] === "down" ? "animate-flashdn" : ""}`}>
            {flash[s] && (
              <span className={`absolute top-2.5 right-3 text-[11px] font-bold rounded px-1.5
                ${flash[s] === "up" ? "text-khuseel bg-khuseel/15" : "text-bad bg-bad/15"}`}>
                {flash[s] === "up" ? "▲" : "▼"}
              </span>
            )}
            <div className={`font-extrabold uppercase tracking-wide ${SIDE_TEXT[s]}`}>{LABEL[s]}</div>
            <div className="text-4xl font-extrabold tracking-tight mt-1">
              {d.multiplier ? d.multiplier.toFixed(2) + "×" : "—"}
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ── pool split bar ───────────────────────────────────────────────────────────────────────────────
function PoolBar({ book }) {
  const k = book.sides.khuseel, b = book.sides.bansod;
  const kw = book.pool ? (100 * k.total) / book.pool : 50;
  return (
    <div className="bg-card border border-edge rounded-2xl px-4 py-3">
      <div className="flex justify-between text-xs text-dim">
        <span>Pool</span><b className="text-gold text-sm">{inr(book.pool)}</b>
      </div>
      <div className="flex h-2 rounded-full overflow-hidden mt-2 bg-raise">
        <span className="bg-khuseel" style={{ width: kw + "%" }} />
        <span className="bg-bansod" style={{ width: 100 - kw + "%" }} />
      </div>
      <div className="flex justify-between text-[11px] text-faint mt-1.5">
        <span>{inr(k.total)} · {k.bettors}</span>
        <span>{inr(b.total)} · {b.bettors}</span>
      </div>
    </div>
  );
}

// ── bet slip ─────────────────────────────────────────────────────────────────────────────────────
function BetSlip({ state, picked, refresh }) {
  const [amount, setAmount] = useState("");
  const [msg, setMsg] = useState(null);
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
    else setMsg({ ok: true, text: "Sent — pay cash to Abhay to confirm." });
    refresh();
  };
  const cancel = async () => { await post("/api/bets/cancel"); refresh(); };

  const ctaCls = picked === "bansod" ? "bg-bansod text-bg" : "bg-khuseel text-bg";

  return (
    <div className="bg-raise border border-edge rounded-2xl p-4 space-y-3 shadow-xl">
      {my_pending && (
        <div className="text-xs bg-gold/10 border border-gold/40 text-gold rounded-xl px-3 py-2 flex justify-between items-center">
          <span>Pending · <b>{LABEL[my_pending.side]} {inr(my_pending.amount)}</b> — pay cash to confirm</span>
          <button onClick={cancel} className="text-bad underline ml-2">Cancel</button>
        </div>
      )}
      <div className="flex justify-between items-center">
        <h2 className="font-bold text-sm">Bet slip</h2>
        {my_bet && (
          <span className="text-xs text-dim">
            Your bet: <b className={SIDE_TEXT[my_bet.side]}>{LABEL[my_bet.side]} {inr(my_bet.amount)}</b>
          </span>
        )}
      </div>
      {blocked ? (
        <p className="text-dim text-sm">{blocked}</p>
      ) : (
        <>
          <div className="flex gap-2">
            <input inputMode="numeric" placeholder="Amount ₹" value={amount}
              onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))}
              className="flex-1 min-w-0 bg-bg border border-edge rounded-xl px-4 py-3 font-bold outline-none focus:border-gold" />
            {[500, 1000, 5000].map((v) => (
              <button key={v} onClick={() => setAmount(String(v))}
                className="bg-bg border border-edge rounded-xl px-3 text-sm text-dim hover:text-ink">
                {v >= 1000 ? v / 1000 + "k" : v}</button>
            ))}
          </div>
          {picked && amt > 0 && mult && (
            <div className="flex justify-between text-xs text-dim px-0.5">
              <span>Payout if {LABEL[picked]} wins</span>
              <b className="text-ink text-sm">{inr(Math.floor(amt * (1 + 0.7 * (mult - 1))))}</b>
            </div>
          )}
          <button disabled={!picked || amt < 1} onClick={submit}
            className={`w-full font-extrabold rounded-xl py-3.5 ${picked && amt >= 1 ? ctaCls : "bg-card text-faint"}`}>
            {picked ? `Bet ${inr(amt)} on ${LABEL[picked]}` : "Pick a swimmer"}
          </button>
        </>
      )}
      {msg && <p className={`text-xs ${msg.ok ? "text-khuseel" : "text-bad"}`}>{msg.text}</p>}
    </div>
  );
}

// ── book ─────────────────────────────────────────────────────────────────────────────────────────
function BookTable({ bets, isOwner, refresh }) {
  const voidBet = async (b) => {
    if (!confirm(`Void ${b.display_name}'s ${inr(b.amount)} bet? (Return their cash.)`)) return;
    await post("/api/admin/bets/void", { key: b.key });
    refresh();
  };
  return (
    <div className="bg-card border border-edge rounded-2xl p-4">
      <h2 className="text-[11px] font-bold tracking-[.13em] text-faint uppercase mb-2">Book</h2>
      <div className="grid grid-cols-2 gap-4">
        {SIDES.map((s) => (
          <div key={s}>
            {bets.filter((b) => b.side === s).map((b) => (
              <div key={b.key} className="flex justify-between items-center text-sm py-1.5 border-b border-edge/50">
                <span className="flex items-center gap-2 min-w-0">
                  <i className={`w-2 h-2 rounded-full shrink-0 ${s === "khuseel" ? "bg-khuseel" : "bg-bansod"}`} />
                  <span className="truncate">{b.display_name}</span>
                </span>
                <span className="text-dim shrink-0 ml-2">
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
function Settlement({ s, race }) {
  const wins = race?.wins;
  return (
    <div className="space-y-4">
      <div className={`rounded-2xl border p-5 text-center
        ${s.winner === "khuseel" ? "border-khuseel/60 bg-khuseel/10" : "border-bansod/60 bg-bansod/10"}`}>
        <div className="text-2xl font-extrabold tracking-tight">
          <span className={SIDE_TEXT[s.winner]}>{LABEL[s.winner].toUpperCase()}</span> WINS
          {wins && ` ${Math.max(wins.khuseel, wins.bansod)}–${Math.min(wins.khuseel, wins.bansod)}`}
        </div>
        <div className="inline-block mt-3 bg-gold/10 text-gold font-bold text-sm rounded-xl px-4 py-1.5">
          Swimmer's cut {inr(s.swimmer_take)}
        </div>
      </div>
      <div className="bg-card border border-edge rounded-2xl p-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-faint text-[10px] uppercase tracking-[.1em] text-left">
            <th className="pb-2 font-semibold">Bettor</th>
            <th className="pb-2 font-semibold text-right">Stake</th>
            <th className="pb-2 font-semibold text-right">Payout</th>
            <th className="pb-2 font-semibold text-right">Net</th></tr></thead>
          <tbody>
            {s.rows.map((r) => (
              <tr key={r.key} className="border-t border-edge/50">
                <td className="py-1.5">
                  <span className="flex items-center gap-2">
                    <i className={`w-2 h-2 rounded-full ${r.side === "khuseel" ? "bg-khuseel" : "bg-bansod"}`} />
                    {r.display_name}
                  </span>
                </td>
                <td className="text-right text-dim">{inr(r.stake)}</td>
                <td className="text-right">{inr(r.payout)}</td>
                <td className={`text-right font-bold ${r.net >= 0 ? "text-khuseel" : "text-bad"}`}>
                  {r.net >= 0 ? "+" : "−"}{inr(Math.abs(r.net))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
    <div className="bg-card border border-gold/50 rounded-2xl p-4 space-y-4">
      <h2 className="text-[11px] font-extrabold tracking-[.13em] uppercase text-gold">Cashier console</h2>

      <div>
        <h3 className="text-[11px] font-bold tracking-[.13em] uppercase text-faint mb-2">
          Pending · collect cash first ({pending.length})</h3>
        {pending.length === 0 && <p className="text-faint text-sm">Queue empty.</p>}
        {pending.map((p) => {
          const raise = p.current && p.current.side === p.side;
          return (
            <div key={p.id} className="flex items-center justify-between bg-raise border border-edge rounded-xl px-3 py-2.5 mb-2 text-sm">
              <div>
                <b>{p.display_name}</b> · <b className={SIDE_TEXT[p.side]}>{LABEL[p.side]}</b>
                <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                  <span className="inline-flex items-baseline gap-1.5 bg-gold/10 border border-gold/40 rounded-lg px-2.5 py-0.5">
                    <span className="text-gold text-[9px] font-extrabold tracking-[.1em]">COLLECT</span>
                    <span className="text-gold font-extrabold">{inr(p.cash_to_collect)}</span>
                  </span>
                  <span className="text-[11px] text-faint bg-bg rounded-md px-2 py-0.5">
                    {raise ? <>Raise <b className="text-dim">{inr(p.current.amount)} → {inr(p.amount)}</b></>
                      : p.current ? <>Switch from {LABEL[p.current.side]} {inr(p.current.amount)}</>
                        : "New bet"}
                  </span>
                </div>
              </div>
              <div className="flex gap-2 shrink-0 ml-2">
                <button onClick={() => act(() => post(`/api/admin/bets/${p.id}/approve`))}
                  className="bg-khuseel text-bg font-extrabold rounded-lg px-3 py-1.5 text-xs">✓ Cash in</button>
                <button onClick={() => act(() => post(`/api/admin/bets/${p.id}/reject`))}
                  className="border border-edge text-bad rounded-lg px-2.5 py-1.5 text-xs">✕</button>
              </div>
            </div>
          );
        })}
      </div>

      <div>
        <h3 className="text-[11px] font-bold tracking-[.13em] uppercase text-faint mb-2">Race console</h3>
        <div className="flex flex-wrap gap-2 items-center">
          {canStart && (
            <button onClick={() => act(() => post("/api/admin/race/start-lap"))}
              className="bg-bad text-ink font-bold rounded-xl px-4 py-2.5">
              ▶ Start lap {race.laps.length + 1}{race.phase === "break1" ? " — closes book" : ""}
            </button>
          )}
          {lapInProgress && (
            <>
              <select value={lapWinner} onChange={(e) => setLapWinner(e.target.value)}
                className="bg-bg border border-edge rounded-xl px-3 py-2.5">
                <option value="">Lap winner…</option>
                {SIDES.map((s) => <option key={s} value={s}>{LABEL[s]}</option>)}
              </select>
              <input placeholder="Time (s)" value={lapTime}
                onChange={(e) => setLapTime(e.target.value.replace(/[^\d.]/g, ""))}
                className="bg-bg border border-edge rounded-xl px-3 py-2.5 w-24" />
              <button disabled={!lapWinner}
                onClick={() => act(() => post("/api/admin/race/lap-result",
                  { winner: lapWinner, time_s: lapTime ? parseFloat(lapTime) : null }))
                  .then(() => { setLapWinner(""); setLapTime(""); })}
                className={`font-bold rounded-xl px-4 py-2.5 ${lapWinner ? "bg-khuseel text-bg" : "bg-raise text-faint"}`}>
                Record result
              </button>
            </>
          )}
          {race.phase === "finished" && (
            <button onClick={() => { if (confirm("Settle the pool? This is final and freezes the payout table.")) act(() => post("/api/admin/settle")); }}
              className="bg-gold text-bg font-extrabold rounded-xl px-4 py-2.5">Settle pool</button>
          )}
          {book.pool === 0 && race.phase === "prerace" && (
            <button onClick={() => act(() => post("/api/admin/seed"))}
              className="bg-raise border border-edge rounded-xl px-4 py-2.5 text-dim">Load WhatsApp book</button>
          )}
          {book.pool > 0 && race.phase === "prerace" && (
            <button onClick={() => { if (confirm("Wipe ALL bets and reload the seed book (full names)? Portal bets placed since seeding will be lost.")) act(() => post("/api/admin/reset-book")); }}
              className="bg-raise border border-edge rounded-xl px-4 py-2.5 text-dim">Reset to seed book</button>
          )}
        </div>
        {race.phase === "break1" && (
          <p className="text-[11px] text-gold mt-2">⚠ Starting lap 2 auto-rejects all unpaid pending bets.</p>
        )}
      </div>

      {race.phase !== "settled" && (
        <div>
          <h3 className="text-[11px] font-bold tracking-[.13em] uppercase text-faint mb-2">
            Manual bet · amount 0 = void</h3>
          <div className="flex flex-wrap gap-2">
            <input placeholder="Name" value={manual.name}
              onChange={(e) => setManual({ ...manual, name: e.target.value })}
              className="bg-bg border border-edge rounded-xl px-3 py-2 w-32" />
            <select value={manual.side} onChange={(e) => setManual({ ...manual, side: e.target.value })}
              className="bg-bg border border-edge rounded-xl px-3 py-2">
              {SIDES.map((s) => <option key={s} value={s}>{LABEL[s]}</option>)}
            </select>
            <input placeholder="₹" inputMode="numeric" value={manual.amount}
              onChange={(e) => setManual({ ...manual, amount: e.target.value.replace(/\D/g, "") })}
              className="bg-bg border border-edge rounded-xl px-3 py-2 w-24" />
            <button disabled={!manual.name || manual.amount === ""}
              onClick={() => act(() => post("/api/admin/bets/manual",
                { name: manual.name, side: manual.side, amount: parseInt(manual.amount, 10) }))
                .then(() => setManual({ name: "", side: "khuseel", amount: "" }))}
              className={`rounded-xl px-4 py-2 font-bold ${manual.name && manual.amount !== "" ? "bg-khuseel text-bg" : "bg-raise text-faint"}`}>
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
      <div className="bg-card border border-edge rounded-2xl p-6 max-w-lg w-full my-8 text-left"
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

  const slip = !settlement && <BetSlip state={state} picked={picked} refresh={refresh} />;

  return (
    <div className="max-w-5xl mx-auto p-4 pb-16">
      <header className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-extrabold tracking-tight">
          🏊 Seekho<span className="text-gold">Stake</span>
        </h1>
        <div className="text-xs text-dim flex items-center gap-3">
          <button onClick={() => setShowRules(true)} className="underline">Rules</button>
          <span>{state.me.name}{state.me.is_owner && <span className="text-gold font-bold"> · ADMIN</span>}</span>
          <a href="/auth/logout" className="underline">Logout</a>
        </div>
      </header>
      {showRules && <Rules onClose={() => setShowRules(false)} />}

      <div className="lg:grid lg:grid-cols-[1fr,340px] lg:gap-5 lg:items-start">
        <div className="space-y-4">
          <RaceStrip race={state.race} />
          {settlement && <Settlement s={settlement} race={state.race} />}
          {state.me.is_owner && <Admin state={state} refresh={refresh} />}
          {!settlement && (
            <>
              <OddsBoard book={state.book} picked={picked} onPick={setPicked} bookOpen={state.race.book_open} />
              <PoolBar book={state.book} />
              <div className="lg:hidden">{slip}</div>
            </>
          )}
          <BookTable bets={state.bets}
            isOwner={state.me.is_owner && !settlement} refresh={refresh} />
        </div>
        <div className="hidden lg:block sticky top-4 space-y-4">{slip}</div>
      </div>
    </div>
  );
}
