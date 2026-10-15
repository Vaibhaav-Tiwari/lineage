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
  tool_trace: { name: string; input: any; ms: number; error?: string }[];
  usage: Record<string, any>;
};

export type EventRow = { id: string; slug: string; kind: string; summary: string; at: string; applied: boolean; pep: string; by: number[]; source_url: string };

export type StewardReport = {
  event: string;
  summary: string;
  changed: string[];
  ripple: { hard: string[]; soft: string[]; superseders: string[]; chunks: string[] };
  paths: Fragment;
  agents: Record<string, { beliefs: string[]; answers: string[]; actions_blocked: string[] }>;
  fixtasks: string[];
  plain?: string;
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, { ...init, headers: { "content-type": "application/json", ...(init?.headers ?? {}) } });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${r.status}`), { status: r.status, body });
  return body as T;
}

export const api = {
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
  claim: (agent: string) => call<any>("/fixtasks/claim", { method: "POST", body: JSON.stringify({ agent }) }),
  drift: () => call<any[]>("/org/drift"),
  clusters: () => call<any[]>("/org/clusters"),
  people: (q: string) => call<any[]>(`/org/people?q=${encodeURIComponent(q)}`),
  whatif: (person_ids: string[]) => call<any>("/org/whatif", { method: "POST", body: JSON.stringify({ person_ids }) }),
  preview: (pep: number) => call<any>("/org/preview", { method: "POST", body: JSON.stringify({ pep }) }),
  peps: (q: string) => call<any[]>(`/org/peps?q=${encodeURIComponent(q)}`),
  beliefs: () => call<any[]>("/beliefs?agent=historian"),
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
    case "Action": return "Add to FAQ";
    default: return n.id;
  }
}
