import { useEffect, useState, useCallback, useRef } from "react";
import { get } from "./api.js";
import Login from "./components/Login.jsx";
import Rules from "./components/Rules.jsx";
import RaceStrip from "./components/RaceStrip.jsx";
import OddsBoard from "./components/OddsBoard.jsx";
import MarketCard from "./components/MarketCard.jsx";
import PoolBar from "./components/PoolBar.jsx";
import BetSlip from "./components/BetSlip.jsx";
import MyBets from "./components/MyBets.jsx";
import BookTable from "./components/BookTable.jsx";
import Settlement from "./components/Settlement.jsx";
import Admin from "./components/Admin.jsx";

// App shell — state, data fetching (SSE + fallback poll + visibility/focus catch-up), and layout.
// All of this is UNCHANGED logic from the pre-revamp version (same state variables, same effect,
// same refresh()/live-sync behavior) — only the header markup and the mobile bet-slip placement
// changed, both direct fixes for audit findings:
//   §10 — the header overflowed at 375px (the brief's stated dominant device): the logo wrapped
//   to two lines, "View as user" wrapped mid-word, "Logout" was clipped off the visible viewport
//   entirely. Now wraps as whole pills onto a second line instead of breaking words or clipping.
//   §5  — BetSlip rendered inline, above all six side-market cards; picking an outcome further
//   down meant scrolling back up to find the slip that had just populated. It's now a fixed
//   bottom sheet on mobile once something is picked, reachable from anywhere on the page — the
//   desktop sticky sidebar placement is unchanged.
export default function App() {
  const [state, setState] = useState(null);
  const [unauth, setUnauth] = useState(false);
  const [authMode, setAuthMode] = useState("oauth");
  const [testLogin, setTestLogin] = useState(false);
  const [deadlineLabel, setDeadlineLabel] = useState("");
  const [picked, setPicked] = useState(null);
  const [settlement, setSettlement] = useState(null);
  const [showRules, setShowRules] = useState(false);
  const [asUser, setAsUser] = useState(false);

  const stateJsonRef = useRef("");
  const refresh = useCallback(async () => {
    const q = asUser ? "?as_user=1" : "";
    const r = await get("/api/state" + q);
    if (r._unauth) { setUnauth(true); return; }
    if (r._error) return;
    setUnauth(false);
    // Live sync can now fire many times a minute (any bettor's action wakes every open tab).
    // Skip the state update — and the re-render it would cause — when nothing actually changed,
    // so a tap in progress never lands on a button that silently shifted a few pixels underneath it.
    const json = JSON.stringify(r);
    if (json !== stateJsonRef.current) {
      stateJsonRef.current = json;
      setState(r);
    }
    if (r.auth_mode) setAuthMode(r.auth_mode);
    if (r.settled && !settlement) {
      const s = await get("/api/settlement" + q);
      if (!s._error) setSettlement(s);
    }
  }, [settlement, asUser]);

  const [live, setLive] = useState(false);

  useEffect(() => {
    get("/api/config").then((c) => {
      if (c && c.auth_mode) setAuthMode(c.auth_mode);
      if (c) setTestLogin(!!c.test_login);
      if (c && c.betting_deadline_label) setDeadlineLabel(c.betting_deadline_label);
    });
    refresh();
    // Push-based sync: the server pings this stream the instant any bet, approval, lap result,
    // or settlement happens, so every open tab updates within one round trip — no polling wait.
    const es = new EventSource("/api/stream");
    // onopen fires on the FIRST connect and on every auto-reconnect. Without an immediate refresh
    // here, a tab that reconnects after any gap (see below) sits on whatever it last saw until
    // the next mutation happens to occur — e.g. someone's bet gets rejected while their phone was
    // locked, the stream reconnects the instant they unlock it, but the odds stay stale until
    // another bettor does something elsewhere. This is very likely the actual "odds don't update"
    // symptom on a phone, since screen-lock/backgrounding is routine mid-race.
    es.onopen = () => { setLive(true); refresh(); };
    es.onerror = () => setLive(false);  // EventSource retries on its own; flips back on reconnect
    es.onmessage = refresh;
    const fallback = setInterval(refresh, 15000);  // safety net if a stream silently drops
    // Mobile browsers throttle/pause timers and can delay SSE delivery for a backgrounded tab —
    // both the interval above and the stream itself can sit stale for longer than expected while
    // locked. Force a fetch the instant the tab is foregrounded again, instead of waiting on
    // whichever of those two happens to fire next.
    const onVisible = () => { if (document.visibilityState === "visible") refresh(); };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", refresh);
    return () => {
      es.close(); clearInterval(fallback);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", refresh);
    };
  }, [refresh]);

  if (unauth) return <Login authMode={authMode} testLogin={testLogin} deadlineLabel={deadlineLabel} onNamed={refresh} />;
  if (!state) return <div className="min-h-screen flex items-center justify-center text-dim">Loading…</div>;

  const main = state.markets.find((m) => m.main);
  const sides = state.markets.filter((m) => !m.main);
  const slip = !settlement && <BetSlip picked={picked} refresh={refresh} onClear={() => setPicked(null)} />;
  const mobileSheetOpen = !!picked && !settlement;

  return (
    <div className={`max-w-5xl mx-auto p-4 transition-[padding] duration-settle
      ${mobileSheetOpen ? "pb-56 lg:pb-16" : "pb-16"}`}>
      <header className="flex items-center justify-between flex-wrap gap-x-3 gap-y-2 mb-4">
        <h1 className="text-lg font-extrabold tracking-tight flex items-center gap-2 shrink-0 whitespace-nowrap">
          🏊 Seekho<span className="text-gold">Stake</span>
          <span title={live ? "Live — instant sync" : "Reconnecting…"}
            className={`inline-flex items-center gap-1.5 text-3xs font-bold tracking-label uppercase
              rounded-full px-2 py-0.5 ${live ? "text-khuseel bg-khuseel/10" : "text-faint bg-raise"}`}>
            <i className={`w-dot h-dot rounded-full ${live ? "bg-khuseel animate-pulse" : "bg-faint"}`} />
            {live ? "Live" : "…"}
          </span>
        </h1>
        <div className="text-xs text-dim flex items-center flex-wrap gap-x-3 gap-y-1.5">
          {state.me.can_admin && (
            <button onClick={() => { setAsUser(!asUser); setSettlement(null); }}
              className={`whitespace-nowrap rounded-lg px-2.5 py-1 font-bold border transition-colors duration-quick
                ${asUser ? "border-gold text-gold" : "border-edge text-dim hover:text-ink"}`}>
              {asUser ? "User view · back to admin" : "View as user"}
            </button>
          )}
          <button onClick={() => setShowRules(true)}
            className="whitespace-nowrap underline hover:text-ink transition-colors duration-quick">Rules</button>
          <span className="whitespace-nowrap">{state.me.name}{state.me.is_owner && <span className="text-gold font-bold"> · ADMIN</span>}</span>
          <a href="/auth/logout"
            className="whitespace-nowrap underline hover:text-ink transition-colors duration-quick">Logout</a>
        </div>
      </header>
      {showRules && <Rules deadlineLabel={deadlineLabel} onClose={() => setShowRules(false)} />}

      <div className="lg:grid lg:grid-cols-[1fr,340px] lg:gap-5 lg:items-start">
        <div className="space-y-4">
          <RaceStrip race={state.race} />
          {settlement && <Settlement s={settlement} race={state.race} />}
          {state.me.is_owner && <Admin state={state} refresh={refresh} />}
          {!settlement && (
            <>
              <OddsBoard market={main} picked={picked} onPick={setPicked} />
              <PoolBar market={main} />
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

      {/* Mobile: fixed bottom sheet, only once an outcome is picked (audit §5) — reachable from
          anywhere on the page instead of requiring a scroll back to a fixed inline position. */}
      {mobileSheetOpen && (
        <div className="lg:hidden fixed inset-x-0 bottom-0 z-30 p-3 pt-8
          bg-gradient-to-t from-bg via-bg/95 to-transparent">
          <div className="max-w-5xl mx-auto">{slip}</div>
        </div>
      )}
    </div>
  );
}
