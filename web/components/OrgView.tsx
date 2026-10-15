"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Fragment } from "@/lib/api";
import Tip from "./Tip";
import Introduce from "./Introduce";
import WhatIf from "./WhatIf";

export default function OrgView({ onShowGraph }: { onShowGraph: (f: Fragment, title: string, focus: string | null) => void }) {
  const [areas, setAreas] = useState<any[]>([]);
  const [w, setW] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [clusters, setClusters] = useState<any[]>([]);
  const [health, setHealth] = useState<Record<string, any>>({});

  useEffect(() => {
    api.drift().then(setAreas).catch(() => setErr("Could not reach the API."));
    api.clusters().then(setClusters).catch(() => {});
    api.health().then((rows) => setHealth(Object.fromEntries(rows.map((r) => [r.area_id, r])))).catch(() => {});
  }, []);
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
      </div>

      <WhatIf onResult={setW} onShowGraph={onShowGraph} />
      <Introduce areas={areas} onShowGraph={onShowGraph} />
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
              {health[a.area_id] && (
                <Tip text="Truck factor: the fewest people who together hold half of this module's recent knowledge. Recent commits count more: each commit's weight halves every six months, computed inside FalkorDB by a JavaScript UDF.">
                  <p className="tile-plain truck" tabIndex={0}>
                    {health[a.area_id].truck_factor === 1
                      ? <>Truck factor 1: <strong>{health[a.area_id].owners[0].name}</strong> holds {Math.round(health[a.area_id].owners[0].share * 100)}% of the recent work.</>
                      : health[a.area_id].truck_factor <= 3
                        ? <>Truck factor {health[a.area_id].truck_factor}: {health[a.area_id].owners.slice(0, health[a.area_id].truck_factor).map((o: any) => o.name).join(", ").replace(/, ([^,]*)$/, " and $1")} hold half of the recent work.</>
                        : <>Truck factor {health[a.area_id].truck_factor}: no small group holds most of the recent work.</>}
                  </p>
                </Tip>
              )}
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
