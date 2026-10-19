import assert from "node:assert/strict";
import test from "node:test";
import { syncAnnouncement, problemCountChanged } from "./sync-announcements.js";
const progress = (done, phase = "processing") => ({
  state: "syncing",
  progress: { done, total: 10, phase }
});
const idle = { state: "ok", progress: null };

test("disappearing progress never reports success or final counts", () => {
  for (const state of ["ok", "error", "queued", "never"]) {
    assert.deepEqual(syncAnnouncement(progress(3), { state, progress: null }, 0), {
      kind: "stopped"
    });
  }
});
test("unchanged polls are silent; progress is throttled except for phase changes", () => {
  assert.equal(syncAnnouncement(null, progress(1), 0), null);
  assert.equal(syncAnnouncement(progress(2), progress(2), 30_000), null);
  assert.equal(syncAnnouncement(progress(2), progress(3), 2_000), null);
  assert.deepEqual(syncAnnouncement(progress(2), progress(3), 10_000), {
    kind: "progress",
    done: 3,
    total: 10
  });
  assert.deepEqual(syncAnnouncement(progress(2), progress(2, "finishing"), 0), {
    kind: "progress",
    done: 2,
    total: 10
  });
  assert.equal(syncAnnouncement(progress(2), progress(3), 30_000, { speakProgress: false }), null);
});
test("start, queue and changed problem counts are distinct events", () => {
  assert.deepEqual(syncAnnouncement(idle, progress(1), 0), { kind: "started" });
  assert.deepEqual(syncAnnouncement(idle, { state: "queued", progress: null }, 0), {
    kind: "queued"
  });
  assert.equal(problemCountChanged(null, 2), false);
  assert.equal(problemCountChanged(2, 2), false);
  assert.equal(problemCountChanged(2, 3), true);
});
