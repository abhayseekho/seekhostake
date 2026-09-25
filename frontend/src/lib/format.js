export const inr = (n) => "₹" + Number(n || 0).toLocaleString("en-IN");

// The odds to SHOW for an outcome: in fixed-odds mode the server sends a Bansod-tilted `fixed_odds`
// (the price a new bet locks); otherwise it's the parimutuel `est_mult`. One helper so the board,
// the cards, and the slip all display the same number.
export const oddsOf = (o) => (o && o.fixed_odds != null ? o.fixed_odds : o && o.est_mult);
export const oddsText = (v) => (v ? v.toFixed(2) + "×" : "—");
