// outcome → accent: khuseel-ish green, bansod-ish blue, neutral gold for yes/no
export const tone = (oid) =>
  oid === "khuseel" || oid.startsWith("k") ? "k" : oid === "bansod" || oid.startsWith("b") ? "b" : "g";

export const TONE_TEXT = { k: "text-khuseel", b: "text-bansod", g: "text-gold" };
export const TONE_SEL = {
  k: "border-khuseel bg-khuseel/10",
  b: "border-bansod bg-bansod/10",
  g: "border-gold bg-gold/10",
};

// Bolder selected-state treatment for the hero odds cards (OddsBoard), where a plain 10%-tint
// border needs more presence than it does on the smaller side-market buttons.
export const TONE_SEL_STRONG = {
  k: "border-khuseel bg-gradient-to-b from-khuseel/15 to-khuseel/5 shadow-[0_0_0_1px_rgba(33,192,101,0.15)]",
  b: "border-bansod bg-gradient-to-b from-bansod/15 to-bansod/5 shadow-[0_0_0_1px_rgba(58,168,240,0.15)]",
  g: "border-gold bg-gradient-to-b from-gold/15 to-gold/5 shadow-[0_0_0_1px_rgba(242,184,59,0.15)]",
};
