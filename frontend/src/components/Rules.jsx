// Copy is FROZEN — verified live in production 24 Sept per docs/release-checklist.md (private-
// pool disclaimer + responsible-gambling line). Every <p>/<b> text node below is byte-identical
// to the pre-revamp version; only structure/classes changed. If a future layout change would
// require touching the wording, stop and flag it rather than editing text here.
export default function Rules({ onClose, deadlineLabel }) {
  const S = ({ n, title, children, emphasis }) => (
    <div className={`mb-5 ${emphasis ? "pt-4 border-t border-edge" : ""}`}>
      <h3 className="flex items-center gap-2 font-bold mb-1.5">
        <span className="inline-flex items-center justify-center w-5 h-5 rounded-md bg-raise
          text-2xs text-dim font-extrabold shrink-0">{n}</span>
        {title}
      </h3>
      <div className="text-sm text-dim space-y-1.5 pl-7">{children}</div>
    </div>
  );
  return (
    <div className="fixed inset-0 bg-overlay z-50 flex items-start justify-center overflow-y-auto p-4"
      onClick={onClose}>
      <div className="animate-rise-in bg-card border border-edge rounded-2xl p-6 max-w-lg w-full my-8 text-left shadow-2xl shadow-black/40"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-5">
          <h2 className="text-xl font-extrabold">Rules</h2>
          <button onClick={onClose}
            className="text-dim text-2xl leading-none hover:text-ink transition-colors duration-quick
              focus-visible:ring-2 focus-visible:ring-edge rounded">×</button>
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
          {deadlineLabel && (
            <p>Regardless of race progress, all betting closes for good at
              <b className="text-gold"> {deadlineLabel}</b>.</p>
          )}
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
        <S n={8} title="Play responsibly" emphasis>
          <p>This is a private, for-fun pool among colleagues — not a licensed gambling product.
            Bet only what you're comfortable losing.</p>
        </S>
        <button onClick={onClose}
          className="w-full bg-khuseel text-bg font-bold rounded-xl py-3 mt-2
            hover:brightness-110 active:scale-[0.99] transition
            focus-visible:ring-2 focus-visible:ring-khuseel/50 focus-visible:ring-offset-2
            focus-visible:ring-offset-card">
          Got it
        </button>
      </div>
    </div>
  );
}
