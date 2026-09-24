import { PHASE_LABEL, LABEL, SIDE_TEXT } from "../lib/constants.js";

// The glance header — audit §3: at rest this looked identical whether nothing was happening or a
// lap was actively in the water, which is backwards (a live lap is the single highest-attention
// moment in the product). `live` now gets a background wash and a real ping ring, not just a
// pulsing dot, so it reads as "happening now" even in peripheral vision.
export default function RaceStrip({ race }) {
  const live = race.phase.startsWith("lap");
  const open = race.book_open;
  return (
    <div className={`border rounded-2xl px-4 py-3 transition-colors duration-settle
      ${live ? "bg-bad/[0.06] border-bad/60" : "bg-card border-edge"}`}>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <span className={`inline-flex items-center gap-2 font-extrabold tracking-label uppercase
          ${live ? "text-bad text-xs" : "text-2xs"} ${!live && (open ? "text-khuseel" : "text-dim")}`}>
          <span className="relative inline-flex w-dot h-dot">
            {live && (
              <i className="absolute inline-flex w-full h-full rounded-full bg-bad opacity-60 animate-ping" />
            )}
            <i className={`relative inline-flex w-full h-full rounded-full
              ${live ? "bg-bad" : open ? "bg-khuseel" : "bg-faint"}`} />
          </span>
          {PHASE_LABEL[race.phase] || race.phase}
        </span>
        <span className="font-extrabold tabular-nums">
          <span className={SIDE_TEXT.khuseel}>KHU {race.wins.khuseel}</span>
          <span className="text-dim mx-1.5">·</span>
          <span className={SIDE_TEXT.bansod}>{race.wins.bansod} BAN</span>
        </span>
      </div>
      {race.laps.length > 0 && (
        <div className="flex gap-1.5 mt-3 flex-wrap">
          {race.laps.map((l) => (
            <span key={l.lap} className="bg-raise border border-edge rounded-lg px-2.5 py-1 text-sm text-dim tabular-nums">
              L{l.lap} <b className={SIDE_TEXT[l.winner]}>{LABEL[l.winner]}</b>
              {l.time_s != null && <span className="text-faint"> {l.time_s}s</span>}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
