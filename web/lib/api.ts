export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type GNode = { id: string; label: string; props: Record<string, any> };
export type GEdge = { src: string; dst: string; type: string; props?: Record<string, any> };
export type Fragment = { nodes: GNode[]; edges: GEdge[] };

export type AskResult = {
  answer_id: string | null;
  text: string;
  abstained: boolean;
  citations: string[];
  evidence: Fragment;
  beliefs: { text: string; evidence: string[]; confidence: number }[];
  tool_trace: { name: string; input: any; ms: number; error?: string; found?: string[]; summary?: string }[];
  usage: Record<string, any>;
  miss?: Miss | null;
};

export type MissAction = { label: string; question?: string; as_of?: string | null };
export type Miss = { kind: "missing" | "not_yet" | "unrecorded" | "unrecognised" | "system"; text: string; actions: MissAction[] };

export type EventRow = { id: string; slug: string; kind: string; summary: string; at: string; applied: boolean; pep: string; by: number[]; source_url: string };

export type StewardReport = {
  event: string;
  summary: string;
  changed: string[];
  ripple: { hard: string[]; soft: string[]; superseders: string[]; chunks: string[] };
  paths: Fragment;
  agents: Record<string, { beliefs: string[]; answers: string[]; actions_blocked: string[] }>;
  fixtasks: string[];
  faq_withdrawn?: number;
  plain?: string;
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, { ...init, headers: { "content-type": "application/json", ...(init?.headers ?? {}) } });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${r.status}`), { status: r.status, body });
  return body as T;
}

export type AskStep = AskResult["tool_trace"][number];
export type AskEvent = { type: "step"; step: AskStep } | { type: "draft" | "final"; result: AskResult } | { type: "error"; message: string };

/** Newline-delimited JSON: complete lines become events; a trailing partial line is kept for the next chunk. */
export function splitEvents(buf: string): { events: AskEvent[]; rest: string } {
  const lines = buf.split("\n");
  const rest = lines.pop() ?? "";
  return { events: lines.filter((l) => l.trim()).map((l) => JSON.parse(l) as AskEvent), rest };
}

/** /ask/stream: reports each graph lookup and the instant draft as they arrive; resolves with the final answer. */
async function askStream(question: string, user_id: string, as_of: string | null, context: Record<string, string>[],
                         focus: string | null, onEvent: (e: AskEvent) => void): Promise<AskResult> {
  const r = await fetch(`${API}/ask/stream`, { method: "POST", headers: { "content-type": "application/json" },
                                               body: JSON.stringify({ question, user_id, as_of, context, focus }) });
  if (!r.ok || !r.body) {
    const body = await r.json().catch(() => ({}));
    throw Object.assign(new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${r.status}`), { status: r.status, body });
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let final: AskResult | null = null;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    const { events, rest } = splitEvents(buf + decoder.decode(value, { stream: true }));
    buf = rest;
    for (const e of events) {
      if (e.type === "error") throw new Error(e.message);
      if (e.type === "final") final = e.result;
      onEvent(e);
    }
  }
  if (!final) throw new Error("The archive stopped before it finished answering. Try asking again.");
  return final;
}

export const api = {
  askStream,
  ask: (question: string, user_id: string, as_of: string | null, context: Record<string, string>[] = [], focus: string | null = null) =>
    call<AskResult>("/ask", { method: "POST", body: JSON.stringify({ question, user_id, as_of, context, focus }) }),
  node: (id: string) => call<any>(`/nodes/${encodeURIComponent(id)}`),
  events: () => call<EventRow[]>("/events"),
  apply: (slug: string) => call<StewardReport>(`/events/${slug}/apply`, { method: "POST" }),
  reset: () => call<any>("/demo/reset", { method: "POST" }),
  rewind: (slug: string) => call<any>(`/events/${slug}/rewind`, { method: "POST" }),
  propose: (kind: string, payload: any, derived_from: string[]) =>
    call<{ id: string }>("/actions", { method: "POST", body: JSON.stringify({ kind, payload, derived_from }) }),
  execute: (id: string) => call<any>(`/actions/${id}/execute`, { method: "POST" }),
  fixtasks: () => call<any[]>("/fixtasks"),
  faq: () => call<any[]>("/faq"),
  health: (asOf?: string | null) => call<any[]>(`/org/health${asOf ? `?as_of=${asOf}` : ""}`),
  introduce: (person_id: string, area_id: string, as_of: string | null = null) =>
    call<any>("/org/introduce", { method: "POST", body: JSON.stringify({ person_id, area_id, as_of }) }),
  security: () => call<any[]>("/ops/security"),
  claim: (agent: string) => call<any>("/fixtasks/claim", { method: "POST", body: JSON.stringify({ agent }) }),
  drift: () => call<any[]>("/org/drift"),
  clusters: () => call<any[]>("/org/clusters"),
  people: (q: string) => call<any[]>(`/org/people?q=${encodeURIComponent(q)}`),
  whatif: (person_ids: string[]) => call<any>("/org/whatif", { method: "POST", body: JSON.stringify({ person_ids }) }),
  preview: (pep: number) => call<any>("/org/preview", { method: "POST", body: JSON.stringify({ pep }) }),
  peps: (q: string) => call<any[]>(`/org/peps?q=${encodeURIComponent(q)}`),
  beliefs: (knownAt?: string) => call<any[]>(`/beliefs?agent=historian${knownAt ? `&known_at=${encodeURIComponent(knownAt)}` : ""}`),
  interests: (uid: string) => call<any[]>(`/users/${uid}/interests`),
  why: (uid: string, area: string) => call<Fragment>(`/users/${uid}/interests/${encodeURIComponent(area)}/why`),
  forget: (uid: string, eid: string) => call<any>(`/users/${uid}/episodes/${encodeURIComponent(eid)}`, { method: "DELETE" }),
  graphs: () => call<{ graph: string; mb: number }[]>("/ops/graphs"),
};

export function mergeFragments(a: Fragment, b: Fragment): Fragment {
  const nodes = new Map(a.nodes.map((n) => [n.id, n]));
  for (const n of b.nodes) nodes.set(n.id, { ...nodes.get(n.id), ...n, props: { ...(nodes.get(n.id)?.props ?? {}), ...n.props } });
  const key = (e: GEdge) => `${e.src}|${e.type}|${e.dst}`;
  const edges = new Map(a.edges.map((e) => [key(e), e]));
  for (const e of b.edges) edges.set(key(e), e);
  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}

/** Does the next answer continue the current topic, i.e. share a proposal or a module with it? */
export function sharesTopic(cur: Fragment, next: Fragment): boolean {
  const topics = new Set(cur.nodes.filter((n) => n.label === "PEP" || n.label === "Area").map((n) => n.id));
  return next.nodes.some((n) => topics.has(n.id));
}

/** Keep big stars readable: a hub with many one-off neighbours shows `max` of them plus a "+N more" node
 *  that holds the rest (clicking it brings them back). Anything in `keep` always stays. */
export function capFanout(f: Fragment, keep: Set<string>, max = 8): Fragment {
  const nbrs = new Map<string, Set<string>>();
  for (const e of f.edges) {
    if (!nbrs.has(e.src)) nbrs.set(e.src, new Set());
    if (!nbrs.has(e.dst)) nbrs.set(e.dst, new Set());
    nbrs.get(e.src)!.add(e.dst);
    nbrs.get(e.dst)!.add(e.src);
  }
  const hidden = new Set<string>();
  const more: GNode[] = [];
  const moreEdges: GEdge[] = [];
  for (const hub of f.nodes) {
    const leaves = [...(nbrs.get(hub.id) ?? [])].filter((id) => nbrs.get(id)!.size === 1 && !keep.has(id) && !hidden.has(id));
    const shown = [...(nbrs.get(hub.id) ?? [])].filter((id) => !leaves.includes(id)).length;
    const room = Math.max(3, max - shown);
    if (leaves.length <= room + 1) continue;
    const extra = leaves.slice(room);
    extra.forEach((id) => hidden.add(id));
    const id = `more:${hub.id}`;
    more.push({ id, label: "More", props: {
      count: extra.length, of: nodeTitle(hub),
      hidden: { nodes: f.nodes.filter((n) => extra.includes(n.id)), edges: f.edges.filter((e) => extra.includes(e.src) || extra.includes(e.dst)) },
    } });
    moreEdges.push({ src: hub.id, dst: id, type: "MORE" });
  }
  if (!more.length) return f;
  return {
    nodes: [...f.nodes.filter((n) => !hidden.has(n.id)), ...more],
    edges: [...f.edges.filter((e) => !hidden.has(e.src) && !hidden.has(e.dst)), ...moreEdges],
  };
}

/** Swap a "+N more" node back for what it was hiding. */
export function expandMore(f: Fragment, moreId: string): Fragment {
  const m = f.nodes.find((n) => n.id === moreId);
  if (!m) return f;
  const rest = { nodes: f.nodes.filter((n) => n.id !== moreId), edges: f.edges.filter((e) => e.dst !== moreId && e.src !== moreId) };
  return mergeFragments(rest, m.props.hidden as Fragment);
}

/** A source written for people, for the numbered notes under an answer. */
export function citationLabel(n: GNode | undefined, id: string): string {
  if (!n) return id;
  const p = n.props ?? {};
  const word: Record<string, string> = { accept: "Acceptance", reject: "Rejection", supersede: "Supersession", withdraw: "Withdrawal" };
  switch (n.label) {
    case "PEP": return `PEP ${p.number ?? id.split(":")[1]}${p.title ? `, ${p.title}` : ""}`;
    case "Decision": return `${word[p.kind] ?? "Decision"} of PEP ${id.split(":")[2]}${p.at ? `, ${String(p.at).slice(0, 10)}` : ""}`;
    case "Post": return `Forum post #${p.post_number ?? ""}${p.created ? `, ${String(p.created).slice(0, 10)}` : ""}`;
    case "PR": return `Pull request ${id.split(":")[1]}${p.title ? `, ${p.title}` : ""}`;
    case "Chunk": return `Passage${p.heading ? ` "${p.heading}"` : ""}`;
    default: return nodeTitle(n);
  }
}

export function nodeDetail(n: GNode): string {
  const p = n.props ?? {};
  switch (n.label) {
    case "PEP": return `Proposal${p.title ? `: ${p.title}` : ""}${p.status ? `. Status ${p.status}` : ""}${p.created ? `, created ${p.created}` : ""}.`;
    case "Person": return `Person${p.github ? ` (GitHub ${p.github})` : ""}.`;
    case "Decision": return `Decision: ${p.kind ?? "?"}${p.at ? ` on ${p.at}` : ""}.`;
    case "Thread": return `Discussion thread${p.title ? `: ${p.title}` : ""}.`;
    case "Post": return `Forum post${p.post_number ? ` #${p.post_number}` : ""}${p.created ? ` from ${p.created}` : ""}.`;
    case "PR": return `Pull request${p.title ? `: ${p.title}` : ""}.`;
    case "Chunk": return `Passage${p.heading ? ` from section "${p.heading}"` : ""}.`;
    case "Answer": return `The Historian's answer: ${String(p.text ?? "").slice(0, 140)}…`;
    case "Action": return "Queued action: add the answer to the onboarding FAQ. It can only run while its evidence is current.";
    case "Area": return `Part of Python: ${p.name ?? n.id}.`;
    case "More": return `${p.count} more linked to ${p.of}, folded away to keep the graph readable. Click to show them.`;
    default: return n.id;
  }
}

export function nodeTitle(n: GNode): string {
  const p = n.props ?? {};
  switch (n.label) {
    case "PEP": return `PEP ${p.number ?? n.id.split(":")[1]}`;
    case "Person": return p.name ?? p.github ?? n.id.split(":")[1];
    case "Decision": return (p.kind ?? "decision").replace(/^\w/, (c: string) => c.toUpperCase());
    case "Thread": return p.title ? String(p.title).slice(0, 38) : "Thread";
    case "Post": return `Post #${p.post_number ?? ""}`;
    case "PR": return `PR ${n.id.split(":")[1]}`;
    case "Chunk": return p.heading ?? "Text";
    case "Event": return "Change event";
    case "Area": return p.name ?? n.id.split(":")[1];
    case "Answer": return "Historian's answer";
    case "Action": return p.kind && p.kind.length < 24 ? p.kind : "Queued action";
    case "More": return `+${p.count} more`;
    default: return n.id;
  }
}
