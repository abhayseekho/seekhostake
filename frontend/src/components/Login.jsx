import { useState } from "react";
import { post } from "../api.js";
import { REASON_TEXT } from "../lib/constants.js";
import Rules from "./Rules.jsx";

// First screen every bettor sees, before any trust in the product has been earned yet (audit
// §2: this had the widest gap to the brief's "real fintech app" bar — a small plain card adrift
// in empty space, no visual identity beyond a swimmer emoji). The VS badge below is the one
// deliberate addition: it states the actual product (a two-sided contest) at a glance using
// nothing but the palette that's already canonical (khuseel/bansod), not new copy.
export default function Login({ authMode, testLogin, deadlineLabel, onNamed }) {
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
    if (r._error) {
      setErr(r._error === "not_allowed" ? "Email must be @seekhoapp.com."
        : r._error === "too_many_attempts" ? REASON_TEXT.too_many_attempts : "Wrong test password.");
    } else onNamed();
  };
  const submitName = async () => {
    const r = await post("/auth/name", { name });
    if (r._error) setErr(r._error === "bad_name" ? "Enter your real name (2–40 chars)." : (REASON_TEXT[r._error] || r._error));
    else onNamed();
  };
  const submitAdmin = async () => {
    const r = await post("/auth/admin", { password: pw });
    if (r._error) setErr(r._error === "too_many_attempts" ? REASON_TEXT.too_many_attempts : "Wrong admin password.");
    else onNamed();
  };

  return (
    <div className="relative min-h-screen flex items-center justify-center p-6 overflow-hidden">
      {/* Ambient rivalry glow — decorative only, reinforces the two-sided identity before the
          card even loads content. Fixed, low-opacity, never competes with foreground text. */}
      <div className="pointer-events-none absolute -top-24 -left-24 w-[420px] h-[420px] rounded-full
        bg-khuseel/[0.07] blur-[100px]" />
      <div className="pointer-events-none absolute -bottom-24 -right-24 w-[420px] h-[420px] rounded-full
        bg-bansod/[0.07] blur-[100px]" />

      <div className="relative bg-card border border-edge rounded-3xl p-8 max-w-sm w-full text-center
        shadow-2xl shadow-black/40">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-raise
          border border-edge text-4xl mb-4">🏊</div>
        <h1 className="text-display-sm font-extrabold tracking-tight mb-2">
          Seekho<span className="text-gold">Stake</span>
        </h1>

        {/* The rivalry, stated visually — same data the rest of the app already uses. */}
        <div className="inline-flex items-center gap-2 bg-bg border border-edge rounded-full
          px-3 py-1.5 mb-4">
          <span className="text-khuseel text-2xs font-extrabold tracking-label uppercase">Khuseel</span>
          <span className="text-faint text-3xs font-bold">VS</span>
          <span className="text-bansod text-2xs font-extrabold tracking-label uppercase">Bansod</span>
        </div>

        <p className="text-dim text-sm mb-1">Best of 3 · 27 Sept</p>
        {deadlineLabel && (
          <p className="text-gold text-2xs font-bold tracking-label uppercase mb-5">
            Betting closes {deadlineLabel}
          </p>
        )}

        <button onClick={() => setShowRules(true)} className="text-dim text-sm underline mb-6
          hover:text-ink transition-colors duration-quick">Rules</button>
        {showRules && <Rules deadlineLabel={deadlineLabel} onClose={() => setShowRules(false)} />}

        {authMode === "name" ? (
          <div className="space-y-3">
            <input
              className="w-full bg-bg border border-edge rounded-xl px-4 py-3 outline-none
                focus-visible:ring-2 focus-visible:ring-khuseel/50 focus:border-khuseel
                transition-colors duration-quick"
              placeholder="Your name" value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submitName()} />
            <button onClick={submitName}
              className="w-full bg-khuseel text-bg font-extrabold rounded-xl py-3
                hover:brightness-110 active:scale-[0.99] transition
                focus-visible:ring-2 focus-visible:ring-khuseel/50 focus-visible:ring-offset-2
                focus-visible:ring-offset-card">Enter</button>
            {err && <p className="text-bad text-sm">{err}</p>}
            {showAdmin ? (
              <div className="flex gap-2">
                <input type="password" placeholder="Admin password" value={pw}
                  onChange={(e) => setPw(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && submitAdmin()}
                  className="flex-1 bg-bg border border-edge rounded-xl px-4 py-2 outline-none
                    focus-visible:ring-2 focus-visible:ring-gold/50 focus:border-gold
                    transition-colors duration-quick" />
                <button onClick={submitAdmin} className="bg-gold text-bg font-bold rounded-xl px-4
                  hover:brightness-110 active:scale-[0.99] transition">Go</button>
              </div>
            ) : (
              <button onClick={() => setShowAdmin(true)}
                className="text-faint text-2xs underline hover:text-dim transition-colors duration-quick">
                Admin login</button>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <a href="/auth/login"
              className="block w-full bg-khuseel text-bg font-extrabold rounded-xl py-3
                hover:brightness-110 active:scale-[0.99] transition
                focus-visible:ring-2 focus-visible:ring-khuseel/50 focus-visible:ring-offset-2
                focus-visible:ring-offset-card">
              Sign in with Google (@seekhoapp.com)
            </a>
            {testLogin && (showTest ? (
              <div className="space-y-2">
                <input placeholder="Test email (@seekhoapp.com)" value={tEmail}
                  onChange={(e) => setTEmail(e.target.value)}
                  className="w-full bg-bg border border-edge rounded-xl px-4 py-2 outline-none
                    text-sm focus-visible:ring-2 focus-visible:ring-gold/50 focus:border-gold
                    transition-colors duration-quick" />
                <div className="flex gap-2">
                  <input type="password" placeholder="Test password" value={tPw}
                    onChange={(e) => setTPw(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && submitTest()}
                    className="flex-1 bg-bg border border-edge rounded-xl px-4 py-2 outline-none
                      text-sm focus-visible:ring-2 focus-visible:ring-gold/50 focus:border-gold
                      transition-colors duration-quick" />
                  <button onClick={submitTest} className="bg-gold text-bg font-bold rounded-xl px-4
                    hover:brightness-110 active:scale-[0.99] transition">Go</button>
                </div>
                {err && <p className="text-bad text-sm">{err}</p>}
              </div>
            ) : (
              <button onClick={() => setShowTest(true)}
                className="text-faint text-2xs underline hover:text-dim transition-colors duration-quick">
                Test login</button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
