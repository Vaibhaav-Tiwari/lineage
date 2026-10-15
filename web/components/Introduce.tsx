"use client";

import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import type { Fragment } from "@/lib/api";
import Combo from "./Combo";
import Tip from "./Tip";

/** "Who can introduce me?": a weighted shortest path (FalkorDB algo.SPpaths) through the strongest working
 *  ties, from a person to whoever now holds the most recent knowledge of a module. */
export default function Introduce({ areas, onShowGraph, asOf = null }: {
  areas: { area_id: string; area: string }[];
  asOf?: string | null;
  onShowGraph: (f: Fragment, title: string, focus: string | null) => void;
}) {
  const [who, setWho] = useState<any>(null);
  const [area, setArea] = useState<string>("");
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const searchPeople = useCallback((q: string) => api.people(q), []);

  async function run(person: any, areaId: string) {
    if (!person || !areaId) return;
    setBusy(true); setRes(null);
    try { setRes(await api.introduce(person.id, areaId, asOf)); } finally { setBusy(false); }
  }
  const areaName = areas.find((a) => a.area_id === area)?.area ?? "";

  return (
    <section className="introduce" aria-label="Find an introduction">
      <h3>Find an introduction</h3>
      <p className="sub">Who could connect a person to whoever now knows a module best, through the people they have worked most closely with.</p>
      <div className="intro-controls">
        <Combo label="From" placeholder="A person, e.g. Guido" search={searchPeople} keyOf={(p: any) => p.id}
               render={(p: any) => <span>{p.name}</span>} onPick={(p: any) => { setWho(p); run(p, area); }} />
        <label className="intro-area">to the people behind
          <select value={area} onChange={(e) => { setArea(e.target.value); run(who, e.target.value); }}>
            <option value="">a module…</option>
            {areas.map((a) => <option key={a.area_id} value={a.area_id}>{a.area}</option>)}
          </select>
        </label>
      </div>
      {busy && <p className="working">Walking the collaboration graph…</p>}
      {res && !busy && (
        res.path.length > 0 ? (
          <div className="intro-result">
            <p>
              {res.path.map((p: any, i: number) => (
                <span key={p.id}>{i > 0 && <span className="arrow"> → </span>}<strong>{p.name}</strong></span>
              ))}
            </p>
            <p className="meta">
              {res.path.length === 2 ? `${who?.name} has worked directly with ${res.to.name}` : `${res.path.length - 2} introduction${res.path.length === 3 ? "" : "s"} away`},
              {" "}who holds {Math.round(res.to.share * 100)}% of the recent work on {areaName}{asOf ? ` as of ${asOf}` : ""}.{" "}
              <Tip text="Weighted shortest path (algo.SPpaths) over two-way collaboration ties; a tie's cost is 1 / how often they worked together, so the route prefers strong working relationships over a short chain of weak ones.">
                <span className="how-link" tabIndex={0}>How is this found?</span>
              </Tip>
            </p>
            <button className="btn quiet" onClick={() => onShowGraph(res.fragment, `How ${who?.name} could reach the people behind ${areaName}.`, res.to.id)}>Show on the graph</button>
          </div>
        ) : (
          <p className="a-note">{res.to ? `No chain of working relationships connects ${who?.name} to ${res.to.name}.` : `Nobody has committed to ${areaName} recently.`}</p>
        )
      )}
    </section>
  );
}
