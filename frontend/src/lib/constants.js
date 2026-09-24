export const SIDES = ["khuseel", "bansod"];
export const LABEL = { khuseel: "Khuseel", bansod: "Bansod" };
export const SIDE_TEXT = { khuseel: "text-khuseel", bansod: "text-bansod" };

export const PHASE_LABEL = {
  prerace: "Pre-race · bets open",
  lap1: "Lap 1 in progress",
  break1: "Break 1 · bets open",
  lap2: "Lap 2 · book closed",
  break2: "Break 2 · book closed",
  lap3: "Lap 3 · decider",
  finished: "Race finished",
  settled: "Settled",
};

export const REASON_TEXT = {
  book_closed: "This market is closed.",
  no_side_switch: "Side switching is locked after lap 1. You can raise your existing pick only.",
  bad_amount: "Enter a valid amount (minimum ₹500).",
  outcome_dead: "This outcome is no longer possible.",
  not_pending: "This request was already handled.",
  arbitrage_bet: "This combination would guarantee you a profit regardless of outcome. One of your bets must carry risk.",
  market_suspended: "This market is paused for review after an unusual odds swing. Check with the organiser.",
  betting_closed: "Betting is closed for this event.",
  name_taken: "That name is already registered and doesn't quite match — add your surname or an initial to tell you apart.",
  too_many_attempts: "Too many attempts. Wait a few minutes and try again.",
};
