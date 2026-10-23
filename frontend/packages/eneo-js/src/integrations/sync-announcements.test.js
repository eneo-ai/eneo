import assert from "node:assert/strict";
import test from "node:test";
import {
  OUTCOME_WAIT_MS,
  PROGRESS_ANNOUNCE_INTERVAL_MS,
  SyncAnnouncer,
  problemCountChanged
} from "./sync-announcements.js";

const idle = (outcome = "before", failures = []) => ({
  state: failures.length > 0 ? "attention" : "ok",
  progress: null,
  outcome,
  failures
});
const queued = { state: "queued", progress: null, outcome: "before", failures: [] };
const syncing = (done, { phase = "processing", background = false, failures = [] } = {}) => ({
  state: "syncing",
  progress: { done, total: 40, phase, background },
  outcome: "before",
  failures
});

function run(announcer, steps) {
  return steps.map(([snapshot, at]) => announcer.next(snapshot, at));
}

test("the first snapshot is not news", () => {
  assert.equal(new SyncAnnouncer().next(syncing(3), 0), null);
});

test("a sync's end waits for the rows to say how it ended", () => {
  const announcer = new SyncAnnouncer();
  assert.deepEqual(
    run(announcer, [
      [idle(), 0],
      [syncing(1), 1_000],
      [idle("before"), 5_000],
      [idle("after"), 6_000]
    ]),
    [null, { kind: "started" }, null, { kind: "finished" }]
  );
  const failing = new SyncAnnouncer();
  assert.deepEqual(
    run(failing, [
      [idle(), 0],
      [syncing(1), 1_000],
      [idle("before"), 5_000],
      [idle("after", ["b@6"]), 6_000]
    ]).at(-1),
    { kind: "failed" }
  );
});

test("a part that was failing already and was not tried again does not fail another's sync", () => {
  const old = ["b@1"];
  const other = new SyncAnnouncer();
  assert.deepEqual(
    run(other, [
      [idle("before", old), 0],
      [syncing(1, { failures: old }), 1_000],
      [idle("before", old), 5_000],
      [idle("after", old), 6_000]
    ]).at(-1),
    { kind: "finished" }
  );
  const retried = new SyncAnnouncer();
  assert.deepEqual(
    run(retried, [
      [idle("before", old), 0],
      [syncing(1, { failures: old }), 1_000],
      [idle("before", old), 5_000],
      [idle("after", ["b@6"]), 6_000]
    ]).at(-1),
    { kind: "failed" }
  );
});

test("without a recorded outcome the end is spoken after a wait, without one", () => {
  const announcer = new SyncAnnouncer();
  run(announcer, [
    [idle(), 0],
    [syncing(1), 1_000],
    [idle("before"), 5_000]
  ]);
  assert.equal(announcer.next(idle("before"), 5_000 + OUTCOME_WAIT_MS - 1), null);
  assert.deepEqual(announcer.next(idle("before"), 5_000 + OUTCOME_WAIT_MS), { kind: "stopped" });
});

test("counts are throttled, only move forward, and reaching the last step is spoken", () => {
  const announcer = new SyncAnnouncer();
  const start = 1_000;
  run(announcer, [
    [idle(), 0],
    [syncing(1), start]
  ]);
  assert.equal(announcer.next(syncing(5), start + PROGRESS_ANNOUNCE_INTERVAL_MS - 1), null);
  assert.deepEqual(announcer.next(syncing(6), start + PROGRESS_ANNOUNCE_INTERVAL_MS), {
    kind: "progress",
    done: 6,
    total: 40
  });
  // A folder of several finishing makes the combined count drop; that is not spoken.
  assert.equal(announcer.next(syncing(4), start + 3 * PROGRESS_ANNOUNCE_INTERVAL_MS), null);
  // Another folder starting moves the phase back; that alone is not news.
  assert.equal(
    announcer.next(
      syncing(4, { phase: "discovering" }),
      start + 3 * PROGRESS_ANNOUNCE_INTERVAL_MS + 1
    ),
    null
  );
  // Reaching the last step is, even inside the throttle.
  assert.deepEqual(
    announcer.next(
      syncing(4, { phase: "finishing" }),
      start + 3 * PROGRESS_ANNOUNCE_INTERVAL_MS + 2
    ),
    { kind: "progress", done: 4, total: 40 }
  );
});

test("a change notification's sync stays quiet unless someone started a sync here", () => {
  const quiet = new SyncAnnouncer();
  assert.deepEqual(
    run(quiet, [
      [idle(), 0],
      [syncing(1, { background: true }), 1_000],
      [syncing(9, { background: true }), 30_000],
      [idle("before"), 31_000],
      [idle("after"), 32_000]
    ]),
    [null, null, null, null, null]
  );
  const started = new SyncAnnouncer();
  assert.deepEqual(
    run(started, [
      [idle(), 0],
      [queued, 500],
      [syncing(1, { background: true }), 1_000]
    ]).slice(1),
    [{ kind: "queued" }, { kind: "started" }]
  );
});

test("a list speaks only what was started from it, and no counts", () => {
  const list = new SyncAnnouncer({ speakProgress: false, onlyStartedHere: true });
  assert.equal(list.next(idle(), 0), null);
  assert.equal(list.next(syncing(1), 1_000), null);
  assert.equal(list.next(idle("before"), 2_000), null);
  assert.equal(list.next(idle("after"), 3_000), null);
  assert.deepEqual(
    run(list, [
      [queued, 4_000],
      [syncing(1), 5_000],
      [syncing(30, { phase: "finishing" }), 60_000],
      [idle("after"), 61_000],
      [idle("later"), 62_000]
    ]),
    [{ kind: "queued" }, { kind: "started" }, null, { kind: "finished" }, null]
  );
});

test("a queued sync that ends before any progress is read still gets its end spoken", () => {
  const announcer = new SyncAnnouncer();
  assert.deepEqual(
    run(announcer, [
      [idle(), 0],
      [queued, 500],
      [idle("after", ["b@2"]), 3_000]
    ]),
    [null, { kind: "queued" }, { kind: "failed" }]
  );
  const silent = new SyncAnnouncer();
  run(silent, [
    [idle(), 0],
    [queued, 500],
    [idle("before"), 3_000]
  ]);
  assert.equal(silent.awaitingUntil, 3_000 + OUTCOME_WAIT_MS);
  assert.deepEqual(silent.next(idle("before"), 3_000 + OUTCOME_WAIT_MS), { kind: "stopped" });
  assert.equal(silent.awaitingUntil, null);
  // That sync is over: a later change notification's sync is not taken for one started here.
  assert.equal(silent.next(syncing(1, { background: true }), 40_000), null);
});

test("progress and outcome arriving in one snapshot are spoken at once", () => {
  const announcer = new SyncAnnouncer();
  assert.deepEqual(
    run(announcer, [
      [idle(), 0],
      [syncing(1), 1_000],
      [idle("after"), 5_000]
    ]).at(-1),
    { kind: "finished" }
  );
});

test("a folder that fails again is a failure even when its rows were re-read mid-sync", () => {
  const announcer = new SyncAnnouncer();
  const before = ["b@1"];
  assert.deepEqual(
    run(announcer, [
      [idle("before", before), 0],
      [syncing(1, { failures: before }), 1_000],
      // A space refresh while it runs already shows the new attempt time.
      [syncing(5, { failures: ["b@2"] }), 3_000],
      [idle("before", ["b@2"]), 5_000],
      [idle("after", ["b@2"]), 6_000]
    ]).at(-1),
    { kind: "failed" }
  );
});

test("a changed problem count is news once both counts are known", () => {
  assert.equal(problemCountChanged(null, 2), false);
  assert.equal(problemCountChanged(2, 2), false);
  assert.equal(problemCountChanged(2, 3), true);
});
