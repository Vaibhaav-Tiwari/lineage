// Node artwork for the evidence graph: proposals as index cards, decisions as rubber stamps,
// answers as paper slips. Drawn on a canvas (so the page's web fonts apply) and cached as data URLs.

export const CARD = { w: 92, h: 54 };
export const STAMP = { w: 88, h: 38 };
export const SLIP = { w: 60, h: 38 };

import type { Palette } from "./theme";

const SCALE = 3;
const cache = new Map<string, string>(); // keyed by palette too, so each theme draws its own artwork

export type Fonts = { serif: string; typed: string };

function canvas(w: number, h: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const c = document.createElement("canvas");
  c.width = w * SCALE; c.height = h * SCALE;
  const ctx = c.getContext("2d")!;
  ctx.scale(SCALE, SCALE);
  return [c, ctx];
}

/** A high-resolution drawing wrapped so its natural size is the node's size (the graph library
 *  otherwise draws a swapped-in image at its full pixel size). */
function sized(c: HTMLCanvasElement, w: number, h: number): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><image width="${w}" height="${h}" href="${c.toDataURL()}"/></svg>`;
  return `data:image/svg+xml;base64,${btoa(svg)}`;
}

function fit(ctx: CanvasRenderingContext2D, text: string, max: number): string {
  if (ctx.measureText(text).width <= max) return text;
  let t = text;
  while (t.length > 1 && ctx.measureText(`${t}…`).width > max) t = t.slice(0, -1);
  return `${t.trimEnd()}…`;
}

function hatch(ctx: CanvasRenderingContext2D, P: Palette, w: number, h: number) {
  ctx.fillStyle = P.cardStale; ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = P.hatchLine; ctx.globalAlpha = 0.45; ctx.lineWidth = 0.8;
  for (let x = -h; x < w; x += 6) { ctx.beginPath(); ctx.moveTo(x, h); ctx.lineTo(x + h, 0); ctx.stroke(); }
  ctx.globalAlpha = 1;
}

/** A proposal: small "PEP" over a big number and a short title. Faded when stale; struck when superseded. */
export function proposalCard(f: Fonts, P: Palette, num: string, title: string, stale: boolean, superseded: boolean): string {
  const key = `card|${P.paper}|${num}|${title}|${stale}|${superseded}`;
  const hit = cache.get(key); if (hit) return hit;
  const { w, h } = CARD;
  const [c, ctx] = canvas(w, h);
  if (stale) hatch(ctx, P, w, h); else { ctx.fillStyle = P.card; ctx.fillRect(0, 0, w, h); }
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = P.inkFaint; ctx.font = `9px ${f.typed}`; ctx.fillText("PEP", 7, 13);
  if (superseded) { ctx.fillStyle = P.stamp; ctx.font = `italic 9.5px ${f.serif}`; ctx.textAlign = "right"; ctx.fillText("superseded", w - 6, 13); ctx.textAlign = "left"; }
  ctx.fillStyle = stale ? P.inkSoft : P.ink; ctx.font = `22px ${f.serif}`; ctx.fillText(num, 7, 35);
  if (superseded) {
    const nw = ctx.measureText(num).width;
    ctx.strokeStyle = P.stamp; ctx.lineWidth = 1.6; ctx.beginPath(); ctx.moveTo(4, 28); ctx.lineTo(nw + 11, 28); ctx.stroke();
  }
  ctx.fillStyle = P.inkSoft; ctx.font = `10px ${f.serif}`; ctx.fillText(fit(ctx, title, w - 12), 7, 48);
  const url = sized(c, w, h);
  cache.set(key, url);
  return url;
}

const STAMP_WORD: Record<string, string> = { accept: "Accepted", reject: "Rejected", supersede: "Superseded", withdraw: "Withdrawn", defer: "Deferred", final: "Final" };

/** A decision: a slightly tilted rubber stamp with the outcome and its date. */
export function decisionStamp(f: Fonts, P: Palette, kind: string, at: string | undefined): string {
  const key = `stamp|${P.paper}|${kind}|${at}`;
  const hit = cache.get(key); if (hit) return hit;
  const { w, h } = STAMP;
  const [c, ctx] = canvas(w, h);
  const color = kind === "accept" || kind === "final" ? P.pine : kind === "reject" || kind === "supersede" ? P.stamp : P.inkSoft;
  const word = STAMP_WORD[kind] ?? (kind ? kind[0].toUpperCase() + kind.slice(1) : "Decision");
  ctx.translate(w / 2, h / 2); ctx.rotate(-0.07);
  ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.strokeRect(-w / 2 + 5, -h / 2 + 4, w - 10, h - 8);
  ctx.fillStyle = color; ctx.textAlign = "center";
  ctx.font = `13px ${f.serif}`; ctx.fillText(word, 0, at ? 0 : 4);
  if (at) { ctx.font = `8.5px ${f.typed}`; ctx.fillText(at, 0, 11); }
  const url = sized(c, w, h);
  cache.set(key, url);
  return url;
}

/** The Historian's answer: a paper slip with a folded corner. Struck in red once it no longer holds. */
export function answerSlip(f: Fonts, P: Palette, stale: boolean): string {
  const key = `slip|${P.paper}|${stale}`;
  const hit = cache.get(key); if (hit) return hit;
  const { w, h } = SLIP;
  const [c, ctx] = canvas(w, h);
  const color = stale ? P.stamp : P.pine;
  ctx.fillStyle = P.card; ctx.strokeStyle = color; ctx.lineWidth = 1.3;
  ctx.beginPath(); ctx.moveTo(2, 2); ctx.lineTo(w - 12, 2); ctx.lineTo(w - 2, 12); ctx.lineTo(w - 2, h - 2); ctx.lineTo(2, h - 2); ctx.closePath(); ctx.fill(); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(w - 12, 2); ctx.lineTo(w - 12, 12); ctx.lineTo(w - 2, 12); ctx.stroke();
  ctx.fillStyle = color; ctx.font = `italic 12px ${f.serif}`; ctx.fillText("Answer", 8, 24);
  if (stale) { ctx.beginPath(); ctx.moveTo(6, 20); ctx.lineTo(48, 20); ctx.lineWidth = 1.2; ctx.stroke(); }
  const url = sized(c, w, h);
  cache.set(key, url);
  return url;
}
