import { test } from "node:test";
import assert from "node:assert/strict";
import { splitEvents } from "../lib/api.ts";

test("complete lines become events and a partial line waits for the next chunk", () => {
  const a = splitEvents('{"type":"step","step":{"name":"decision_path"}}\n{"type":"dr');
  assert.deepEqual(a.events.map((e) => e.type), ["step"]);
  const b = splitEvents(a.rest + 'aft","result":{}}\n\n{"type":"final","result":{}}\n');
  assert.deepEqual(b.events.map((e) => e.type), ["draft", "final"]);
  assert.equal(b.rest, "");
});
