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
  const [interests, setInterests] = useState<any[]>([]);
  const [why, setWhy] = useState<Record<string, any[]>>({});
  const [proof, setProof] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const pendingRef = useRef<Pending | null>(null);
  pendingRef.current = pending;

  async function load() {
    setBeliefs(await api.beliefs().catch(() => []));
    const ints = await api.interests(uid).catch(() => []);
    setInterests(ints);
    const w: Record<string, any[]> = {};
    for (const i of ints) w[i.area] = (await api.why(uid, i.area)).nodes.filter((n) => n.label === "Episode");
    setWhy(w);
  }
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

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
        {beliefs.length === 0 && <p className="working">No beliefs yet. Ask something first.</p>}
        {beliefs.map((b) => (
          <div key={b.id} className={`belief ${b.status}`}>
            <Tip text={STATUS_HELP[b.status] ?? b.status}><span className={`pill ${b.status}`} tabIndex={0}>{b.status}</span></Tip>
            <span><span className="txt">{b.text}</span>{b.stale_because && <span className="a-note" style={{ display: "block" }}>No longer current: {b.stale_because}</span>}</span>
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
    </main>
  );
}
