import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CorrectionSet } from "./transcript-corrections";
import { AUTOSAVE_DELAY_MS, CorrectionsDraft } from "./transcript-draft";

const set = (corrected: string): CorrectionSet => ({
  occurrences: [{ segment_index: 0, char_start: 0, char_end: 3, original: "Hej", corrected }],
  speakerEdits: [],
  names: {}
});
const EMPTY: CorrectionSet = { occurrences: [], speakerEdits: [], names: {} };

/** A save the test answers: each call waits until the test resolves or rejects it. */
function server() {
  const calls: { set: CorrectionSet; revision: number | null }[] = [];
  const answers: { resolve: (revision: number) => void; reject: (error: unknown) => void }[] = [];
  const save = vi.fn(
    (draftSet: CorrectionSet, revision: number | null) =>
      new Promise<number | null>((resolve, reject) => {
        calls.push({ set: draftSet, revision });
        answers.push({ resolve, reject });
      })
  );
  return { save, calls, answers };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("CorrectionsDraft", () => {
  it("applies a change at once and saves it a moment later, fenced by the last revision", async () => {
    const { save, calls, answers } = server();
    const draft = new CorrectionsDraft(EMPTY, 3, save);
    draft.change(set("Hallå"));
    expect(draft.getSnapshot()).toMatchObject({ status: "waiting", set: set("Hallå") });
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY_MS - 1);
    expect(save).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(calls).toEqual([{ set: set("Hallå"), revision: 3 }]);
    expect(draft.getSnapshot().status).toBe("saving");
    answers[0]!.resolve(4);
    await vi.advanceTimersByTimeAsync(0);
    expect(draft.getSnapshot()).toMatchObject({ status: "saved", revision: 4 });
  });

  it("saves a change made during a save after it, with the revision that save got", async () => {
    const { calls, answers, save } = server();
    const draft = new CorrectionsDraft(EMPTY, 1, save);
    draft.change(set("A"));
    const flushed = draft.flush();
    draft.change(set("B"));
    answers[0]!.resolve(2);
    await vi.advanceTimersByTimeAsync(0);
    expect(calls.map((call) => [call.set, call.revision])).toEqual([
      [set("A"), 1],
      [set("B"), 2]
    ]);
    answers[1]!.resolve(3);
    await expect(flushed).resolves.toBe(true);
    expect(draft.getSnapshot()).toMatchObject({ status: "saved", revision: 3, set: set("B") });
  });

  it("keeps the draft after a failed save, saves nothing more until retried, and retries the latest", async () => {
    const { calls, answers, save } = server();
    const draft = new CorrectionsDraft(EMPTY, 1, save);
    draft.change(set("A"));
    const flushed = draft.flush();
    const refusal = new Error("offline");
    answers[0]!.reject(refusal);
    await expect(flushed).resolves.toBe(false);
    expect(draft.getSnapshot()).toMatchObject({
      status: "failed",
      problem: refusal,
      set: set("A")
    });

    draft.change(set("B"));
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY_MS * 5);
    expect(calls).toHaveLength(1);
    expect(draft.getSnapshot()).toMatchObject({ status: "failed", set: set("B") });

    const retried = draft.retry();
    expect(calls.at(-1)).toEqual({ set: set("B"), revision: 1 });
    answers[1]!.resolve(2);
    await expect(retried).resolves.toBe(true);
  });

  it("takes over the server's set only while it holds no changes, and drops them on discard", async () => {
    const { answers, save } = server();
    const draft = new CorrectionsDraft(EMPTY, 1, save);
    draft.sync(set("Server"), 2);
    expect(draft.getSnapshot()).toMatchObject({ set: set("Server"), revision: 2 });

    draft.change(set("Mine"));
    draft.sync(set("Someone else"), 3);
    expect(draft.getSnapshot().set).toEqual(set("Mine"));

    const flushed = draft.flush();
    draft.discard(set("Someone else"), 3);
    // The save on its way answers nobody.
    answers[0]!.resolve(9);
    await flushed;
    expect(draft.getSnapshot()).toMatchObject({
      status: "saved",
      revision: 3,
      set: set("Someone else")
    });
  });
});
