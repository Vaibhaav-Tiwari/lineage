"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import Tip from "./Tip";

const UNDO_SECONDS = 8;
const STATUS_HELP: Record<string, string> = {
  committed: "Concluded with enough confidence to act on.",
  tentative: "Low confidence. Actions that depend on it are held back.",
  stale: "The evidence it rests on has changed, so it no longer holds.",
};

type Pending = { area: string; eid: string; question: string; left: number };

export default function MemoryView({ uid }: { uid: string }) {
  const [beliefs, setBeliefs] = useState<any[]>([]);
  const [faq, setFaq] = useState<any[]>([]);
  const [moments, setMoments] = useState<string[]>([]); // when Lineage learned that something changed
  const [knownAt, setKnownAt] = useState<string>("");
  const [checks, setChecks] = useState<any[] | null>(null);
  const [interests, setInterests] = useState<any[]>([]);
  const [why, setWhy] = useState<Record<string, any[]>>({});
  const [proof, setProof] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const pendingRef = useRef<Pending | null>(null);
  pendingRef.current = pending;

  async function load() {
    const now = await api.beliefs().catch(() => []);
    setMoments([...new Set<string>(now.map((b: any) => b.stale_at).filter(Boolean))].sort().reverse());
    setBeliefs(knownAt ? await api.beliefs(knownAt).catch(() => []) : now);
    setFaq(await api.faq().catch(() => []));
    api.security().then(setChecks).catch(() => setChecks([]));
    const ints = await api.interests(uid).catch(() => []);
    setInterests(ints);
    const w: Record<string, any[]> = {};
    for (const i of ints) w[i.area] = (await api.why(uid, i.area)).nodes.filter((n) => n.label === "Episode");
    setWhy(w);
  }
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [knownAt]);
  // one second before the moment it learned of a change: what it believed just before
  const before = (iso: string) => new Date(new Date(iso).getTime() - 1000).toISOString().replace(".000Z", "+00:00");
  const fmt = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

  async function commit(p: Pending) {
    await api.forget(uid, p.eid);
    setPending(null);
    await load();
    const left = (await api.why(uid, p.area)).nodes.filter((n) => n.id === p.eid).length;
    setProof(`Forgotten for good. Paths from “${p.area.replace("area:", "")}” back to that question: ${left}.`);
  }

  // countdown; delete only when it reaches zero
  useEffect(() => {
    if (!pending) return;
    if (pending.left <= 0) { commit(pending); return; }
    const t = setTimeout(() => setPending((p) => (p ? { ...p, left: p.left - 1 } : p)), 1000);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending]);

  // leaving the page during the undo window still forgets — never silently dropped
  useEffect(() => () => { if (pendingRef.current) api.forget(uid, pendingRef.current.eid).catch(() => {}); }, [uid]);

  function forget(area: string, ep: any) {
    if (pending) commit(pending);
    setProof(null);
    setPending({ area, eid: ep.id, question: ep.props.question, left: UNDO_SECONDS });
  }

  const hidden = pending?.eid;
  return (
    <main className="memory">
      <section>
        <h2>What the Historian believes</h2>
        <p className="sub">Each belief rests on evidence in the archive. When that evidence changes, the belief is marked stale instead of quietly lingering.</p>
        {moments.length > 0 && (
          <label className="known-at">
            <Tip text="Record time: Lineage keeps when it learned each belief no longer held, so you can see what the agent believed at any earlier moment, separately from what was true then (the time dial).">
              <span tabIndex={0}>What it believed</span>
            </Tip>
            <select value={knownAt} onChange={(e) => setKnownAt(e.target.value)}>
              <option value="">now</option>
              {moments.map((m) => <option key={m} value={before(m)}>just before it learned of a change ({fmt(m)})</option>)}
            </select>
          </label>
        )}
        {beliefs.length === 0 && <p className="working">No beliefs yet. Ask something first.</p>}
        {beliefs.map((b) => (
          <div key={b.id} className={`belief ${b.status}`}>
            <Tip text={STATUS_HELP[b.status] ?? b.status}><span className={`pill ${b.status}`} tabIndex={0}>{b.status}</span></Tip>
            <span><span className="txt">{b.text}</span>{b.stale_because && <span className="a-note" style={{ display: "block" }}>No longer current: {b.stale_because}</span>}</span>
          </div>
        ))}
      </section>
      <section>
        <h2>Onboarding FAQ</h2>
        <p className="sub">Answers the agents published after the action gate let them through. When an answer&rsquo;s evidence changes, the Steward withdraws the entry and says why.</p>
        {faq.length === 0 && <p className="working">Nothing published yet. Queue &ldquo;publish to the onboarding FAQ&rdquo; on an answer and run it.</p>}
        {faq.map((f) => (
          <div key={f.id} className={`faq ${f.status}`}>
            <div className="row">
              <strong>{f.question}</strong>
              <span className={`pill ${f.status === "live" ? "committed" : "stale"}`}>{f.status === "live" ? "live" : "withdrawn"}</span>
            </div>
            <p className={f.status === "live" ? "" : "struck-static"}>{f.answer.replace(/\[\d+\]/g, "")}</p>
            {f.status !== "live" && <p className="margin-note">Withdrawn: {f.withdrawn_reason}</p>}
          </div>
        ))}
      </section>
      <section>
        <h2>What it remembers about you</h2>
        <p className="sub">Interests it inferred from your questions, with the questions that suggested them. Forget any of them.</p>
        {pending && (
          <div className="undo-bar" role="status">
            <span>Forgetting “{pending.question.slice(0, 60)}{pending.question.length > 60 ? "…" : ""}”</span>
            <button onClick={() => setPending(null)}>Undo</button>
            <span className="count">{pending.left}s</span>
          </div>
        )}
        {proof && <p className="proof">{proof}</p>}
        {interests.length === 0 && <p className="working">Nothing remembered about you.</p>}
        {interests.map((i) => {
          const eps = (why[i.area] ?? []).filter((ep) => ep.id !== hidden);
          if (!eps.length) return null;
          return (
            <div key={i.area} className="interest">
              <div className="row"><strong className="typed">{i.area.replace("area:", "")}</strong>
                <Tip text="How many of your questions pointed to this topic."><span className="trace" tabIndex={0}>weight {eps.length}</span></Tip></div>
              {eps.map((ep) => (
                <div key={ep.id} className="episode">
                  <span>“{ep.props.question}”</span>
                  <button className="btn quiet" onClick={() => forget(i.area, ep)}>Forget</button>
                </div>
              ))}
            </div>
          );
        })}
      </section>
      <section className="security">
        <h2>How the agents are kept apart</h2>
        <p className="sub">Each agent logs in to FalkorDB as its own user, and the database itself enforces what it may touch. These checks run live every time you open this page: harmless reads are really run as the agent; anything that would write or destroy is asked of the database&rsquo;s permission engine (<span className="typed">ACL DRYRUN</span>), so nothing is changed to prove it.</p>
        {checks === null && <p className="working">Running the checks…</p>}
        {checks && checks.length > 0 && (
          <>
            <p className={checks.every((c) => c.ok) ? "proof" : "a-note"}>
              {checks.every((c) => c.ok) ? `All ${checks.length} boundaries hold.` : `${checks.filter((c) => !c.ok).length} of ${checks.length} boundaries do not hold.`}
            </p>
            <div className="sec-table" role="table" aria-label="Permission checks">
              {checks.map((c) => (
                <div key={c.agent + c.check} role="row" className={`sec-row ${c.ok ? "ok" : "bad"}`}>
                  <span role="cell" className="who">{c.agent === "historian" ? "Historian" : "Steward"}</span>
                  <span role="cell">tries to {c.check}</span>
                  <Tip text={`${c.command}: ${c.detail}. Checked by: ${c.how}.`}>
                    <span role="cell" tabIndex={0} className={`verdict-pill ${c.allowed ? "allowed" : "refused"}`}>{c.allowed ? "allowed" : "refused"}</span>
                  </Tip>
                  <span role="cell" className="mark" aria-label={c.ok ? "as intended" : "not as intended"}>{c.ok ? "as intended" : "NOT as intended"}</span>
                </div>
              ))}
            </div>
            <p className="how">Known limit: the database&rsquo;s rules cannot express the direction of a copy, so the Steward&rsquo;s right to copy the company graph into a what-if fork would also let it copy a fork back over a missing company graph name.</p>
          </>
        )}
      </section>
    </main>
  );
}
