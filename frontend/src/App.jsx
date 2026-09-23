import React, { useEffect, useState, useCallback, useRef } from "react";
import { get, post } from "./api.js";

const SIDES = ["khuseel", "bansod"];
const LABEL = { khuseel: "Khuseel", bansod: "Bansod" };
const SIDE_TEXT = { khuseel: "text-khuseel", bansod: "text-bansod" };
const inr = (n) => "₹" + Number(n || 0).toLocaleString("en-IN");

// outcome → accent: khuseel-ish green, bansod-ish blue, neutral gold for yes/no
const tone = (oid) =>
  oid === "khuseel" || oid.startsWith("k") ? "k" : oid === "bansod" || oid.startsWith("b") ? "b" : "g";
const TONE_TEXT = { k: "text-khuseel", b: "text-bansod", g: "text-gold" };
const TONE_SEL = {
  k: "border-khuseel bg-khuseel/10",
  b: "border-bansod bg-bansod/10",
  g: "border-gold bg-gold/10",
};

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
  book_closed: "This market is closed.",
  no_side_switch: "Side switching is locked after lap 1. You can raise your existing pick only.",
  bad_amount: "Enter a valid amount (minimum ₹1).",
  outcome_dead: "This outcome is no longer possible.",
  not_pending: "This request was already handled.",
};

// ── login ────────────────────────────────────────────────────────────────────────────────────────
function Login({ authMode, testLogin, onNamed }) {
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [showRules, setShowRules] = useState(false);
  const [showAdmin, setShowAdmin] = useState(false);
  const [pw, setPw] = useState("");
  const [showTest, setShowTest] = useState(false);
  const [tEmail, setTEmail] = useState("");
  const [tPw, setTPw] = useState("");
  const submitTest = async () => {
    const r = await post("/auth/test", { email: tEmail, password: tPw });
    if (r._error) setErr(r._error === "not_allowed" ? "Email must be @seekhoapp.com." : "Wrong test password.");
    else onNamed();
  };
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
        <p className="text-dim mb-2">Khuseel vs Bansod · Best of 3 · 27 Sept</p>
        <button onClick={() => setShowRules(true)} className="text-dim text-sm underline mb-6">Rules</button>
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
          <div className="space-y-3">
            <a href="/auth/login"
              className="block w-full bg-khuseel text-bg font-extrabold rounded-xl py-3">
              Sign in with Google (@seekhoapp.com)
            </a>
            {testLogin && (showTest ? (
              <div className="space-y-2">
                <input placeholder="Test email (@seekhoapp.com)" value={tEmail}
                  onChange={(e) => setTEmail(e.target.value)}
                  className="w-full bg-bg border border-edge rounded-xl px-4 py-2 outline-none text-sm" />
                <div className="flex gap-2">
                  <input type="password" placeholder="Test password" value={tPw}
                    onChange={(e) => setTPw(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && submitTest()}
                    className="flex-1 bg-bg border border-edge rounded-xl px-4 py-2 outline-none text-sm" />
                  <button onClick={submitTest} className="bg-gold text-bg font-bold rounded-xl px-4">Go</button>
                </div>
                {err && <p className="text-bad text-sm">{err}</p>}
              </div>
            ) : (
              <button onClick={() => setShowTest(true)} className="text-faint text-xs underline">Test login</button>
            ))}
          </div>
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

// ── main market: big odds board (flashes on movement) ────────────────────────────────────────────
function OddsBoard({ market, picked, onPick }) {
  const prev = useRef({});
  const [flash, setFlash] = useState({});
  useEffect(() => {
    const f = {};
    for (const o of market.outcomes) {
      const m = o.est_mult, p = prev.current[o.id];
      if (p != null && m != null && m !== p) f[o.id] = m > p ? "up" : "down";
      prev.current[o.id] = m;
    }
    if (Object.keys(f).length) {
      setFlash(f);
      const t = setTimeout(() => setFlash({}), 900);
      return () => clearTimeout(t);
    }
  }, [market]);

  return (
    <div className="grid grid-cols-2 gap-3">
      {market.outcomes.map((o) => {
        const sel = picked && picked.market === market.id && picked.outcome === o.id;
        return (
          <button key={o.id} disabled={!market.open}
            onClick={() => onPick({ market: market.id, outcome: o.id, label: o.label, name: market.name, est: o.est_mult })}
            className={`relative rounded-2xl p-4 text-left border-2 transition bg-card
              ${sel ? TONE_SEL[tone(o.id)] : "border-edge"} ${market.open ? "hover:border-dim" : "opacity-90"}
              ${flash[o.id] === "up" ? "animate-flashup" : flash[o.id] === "down" ? "animate-flashdn" : ""}`}>
            {flash[o.id] && (
              <span className={`absolute top-2.5 right-3 text-[11px] font-bold rounded px-1.5
                ${flash[o.id] === "up" ? "text-khuseel bg-khuseel/15" : "text-bad bg-bad/15"}`}>
                {flash[o.id] === "up" ? "▲" : "▼"}
              </span>
            )}
            <div className={`font-extrabold uppercase tracking-wide ${TONE_TEXT[tone(o.id)]}`}>{o.label}</div>
            <div className="text-4xl font-extrabold tracking-tight mt-1">
              {o.est_mult ? o.est_mult.toFixed(2) + "×" : "—"}
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ── side market card ─────────────────────────────────────────────────────────────────────────────
function MarketCard({ market, picked, onPick, myBets }) {
  const my = market.my_bet, pend = market.my_pending;
  return (
    <div className="bg-card border border-edge rounded-2xl p-4">
      <div className="flex justify-between items-baseline gap-2">
        <h2 className="font-bold text-sm">{market.name}</h2>
        <span className="text-[10px] font-bold tracking-[.1em] uppercase shrink-0">
          {market.open
            ? <span className="text-khuseel">Open</span>
            : <span className="text-faint">Closed</span>}
        </span>
      </div>
      <p className="text-[11px] text-faint mb-3 mt-0.5 min-h-[14px]">{market.sub || ""}</p>
      <div className="grid grid-cols-2 gap-2">
        {market.outcomes.map((o) => {
          const sel = picked && picked.market === market.id && picked.outcome === o.id;
          const dead = !o.alive;
          return (
            <button key={o.id} disabled={!market.open || dead}
              onClick={() => onPick({ market: market.id, outcome: o.id, label: o.label, name: market.name, est: o.est_mult })}
              className={`rounded-xl px-3 py-2.5 text-left border-2 transition bg-raise
                ${sel ? TONE_SEL[tone(o.id)] : "border-edge"}
                ${dead ? "opacity-40" : market.open ? "hover:border-dim" : "opacity-80"}`}>
              <div className={`text-xs font-semibold ${TONE_TEXT[tone(o.id)]}`}>{o.label}</div>
              <div className="text-xl font-extrabold">
                {dead ? "—" : o.est_mult ? o.est_mult.toFixed(2) + "×" : "—"}
              </div>
            </button>
          );
        })}
      </div>
      {(my || pend) && (
        <p className="text-[11px] mt-2 text-dim">
          {my && <>Your bet: <b className="text-ink">{labelOf(market, my.outcome)} {inr(my.amount)}</b></>}
          {my && pend && " · "}
          {pend && <span className="text-gold">Pending: {labelOf(market, pend.outcome)} {inr(pend.amount)}</span>}
        </p>
      )}
    </div>
  );
}

const labelOf = (market, oid) => {
  const o = market.outcomes.find((x) => x.id === oid);
  return o ? o.label : oid;
};

// ── pool split bar (main market) ─────────────────────────────────────────────────────────────────
function PoolBar({ market }) {
  const k = market.outcomes.find((o) => o.id === "khuseel");
  const b = market.outcomes.find((o) => o.id === "bansod");
  const kw = market.pool ? (100 * k.total) / market.pool : 50;
  return (
    <div className="bg-card border border-edge rounded-2xl px-4 py-3">
      <div className="flex justify-between text-xs text-dim">
        <span>Pool</span><b className="text-gold text-sm">{inr(market.pool)}</b>
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
function BetSlip({ picked, refresh, onClear }) {
  const [amount, setAmount] = useState("");
  const [msg, setMsg] = useState(null);
  const amt = parseInt(amount, 10) || 0;

  const submit = async () => {
    setMsg(null);
    const r = await post("/api/bets", { market: picked.market, outcome: picked.outcome, amount: amt });
    if (r._error) setMsg({ ok: false, text: REASON_TEXT[r._error] || r._error });
    else { setMsg({ ok: true, text: "Request submitted. Pay cash to confirm your bet." }); setAmount(""); }
    refresh();
  };

  return (
    <div className="bg-raise border border-edge rounded-2xl p-4 space-y-3 shadow-xl">
      <div className="flex justify-between items-center">
        <h2 className="text-[11px] font-bold tracking-[.13em] text-faint uppercase">Bet slip</h2>
        {picked && <button onClick={onClear} className="text-faint text-xs underline">Clear</button>}
      </div>
      {!picked ? (
        <p className="text-dim text-sm">Select an outcome to place a bet.</p>
      ) : (
        <>
          <p className="text-xs text-dim">
            {picked.name} — <b className="text-ink">{picked.label}</b>
            {picked.est && <span> @ {picked.est.toFixed(2)}×</span>}
          </p>
          <div className="flex gap-2">
            <input inputMode="numeric" placeholder="Amount ₹" value={amount}
              onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))}
              className="flex-1 min-w-0 bg-bg border border-edge rounded-xl px-4 py-3 font-bold outline-none focus:border-gold" />
            {[100, 500, 1000].map((v) => (
              <button key={v} onClick={() => setAmount(String(v))}
                className="bg-bg border border-edge rounded-xl px-3 text-sm text-dim hover:text-ink">
                {v >= 1000 ? v / 1000 + "k" : v}</button>
            ))}
          </div>
          {amt > 0 && (picked.est ? (
            <div className="flex justify-between text-xs text-dim px-0.5">
              <span>Indicative payout</span>
              <b className="text-ink text-sm">{inr(Math.floor(amt * picked.est))}</b>
            </div>
          ) : (
            <p className="text-[11px] text-faint px-0.5">
              Odds form once bets are placed on this outcome.
            </p>
          ))}
          <button disabled={amt < 1} onClick={submit}
            className={`w-full font-extrabold rounded-xl py-3.5 ${amt >= 1 ? "bg-khuseel text-bg" : "bg-card text-faint"}`}>
            {amt >= 1 ? `Bet ${inr(amt)} on ${picked.label}` : "Enter amount"}
          </button>
        </>
      )}
      {msg && <p className={`text-xs ${msg.ok ? "text-khuseel" : "text-bad"}`}>{msg.text}</p>}
    </div>
  );
}

// ── my bets ──────────────────────────────────────────────────────────────────────────────────────
function MyBets({ markets, refresh }) {
  const rows = [];
  for (const m of markets) {
    if (m.my_bet) rows.push({ m, ...m.my_bet, status: "APPROVED" });
    if (m.my_pending) rows.push({ m, ...m.my_pending, status: "PENDING" });
  }
  if (!rows.length) return null;
  const cancel = async (market) => { await post("/api/bets/cancel", { market }); refresh(); };
  return (
    <div className="bg-card border border-edge rounded-2xl p-4">
      <h2 className="text-[11px] font-bold tracking-[.13em] text-faint uppercase mb-2">My bets</h2>
      {rows.map((r, i) => (
        <div key={i} className="flex justify-between items-center text-sm py-1.5 border-b border-edge/50 last:border-0">
          <span>{r.m.name} · <b className={TONE_TEXT[tone(r.outcome)]}>{labelOf(r.m, r.outcome)}</b> {inr(r.amount)}</span>
          {r.status === "PENDING" ? (
            <span className="text-gold text-xs font-bold">
              PENDING <button onClick={() => cancel(r.m.id)} className="text-bad underline font-normal ml-1">Cancel</button>
            </span>
          ) : (
            <span className="text-khuseel text-xs font-bold">IN POOL</span>
          )}
        </div>
      ))}
    </div>
  );
}

// ── main-market book ─────────────────────────────────────────────────────────────────────────────
function BookTable({ bets, isOwner, refresh }) {
  const voidBet = async (b) => {
    if (!confirm(`Void ${b.display_name}'s ${inr(b.amount)} bet? (Return their cash.)`)) return;
    await post("/api/admin/bets/void", { key: b.key, market: "match" });
    refresh();
  };
  return (
    <div className="bg-card border border-edge rounded-2xl p-4">
      <h2 className="text-[11px] font-bold tracking-[.13em] text-faint uppercase mb-2">Match-winner book</h2>
      <div className="grid grid-cols-2 gap-4">
        {SIDES.map((s) => (
          <div key={s}>
            {bets.filter((b) => b.side === s).map((b) => (
              <div key={b.key} className="flex justify-between items-center text-sm py-1.5 border-b border-edge/50">
                <span className="flex items-center gap-2 min-w-0">
                  <i className={`w-2 h-2 rounded-full shrink-0 ${s === "khuseel" ? "bg-khuseel" : "bg-bansod"}`} />
                  <span className={`truncate ${b.key === "house" ? "text-gold font-bold" : ""}`}>{b.display_name}</span>
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
        <div className="flex justify-center gap-2 mt-3 flex-wrap">
          <span className="bg-gold/10 text-gold font-bold text-sm rounded-xl px-4 py-1.5">
            Swimmer {inr(s.swimmer_take)}
          </span>
          {s.house_take != null && (
            <span className="bg-raise text-dim font-bold text-sm rounded-xl px-4 py-1.5">
              House {inr(s.house_take)}
            </span>
          )}
        </div>
      </div>

      <div className="bg-card border border-edge rounded-2xl p-4">
        <h2 className="text-[11px] font-bold tracking-[.13em] text-faint uppercase mb-2">Markets</h2>
        <div className="flex flex-wrap gap-2">
          {s.markets.map((m) => (
            <span key={m.market} className="bg-raise rounded-lg px-2.5 py-1 text-xs text-dim">
              {m.name}: <b className="text-ink">{m.void ? "Void — refunded" : (m.won_label || m.won)}</b>
            </span>
          ))}
        </div>
      </div>

      <div className="bg-card border border-edge rounded-2xl p-4 overflow-x-auto">
        <h2 className="text-[11px] font-bold tracking-[.13em] text-faint uppercase mb-2">
          Payout sheet</h2>
        <table className="w-full text-sm">
          <thead><tr className="text-faint text-[10px] uppercase tracking-[.1em] text-left">
            <th className="pb-2 font-semibold">Bettor</th>
            <th className="pb-2 font-semibold text-right">Staked</th>
            <th className="pb-2 font-semibold text-right">Gets back</th>
            <th className="pb-2 font-semibold text-right">Net</th></tr></thead>
          <tbody>
            {s.aggregate.map((r) => (
              <tr key={r.key} className="border-t border-edge/50">
                <td className="py-1.5">{r.display_name}</td>
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
  const [manual, setManual] = useState({ name: "", market: "match", outcome: "khuseel", amount: "" });
  const [seedAmt, setSeedAmt] = useState("");
  const [msg, setMsg] = useState("");
  const { race, markets, house } = state;
  const matchPool = markets.find((m) => m.id === "match").pool;

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

  const manualMarket = markets.find((m) => m.id === manual.market);
  const lapInProgress = race.phase.startsWith("lap");
  const canStart = ["prerace", "break1", "break2"].includes(race.phase);

  return (
    <div className="bg-card border border-gold/50 rounded-2xl p-4 space-y-4">
      <h2 className="text-[11px] font-extrabold tracking-[.13em] uppercase text-gold">Cashier console</h2>

      <div>
        <h3 className="text-[11px] font-bold tracking-[.13em] uppercase text-faint mb-2">
          Pending · collect cash first ({pending.length})</h3>
        {pending.length === 0 && <p className="text-faint text-sm">No pending requests.</p>}
        {pending.map((p) => {
          const raise = p.current && p.current.outcome === p.outcome;
          return (
            <div key={p.id} className="flex items-center justify-between bg-raise border border-edge rounded-xl px-3 py-2.5 mb-2 text-sm">
              <div>
                <b>{p.display_name}</b> · {p.market_name} · <b className={TONE_TEXT[tone(p.outcome)]}>{p.outcome_label}</b>
                <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                  <span className="inline-flex items-baseline gap-1.5 bg-gold/10 border border-gold/40 rounded-lg px-2.5 py-0.5">
                    <span className="text-gold text-[9px] font-extrabold tracking-[.1em]">COLLECT</span>
                    <span className="text-gold font-extrabold">{inr(p.cash_to_collect)}</span>
                  </span>
                  <span className="text-[11px] text-faint bg-bg rounded-md px-2 py-0.5">
                    {raise ? <>Raise <b className="text-dim">{inr(p.current.amount)} → {inr(p.amount)}</b></>
                      : p.current ? <>Replaces {inr(p.current.amount)} on other outcome</>
                        : "New bet"}
                  </span>
                </div>
              </div>
              <div className="flex gap-2 shrink-0 ml-2">
                <button onClick={() => act(() => post(`/api/admin/bets/${p.id}/approve`))}
                  className="bg-khuseel text-bg font-extrabold rounded-lg px-3 py-1.5 text-xs">Approve</button>
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
            <button onClick={() => { if (confirm("Settle every market? This is final and freezes the payout sheet.")) act(() => post("/api/admin/settle")); }}
              className="bg-gold text-bg font-extrabold rounded-xl px-4 py-2.5">Settle all markets</button>
          )}
          {matchPool === 0 && race.phase === "prerace" && (
            <button onClick={() => act(() => post("/api/admin/seed"))}
              className="bg-raise border border-edge rounded-xl px-4 py-2.5 text-dim">Load seed book</button>
          )}
          {matchPool > 0 && race.phase === "prerace" && (
            <button onClick={() => { if (confirm("Wipe ALL bets in ALL markets and reload the seed book? Portal bets placed since seeding will be lost.")) act(() => post("/api/admin/reset-book")); }}
              className="bg-raise border border-edge rounded-xl px-4 py-2.5 text-dim">Reset to seed book</button>
          )}
        </div>
        {race.phase === "break1" && (
          <p className="text-[11px] text-gold mt-2">Starting lap 2 closes all betting; unapproved requests are rejected.</p>
        )}
      </div>

      {house && race.phase !== "settled" && (
        <div>
          <h3 className="text-[11px] font-bold tracking-[.13em] uppercase text-faint mb-2">
            House seed · cap {inr(house.seed_cap)} (= expected rake)</h3>
          <div className="flex flex-wrap gap-2 items-center">
            <span className="text-xs text-dim">
              {house.seed ? <>Current: <b className={TONE_TEXT[tone(house.seed.outcome)]}>
                {LABEL[house.seed.outcome]} {inr(house.seed.amount)}</b></> : "No seed placed."}
            </span>
            <input placeholder="₹" inputMode="numeric" value={seedAmt}
              onChange={(e) => setSeedAmt(e.target.value.replace(/\D/g, ""))}
              className="bg-bg border border-edge rounded-xl px-3 py-2 w-24" />
            {SIDES.map((s) => (
              <button key={s} disabled={seedAmt === ""}
                onClick={() => act(() => post("/api/admin/house-seed",
                  { outcome: s, amount: parseInt(seedAmt, 10) || 0 })).then(() => setSeedAmt(""))}
                className={`rounded-xl px-3 py-2 text-xs font-bold border border-edge ${SIDE_TEXT[s]}`}>
                Seed {LABEL[s]}
              </button>
            ))}
            {house.seed && (
              <button onClick={() => act(() => post("/api/admin/house-seed", { outcome: house.seed.outcome, amount: 0 }))}
                className="text-bad text-xs underline">Remove seed</button>
            )}
            <button onClick={() => act(() => post("/api/admin/side-seeds", { per_market: 200, tilt: true }))}
              className="rounded-xl px-3 py-2 text-xs font-bold border border-edge text-gold">
              Seed side odds · ₹200/market · Bansod-tilted
            </button>
            <button onClick={() => act(() => post("/api/admin/side-seeds", { per_market: 0 }))}
              className="text-faint text-xs underline">Clear side liquidity</button>
          </div>
        </div>
      )}

      {race.phase !== "settled" && (
        <div>
          <h3 className="text-[11px] font-bold tracking-[.13em] uppercase text-faint mb-2">
            Manual bet · amount 0 = void</h3>
          <div className="flex flex-wrap gap-2">
            <input placeholder="Name" value={manual.name}
              onChange={(e) => setManual({ ...manual, name: e.target.value })}
              className="bg-bg border border-edge rounded-xl px-3 py-2 w-32" />
            <select value={manual.market}
              onChange={(e) => {
                const mk = markets.find((m) => m.id === e.target.value);
                setManual({ ...manual, market: e.target.value, outcome: mk.outcomes[0].id });
              }}
              className="bg-bg border border-edge rounded-xl px-3 py-2">
              {markets.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
            <select value={manual.outcome} onChange={(e) => setManual({ ...manual, outcome: e.target.value })}
              className="bg-bg border border-edge rounded-xl px-3 py-2">
              {manualMarket.outcomes.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
            </select>
            <input placeholder="₹" inputMode="numeric" value={manual.amount}
              onChange={(e) => setManual({ ...manual, amount: e.target.value.replace(/\D/g, "") })}
              className="bg-bg border border-edge rounded-xl px-3 py-2 w-24" />
            <button disabled={!manual.name || manual.amount === ""}
              onClick={() => act(() => post("/api/admin/bets/manual",
                { name: manual.name, market: manual.market, outcome: manual.outcome,
                  amount: parseInt(manual.amount, 10) }))
                .then(() => setManual({ name: "", market: "match", outcome: "khuseel", amount: "" }))}
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
          <h2 className="text-xl font-extrabold">Rules</h2>
          <button onClick={onClose} className="text-dim text-2xl leading-none">×</button>
        </div>

        <S n={1} title="The race">
          <p>Khuseel vs Bansod, best of 3 laps of 25m. First to 2 lap wins takes the match;
            a 2–0 start ends it. ~15-minute break between laps.</p>
        </S>
        <S n={2} title="Placing a bet">
          <p>Pay your stake in <b className="text-ink">cash to the organiser</b>, then submit the
            bet here. It remains <b className="text-gold">pending</b> until the organiser approves
            it. Only approved bets enter a pool.</p>
        </S>
        <S n={3} title="Markets">
          <p><b className="text-ink">Match Winner</b> is the main market; side markets are listed
            on the board. One live bet per person per market — a newer approved bet replaces your
            earlier one in that market.</p>
          <p>Outcomes that become impossible mid-race close automatically. A market that never
            takes place (e.g. Lap 3 Winner in a 2–0 result) is <b className="text-ink">void and
            fully refunded</b>.</p>
        </S>
        <S n={4} title="Betting windows">
          <p>Bets are accepted before the race and during break 1. On the main market, sides are
            locked once lap 1 starts — raises only. All betting
            <b className="text-ink"> closes when lap 2 starts</b>; unapproved requests are then
            rejected and cash returned.</p>
        </S>
        <S n={5} title="Payouts">
          <p>Pool betting: a losing stake is forfeited; a winning bet is paid from the pool at the
            prevailing multiplier. On the main market, <b className="text-gold">30% of the winnings
            pot goes to the winning swimmer</b>.</p>
          <p>Payouts round down to the rupee. The settlement payout sheet is the authoritative
            record.</p>
        </S>
        <S n={6} title="Odds">
          <p>Displayed multipliers are <b className="text-ink">indicative</b> and move with the
            pool; they are final when the book closes.</p>
        </S>
        <S n={7} title="Disputes">
          <p>Lap results are recorded by the organiser at the pool. The organiser's decision is
            final.</p>
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
  const [testLogin, setTestLogin] = useState(false);
  const [picked, setPicked] = useState(null);
  const [settlement, setSettlement] = useState(null);
  const [showRules, setShowRules] = useState(false);
  const [asUser, setAsUser] = useState(false);

  const refresh = useCallback(async () => {
    const q = asUser ? "?as_user=1" : "";
    const r = await get("/api/state" + q);
    if (r._unauth) { setUnauth(true); return; }
    if (r._error) return;
    setUnauth(false);
    setState(r);
    if (r.auth_mode) setAuthMode(r.auth_mode);
    if (r.settled && !settlement) {
      const s = await get("/api/settlement" + q);
      if (!s._error) setSettlement(s);
    }
  }, [settlement, asUser]);

  useEffect(() => {
    get("/api/config").then((c) => {
      if (c && c.auth_mode) setAuthMode(c.auth_mode);
      if (c) setTestLogin(!!c.test_login);
    });
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [refresh]);

  if (unauth) return <Login authMode={authMode} testLogin={testLogin} onNamed={refresh} />;
  if (!state) return <div className="min-h-screen flex items-center justify-center text-dim">Loading…</div>;

  const main = state.markets.find((m) => m.main);
  const sides = state.markets.filter((m) => !m.main);
  const slip = !settlement && <BetSlip picked={picked} refresh={refresh} onClear={() => setPicked(null)} />;

  return (
    <div className="max-w-5xl mx-auto p-4 pb-16">
      <header className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-extrabold tracking-tight">
          🏊 Seekho<span className="text-gold">Stake</span>
        </h1>
        <div className="text-xs text-dim flex items-center gap-3">
          {state.me.can_admin && (
            <button onClick={() => { setAsUser(!asUser); setSettlement(null); }}
              className={`rounded-lg px-2.5 py-1 font-bold border ${asUser
                ? "border-gold text-gold" : "border-edge text-dim"}`}>
              {asUser ? "User view · back to admin" : "View as user"}
            </button>
          )}
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
              <OddsBoard market={main} picked={picked} onPick={setPicked} />
              <PoolBar market={main} />
              <div className="lg:hidden">{slip}</div>
              <div className="grid sm:grid-cols-2 gap-3">
                {sides.map((m) => (
                  <MarketCard key={m.id} market={m} picked={picked} onPick={setPicked} />
                ))}
              </div>
              <MyBets markets={state.markets} refresh={refresh} />
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
