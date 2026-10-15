"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const KINDS: Record<string, string> = {
  PEP: "Proposal", Person: "Person", Decision: "Decision", Thread: "Discussion thread", Post: "Forum post",
  PR: "Pull request", Chunk: "Passage of a proposal", Area: "Part of Python", Event: "Change event",
};

export default function IndexCard({ id, stale, onOpen, version }: { id: string | null; stale: Set<string>; onOpen: (id: string) => void; version: number }) {
  const [card, setCard] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setErr(null);
    api.node(id).then(setCard).catch(() => { setCard(null); setErr("This item lives in an agent's memory, not the company archive."); });
  }, [id, version]);

  if (!id) return <p className="inspector-empty">Select anything in the graph to open its card.</p>;
  if (err) return <p className="inspector-empty">{err}</p>;
  if (!card) return <p className="inspector-empty">Opening the card…</p>;

  const p = card.props;
  const decisions = card.neighbours.filter((n: any) => n.label === "Decision");
  const status = card.label === "PEP" ? (p.status as string) : null;
  const stampKind = card.label === "Decision" ? p.kind : status === "Superseded" ? "supersede" : status === "Rejected" ? "reject" : status ? "accept" : null;
  const stampText = card.label === "Decision" ? p.kind : status;
  const title = card.label === "PEP" ? `PEP ${p.number}` : p.name ?? p.title ?? p.heading ?? card.id;
  const isStale = stale.has(card.id) || p.stale;

  return (
    <article className={`card ${isStale ? "stale" : ""}`} key={`${card.id}-${status}`}>
      {stampKind && <span className={`stamp ${stampKind}`}>{String(stampText).toUpperCase()}</span>}
      <div className="kind">{KINDS[card.label] ?? card.label}</div>
      <h3>{title}</h3>
      {card.label === "PEP" && <p className="title">{p.title}</p>}
      {isStale && p.stale_because && <p className="a-note">No longer current: {p.stale_because}</p>}
      <dl>
        <dt>Id</dt><dd className="typed">{card.id}</dd>
        {p.created && <><dt>Created</dt><dd>{p.created}</dd></>}
        {p.at && <><dt>Date</dt><dd>{p.at}</dd></>}
        {p.github && <><dt>GitHub</dt><dd className="typed">{p.github}</dd></>}
        {p.python_version && <><dt>Python</dt><dd>{p.python_version}</dd></>}
        {p.source_url && <><dt>Source</dt><dd><a href={p.source_url} target="_blank" rel="noreferrer">Open original</a></dd></>}
      </dl>
      {p.text && <div className="excerpt">{p.text}</div>}
      {decisions.length > 0 && card.label !== "Decision" && (
        <>
          <h4>Decisions</h4>
          <ul>{decisions.map((d: any) => <li key={d.id}><button onClick={() => onOpen(d.id)}>{d.name}</button></li>)}</ul>
        </>
      )}
      <h4>Connected</h4>
      <ul>
        {card.neighbours.filter((n: any) => n.label !== "Chunk").slice(0, 14).map((n: any) => (
          <li key={`${n.rel}-${n.direction}-${n.id}`}>
            <span style={{ color: "var(--ink-faint)" }}>{n.direction === "out" ? n.rel.toLowerCase().replace("_", " ") : `${n.rel.toLowerCase().replace("_", " ")} by`} </span>
            <button onClick={() => onOpen(n.id)}>{n.name ?? n.id}</button>
          </li>
        ))}
      </ul>
      {card.beliefs.length > 0 && (
        <>
          <h4>The Historian believes, because of this</h4>
          <ul>{card.beliefs.map((b: any) => <li key={b.id} style={b.status === "stale" ? { textDecoration: "line-through", color: "var(--ink-faint)" } : {}}>{b.text}</li>)}</ul>
        </>
      )}
    </article>
  );
}
