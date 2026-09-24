import { useState } from "react";
import { post } from "../api.js";
import { REASON_TEXT } from "../lib/constants.js";
import Rules from "./Rules.jsx";

// Google's own 4-color "G" mark — standard on every "Sign in with Google" button on the web.
// Using it (over a plain text link) is the single biggest recognizability/trust signal available
// on this screen for zero new copy.
function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" className="shrink-0">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.91c1.7-1.57 2.69-3.88 2.69-6.62z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.91-2.26c-.81.54-1.84.86-3.05.86-2.34 0-4.32-1.58-5.03-3.71H.95v2.33A9 9 0 0 0 9 18z" />
      <path fill="#FBBC05" d="M3.97 10.71A5.41 5.41 0 0 1 3.68 9c0-.59.1-1.17.29-1.71V4.96H.95A9 9 0 0 0 0 9c0 1.45.35 2.83.95 4.04l3.02-2.33z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.51.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .95 4.96l3.02 2.33C4.68 5.16 6.66 3.58 9 3.58z" />
    </svg>
  );
}

// First screen every bettor sees, before any trust in the product has been earned yet (audit
// §2: this had the widest gap to the brief's "real fintech app" bar — a small plain card adrift
// in empty space, no visual identity beyond a swimmer emoji). The VS badge states the actual
// product (a two-sided contest) at a glance using only the palette that's already canonical.
// This pass (follow-up polish, live-screenshot review): the card read as too small and adrift on
// wide desktop viewports specifically — real-world rendering made the ambient glow nearly
// invisible and left a lot of dead space with nothing tying it back to "a swim race." Added a
// subtle pool-lane line pattern across the full background (the one concrete visual motif this
// product actually has and wasn't using anywhere), stronger glow, and a real Google "G" mark on
// the sign-in button — the de facto standard for OAuth buttons, and free trust signal.
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
      {/* Pool-lane texture — faint horizontal rules across the whole viewport. The one visual
          motif this product actually has (it's a swim race) that wasn't used anywhere before. */}
      <div className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage: "repeating-linear-gradient(180deg, rgba(234,241,247,0.035) 0px, rgba(234,241,247,0.035) 1px, transparent 1px, transparent 64px)",
        }} />

      {/* Ambient rivalry glow — decorative, reinforces the two-sided identity before the card
          even loads content. Bumped up from the first pass: measured as barely visible on a
          real monitor at the original size/opacity. */}
      <div className="pointer-events-none absolute -top-32 -left-32 w-[560px] h-[560px] rounded-full
        bg-khuseel/[0.12] blur-[120px]" />
      <div className="pointer-events-none absolute -bottom-32 -right-32 w-[560px] h-[560px] rounded-full
        bg-bansod/[0.12] blur-[120px]" />

      <div className="relative bg-card border border-edge rounded-3xl p-8 sm:p-9 max-w-sm w-full text-center
        shadow-2xl shadow-black/50">
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
              className="flex items-center justify-center gap-2.5 w-full bg-ink text-bg font-bold rounded-xl py-3
                hover:brightness-95 active:scale-[0.99] transition
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink/50 focus-visible:ring-offset-2
                focus-visible:ring-offset-card">
              <GoogleIcon />
              Sign in with Google
            </a>
            <p className="text-faint text-3xs tracking-label uppercase">@seekhoapp.com accounts only</p>
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
