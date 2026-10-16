"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { useDismiss } from "@/lib/useDismiss";
import type { EventRow } from "@/lib/api";
import Tip from "./Tip";

const START = 2000, END = 2027;
const pct = (d: Date) => ((d.getFullYear() + d.getMonth() / 12 + d.getDate() / 365 - START) / (END - START)) * 100;

export type Tick = { id: string; at: string; label: string };

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fmtDay = (iso: string) => { const [y, m, d] = iso.split("-").map(Number); return `${d} ${MONTHS[m - 1]} ${y}`; };
const pinLabel = (e: EventRow) => (e.kind === "supersede" ? `PEP ${e.pep.split(":")[1]} replaced` : e.summary.split(/[.(]/)[0]);

export default function TimeRail({
  events, ticks, span, asOf, onAsOf, onApply, onUndo, onReset, applying,
}: {
  events: EventRow[];
  ticks: Tick[];
  span: { from: string; to: string } | null;
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
  const years = useMemo(() => Array.from({ length: END - START }, (_, i) => START + i), []);
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
      <div className="rail-status" aria-live="polite">
        {asOf ? <>As of <strong className="typed">{asOf}</strong> <button onClick={() => onAsOf(null)}>Back to today</button></> : "As of today"}
      </div>
      <div className="rail-track" ref={track}>
        {span && (() => {
          const a = pct(new Date(span.from)), b = pct(new Date(span.to));
          const years = span.from.slice(0, 4) === span.to.slice(0, 4) ? span.from.slice(0, 4) : `${span.from.slice(0, 4)} to ${span.to.slice(0, 4)}`;
          return (
            <span className="rail-span" style={{ left: `${a}%`, width: `max(6px, ${b - a}%)` }}>
              <Tip side="bottom" text={`The evidence on the graph covers ${years}: from the earliest proposal or decision it rests on (${span.from}) to the latest (${span.to}).`}>
                <span className="rail-span-hit" tabIndex={0} aria-label={`The evidence on the graph covers ${years}`} />
              </Tip>
            </span>
          );
        })()}
        <div className="rail-line" />
        {years.map((y) => (
          <span key={y} className={`rail-mark ${y % 5 === 0 ? "major" : ""}`} style={{ left: `${((y - START) / (END - START)) * 100}%` }}>
            {y % 5 === 0 && <span className="rail-year">{y}</span>}
          </span>
        ))}
        {ticks.map((t) => (
          <span key={t.id} className="rail-tick-hit" style={{ left: `${pct(new Date(t.at))}%` }}>
            <Tip text={`${t.label}, ${t.at}`}><span className="rail-dot" tabIndex={0} aria-label={`${t.label}, ${t.at}`} /></Tip>
          </span>
        ))}
        {events.map((e) => (
          <div key={e.id} ref={open === e.slug ? pinBox : undefined} style={{ position: "absolute", left: `${pct(new Date(e.at))}%`, top: 0 }}>
            <Tip side="bottom" text={e.applied ? "Applied. Click to undo it." : "A real change from Python's history. Click to replay it and see what goes stale."}>
              <button className={`rail-pin ${e.applied ? "applied" : ""}`} aria-label={`Change event: ${e.summary}`} onClick={() => setOpen(open === e.slug ? null : e.slug)}>
                <span className="head" /><span className="stem" />
              </button>
            </Tip>
            <span className={`rail-pin-label ${pct(new Date(e.at)) > 50 ? "left" : ""}`} aria-hidden="true">
              {fmtDay(e.at)}: {pinLabel(e)}{e.applied ? " (applied)" : ""}
            </span>
            {open === e.slug && (
              <div className="pin-pop" role="dialog">
                <p className="pin-when">{fmtDay(e.at)}{e.applied ? ", applied" : ""}</p>
                <p>{e.summary}</p>
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
             title="Drag back in time to ask as of an earlier date"
             aria-label="Answer as of date. Arrow keys move six months; End returns to today."
             aria-valuemin={START} aria-valuemax={END} aria-valuenow={asOf ? Number(asOf.slice(0, 4)) : END} aria-valuetext={asOf ?? "today"}
             onKeyDown={nudge} />
        {!asOf && !dragging && <span className="rail-today" style={{ left: `${handle}%` }}>today</span>}
      </div>
      <div className="rail-side">
        <button onClick={() => setConfirmReset(true)}>Reset demo</button>
        {confirmReset && (
          <span className="confirm" role="dialog">
            <span>Reset everything? Agent memory and the task board are cleared.</span>
            <button className="danger" onClick={() => { setConfirmReset(false); onReset(); }}>Yes, reset</button>
            <button onClick={() => setConfirmReset(false)}>Cancel</button>
          </span>
        )}
      </div>
    </section>
  );
}
