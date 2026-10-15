"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { api, AskResult, EventRow, Fragment, GNode, mergeFragments, StewardReport } from "@/lib/api";
import TimeRail from "./TimeRail";
import IndexCard from "./IndexCard";
import OrgView from "./OrgView";
import MemoryView from "./MemoryView";
import type { Wave } from "./EvidenceGraph";

const EvidenceGraph = dynamic(() => import("./EvidenceGraph"), { ssr: false });
const UID = "visitor";
const EMPTY: Fragment = { nodes: [], edges: [] };
const n = (k: number, word: string) => `${k} ${word}${k === 1 ? "" : "s"}`;

type ActionItem = { id: string; status: "pending" | "done" | "blocked"; reason?: string };
type Entry = { kind: "qa"; q: string; asOf: string | null; result?: AskResult; error?: string; actions: ActionItem[]; stale?: string }
  | { kind: "steward"; text: string };

const SUGGESTIONS = [
  "How does Python handle annotations under PEP 563, and who decided it?",
  "Who decided to accept PEP 649, and where was it announced?",
  "Who should I ask about asyncio today?",
  "Why was PEP 572, the walrus operator, accepted?",
];

export default function Workspace() {
  const [view, setView] = useState<"ask" | "org" | "memory">("ask");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [fragment, setFragment] = useState<Fragment>(EMPTY);
  const [cited, setCited] = useState<Set<string>>(new Set());
  const [stale, setStale] = useState<Set<string>>(new Set());
  const [wave, setWave] = useState<Wave>(null);
  const [path, setPath] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [cardVersion, setCardVersion] = useState(0);
  const [graphs, setGraphs] = useState<{ graph: string; mb: number }[]>([]);
  const [online, setOnline] = useState(true);
  const [lastMs, setLastMs] = useState<number | null>(null);

  const refresh = useCallback(() => {
    api.events().then(setEvents).catch(() => setOnline(false));
    api.graphs().then((g) => { setGraphs(g); setOnline(true); }).catch(() => setOnline(false));
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  const ticks = useMemo(() => fragment.nodes.filter((n) => n.label === "Decision" && n.props?.at).map((n) => ({ id: n.id, at: n.props.at })), [fragment]);

  function patchEntry(i: number, fn: (e: Entry & { kind: "qa" }) => Entry) {
    setEntries((xs) => xs.map((e, j) => (j === i && e.kind === "qa" ? fn(e) : e)));
  }

  async function ask(q: string) {
    if (!q.trim() || busy) return;
    const i = entries.length;
    setEntries((xs) => [...xs, { kind: "qa", q, asOf, actions: [] }]);
    setQuestion("");
    setBusy(true);
    try {
      const r = await api.ask(q, UID, asOf);
      patchEntry(i, (e) => ({ ...e, result: r }));
      setLastMs(r.tool_trace.reduce((s, t) => s + t.ms, 0));
      if (!r.abstained && r.answer_id) {
        const answer: GNode = { id: r.answer_id, label: "Answer", props: { text: r.text } };
        const memory: Fragment = {
          nodes: [answer],
          edges: r.citations.filter((c) => r.evidence.nodes.some((n) => n.id === c)).map((c) => ({ src: r.answer_id!, dst: c, type: "DERIVED_FROM" })),
        };
        setFragment((f) => mergeFragments(mergeFragments(f, r.evidence), memory));
        setCited((s) => new Set([...s, ...r.citations]));
        setSelected(r.citations.find((c) => c.startsWith("pep:")) ?? r.citations[0] ?? null);
      }
    } catch (err: any) {
      patchEntry(i, (e) => ({ ...e, error: err.message ?? "The archive did not answer." }));
    } finally {
      setBusy(false);
      refresh();
    }
  }

  async function queueAction(i: number, answerId: string, q: string) {
    const { id } = await api.propose("add_to_onboarding_faq", { question: q }, [answerId]);
    patchEntry(i, (e) => ({ ...e, actions: [...e.actions, { id, status: "pending" }] }));
    setFragment((f) => mergeFragments(f, { nodes: [{ id, label: "Action", props: { kind: "Add to onboarding FAQ" } }], edges: [{ src: id, dst: answerId, type: "DERIVED_FROM" }] }));
  }

  async function runAction(i: number, id: string) {
    try {
      await api.execute(id);
      patchEntry(i, (e) => ({ ...e, actions: e.actions.map((a) => (a.id === id ? { ...a, status: "done" } : a)) }));
      setPath([]);
    } catch (err: any) {
      const detail = err.body?.detail ?? {};
      const chain: string[] = (detail.path ?? []).map((x: string) => x.replace(/^ev:/, ""));
      patchEntry(i, (e) => ({ ...e, actions: e.actions.map((a) => (a.id === id ? { ...a, status: "blocked", reason: detail.reason } : a)) }));
      const shown = chain.filter((x) => fragment.nodes.some((n) => n.id === x) || x.startsWith("action:"));
      setPath(shown);
      const culprit = chain[chain.length - 1];
      if (culprit) setSelected(culprit);
    }
  }

  async function apply(slug: string) {
    setApplying(true);
    try {
      const rep: StewardReport = await api.apply(slug);
      const h = rep.agents.historian ?? { beliefs: [], answers: [], actions_blocked: [] };
      const staleIds = [...rep.ripple.hard, ...rep.ripple.soft, ...rep.ripple.chunks, ...h.answers, ...h.actions_blocked];
      setFragment((f) => mergeFragments(f, rep.paths));
      setStale((s) => new Set([...s, ...staleIds]));
      setWave({ origin: rep.changed, stale: staleIds, key: Date.now() });
      setEntries((xs) => [
        ...xs.map((e) => e.kind === "qa" ? {
          ...e,
          stale: e.result?.answer_id && h.answers.includes(e.result.answer_id) ? rep.summary : e.stale,
          actions: e.actions.map((a) => (h.actions_blocked.includes(a.id) ? { ...a, status: "blocked" as const, reason: "Blocked by the Steward: it rests on knowledge that just changed. Run it to see why." } : a)),
        } : e),
        { kind: "steward", text: `${rep.summary} I re-checked everything built on ${rep.changed.join(", ")}: ${n(h.answers.length, "answer")} and ${n(h.beliefs.length, "belief")} no longer hold, ${n(h.actions_blocked.length, "queued action")} on hold, and ${n(rep.fixtasks.length, "proposal")} that cite it now have a review task.` },
      ]);
      setSelected(rep.changed[0]);
      setCardVersion((v) => v + 1);
    } finally {
      setApplying(false);
      refresh();
    }
  }

  async function reset() {
    await api.reset();
    setEntries([]); setFragment(EMPTY); setCited(new Set()); setStale(new Set()); setWave(null); setPath([]); setSelected(null);
    refresh();
  }

  return (
    <div className="frame">
      <header className="masthead">
        <h1>Lineage</h1>
        <span className="motto">The company brain that remembers why, and un-learns when the truth changes.</span>
        <nav className="views" aria-label="Views">
          {(["ask", "org", "memory"] as const).map((v) => (
            <button key={v} aria-pressed={view === v} onClick={() => setView(v)}>{v === "ask" ? "Ask" : v === "org" ? "Organisation" : "Memory"}</button>
          ))}
        </nav>
      </header>
      <TimeRail events={events} ticks={ticks} asOf={asOf} onAsOf={setAsOf} onApply={apply} onReset={reset} applying={applying} />

      {view === "ask" && (
        <main className="workspace">
          <section className="column conversation" aria-label="Conversation">
            <div className="thread">
              {entries.length === 0 && (
                <div className="intro">
                  <h2>Ask the archive of the Python project.</h2>
                  <p>Every answer is built from the graph: proposals, decisions, the people who made them, and the threads where they were argued. Each claim links to its evidence.</p>
                  <div className="suggest">{SUGGESTIONS.map((s) => <button key={s} onClick={() => ask(s)}>{s}</button>)}</div>
                </div>
              )}
              {entries.map((e, i) => e.kind === "steward" ? (
                <p key={i} className="a-note" style={{ borderLeft: "2px solid var(--stamp)", paddingLeft: "0.7rem", fontSize: "var(--step-0)" }}>
                  <strong>Steward.</strong> {e.text}
                </p>
              ) : (
                <div key={i}>
                  <p className="q">{e.q}</p>
                  {e.asOf && <div className="trace">as of {e.asOf}</div>}
                  {!e.result && !e.error && <p className="a working">Consulting the archive…</p>}
                  {e.error && <p className="a-note">{e.error}</p>}
                  {e.result && (
                    <>
                      <p className={`a ${e.stale ? "stale" : ""}`}>{e.result.text}</p>
                      {e.stale && <p className="a-note">No longer current: {e.stale}</p>}
                      <div className="chips">
                        {e.result.citations.map((c) => (
                          <button key={c} className={`chip ${stale.has(c) ? "stale" : ""}`} aria-pressed={selected === c} onClick={() => setSelected(c)}>{c}</button>
                        ))}
                      </div>
                      {e.result.tool_trace.length > 0 && (
                        <div className="trace">Walked the graph with {e.result.tool_trace.map((t) => `${t.name.replace("_", " ")} (${Math.round(t.ms)} ms)`).join(", ")}.</div>
                      )}
                      {e.result.answer_id && (
                        <div className="actions">
                          {e.actions.map((a) => (
                            <div key={a.id} className={`action ${a.status}`}>
                              <span className="what">Add this answer to the onboarding FAQ</span>
                              {a.status === "done" && <span className="typed" style={{ color: "var(--pine)" }}>Added</span>}
                              {a.status !== "done" && <button className="btn" onClick={() => runAction(i, a.id)}>Run</button>}
                              {a.status === "blocked" && a.reason && <span className="why">{a.reason}</span>}
                            </div>
                          ))}
                          {e.actions.length === 0 && !e.stale && (
                            <button className="btn quiet" onClick={() => queueAction(i, e.result!.answer_id!, e.q)}>Queue: add to onboarding FAQ</button>
                          )}
                        </div>
                      )}
                    </>
                  )}
                </div>
              ))}
            </div>
            <div className="asker">
              <form onSubmit={(ev) => { ev.preventDefault(); ask(question); }}>
                <textarea aria-label="Your question" placeholder="Why was it decided this way? Who knows this part?" value={question} rows={2}
                          onChange={(ev) => setQuestion(ev.target.value)}
                          onKeyDown={(ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); ask(question); } }} />
                <button className="btn" disabled={busy || !question.trim()}>{busy ? "Asking…" : "Ask"}</button>
              </form>
              {asOf && <div className="asof">Answers will ignore anything after {asOf}.</div>}
            </div>
          </section>

          <section className="canvas" aria-label="Evidence">
            <EvidenceGraph fragment={fragment} cited={cited} stale={stale} wave={wave} path={path} onSelect={setSelected} />
            {fragment.nodes.length === 0 && <div className="canvas-empty">The evidence behind each answer is drawn here.</div>}
            {fragment.nodes.length > 0 && (
              <div className="legend"><span><i className="lg-cited" />cited in an answer</span><span><i className="lg-stale" />no longer current</span></div>
            )}
          </section>

          <aside className="column inspector" aria-label="Card">
            <IndexCard id={selected} stale={stale} onOpen={setSelected} version={cardVersion} />
          </aside>
        </main>
      )}
      {view === "org" && <OrgView />}
      {view === "memory" && <MemoryView uid={UID} />}

      <footer className="strip">
        <span><span className={`dot ${online ? "" : "off"}`} />{online ? "Historian and Steward online" : "API offline — start it with uvicorn"}</span>
        <span>{graphs.length} graphs in FalkorDB, {graphs.reduce((s, g) => s + g.mb, 0).toFixed(0)} MB</span>
        {lastMs !== null && <span>Last answer walked the graph in {Math.round(lastMs)} ms</span>}
        <span style={{ marginLeft: "auto" }}>Data: the public Python project (PEPs, discuss.python.org, CPython)</span>
      </footer>
    </div>
  );
}
