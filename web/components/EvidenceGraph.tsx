"use client";

import { useEffect, useRef, useState } from "react";
import type { Core } from "cytoscape";
import { Fragment, nodeDetail, nodeTitle } from "@/lib/api";

export type Wave = { origin: string[]; stale: string[]; key: number } | null;

const HATCH =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    `<svg xmlns='http://www.w3.org/2000/svg' width='8' height='8'><path d='M-2,2 l4,-4 M0,8 l8,-8 M6,10 l4,-4' stroke='#7d8697' stroke-width='1' stroke-opacity='0.55'/></svg>`,
  );

function stylesheet(font: string, typed: string): any[] {
  return [
    { selector: "node", style: {
        label: "data(title)", "font-family": font, "font-size": 11, color: "#18233a",
        "text-valign": "bottom", "text-margin-y": 5, "text-wrap": "ellipsis", "text-max-width": 130,
        "background-color": "#f8f9fa", "border-width": 1.5, "border-color": "#18233a", width: 22, height: 22,
        "transition-property": "background-color, border-color, color, opacity", "transition-duration": 600 } },
    { selector: "node[label = 'PEP']", style: {
        shape: "rectangle", width: 52, height: 30, "text-valign": "center", "text-margin-y": 0, "font-family": typed,
        "font-size": 11, "font-weight": 700 } },
    { selector: "node[label = 'Person']", style: { shape: "ellipse", "background-color": "#dce6f0", "border-color": "#2f5d8c" } },
    { selector: "node[label = 'Decision']", style: { shape: "diamond", width: 20, height: 20, "border-color": "#2e7d5b", "background-color": "#dcebe3" } },
    { selector: "node[kind = 'supersede']", style: { "border-color": "#c2273d", "background-color": "#f6dde1" } },
    { selector: "node[label = 'Thread'], node[label = 'Post']", style: { shape: "round-rectangle", width: 18, height: 14, "border-color": "#7d8697" } },
    { selector: "node[label = 'PR']", style: { shape: "barrel", width: 20, height: 16, "border-color": "#4a5468" } },
    { selector: "node[label = 'Chunk']", style: { shape: "rectangle", width: 12, height: 16, "border-style": "dashed", "border-color": "#7d8697", "font-size": 9 } },
    { selector: "node[label = 'Area']", style: { shape: "hexagon", "background-color": "#dcebe3", "border-color": "#2e7d5b" } },
    { selector: "node[label = 'Event']", style: { shape: "star", "background-color": "#c2273d", "border-color": "#c2273d", width: 22, height: 22 } },
    { selector: "node[label = 'Answer']", style: { shape: "round-rectangle", width: 26, height: 18, "background-color": "#dcebe3", "border-color": "#2e7d5b", "border-style": "double", "border-width": 3 } },
    { selector: "node[label = 'Action']", style: { shape: "triangle", width: 22, height: 20, "background-color": "#f8f9fa", "border-color": "#18233a" } },
    { selector: "edge[type = 'DERIVED_FROM']", style: { "line-style": "dotted", "line-color": "#2e7d5b", "target-arrow-color": "#2e7d5b" } },
    { selector: "edge", style: {
        width: 1, "line-color": "#9aa3b2", "curve-style": "bezier", "target-arrow-shape": "triangle", "target-arrow-color": "#9aa3b2",
        "arrow-scale": 0.7, "transition-property": "line-color, width", "transition-duration": 500 } },
    { selector: "edge[type = 'SUPERSEDES']", style: { width: 2.2, "line-color": "#c2273d", "target-arrow-color": "#c2273d" } },
    { selector: "edge:selected, edge.labelled", style: {
        label: "data(type)", "font-family": font, "font-size": 9, color: "#4a5468", "text-rotation": "autorotate",
        "text-background-color": "#eef1f3", "text-background-opacity": 1 } },
    { selector: "node.cited", style: { "border-width": 3, "border-color": "#2f5d8c" } },
    { selector: "node.stale", style: {
        "background-color": "#c9cfd6", "background-image": HATCH, "background-repeat": "repeat", "background-fit": "none",
        "border-color": "#7d8697", "border-style": "dashed", color: "#7d8697" } },
    { selector: "edge.stale", style: { "line-color": "#c9cfd6", "target-arrow-color": "#c9cfd6", "line-style": "dashed" } },
    { selector: "node.path", style: { "border-color": "#c2273d", "border-width": 3.5 } },
    { selector: "edge.path", style: { "line-color": "#c2273d", "target-arrow-color": "#c2273d", width: 3, label: "data(type)",
        "font-size": 9, color: "#c2273d", "text-background-color": "#eef1f3", "text-background-opacity": 1 } },
    { selector: "node:selected", style: { "overlay-color": "#2f5d8c", "overlay-opacity": 0.12, "overlay-padding": 6 } },
  ];
}

export default function EvidenceGraph({
  fragment, cited, stale, wave, path, onSelect, fitSignal = 0,
}: {
  fragment: Fragment;
  cited: Set<string>;
  stale: Set<string>;
  wave: Wave;
  path: string[];
  onSelect: (id: string) => void;
  fitSignal?: number;
}) {
  const host = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const timers = useRef<number[]>([]);
  const [tip, setTip] = useState<{ x: number; y: number; title: string; detail: string; stale: boolean } | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const cytoscape = (await import("cytoscape")).default;
      const fcose = (await import("cytoscape-fcose")).default;
      try { cytoscape.use(fcose); } catch { /* already registered */ }
      if (cancelled || !host.current) return;
      const css = getComputedStyle(document.documentElement);
      const font = `${css.getPropertyValue("--font-text").trim() || "Georgia"}, Georgia, serif`;
      const typed = `${css.getPropertyValue("--font-typed").trim() || "Courier New"}, monospace`;
      const cy = cytoscape({ container: host.current, style: stylesheet(font, typed), wheelSensitivity: 0.25, minZoom: 0.2, maxZoom: 3 });
      cy.on("tap", "node", (e) => onSelect(e.target.id()));
      cy.on("mouseover", "node", (e) => {
        const n = e.target, pos = n.renderedPosition();
        setTip({ x: pos.x, y: pos.y, title: n.data("title"), detail: n.data("detail"), stale: n.hasClass("stale") });
      });
      cy.on("mouseout", "node", () => setTip(null));
      cy.on("pan zoom tap", () => setTip(null));
      cy.on("mouseover", "edge", (e) => e.target.addClass("labelled"));
      cy.on("mouseout", "edge", (e) => e.target.removeClass("labelled"));
      cyRef.current = cy;
      const ro = new ResizeObserver(() => { cy.resize(); });
      ro.observe(host.current);
      (cy as any)._ro = ro;
    })();
    return () => { cancelled = true; (cyRef.current as any)?._ro?.disconnect(); cyRef.current?.destroy(); cyRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // add new elements, then re-layout (existing nodes keep their places)
  useEffect(() => {
    const cy = cyRef.current;
    const t = window.setTimeout(() => {
      const c = cyRef.current;
      if (!c) return;
      const ids = new Set(fragment.nodes.map((n) => n.id));
      c.elements().filter((el) => el.isNode() && !ids.has(el.id())).remove();
      const added: any[] = [];
      for (const n of fragment.nodes) {
        const data = { id: n.id, label: n.label, title: nodeTitle(n), detail: nodeDetail(n), kind: n.props?.kind ?? "" };
        const el = c.getElementById(n.id);
        if (el.nonempty()) el.data(data);
        else added.push({ group: "nodes", data });
      }
      for (const e of fragment.edges) {
        const id = `${e.src}|${e.type}|${e.dst}`;
        if (ids.has(e.src) && ids.has(e.dst) && c.getElementById(id).empty())
          added.push({ group: "edges", data: { id, source: e.src, target: e.dst, type: e.type } });
      }
      if (added.length) {
        c.add(added);
        c.layout({ name: "fcose", animate: true, animationDuration: 650, randomize: c.nodes().length === added.filter((a) => a.group === "nodes").length,
                   nodeRepulsion: 9000, idealEdgeLength: 80, padding: 40, nodeDimensionsIncludeLabels: true } as any).run();
      }
    }, cy ? 0 : 120);
    return () => window.clearTimeout(t);
  }, [fragment]);

  useEffect(() => {
    const c = cyRef.current;
    if (!c) return;
    c.nodes().forEach((n) => { n.toggleClass("cited", cited.has(n.id())); });
  }, [cited, fragment]);

  // stale without animation (e.g. after reload)
  useEffect(() => {
    const c = cyRef.current;
    if (!c || wave) return;
    c.nodes().forEach((n) => { n.toggleClass("stale", stale.has(n.id())); });
    c.edges().forEach((e) => { e.toggleClass("stale", stale.has(e.source().id()) && stale.has(e.target().id())); });
  }, [stale, fragment, wave]);

  // the bleach wave: stale-ness spreads outward from the changed PEP.
  // Runs a beat later so nodes added in the same update (e.g. citing PEPs) exist.
  useEffect(() => {
    if (!wave) return;
    timers.current.forEach(clearTimeout);
    const start = window.setTimeout(() => {
      const c = cyRef.current;
      if (!c) return;
      const staleSet = new Set(wave.stale);
      const roots = c.nodes().filter((n) => wave.origin.includes(n.id()));
      const dist = new Map<string, number>();
      if (roots.nonempty()) {
        c.elements().bfs({ roots, directed: false, visit: (v, _e, _u, _i, depth) => { dist.set(v.id(), depth); } });
      }
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      c.nodes().forEach((n) => {
        if (!staleSet.has(n.id())) return;
        const d = dist.get(n.id()) ?? 4;
        timers.current.push(window.setTimeout(() => {
          n.addClass("stale");
          n.connectedEdges().forEach((e) => { if (staleSet.has(e.source().id()) && staleSet.has(e.target().id())) e.addClass("stale"); });
        }, reduce ? 0 : 200 + d * 280));
      });
    }, 120);
    timers.current.push(start);
    return () => timers.current.forEach(clearTimeout);
  }, [wave]);

  // re-fit on request (Fit button, entering/leaving focus mode)
  useEffect(() => {
    const c = cyRef.current;
    if (!c || !fitSignal) return;
    const t = window.setTimeout(() => { c.resize(); c.animate({ fit: { eles: c.elements(), padding: 40 } }, { duration: 300 }); }, 280);
    return () => window.clearTimeout(t);
  }, [fitSignal]);

  // highlight a blocking chain
  useEffect(() => {
    const c = cyRef.current;
    if (!c) return;
    c.elements().removeClass("path");
    path.forEach((id, i) => {
      c.getElementById(id).addClass("path");
      const next = path[i + 1];
      if (next) c.edges().filter((e) => (e.source().id() === id && e.target().id() === next) || (e.source().id() === next && e.target().id() === id)).addClass("path");
    });
  }, [path, fragment]);

  return (
    <>
      <div ref={host} className="cy" role="img" aria-label="Evidence graph" />
      {tip && (
        <div className="node-tip" style={{ left: tip.x + 16, top: tip.y + 12 }}>
          <strong>{tip.title}</strong>
          {tip.detail}
          {tip.stale && <div className="stale-why">No longer current: the truth it rests on has changed.</div>}
        </div>
      )}
    </>
  );
}
