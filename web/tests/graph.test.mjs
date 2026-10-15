import { test } from "node:test";
import assert from "node:assert/strict";
import { capFanout, expandMore, sharesTopic } from "../lib/api.ts";

const star = (n) => ({
  nodes: [{ id: "area:asyncio", label: "Area", props: { name: "asyncio" } },
          ...Array.from({ length: n }, (_, i) => ({ id: `person:p${i}`, label: "Person", props: { name: `P${i}` } }))],
  edges: Array.from({ length: n }, (_, i) => ({ src: `person:p${i}`, dst: "area:asyncio", type: "COMMITTED_TO" })),
});

test("a 40-person star folds into the kept people plus one '+N more' node", () => {
  const out = capFanout(star(40), new Set(["person:p0", "person:p1"]), 8);
  const people = out.nodes.filter((n) => n.label === "Person").map((n) => n.id);
  assert.ok(people.includes("person:p0") && people.includes("person:p1"));
  assert.equal(people.length, 8);
  const more = out.nodes.find((n) => n.label === "More");
  assert.equal(more.props.count, 32);
  assert.ok(out.edges.some((e) => e.type === "MORE" && e.src === "area:asyncio"));
});

test("small fragments are left alone", () => {
  const f = star(6);
  assert.equal(capFanout(f, new Set(), 8), f);
});

test("clicking '+N more' brings every hidden node and edge back", () => {
  const out = capFanout(star(40), new Set(), 8);
  const back = expandMore(out, "more:area:asyncio");
  assert.equal(back.nodes.filter((n) => n.label === "Person").length, 40);
  assert.equal(back.edges.length, 40);
  assert.ok(!back.nodes.some((n) => n.label === "More"));
});

test("a follow-up sharing a proposal or module continues the topic; an unrelated one does not", () => {
  const pep455 = { nodes: [{ id: "pep:455", label: "PEP", props: {} }, { id: "person:pitrou", label: "Person", props: {} }], edges: [] };
  assert.equal(sharesTopic(pep455, { nodes: [{ id: "pep:455", label: "PEP", props: {} }], edges: [] }), true);
  assert.equal(sharesTopic(pep455, star(3)), false);
  // sharing only a person (people span many topics) is not the same topic
  assert.equal(sharesTopic(pep455, { nodes: [{ id: "person:pitrou", label: "Person", props: {} }], edges: [] }), false);
});
