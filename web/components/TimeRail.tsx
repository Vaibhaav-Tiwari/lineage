"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { useDismiss } from "@/lib/useDismiss";
import type { EventRow } from "@/lib/api";
import Tip from "./Tip";

const START = 2000, END = 2027;
const pct = (d: Date) => ((d.getFullYear() + d.getMonth() / 12 + d.getDate() / 365 - START) / (END - START)) * 100;

export type Tick = { id: string; at: string; label: string };

export default function TimeRail({
  events, ticks, asOf, onAsOf, onApply, onUndo, onReset, applying,
}: {
  events: EventRow[];
  ticks: Tick[];
  asOf: string | null;
  onAsOf: (d: string | null) => void;
  onApply: (slug: string) => void;
  onUndo: (slug: string) => void;
  onReset: () => void;
  applying: boolean;
}) {
  const track = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const pinBox = useRef<HTMLDivElement>(null);
  useDismiss(pinBox, open !== null, useCallback(() => setOpen(null), []));
  const years = useMemo(() => Array.from({ length: (END - START) / 3 + 1 }, (_, i) => START + i * 3), []);
  const handle = asOf ? pct(new Date(asOf)) : 100;

  function setFromX(clientX: number) {
    const el = track.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
    if (f > 0.985) return onAsOf(null);
    const y = START + f * (END - START);
    onAsOf(new Date(Math.floor(y), Math.floor((y % 1) * 12), 15).toISOString().slice(0, 10));
  }

  function drag(e: React.PointerEvent) {
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    setDragging(true);
    const move = (ev: PointerEvent) => setFromX(ev.clientX);
    const up = () => { setDragging(false); window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  function nudge(e: React.KeyboardEvent) {
    const cur = asOf ? new Date(asOf) : new Date();
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      cur.setMonth(cur.getMonth() + (e.key === "ArrowLeft" ? -6 : 6));
      onAsOf(cur > new Date() ? null : cur.toISOString().slice(0, 10));
    }
    if (e.key === "Escape" || e.key === "End") onAsOf(null);
  }

  return (
    <section className="rail" aria-label="Time">
      <div className="rail-meta">
        <span>{asOf ? <>Answering as of <strong>{asOf}</strong>: anything later is ignored.</> : "Answering with everything known today."}</span>
        {asOf ? <button onClick={() => onAsOf(null)}>Back to today</button> : <span style={{ fontStyle: "italic" }}>Drag the dial back in time to ask as of an earlier date.</span>}
        <span style={{ marginLeft: "auto" }}>Red pins are real changes you can replay.</span>
        {confirmReset ? (
          <span className="confirm">
            <span>Reset everything? Agent memory and the task board are cleared.</span>
            <button className="danger" onClick={() => { setConfirmReset(false); onReset(); }}>Yes, reset</button>
            <button onClick={() => setConfirmReset(false)}>Cancel</button>
          </span>
        ) : <button onClick={() => setConfirmReset(true)}>Reset demo</button>}
      </div>
      <div className="rail-track" ref={track}>
        <div className="rail-line" />
        {years.map((y) => <span key={y} className="rail-year" style={{ left: `${((y - START) / (END - START)) * 100}%` }}>{y}</span>)}
        {ticks.map((t) => (
          <span key={t.id} className="rail-tick-hit" style={{ left: `${pct(new Date(t.at))}%` }}>
            <Tip text={`${t.label}, ${t.at}`}><span className="rail-tick decision" tabIndex={0} style={{ position: "absolute", left: 5 }} aria-label={`${t.label}, ${t.at}`} /></Tip>
          </span>
        ))}
        {events.map((e) => (
          <div key={e.id} ref={open === e.slug ? pinBox : undefined} style={{ position: "absolute", left: `${pct(new Date(e.at))}%`, top: 0 }}>
            <Tip side="bottom" text={e.applied ? "Applied. Click to undo it." : "A real change from Python's history. Click to replay it and see what goes stale."}>
              <button className={`rail-pin ${e.applied ? "applied" : ""}`} aria-label={`Change event: ${e.summary}`} onClick={() => setOpen(open === e.slug ? null : e.slug)}>
                <span className="head" /><span className="stem" />
              </button>
            </Tip>
            {open === e.slug && (
              <div className="pin-pop" role="dialog">
                <p><strong>{e.at}</strong> — {e.summary}</p>
                {e.applied ? (
                  <>
                    <p className="typed">Applied. Everything built on {e.pep} was re-checked.</p>
                    <button className="btn quiet" disabled={applying} onClick={() => { onUndo(e.slug); setOpen(null); }}>Undo this change</button>
                  </>
                ) : (
                  <button className="btn" disabled={applying} onClick={() => { onApply(e.slug); setOpen(null); }}>
                    {applying ? "Applying…" : "Apply this change"}
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
        {dragging && <span className="rail-bubble" style={{ left: `${handle}%` }}>{asOf ?? "today"}</span>}
        <div className="rail-handle" style={{ left: `${handle}%` }} onPointerDown={drag} role="slider" tabIndex={0}
             aria-label="Answer as of date. Arrow keys move six months; End returns to today."
             aria-valuemin={START} aria-valuemax={END} aria-valuenow={asOf ? Number(asOf.slice(0, 4)) : END} aria-valuetext={asOf ?? "today"}
             onKeyDown={nudge} />
        {!asOf && !dragging && <span className="rail-today" style={{ left: `${handle}%` }}>today</span>}
      </div>
    </section>
  );
}
