"use client";

import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import type { Fragment } from "@/lib/api";
import Combo from "./Combo";
import Tip from "./Tip";

type Mode = "person" | "group" | "proposal";
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
const SHOW = 6;

function personMeta(p: any) {
  const bits = [];
  if (p.handle && p.handle !== p.name) bits.push(p.handle);
  if (p.peps) bits.push(plural(p.peps, "proposal"));
  else if (p.commits) bits.push(plural(p.commits, "commit"));
  return bits.join(", ");
}

export default function WhatIf({ onResult, onShowGraph }: {
  onResult: (w: any | null) => void;
  onShowGraph: (f: Fragment, title: string, focus: string | null) => void;
}) {
  const [mode, setMode] = useState<Mode>("person");
  const [group, setGroup] = useState<any[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);
  const [preview, setPreview] = useState<any>(null);
  const [showHow, setShowHow] = useState(false);

  const searchPeople = useCallback((q: string) => api.people(q), []);
  const searchPeps = useCallback((q: string) => api.peps(q), []);

  async function runPeople(people: any[]) {
    setBusy(`Copying the whole graph, removing ${people.map((p) => p.name).join(", ")} from the copy, re-running the algorithms…`);
    setResult(null); setPreview(null); setShowHow(false); onResult(null);
    try { const w = await api.whatif(people.map((p) => p.id)); setResult(w); onResult(w); } finally { setBusy(null); }
  }

  function showPeople(focus: string | null) {
    onShowGraph(result.fragment, `If ${result.person.name} left: names in red leave, modules in red lose their owner, names in green could step in.`, focus);
  }

  function showReversal(focus: string | null) {
    onShowGraph(preview.fragment, `If PEP ${preview.pep.number} were reversed, the hatched proposals and answers would need review.`, focus);
  }

  async function runPreview(pep: any) {
    setBusy(`Tracing everything that rests on PEP ${pep.number}…`);
    setResult(null); setPreview(null); onResult(null);
    try { setPreview(await api.preview(pep.number)); } finally { setBusy(null); }
  }

  return (
    <section className="whatif-panel" aria-label="What if">
      <div className="whatif-controls">
      <div className="whatif-modes" role="tablist">
        <span>What if</span>
        {([["person", "a person left"], ["group", "a group left"], ["proposal", "a proposal were reversed"]] as const).map(([m, label]) => (
          <button key={m} role="tab" aria-selected={mode === m} onClick={() => { setMode(m); setGroup([]); }}>{label}</button>
        ))}
      </div>

      {mode === "person" && (
        <Combo label="Person" placeholder="Start typing a name, e.g. Guido" search={searchPeople} keyOf={(p: any) => p.id}
               render={(p: any) => <><span>{p.name}</span> <span className="meta">{personMeta(p)}</span></>}
               onPick={(p: any) => runPeople([p])} />
      )}
      {mode === "group" && (
        <div className="group-pick">
          <Combo label="Add a person" placeholder="Add people one by one…" search={searchPeople} keyOf={(p: any) => p.id}
                 render={(p: any) => <><span>{p.name}</span> <span className="meta">{personMeta(p)}</span></>}
                 onPick={(p: any) => setGroup((g) => (g.some((x) => x.id === p.id) ? g : [...g, p]))} />
          <div className="chosen">
            {group.map((p) => (
              <span key={p.id} className="chosen-chip">{p.name}
                <button aria-label={`Remove ${p.name}`} onClick={() => setGroup((g) => g.filter((x) => x.id !== p.id))}>×</button></span>
            ))}
            {group.length < 2 && <span className="meta">Add at least two people.</span>}
            <button className="btn" disabled={group.length < 2 || !!busy} onClick={() => runPeople(group)}>See what happens</button>
          </div>
        </div>
      )}
      {mode === "proposal" && (
        <Combo label="Proposal" placeholder="PEP number or title, e.g. 484 or type hints" search={searchPeps} keyOf={(p: any) => p.id}
               render={(p: any) => <><span className="typed">PEP {p.number}</span> <span>{p.title}</span> <span className="meta">{p.status}</span></>}
               onPick={(p: any) => runPreview(p)} />
      )}

      </div>

      <div className="whatif-result" aria-live="polite">
      {!result && !preview && !busy && (
        <div className="whatif-empty">
          <h3>Ask what would break</h3>
          <p>Pick a person, a group of people, or a proposal. Lineage copies the whole graph, applies your &ldquo;what if&rdquo; to the copy, and tells you in plain words what would be left without an owner and who could step in.</p>
          <p>The real graph is never touched.</p>
        </div>
      )}
      {busy && <div className="whatif-empty"><p className="working">{busy}</p></div>}

      {result && (
        <div className="verdict">
          <h3>{result.plain.headline}</h3>
          <ul className="plain-list">{result.plain.bullets.map((b: string) => <li key={b}>{b}</li>)}</ul>
          {result.areas?.length > 0 && (
            <ul className="affected" aria-label="Parts of Python affected">
              {result.areas.slice(0, SHOW).map((a: any) => (
                <li key={a.id}>
                  <Tip text={a.state === "orphaned"
                    ? `Nobody else is listed for ${a.name} or has committed to it in the last 12 months. Click to see it on the graph.`
                    : `Only one person would still be looking after ${a.name}. Click to see it on the graph.`}>
                    <button className="row-link" onClick={() => showPeople(a.id)}><span className="typed">{a.name}</span></button>
                  </Tip>
                  <span className={`state ${a.state}`}>{a.state === "orphaned" ? "no one left" : "one person left"}</span>
                  {a.successors.length > 0 && (
                    <span className="meta">
                      Could step in:{" "}
                      {a.successors.map((x: any, i: number) => (
                        <span key={x.id}>
                          {i > 0 && ", "}
                          <Tip text={x.basis === "commits"
                            ? `${plural(x.commits, "commit")} to ${a.name} in the last 12 months. Click to see them on the graph.`
                            : `Works most closely with ${result.person.name}; nobody else commits to ${a.name}. Click to see them on the graph.`}>
                            <button className="linkish" onClick={() => showPeople(x.id)}>{x.name}</button>
                          </Tip>
                        </span>
                      ))}
                    </span>
                  )}
                </li>
              ))}
              {result.areas.length > SHOW && <li className="meta">and {result.areas.length - SHOW} more on the graph</li>}
            </ul>
          )}
          <div className="whatif-actions">
            <button className="btn" onClick={() => showPeople(null)}>Show on the graph</button>
          </div>
          <button className="linkish" aria-expanded={showHow} onClick={() => setShowHow(!showHow)}>
            {showHow ? "Hide how this was measured" : "Show how this was measured"}
          </button>
          {showHow && (
            <p className="how">
              Computed on a throwaway copy of the graph ({Math.round(result.fork_mb)} MB, {Math.round(result.ms / 100) / 10} s) with <span className="typed">GRAPH.COPY</span>; the live graph was not touched.
              {" "}Weakly connected components on the collaboration graph: {result.components_before} groups before, {result.components_after} after.
              {result.bridge_rank ? ` Betweenness centrality: best rank ${result.bridge_rank} of ${result.people_ranked}.` : ""}
              {" "}A module counts as covered when someone is listed and not inactive, or made at least 3 commits in the last 12 months.
            </p>
          )}
        </div>
      )}

      {preview && (
        <div className="verdict">
          <h3>If PEP {preview.pep.number} were reversed</h3>
          <p style={{ margin: "0 0 0.5rem" }}>{preview.plain}</p>
          {preview.dependents.length > 0 && (
            <ul className="affected" aria-label="Proposals that would need review">
              {preview.dependents.slice(0, SHOW).map((d: any) => (
                <li key={d.id}>
                  <Tip text={`${d.title}. ${d.status ?? "Status unknown"}${d.created ? `, written ${d.created}` : ""}. It ${d.relation} PEP ${preview.pep.number}, so it would need review. Click to see it on the graph.`}>
                    <button className="row-link" onClick={() => showReversal(d.id)}>
                      <span className="typed">PEP {d.number}</span> <span className="ttl">{d.title}</span>
                    </button>
                  </Tip>
                  <span className="meta">{[d.status, d.created?.slice(0, 4)].filter(Boolean).join(", ")}. {d.relation === "requires" ? "Requires" : "Cites"} PEP {preview.pep.number}.</span>
                </li>
              ))}
              {preview.dependents.length > SHOW && <li className="meta">and {preview.dependents.length - SHOW} more on the graph</li>}
            </ul>
          )}
          <div className="whatif-actions">
            <button className="btn" onClick={() => showReversal(preview.pep.id)}>Show on the graph</button>
          </div>
          <p className="how">A dry run of the Steward: read-only queries walk the citation graph and every agent&rsquo;s DERIVED_FROM chains. To really apply a change, use a red pin on the timeline.</p>
        </div>
      )}
      </div>
    </section>
  );
}
