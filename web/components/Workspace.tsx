"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { api, AskResult, capFanout, EventRow, expandMore, Fragment, GNode, mergeFragments, sharesTopic, StewardReport } from "@/lib/api";
import TimeRail from "./TimeRail";
import AnswerText from "./AnswerText";
import IndexCard from "./IndexCard";
import GraphKey from "./GraphKey";
import Tip from "./Tip";
import OrgView from "./OrgView";
import MemoryView from "./MemoryView";
import type { Replay, Wave } from "./EvidenceGraph";

const EvidenceGraph = dynamic(() => import("./EvidenceGraph"), { ssr: false });
const UID = "visitor";
const EMPTY: Fragment = { nodes: [], edges: [] };

function stepLabel(t: { name: string; input: any }): string {
  const i = t.input ?? {};
  switch (t.name) {
    case "search": return `Searched the archive for “${i.query}”`;
    case "decision_path": return `Followed how PEP ${i.pep} was decided`;
    case "pep_timeline": return `Read the timeline of PEP ${i.pep}`;
    case "who_knows": return `Looked up who knows ${i.topic}`;
    case "related_peps": return `Found proposals related to PEP ${i.pep}`;
    case "connection": return `Traced how ${i.a} connects to ${i.b}`;
    default: return t.name.replace(/_/g, " ");
  }
}
const n = (k: number, word: string, plural = `${word}s`) => `${k} ${k === 1 ? word : plural}`;

type ActionKind = "add_to_onboarding_faq" | "ask_owner_review";
type ActionItem = { id: string; kind: ActionKind; status: "pending" | "done" | "blocked"; reason?: string; effect?: string };
const ACTIONS: Record<ActionKind, { queue: string; what: string; node: string }> = {
  add_to_onboarding_faq: { queue: "Queue: publish to the onboarding FAQ", what: "Publish this answer to the onboarding FAQ", node: "Publish to FAQ" },
  ask_owner_review: { queue: "Queue: ask the owners to confirm", what: "Ask the owners of this part of Python to confirm it", node: "Ask owners" },
};
type Entry = { kind: "qa"; q: string; asOf: string | null; result?: AskResult; error?: string; actions: ActionItem[]; stale?: { note: string; at: string };
  frag?: Fragment; prev?: Fragment } // this answer's own graph; the graph it replaced (new topic)
  | { kind: "steward"; text: string; details?: string };

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
  const [beforeApply, setBeforeApply] = useState<Fragment | null>(null);
  const [showLeft, setShowLeft] = useState(true);
  const [showRight, setShowRight] = useState(true);
  const [fitSignal, setFitSignal] = useState(0);
  const [previewNote, setPreviewNote] = useState<string | null>(null);
  const [replay, setReplay] = useState<Replay>(null);
  const [beforePreview, setBeforePreview] = useState<Fragment>(EMPTY);
  const focus = !showLeft && !showRight;
  const setPanels = (l: boolean, r: boolean) => { setShowLeft(l); setShowRight(r); setFitSignal((n) => n + 1); };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && focus) setPanels(true, true); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus]);
  const [graphs, setGraphs] = useState<{ graph: string; mb: number }[]>([]);
  const [online, setOnline] = useState(true);
  const [lastMs, setLastMs] = useState<number | null>(null);

  const refresh = useCallback(() => {
    api.events().then(setEvents).catch(() => setOnline(false));
    api.graphs().then((g) => { setGraphs(g); setOnline(true); }).catch(() => setOnline(false));
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  const ticks = useMemo(() => fragment.nodes.filter((n) => n.label === "Decision" && n.props?.at).map((n) => {
    const pep = n.id.split(":")[2];
    return { id: n.id, at: n.props.at, label: `PEP ${pep} ${n.props.kind === "accept" ? "accepted" : n.props.kind === "reject" ? "rejected" : n.props.kind}` };
  }), [fragment]);
  // the years the evidence on the graph covers, drawn as a band on the time ruler
  const span = useMemo(() => {
    const days = fragment.nodes.flatMap((n) => [n.props?.at, n.props?.created])
      .map((d) => (typeof d === "string" ? d.slice(0, 10) : ""))
      .filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d)).sort();
    return days.length ? { from: days[0], to: days[days.length - 1] } : null;
  }, [fragment]);
  const [hintsOff, setHintsOff] = useState(false);
  useEffect(() => { try { setHintsOff(localStorage.getItem("lineage.hints") === "off"); } catch { /* private mode */ } }, []);
  const hideHints = () => { setHintsOff(true); try { localStorage.setItem("lineage.hints", "off"); } catch { /* ignore */ } };
  const hint = useMemo(() => {
    if (hintsOff) return null;
    const qas = entries.filter((e): e is Entry & { kind: "qa" } => e.kind === "qa" && !!e.result && !e.result.abstained);
    const applied = events.some((e) => e.applied);
    const queued = qas.some((e) => e.actions.length > 0);
    const blocked = qas.some((e) => e.actions.some((a) => a.status === "blocked" && a.reason?.startsWith("blocked:")));
    if (!qas.length) return null;
    if (!queued && !applied) return "Next: queue this answer for the onboarding FAQ and run it, then open the red pin on the timeline to replay a real change.";
    if (queued && !applied) return "Now open the red pin on the timeline and apply the change. Watch what goes stale, and check the FAQ in Memory.";
    if (applied && queued && !blocked) return "Press Run on the queued action. The Steward will refuse it and show you the chain of evidence that changed.";
    return "Try a follow-up question, drag the timeline dial back to 2020 and ask again, or open Organisation to see what happens if someone leaves.";
  }, [entries, events, hintsOff]);

  function patchEntry(i: number, fn: (e: Entry & { kind: "qa" }) => Entry) {
    setEntries((xs) => xs.map((e, j) => (j === i && e.kind === "qa" ? fn(e) : e)));
  }

  async function ask(q: string, when?: string | null) {
    if (!q.trim() || busy) return;
    const at = when === undefined ? asOf : when; // a "no answer" button can move the dial
    if (when !== undefined) setAsOf(when);
    const i = entries.length;
    setEntries((xs) => [...xs, { kind: "qa", q, asOf: at, actions: [] }]);
    setQuestion("");
    setBusy(true);
    try {
      const context: Record<string, string>[] = entries.slice(-4).map((e): Record<string, string> =>
        e.kind === "steward" ? { note: `Steward: ${e.text}` } : { q: e.q, a: e.result?.text ?? "" });
      const r = await api.ask(q, UID, at, context, selected);
      patchEntry(i, (e) => ({ ...e, result: r }));
      setLastMs(r.tool_trace.reduce((s, t) => s + t.ms, 0));
      if (!r.abstained && r.answer_id) {
        const answer: GNode = { id: r.answer_id, label: "Answer", props: { text: r.text } };
        const memory: Fragment = {
          nodes: [answer],
          edges: r.citations.filter((c) => r.evidence.nodes.some((n) => n.id === c)).map((c) => ({ src: r.answer_id!, dst: c, type: "DERIVED_FROM" })),
        };
        const own = capFanout(mergeFragments(r.evidence, memory), new Set([...r.citations, r.answer_id]));
        // a follow-up on the same proposal or module builds on the graph; a new topic starts a fresh one
        // a what-if preview on the canvas is not part of the conversation: answers build on the graph behind it
        const base = previewNote ? beforePreview : fragment;
        if (previewNote) { setPreviewNote(null); setBeforePreview(EMPTY); }
        const sameTopic = base.nodes.length === 0 || sharesTopic(base, r.evidence);
        const before = base;
        setFragment(sameTopic ? mergeFragments(base, own) : own);
        setCited((s) => new Set(sameTopic ? [...s, ...r.citations] : r.citations));
        if (!sameTopic) setPath([]);
        patchEntry(i, (e) => ({ ...e, frag: own, prev: sameTopic ? undefined : before }));
        setSelected(r.citations.find((c) => c.startsWith("pep:")) ?? r.citations[0] ?? null);
      }
    } catch (err: any) {
      patchEntry(i, (e) => ({ ...e, error: err.message ?? "The archive did not answer." }));
    } finally {
      setBusy(false);
      refresh();
    }
  }

  async function queueAction(i: number, answerId: string, q: string, kind: ActionKind) {
    const { id } = await api.propose(kind, { question: q }, [answerId]);
    patchEntry(i, (e) => ({ ...e, actions: [...e.actions, { id, kind, status: "pending" }] }));
    setFragment((f) => mergeFragments(f, { nodes: [{ id, label: "Action", props: { kind: ACTIONS[kind].node } }], edges: [{ src: id, dst: answerId, type: "DERIVED_FROM" }] }));
  }

  async function runAction(i: number, id: string) {
    try {
      const r = await api.execute(id);
      const effect = r.effect?.kind === "faq" ? "Published. It will be withdrawn automatically if its evidence changes; see Memory."
        : r.effect?.kind === "task" ? "Done: a review task is open on the shared board for the owners." : "Done.";
      patchEntry(i, (e) => ({ ...e, actions: e.actions.map((a) => (a.id === id ? { ...a, status: "done", effect } : a)) }));
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

  /** Replay how an answer was found: each tool step lights up what it reached, then the answer and its sources. */
  function replayAnswer(e: Entry & { kind: "qa" }) {
    const r = e.result!;
    const onCanvas = fragment.nodes.some((n) => n.id === r.answer_id);
    const graph = onCanvas && !previewNote ? fragment : e.frag ?? fragment;
    if (!onCanvas || previewNote) { setPreviewNote(null); setBeforePreview(EMPTY); setFragment(graph); setCited(new Set(r.citations)); }
    const shown = new Set(graph.nodes.map((n) => n.id));
    const steps = r.tool_trace.map((t) => {
      const ids = (t.found ?? []).filter((id: string) => shown.has(id));
      const what = stepLabel(t);
      return { label: t.error ? `${what} (the query failed)` : `${what}: ${ids.length ? `${ids.length} of the things on this graph` : "nothing that stayed on this graph"}.`, ids };
    });
    const finish = [r.answer_id!, ...r.citations].filter((id) => shown.has(id));
    setReplay({ key: Date.now(), steps, finish, finishLabel: `Answered, citing ${r.citations.length} source${r.citations.length === 1 ? "" : "s"}.` });
  }

  /** Draw a what-if result from the Organisation view on the Ask graph, clearly marked as a preview. */
  function showPreview(frag: Fragment, title: string, focus: string | null) {
    if (!previewNote) setBeforePreview(fragment);
    setPreviewNote(title);
    setFragment(frag);
    setCited(new Set()); setPath([]);
    setSelected(focus);
    setView("ask");
  }

  function closePreview() {
    setFragment(beforePreview);
    setPreviewNote(null); setBeforePreview(EMPTY); setSelected(null);
  }

  async function apply(slug: string) {
    setView("ask"); // the ripple is drawn on the Ask graph, wherever the pin was clicked
    setApplying(true);
    try {
      setBeforeApply(fragment);
      const rep: StewardReport = await api.apply(slug);
      const h = rep.agents.historian ?? { beliefs: [], answers: [], actions_blocked: [] };
      const staleIds = [...rep.ripple.hard, ...rep.ripple.soft, ...rep.ripple.chunks, ...h.answers, ...h.actions_blocked];
      const ev = events.find((x) => x.slug === slug);
      const proposal = (id: string) => `PEP ${id.split(":")[1]}`;
      const note = ev && ev.kind === "supersede" && ev.by?.length
        ? `${proposal(ev.pep)} was replaced by ${ev.by.map((b) => `PEP ${b}`).join(" and ")}.`
        : rep.summary;
      const staleNote = { note, at: ev?.at ?? "" };
      // the replaced proposal's card shows its new status (struck number, "superseded")
      const replaced: Fragment = ev?.kind === "supersede" ? { nodes: [{ id: ev.pep, label: "PEP", props: { status: "Superseded" } }], edges: [] } : EMPTY;
      setFragment((f) => mergeFragments(mergeFragments(f, rep.paths), replaced));
      setStale((s) => new Set([...s, ...staleIds]));
      setWave({ origin: rep.changed, stale: staleIds, key: Date.now() });
      setEntries((xs) => [
        ...xs.map((e) => e.kind === "qa" ? {
          ...e,
          stale: e.result?.answer_id && h.answers.includes(e.result.answer_id) ? staleNote : e.stale,
          actions: e.actions.map((a) => (h.actions_blocked.includes(a.id) ? { ...a, status: "blocked" as const, reason: "Blocked by the Steward: it rests on knowledge that just changed. Run it to see why." } : a)),
        } : e),
        { kind: "steward", text: rep.plain ?? rep.summary, details: `${rep.summary} I re-checked everything built on ${rep.changed.join(", ")}: ${n(h.answers.length, "answer")} and ${n(h.beliefs.length, "belief")} no longer hold, ${n(h.actions_blocked.length, "queued action")} on hold, and ${n(rep.fixtasks.length, "proposal")} that cite it now have a review task.${rep.faq_withdrawn ? ` ${n(rep.faq_withdrawn, "published FAQ entry", "published FAQ entries")} withdrawn.` : ""}` },
      ]);
      setSelected(rep.changed[0]);
      setCardVersion((v) => v + 1);
    } finally {
      setApplying(false);
      refresh();
    }
  }

  async function undo(slug: string) {
    setView("ask");
    setApplying(true);
    try {
      await api.rewind(slug);
      setStale(new Set()); setWave(null); setPath([]);
      if (beforeApply) setFragment(beforeApply);
      setEntries((xs) => [
        ...xs.map((e) => e.kind === "qa" ? { ...e, stale: undefined, actions: e.actions.map((a) => (a.status === "blocked" ? { ...a, status: "pending" as const, reason: undefined } : a)) } : e),
        { kind: "steward", text: "Change undone. The proposal, the agent's beliefs and answers, the queued action and the review tasks are back to how they were." },
      ]);
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
      <TimeRail events={events} ticks={ticks} span={span} asOf={asOf} onAsOf={setAsOf} onApply={apply} onUndo={undo} onReset={reset} applying={applying} />

      {view === "ask" && (
        <main className={`workspace ${showLeft ? "" : "no-left"} ${showRight ? "" : "no-right"}`}>
          <section className="column conversation" aria-label="Conversation" hidden={!showLeft}>
            <div className="thread">
              {entries.length === 0 && (
                <div className="intro">
                  <h2>Ask the archive of the Python project.</h2>
                  <p>Every answer is built from the graph: proposals, decisions, the people who made them, and the threads where they were argued. Each claim links to its evidence.</p>
                  <div className="suggest">{SUGGESTIONS.map((s) => <button key={s} onClick={() => ask(s)}>{s}</button>)}</div>
                </div>
              )}
              {entries.map((e, i) => e.kind === "steward" ? (
                <div key={i} className="a-note" style={{ borderLeft: "2px solid var(--stamp)", paddingLeft: "0.7rem", fontSize: "var(--step-0)" }}>
                  <strong>Steward.</strong> {e.text}
                  {e.details && (
                    <details className="steward-details"><summary>Details</summary>{e.details}</details>
                  )}
                </div>
              ) : (
                <div key={i}>
                  <p className="q">{e.q}</p>
                  {e.asOf && <div className="trace">as of {e.asOf}</div>}
                  {!e.result && !e.error && <p className="a working">Consulting the archive…</p>}
                  {e.error && <p className="a-note">{e.error}</p>}
                  {e.result && (
                    <>
                      <AnswerText text={e.result.text} citations={e.result.citations} nodes={e.result.evidence.nodes}
                                  struck={!!e.stale} stale={stale} selected={selected} onPick={setSelected}>
                      {e.stale && (
                        <p className="margin-note">
                          No longer true{e.stale.at && <> as of <span className="typed">{e.stale.at}</span></>}. {e.stale.note}{" "}
                          <button className="linkish stamp-link" disabled={busy} onClick={() => ask(e.q, null)}>Ask again with today&rsquo;s facts</button>
                        </p>
                      )}
                      </AnswerText>
                      {e.result.miss && e.result.miss.actions.length > 0 && (
                        <div className="miss-actions">
                          {e.result.miss.actions.map((a) => (
                            <button key={a.label} className="btn quiet" disabled={busy}
                                    onClick={() => (a.question ? ask(a.question, a.as_of) : ask(e.q, a.as_of ?? null))}>{a.label}</button>
                          ))}
                        </div>
                      )}
                      {e.result.tool_trace.length > 0 && (
                        <div className="trace">
                          Walked the graph with {e.result.tool_trace.map((t) => `${t.name.replace("_", " ")} (${Math.round(t.ms)} ms)`).join(", ")}.
                          {e.result.answer_id && <> <button className="linkish replay-link" onClick={() => replayAnswer(e)}>Replay how this was found</button></>}
                        </div>
                      )}
                      {e.frag && (
                        <div className="trace topic-note">
                          {e.prev && <>New topic, so the graph started afresh. <button className="linkish" onClick={() => { setFragment((f) => mergeFragments(e.prev!, f)); patchEntry(i, (x) => ({ ...x, prev: undefined })); }}>Bring back the earlier graph</button> </>}
                          {i < entries.length - 1 && <button className="linkish" onClick={() => { setFragment(e.frag!); setCited(new Set(e.result!.citations)); setPath([]); }}>Show only this answer&rsquo;s graph</button>}
                        </div>
                      )}
                      {e.result.answer_id && (
                        <div className="actions">
                          {e.actions.map((a) => (
                            <div key={a.id} className={`action ${a.status}`}>
                              <span className="what">{ACTIONS[a.kind].what}</span>
                              {a.status !== "done" && <button className="btn" onClick={() => runAction(i, a.id)}>Run</button>}
                              {a.status === "done" && a.effect && <span className="why done-note">{a.effect}</span>}
                              {a.status === "blocked" && a.reason && <span className="why">{a.reason}</span>}
                            </div>
                          ))}
                          {!e.stale && (Object.keys(ACTIONS) as ActionKind[]).filter((k) => !e.actions.some((a) => a.kind === k)).map((k) => (
                            <button key={k} className="btn quiet" onClick={() => queueAction(i, e.result!.answer_id!, e.q, k)}>{ACTIONS[k].queue}</button>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              ))}
              {hint && <p className="hint"><span>{hint}</span><button onClick={hideHints}>Hide tips</button></p>}
            </div>
            <div className="asker">
              <form onSubmit={(ev) => { ev.preventDefault(); ask(question); }}>
                <textarea aria-label="Your question" placeholder={entries.some((e) => e.kind === "qa" && e.result && !e.result.abstained)
                            ? "Ask a follow-up — e.g. why was it decided this way?"
                            : "Ask about a PEP, a Python module or a person — e.g. Who decided PEP 649?"} value={question} rows={2}
                          onChange={(ev) => setQuestion(ev.target.value)}
                          onKeyDown={(ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); ask(question); } }} />
                <button className="btn" disabled={busy || !question.trim()}>{busy ? "Asking…" : "Ask"}</button>
              </form>
              {asOf && <div className="asof">Answers will ignore anything after {asOf}.</div>}
            </div>
          </section>

          <section className="canvas" aria-label="Evidence">
            {previewNote && (
              <div className="preview-banner" role="status">
                <span><strong>Preview.</strong> {previewNote} Nothing has been changed.</span>
                <button className="linkish" onClick={closePreview}>Back to your graph</button>
              </div>
            )}
            <div className="canvas-tools" role="toolbar" aria-label="Graph view">
              <Tip side="bottom" text={showLeft ? "Hide the conversation to give the graph more room." : "Show the conversation again."}>
                <button onClick={() => setPanels(!showLeft, showRight)} aria-pressed={!showLeft}>{showLeft ? "Hide conversation" : "Show conversation"}</button>
              </Tip>
              <Tip side="bottom" text={showRight ? "Hide the card on the right." : "Show the card again."}>
                <button onClick={() => setPanels(showLeft, !showRight)} aria-pressed={!showRight}>{showRight ? "Hide card" : "Show card"}</button>
              </Tip>
              <Tip side="bottom" text={focus ? "Leave focus mode (Esc)." : "Graph only: hide both panels. Press Esc to come back."}>
                <button onClick={() => (focus ? setPanels(true, true) : setPanels(false, false))} aria-pressed={focus}>{focus ? "Exit focus" : "Focus"}</button>
              </Tip>
              <Tip side="bottom" text="Re-centre and zoom so everything fits.">
                <button onClick={() => setFitSignal((n) => n + 1)}>Fit</button>
              </Tip>
            </div>
            <EvidenceGraph fragment={fragment} cited={cited} stale={stale} wave={wave} path={path} onSelect={(id) => (id?.startsWith("more:") ? setFragment((f) => expandMore(f, id)) : setSelected(id))} fitSignal={fitSignal} replay={replay} onReplayEnd={() => setReplay(null)} />
            {fragment.nodes.length > 0 && <GraphKey />}
            {fragment.nodes.length === 0 && <div className="canvas-empty">The evidence behind each answer is drawn here.</div>}
            {fragment.nodes.length > 0 && (
              <div className="legend"><span><i className="lg-cited" />cited in an answer</span><span><i className="lg-stale" />no longer current</span></div>
            )}
          </section>

          <aside className="column inspector" aria-label="Card" hidden={!showRight}>
            <IndexCard id={selected} stale={stale} onOpen={setSelected} version={cardVersion} />
          </aside>
        </main>
      )}
      {view === "org" && <OrgView onShowGraph={showPreview} asOf={asOf} />}
      {view === "memory" && <MemoryView uid={UID} />}

      <footer className="strip">
        <span><span className={`dot ${online ? "" : "off"}`} />{online ? "Historian and Steward online" : "API offline — start it with uvicorn"}</span>
        <Tip text="The company archive, each agent's memory, each visitor's memory and the shared task board are separate graphs. FalkorDB itself enforces who may write which.">
          <span tabIndex={0}>{graphs.length} graphs in FalkorDB, {graphs.reduce((s, g) => s + g.mb, 0).toFixed(0)} MB</span>
        </Tip>
        {lastMs !== null && <span>Last answer walked the graph in {Math.round(lastMs)} ms</span>}
        <span style={{ marginLeft: "auto" }}>Data: the public Python project (PEPs, discuss.python.org, CPython)</span>
      </footer>
    </div>
  );
}
