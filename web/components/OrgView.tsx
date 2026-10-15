"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import Tip from "./Tip";

export default function OrgView() {
  const [areas, setAreas] = useState<any[]>([]);
  const [q, setQ] = useState("");
  const [people, setPeople] = useState<any[]>([]);
  const [w, setW] = useState<any>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [picked, setPicked] = useState(false);
  const [clusters, setClusters] = useState<any[]>([]);
  const [showHow, setShowHow] = useState(false);

  useEffect(() => {
    api.drift().then(setAreas).catch(() => setErr("Could not reach the API."));
    api.clusters().then(setClusters).catch(() => {});
  }, []);
  useEffect(() => {
    if (picked || q.trim().length < 2) { setPeople([]); return; }
    const t = setTimeout(() => api.people(q).then(setPeople).catch(() => {}), 200);
    return () => clearTimeout(t);
  }, [q, picked]);

  async function simulate(p: any) {
    setShowHow(false); setPicked(true); setPeople([]); setQ(p.name ?? p.github); setRunning(p.name ?? p.github); setW(null);
    try { setW(await api.whatif(p.id)); } finally { setRunning(null); }
  }

  const lost = new Set<string>(w?.orphaned_areas ?? []);
  const risk = new Set<string>((w?.at_risk_areas ?? []).map((a: any) => a.area));
  const counts = areas.reduce((m: any, a) => ({ ...m, [a.status]: (m[a.status] ?? 0) + 1 }), {});

  return (
    <main className="org">
      <div className="org-head">
        <div>
          <h2>Who really owns what</h2>
          <p>For each module, people listed as owners in the official experts index, against people who actually committed in the last twelve months.</p>
        </div>
        <div className="key">
          <span><span className="person listed">name</span> listed, no recent commits</span>
          <span><span className="person revealed">name</span> committing, not listed</span>
          <span><span className="person listed revealed">name</span> listed and committing</span>
        </div>
        <div className="whatif">
          <label htmlFor="who">What if</label>
          <input id="who" value={q} onChange={(e) => { setPicked(false); setQ(e.target.value); }} placeholder="a person left… (try Guido)" autoComplete="off" />
          {people.length > 0 && (
            <div className="whatif-results">
              {people.map((p) => <button key={p.id} onClick={() => simulate(p)}>{p.name ?? p.github} <span className="typed" style={{ color: "var(--ink-faint)" }}>{p.peps} PEPs</span></button>)}
            </div>
          )}
        </div>
      </div>

      {running && <p className="working">Copying the whole graph, removing {running} from the copy, re-running the algorithms…</p>}
      {w && (
        <div className="verdict">
          <h3>{w.plain.headline}</h3>
          <ul className="plain-list">{w.plain.bullets.map((b: string) => <li key={b}>{b}</li>)}</ul>
          <button className="linkish" aria-expanded={showHow} onClick={() => setShowHow(!showHow)}>
            {showHow ? "Hide how this was measured" : "Show how this was measured"}
          </button>
          {showHow && (
            <p className="how">
              Computed on a throwaway copy of the graph ({Math.round(w.fork_mb)} MB, {Math.round(w.ms / 100) / 10} s) with <span className="typed">GRAPH.COPY</span>; the live graph was not touched.
              {" "}Weakly connected components on the collaboration graph: {w.components_before} groups before, {w.components_after} after.
              {" "}Betweenness centrality: rank {w.bridge_rank} of {w.people_ranked} (score {w.bridge_score}).
              {" "}Modules counted as covered when someone is listed and not inactive, or made at least 3 commits in the last 12 months.
            </p>
          )}
        </div>
      )}
      {err && <p className="a-note">{err}</p>}
      <p className="trace" style={{ marginBottom: "0.8rem" }}>
        {counts.healthy ?? 0} healthy, {counts.drifting ?? 0} drifting, {counts.orphaned ?? 0} orphaned, out of {areas.length} modules with commit data.
      </p>
      <div className="tiles">
        {areas.map((a) => {
          const committing = new Set(a.revealed.filter((r: any) => r.commits >= 3).map((r: any) => r.who));
          const listed = new Set(a.declared.filter((d: string) => !a.inactive.includes(d)));
          const everyone = [...new Set([...listed, ...committing])].sort();
          return (
            <section key={a.area_id} className={`tile ${lost.has(a.area) ? "lost" : risk.has(a.area) ? "risk" : ""}`}>
              <h3>{a.area}</h3>
              <div className={`status ${lost.has(a.area) ? "orphaned" : a.status}`}>
                {lost.has(a.area) ? "would be orphaned" : risk.has(a.area) ? "would rest on one person" : a.status}
              </div>
              <p className="tile-plain">{a.plain}</p>
              <div className="people">
                {everyone.map((p: any) => (
                  <Tip key={p} text={listed.has(p) ? (committing.has(p) ? "Listed as an owner and committing in the last 12 months." : "Listed as an owner, but no commits in the last 12 months.") : "Committing regularly, but not listed as an owner."}>
                    <span tabIndex={0} className={`person ${listed.has(p) ? "listed" : ""} ${committing.has(p) ? "revealed" : ""} ${listed.has(p) && !committing.has(p) ? "quiet" : ""}`}>{p}</span>
                  </Tip>
                ))}
              </div>
            </section>
          );
        })}
      </div>
      {clusters.length > 0 && (
        <section style={{ marginTop: "2.2rem" }}>
          <h2 style={{ fontFamily: "var(--display)", fontWeight: 400, fontSize: "var(--step-2)", margin: "0 0 0.2rem" }}>Topics the proposals form</h2>
          <p className="trace" style={{ margin: "0 0 0.9rem", maxWidth: "70ch" }}>
            Communities found by label propagation over the citation graph, each named after its most influential proposal (PageRank).
          </p>
          <div className="tiles">
            {clusters.map((c) => (
              <section key={c.id} className="tile">
                <h3 style={{ fontFamily: "var(--display)", fontWeight: 400, fontSize: "var(--step-1)" }}>{c.label}</h3>
                <div className="status">{c.size} proposals{c.areas.length ? `, mostly about ${c.areas.slice(0, 2).join(" and ")}` : ""}</div>
                <div className="people">{c.top.slice(0, 6).map((p: any) => <span key={p.id} className="person" title={p.title}>PEP {p.number}</span>)}</div>
              </section>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
