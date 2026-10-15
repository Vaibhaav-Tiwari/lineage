"use client";

import { useEffect, useRef, useState } from "react";
import type { Core } from "cytoscape";
import { Fragment, GNode, nodeDetail, nodeTitle } from "@/lib/api";
import { answerSlip, CARD, decisionStamp, Fonts, proposalCard, SLIP, STAMP } from "@/lib/cards";

export type Wave = { origin: string[]; stale: string[]; key: number } | null;
/** "Replay how this answer was found": each tool step lights up what it reached, then the answer and its sources. */
export type Replay = { key: number; steps: { label: string; ids: string[] }[]; finish: string[]; finishLabel: string } | null;

const HATCH =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    `<svg xmlns='http://www.w3.org/2000/svg' width='8' height='8'><path d='M-2,2 l4,-4 M0,8 l8,-8 M6,10 l4,-4' stroke='#7d8697' stroke-width='1' stroke-opacity='0.55'/></svg>`,
  );

// drawn artwork is 3x resolution: always size it to the node, never to its natural pixels
const FILL = { "background-fit": "none", "background-width": "100%", "background-height": "100%", "background-clip": "none" };

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
    { selector: "node[label = 'More']", style: { shape: "round-rectangle", width: 30, height: 16, "background-color": "#f8f9fa", "border-style": "dashed", "border-color": "#7d8697", "font-style": "italic" } },
    { selector: "node[label = 'Action']", style: { shape: "triangle", width: 22, height: 20, "background-color": "#f8f9fa", "border-color": "#18233a" } },
    { selector: "edge[type = 'DERIVED_FROM']", style: { "line-style": "dotted", "line-color": "#2e7d5b", "target-arrow-color": "#2e7d5b" } },
    { selector: "edge", style: {
        width: 1, "line-color": "#9aa3b2", "curve-style": "bezier", "target-arrow-shape": "triangle", "target-arrow-color": "#9aa3b2",
        "arrow-scale": 0.7, "transition-property": "line-color, width, opacity", "transition-duration": 500 } },
    { selector: "edge[type = 'MORE']", style: { "line-style": "dashed", "target-arrow-shape": "none" } },
    { selector: "edge[type = 'SUPERSEDES']", style: {
        width: 2.2, "line-color": "#c2273d", "target-arrow-color": "#c2273d", label: "replaces", "font-family": font, "font-style": "italic",
        "font-size": 10, color: "#c2273d", "text-rotation": "autorotate", "text-background-color": "#eef1f3", "text-background-opacity": 1,
        "text-background-padding": "1px" } },
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
    // ---- archive vocabulary: cards, names, stamps, slips ----
    { selector: "node[label = 'PEP']", style: {
        shape: "rectangle", width: CARD.w, height: CARD.h, label: "", "background-image": "data(art)", ...FILL,
        "background-color": "#f8f9fa", "border-width": 1.2, "border-color": "#18233a", "border-style": "solid" } },
    { selector: "node[label = 'PEP'].stale", style: { "background-image": "data(artStale)", "border-style": "dashed", "border-color": "#7d8697" } },
    { selector: "node[label = 'PEP'].cited", style: { "border-width": 2.4, "border-color": "#2f5d8c" } },
    { selector: "node[label = 'Person']", style: {
        width: 9, height: 9, "background-color": "#f8f9fa", "background-image": "none", "border-width": 1.5, "border-color": "#2f5d8c", "border-style": "solid",
        "text-halign": "right", "text-valign": "center", "text-margin-x": 5, "text-margin-y": 0, "font-size": 13, "text-max-width": 160 } },
    { selector: "node[label = 'Person'].cited", style: { "border-width": 2.5 } },
    { selector: "node[label = 'Person'].stale", style: { opacity: 0.5 } },
    { selector: "node[label = 'Decision'], node[label = 'Answer']", style: {
        shape: "rectangle", label: "", "background-image": "data(art)", ...FILL, "background-opacity": 0,
        "border-width": 0, "background-image-opacity": 1 } },
    { selector: "node[label = 'Decision']", style: { width: STAMP.w, height: STAMP.h } },
    { selector: "node[label = 'Answer']", style: { width: SLIP.w, height: SLIP.h } },
    { selector: "node[label = 'Decision'].stale", style: { "background-image": "data(art)", "background-opacity": 0, "border-width": 0, opacity: 0.45 } },
    { selector: "node[label = 'Answer'].stale", style: { "background-image": "data(artStale)", "background-opacity": 0, "border-width": 0 } },
    { selector: "node[label = 'Decision'].cited, node[label = 'Answer'].cited", style: { "border-width": 0 } },
    // ---- replay ----
    { selector: "node.dim", style: { opacity: 0.12 } },
    { selector: "edge.dim", style: { opacity: 0.06 } },
    { selector: "node.lit", style: { opacity: 1, "overlay-color": "#9a7631", "overlay-opacity": 0.22, "overlay-padding": 9, "overlay-shape": "round-rectangle" } },
    // ---- what-if previews: nothing is changed, so these are marked as "would", never as stale ----
    { selector: "node[would = 'reverse']", style: { "border-color": "#c2273d", "border-style": "dashed", "border-width": 2.5 } },
    { selector: "node[would = 'review'][label = 'PEP'], node[would = 'review'][label = 'Answer']", style: {
        "background-image": "data(artStale)", "border-style": "dashed", "border-color": "#7d8697" } },
    { selector: "node[would = 'review'][label = 'Answer']", style: { "border-width": 0 } },
    { selector: "node[would = 'leave']", style: { "border-color": "#c2273d", "border-style": "dashed", "border-width": 2, color: "#c2273d" } },
    { selector: "node[would = 'step_in']", style: { "border-color": "#2e7d5b", "border-width": 2.5, color: "#2e7d5b" } },
    { selector: "node[would = 'orphaned']", style: { "border-color": "#c2273d", "border-width": 2.5, "background-color": "#f6dde1" } },
    { selector: "node[would = 'one_left']", style: { "border-color": "#c2273d", "border-width": 1.5, "border-style": "dashed" } },
    { selector: "edge[type = 'TIE']", style: { "target-arrow-shape": "none", "line-color": "#2f5d8c", width: 2, label: "worked with",
        "font-family": font, "font-style": "italic", "font-size": 10, color: "#2f5d8c", "text-rotation": "autorotate",
        "text-background-color": "#eef1f3", "text-background-opacity": 1 } },
    { selector: "edge[type = 'STEP_IN']", style: {
        "line-style": "dashed", "line-color": "#2e7d5b", "target-arrow-color": "#2e7d5b", label: "could step in", "font-family": font,
        "font-style": "italic", "font-size": 10, color: "#2e7d5b", "text-rotation": "autorotate", "text-background-color": "#eef1f3",
        "text-background-opacity": 1 } },
  ];
}

const SUPERSEDED = new Set(["Superseded", "Replaced"]);

/** Artwork for the node kinds that are drawn rather than styled. */
function art(n: GNode, f: Fonts | null): Record<string, string> {
  if (!f) return {};
  const p = n.props ?? {};
  if (n.label === "PEP") {
    const num = String(p.number ?? n.id.split(":")[1]), title = String(p.title ?? "");
    const gone = SUPERSEDED.has(p.status);
    return { art: proposalCard(f, num, title, false, gone), artStale: proposalCard(f, num, title, true, gone) };
  }
  if (n.label === "Decision") return { art: decisionStamp(f, String(p.kind ?? ""), p.at ? String(p.at).slice(0, 10) : undefined) };
  if (n.label === "Answer") return { art: answerSlip(f, false), artStale: answerSlip(f, true) };
  return {};
}

export default function EvidenceGraph({
  fragment, cited, stale, wave, path, onSelect, fitSignal = 0, replay = null, onReplayEnd,
}: {
  fragment: Fragment;
  cited: Set<string>;
  stale: Set<string>;
  wave: Wave;
  path: string[];
  onSelect: (id: string) => void;
  fitSignal?: number;
  replay?: Replay;
  onReplayEnd?: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const timers = useRef<number[]>([]);
  const fonts = useRef<Fonts | null>(null);
  const [ready, setReady] = useState(false);
  const [caption, setCaption] = useState<{ n: number; of: number; text: string } | null>(null);
  const replayTimers = useRef<number[]>([]);
  const [tip, setTip] = useState<{ x: number; y: number; title: string; detail: string; stale: boolean } | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const cytoscape = (await import("cytoscape")).default;
      const fcose = (await import("cytoscape-fcose")).default;
      try { cytoscape.use(fcose); } catch { /* already registered */ }
      if (cancelled || !host.current) return;
      const css = getComputedStyle(document.documentElement);
      const font = `"Libre Caslon Condensed", Georgia, serif`;
      const typed = `${css.getPropertyValue("--font-typed").trim() || "Courier New"}, monospace`;
      // the node artwork is drawn on a canvas, so the faces must be loaded before the first drawing
      await Promise.all([`22px ${font}`, `italic 12px ${font}`, `9px ${typed}`].map((q) => document.fonts.load(q).catch(() => null)));
      fonts.current = { serif: font, typed };
      if (cancelled || !host.current) return;
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
      setReady(true);
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
        const data = { id: n.id, label: n.label, title: nodeTitle(n), detail: nodeDetail(n), kind: n.props?.kind ?? "", would: n.props?.would ?? "", ...art(n, fonts.current) };
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
                   nodeRepulsion: 20000, idealEdgeLength: 115, nodeSeparation: 110, padding: 40, nodeDimensionsIncludeLabels: true,
                   // a handful of nodes would otherwise be blown up to fill the canvas
                   stop: () => { if (c.zoom() > 1.25) { c.zoom({ level: 1.25, renderedPosition: { x: c.width() / 2, y: c.height() / 2 } }); c.center(); } },
                 } as any).run();
      }
    }, cy ? 0 : 120);
    return () => window.clearTimeout(t);
  }, [fragment, ready]);

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
    const t = window.setTimeout(() => { c.resize(); c.animate({ fit: { eles: c.elements(), padding: 40 } }, {
      duration: 300, complete: () => { if (c.zoom() > 1.25) { c.zoom({ level: 1.25, renderedPosition: { x: c.width() / 2, y: c.height() / 2 } }); c.center(); } },
    }); }, 280);
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

  // replay: fade everything, then light each step's findings in turn, then the answer and its sources
  useEffect(() => {
    const c = cyRef.current;
    replayTimers.current.forEach(clearTimeout); replayTimers.current = [];
    if (!c || !replay) { c?.elements().removeClass("dim lit"); setCaption(null); return; }
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const gap = reduce ? 2200 : 1700;
    const frames = [...replay.steps, { label: replay.finishLabel, ids: replay.finish }];
    const at = (ms: number, fn: () => void) => replayTimers.current.push(window.setTimeout(fn, ms));
    at(250, () => { c.elements().addClass("dim").removeClass("lit"); });
    frames.forEach((f, i) => at(500 + i * gap, () => {
      const hit = c.nodes().filter((n) => f.ids.includes(n.id()));
      c.nodes(".lit").removeClass("lit");
      hit.removeClass("dim").addClass("lit");
      hit.edgesWith(c.nodes().not(".dim")).removeClass("dim");
      setCaption({ n: i + 1, of: frames.length, text: f.label });
    }));
    at(500 + frames.length * gap + 600, () => {
      c.elements().removeClass("dim lit"); setCaption(null); onReplayEnd?.();
    });
    return () => { replayTimers.current.forEach(clearTimeout); replayTimers.current = []; c.elements().removeClass("dim lit"); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replay?.key]);

  function stopReplay() {
    replayTimers.current.forEach(clearTimeout); replayTimers.current = [];
    cyRef.current?.elements().removeClass("dim lit"); setCaption(null); onReplayEnd?.();
  }

  return (
    <>
      <div ref={host} className="cy" role="img" aria-label="Evidence graph" />
      {caption && (
        <div className="replay-caption" role="status" aria-live="polite">
          <span className="step typed">{caption.n === caption.of ? "Answer" : `Step ${caption.n} of ${caption.of - 1}`}</span>
          <span>{caption.text}</span>
          <button className="linkish" onClick={stopReplay}>Stop</button>
        </div>
      )}
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
