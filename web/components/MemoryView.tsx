"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function MemoryView({ uid }: { uid: string }) {
  const [beliefs, setBeliefs] = useState<any[]>([]);
  const [interests, setInterests] = useState<any[]>([]);
  const [why, setWhy] = useState<Record<string, any[]>>({});
  const [proof, setProof] = useState<string | null>(null);

  async function load() {
    setBeliefs(await api.beliefs().catch(() => []));
    const ints = await api.interests(uid).catch(() => []);
    setInterests(ints);
    const w: Record<string, any[]> = {};
    for (const i of ints) w[i.area] = (await api.why(uid, i.area)).nodes.filter((n) => n.label === "Episode");
    setWhy(w);
  }
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  async function forget(area: string, eid: string) {
    await api.forget(uid, eid);
    await load();
    const left = (await api.why(uid, area)).nodes.filter((n) => n.id === eid).length;
    setProof(`Forgotten. Paths from “${area.replace("area:", "")}” back to that question: ${left}.`);
  }

  return (
    <main className="memory">
      <section>
        <h2>What the Historian believes</h2>
        <p className="sub">Each belief rests on evidence in the archive. When that evidence changes, the belief is marked stale instead of quietly lingering.</p>
        {beliefs.length === 0 && <p className="working">No beliefs yet. Ask something first.</p>}
        {beliefs.map((b) => (
          <div key={b.id} className={`belief ${b.status}`}>
            <span className={`pill ${b.status}`}>{b.status}</span>
            <span><span className="txt">{b.text}</span>{b.stale_because && <span className="a-note" style={{ display: "block" }}>No longer current: {b.stale_because}</span>}</span>
          </div>
        ))}
      </section>
      <section>
        <h2>What it remembers about you</h2>
        <p className="sub">Interests it inferred from your questions, with the questions that suggested them. Forget any of them.</p>
        {proof && <p className="proof">{proof}</p>}
        {interests.length === 0 && <p className="working">Nothing remembered about you.</p>}
        {interests.map((i) => (
          <div key={i.area} className="interest">
            <div className="row"><strong className="typed">{i.area.replace("area:", "")}</strong><span className="trace">weight {i.weight}</span></div>
            {(why[i.area] ?? []).map((ep) => (
              <div key={ep.id} className="episode">
                <span>“{ep.props.question}”</span>
                <button className="btn quiet" onClick={() => forget(i.area, ep.id)}>Forget</button>
              </div>
            ))}
          </div>
        ))}
      </section>
    </main>
  );
}
