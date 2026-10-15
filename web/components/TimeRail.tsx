"use client";

import { useMemo, useRef, useState } from "react";
import type { EventRow } from "@/lib/api";

const START = 2000, END = 2027;
const pct = (d: Date) => ((d.getFullYear() + d.getMonth() / 12 + d.getDate() / 365 - START) / (END - START)) * 100;

export default function TimeRail({
  events, ticks, asOf, onAsOf, onApply, onReset, applying,
}: {
  events: EventRow[];
  ticks: { at: string; id: string }[];
  asOf: string | null;
  onAsOf: (d: string | null) => void;
  onApply: (slug: string) => void;
  onReset: () => void;
  applying: boolean;
}) {
  const track = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState<string | null>(null);
  const years = useMemo(() => Array.from({ length: (END - START) / 3 + 1 }, (_, i) => START + i * 3), []);
  const handle = asOf ? pct(new Date(asOf)) : 100;

  function drag(e: React.PointerEvent) {
    const el = track.current;
    if (!el) return;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    const move = (ev: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const f = Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width));
      if (f > 0.985) return onAsOf(null);
      const y = START + f * (END - START);
      const d = new Date(Math.floor(y), Math.floor((y % 1) * 12), 15);
      onAsOf(d.toISOString().slice(0, 10));
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  return (
    <section className="rail" aria-label="Time">
      <div className="rail-meta">
        <span>{asOf ? <>Answering as of <strong>{asOf}</strong></> : "Answering with everything known today"}</span>
        {asOf && <button onClick={() => onAsOf(null)}>Back to today</button>}
        <span style={{ marginLeft: "auto" }}>Red pins are real changes you can replay.</span>
        <button onClick={onReset}>Reset demo</button>
      </div>
      <div className="rail-track" ref={track}>
        <div className="rail-line" />
        {years.map((y) => <span key={y} className="rail-year" style={{ left: `${((y - START) / (END - START)) * 100}%` }}>{y}</span>)}
        {ticks.map((t) => <span key={t.id} className="rail-tick decision" title={`${t.id} · ${t.at}`} style={{ left: `${pct(new Date(t.at))}%` }} />)}
        {events.map((e) => (
          <div key={e.id} style={{ position: "absolute", left: `${pct(new Date(e.at))}%`, top: 0 }}>
            <button className={`rail-pin ${e.applied ? "applied" : ""}`} aria-label={`Change event: ${e.summary}`} onClick={() => setOpen(open === e.slug ? null : e.slug)}>
              <span className="head" /><span className="stem" />
            </button>
            {open === e.slug && (
              <div className="pin-pop" role="dialog">
                <p><strong>{e.at}</strong> — {e.summary}</p>
                {e.applied ? <p className="typed">Applied. Everything built on <span>{e.pep}</span> was re-checked.</p> : (
                  <button className="btn" disabled={applying} onClick={() => { onApply(e.slug); setOpen(null); }}>
                    {applying ? "Applying…" : "Apply this change"}
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
        <div className="rail-handle" style={{ left: `${handle}%` }} onPointerDown={drag} role="slider" aria-label="Answer as of date"
             aria-valuetext={asOf ?? "today"} tabIndex={0}
             onKeyDown={(e) => { if (e.key === "Escape") onAsOf(null); }} />
      </div>
    </section>
  );
}
