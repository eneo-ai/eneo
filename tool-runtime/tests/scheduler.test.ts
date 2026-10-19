import { expect, test } from "bun:test";
import { Scheduler } from "../src/scheduler";
import { ToolError } from "../src/errors";

function gate() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
test("idle capacity is borrowed and waiting groups rotate", async () => {
  const scheduler = new Scheduler(1);
  const first = gate();
  const sequence: string[] = [];
  const running = scheduler.run(() => first.promise, "a");
  const a = scheduler.run(async () => {
    sequence.push("a");
  }, "a");
  const b = scheduler.run(async () => {
    sequence.push("b");
  }, "b");
  first.resolve();
  await Promise.all([running, a, b]);
  expect(sequence).toEqual(["b", "a"]);
  expect(scheduler.status).toEqual({ active: 0, queued: 0 });
  const two = new Scheduler(2);
  const wait = gate();
  const jobs = [two.run(() => wait.promise, "a"), two.run(() => wait.promise, "a")];
  expect(two.status.active).toBe(2);
  wait.resolve();
  await Promise.all(jobs);
});
test("queue limits and queued cancellation do not leak slots", async () => {
  const scheduler = new Scheduler(1, 2, 1);
  const first = gate();
  const running = scheduler.run(() => first.promise, "a");
  const controller = new AbortController();
  const queued = scheduler.run(
    async () => {
      throw new Error("must not execute");
    },
    "a",
    controller.signal,
  );
  const rejection = queued.catch((error) => error);
  await expect(scheduler.run(async () => {}, "a")).rejects.toMatchObject({ code: "BUSY" });
  controller.abort(new ToolError("CANCELLED", "cancel"));
  expect(await rejection).toMatchObject({ code: "CANCELLED" });
  expect(scheduler.status.queued).toBe(0);
  first.resolve();
  await running;
  await expect(
    scheduler.run(async () => {
      throw new Error("failure");
    }, "b"),
  ).rejects.toThrow("failure");
  expect(scheduler.status).toEqual({ active: 0, queued: 0 });
});
