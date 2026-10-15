"use client";

import { citationLabel, GNode } from "@/lib/api";

/** An answer set like a scholarly edition: "[n]" markers become superscript note numbers,
 *  and the sources are listed underneath in plain words, each still a link into the graph. */
export default function AnswerText({ text, citations, nodes, struck, stale, selected, onPick, children }: {
  text: string;
  citations: string[];
  nodes: GNode[];
  struck: boolean;
  stale: Set<string>;
  selected: string | null;
  onPick: (id: string) => void;
  children?: React.ReactNode; // shown between the answer and its sources (e.g. the "no longer true" note)
}) {
  const parts = text.split(/(\[\d+\])/g).filter(Boolean);
  const body = parts.map((part, i) => {
    const m = part.match(/^\[(\d+)\]$/);
    const id = m ? citations[Number(m[1]) - 1] : undefined;
    if (!m) return <span key={i}>{part}</span>;
    if (!id) return null;
    return (
      <sup key={i} className="fn">
        <button onClick={() => onPick(id)} aria-label={`Source ${m[1]}: ${citationLabel(nodes.find((n) => n.id === id), id)}`}>{m[1]}</button>
      </sup>
    );
  });
  return (
    <>
      <p className="a">{struck ? <span className="struck">{body}</span> : body}</p>
      {children}
      {citations.length > 0 && (
        <ol className="notes" aria-label="Sources">
          {citations.map((id, i) => (
            <li key={id} className={stale.has(id) ? "stale" : ""}>
              <span className="n">{i + 1}</span>
              <button aria-pressed={selected === id} onClick={() => onPick(id)}
                      title={stale.has(id) ? "No longer current. Click to see it in the graph." : "Show it in the graph and open its card."}>
                {citationLabel(nodes.find((n) => n.id === id), id)} <span className="typed">{id}</span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
