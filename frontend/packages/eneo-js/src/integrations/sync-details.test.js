import assert from "node:assert/strict";
import test from "node:test";
import { createSyncDetailsLoader } from "./sync-details.js";

const respond = (request) => ({
  items: request.items.map((item) => ({
    integration_knowledge_id: item.integration_knowledge_id,
    history: { offset: item.offset, items: [], total_count: 0 },
    skipped: { items: [], total: 0 }
  }))
});

test("a source with 120 imports makes three serial requests, preserving every result", async () => {
  const calls = [];
  let active = 0;
  const load = createSyncDetailsLoader(async (space, request) => {
    assert.equal(++active, 1);
    calls.push({ space, request });
    await Promise.resolve();
    active--;
    return respond(request);
  });
  const results = await Promise.all(Array.from({ length: 120 }, (_, i) => load("s", String(i))));
  assert.deepEqual(
    calls.map(({ request }) => request.items.length),
    [50, 50, 20]
  );
  assert.deepEqual(
    results.map((item) => item.integration_knowledge_id),
    Array.from({ length: 120 }, (_, i) => String(i))
  );
});

test("space, page size and different offsets of the same item never mix", async () => {
  const calls = [];
  const load = createSyncDetailsLoader(async (space, request) => {
    calls.push({ space, request });
    return respond(request);
  });
  const results = await Promise.all([
    load("a", "same", 0),
    load("a", "same", 0),
    load("a", "same", 10),
    load("b", "same", 0),
    load("a", "other", 0, 1)
  ]);
  assert.equal(calls.length, 4);
  assert.equal(results[2].history.offset, 10);
  assert.equal(results[0], results[1]);
});

test("a failed or malformed response rejects every waiter and permits a fresh retry", async () => {
  for (const response of [
    () => {
      throw new Error("offline");
    },
    () => ({ items: [] })
  ]) {
    let fail = true;
    const load = createSyncDetailsLoader(async (_, request) =>
      fail ? response() : respond(request)
    );
    const first = await Promise.allSettled([load("s", "a"), load("s", "b")]);
    assert.deepEqual(
      first.map((item) => item.status),
      ["rejected", "rejected"]
    );
    fail = false;
    assert.equal((await load("s", "a")).integration_knowledge_id, "a");
  }
});

test("a later revision can finish while an earlier history request is still pending", async () => {
  let release;
  let calls = 0;
  const load = createSyncDetailsLoader(async (_, request) => {
    if (++calls === 1)
      return new Promise((resolve) => {
        release = () => resolve(respond(request));
      });
    return respond(request);
  });
  const older = load("s", "a", 10);
  await Promise.resolve();
  const newer = await load("s", "a", 0);
  assert.equal(newer.history.offset, 0);
  release();
  assert.equal((await older).history.offset, 10);
});
