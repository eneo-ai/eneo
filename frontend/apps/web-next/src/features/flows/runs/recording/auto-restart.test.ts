import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AutoRestart, RESTART_DELAYS_MS, type RestartOutcome } from "./auto-restart";

function setup(outcomes: RestartOutcome[]) {
  let now = 0;
  const restart = new AutoRestart(() => now);
  const attempt = vi.fn(() => Promise.resolve(outcomes.shift() ?? "failed"));
  const onStarted = vi.fn();
  restart.setHandlers({ attempt, onStarted });
  return {
    restart,
    attempt,
    onStarted,
    advance: async (ms: number) => {
      now += ms;
      await vi.advanceTimersByTimeAsync(ms);
    }
  };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("AutoRestart", () => {
  it("tries again after a pause, and says when it is recording again", async () => {
    const { restart, attempt, onStarted, advance } = setup(["failed", "started"]);
    restart.lost();
    expect(restart.getSnapshot()).toEqual({ phase: "waiting", attempt: 1 });
    await advance(RESTART_DELAYS_MS[0] - 1);
    expect(attempt).not.toHaveBeenCalled();
    await advance(1);
    expect(attempt).toHaveBeenCalledTimes(1);
    expect(restart.getSnapshot()).toEqual({ phase: "waiting", attempt: 2 });
    await advance(RESTART_DELAYS_MS[1]);
    expect(attempt).toHaveBeenCalledTimes(2);
    expect(restart.getSnapshot()).toEqual({ phase: "idle" });
    expect(onStarted).toHaveBeenCalledTimes(1);
  });

  it("gives up after its last try", async () => {
    const { restart, attempt, onStarted, advance } = setup([]);
    restart.lost();
    for (const delay of RESTART_DELAYS_MS) await advance(delay);
    expect(attempt).toHaveBeenCalledTimes(RESTART_DELAYS_MS.length);
    expect(restart.getSnapshot()).toEqual({ phase: "failed" });
    expect(onStarted).not.toHaveBeenCalled();
  });

  it("stops trying when there is nothing to try", async () => {
    const { restart, attempt, advance } = setup(["refused"]);
    restart.lost();
    await advance(RESTART_DELAYS_MS[0]);
    expect(restart.getSnapshot()).toEqual({ phase: "idle" });
    await advance(10_000);
    expect(attempt).toHaveBeenCalledTimes(1);
  });

  it("leaves it to the person once they take over", async () => {
    let finish: (outcome: RestartOutcome) => void = () => undefined;
    const restart = new AutoRestart();
    const onStarted = vi.fn();
    restart.setHandlers({
      attempt: () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
      onStarted
    });
    restart.lost();
    await vi.advanceTimersByTimeAsync(RESTART_DELAYS_MS[0]);
    restart.cancel();
    finish("started");
    await vi.advanceTimersByTimeAsync(0);
    expect(restart.getSnapshot()).toEqual({ phase: "idle" });
    expect(onStarted).not.toHaveBeenCalled();
  });
});
