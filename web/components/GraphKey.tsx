"use client";

import { useCallback, useRef, useState } from "react";
import { useDismiss } from "@/lib/useDismiss";

const ROWS: [string, string, string][] = [
  ["key-pep", "Proposal (PEP)", "A Python Enhancement Proposal: the documents decisions are made about."],
  ["key-person", "Person", "An author, decider or contributor. One person even if they appear under several names."],
  ["key-decision", "Decision", "Accepted, rejected or superseded, with the date and who announced it."],
  ["key-answer", "Historian's answer", "What the agent told you. Dotted green lines show the evidence it rests on."],
  ["key-action", "Queued action", "Something the agent wants to do. It may only run while its evidence is still current."],
  ["key-small", "Thread, post, PR, passage", "Where it was discussed, the code that implemented it, the exact passage cited."],
  ["key-stale", "No longer current", "Faded and hatched: the truth this rests on has changed."],
];

export default function GraphKey() {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useDismiss(box, open, useCallback(() => setOpen(false), []));
  return (
    <div className="graph-key" ref={box}>
      <button className="key-btn" aria-expanded={open} aria-controls="graph-key" onClick={() => setOpen(!open)} title="What the shapes mean">?</button>
      {open && (
        <div id="graph-key" className="key-panel" role="dialog" aria-label="Graph key">
          <h4>Reading the graph</h4>
          <ul>
            {ROWS.map(([cls, name, what]) => (
              <li key={name}><i className={cls} /><span><strong>{name}.</strong> {what}</span></li>
            ))}
            <li><i className="key-red-line" /><span><strong>Red arrow.</strong> &ldquo;Replaces&rdquo;, or the chain that blocked an action.</span></li>
          </ul>
          <p>Hover a shape for its details; click it to open its card.</p>
        </div>
      )}
    </div>
  );
}
