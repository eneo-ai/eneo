import type { Release } from "@eneo/whats-new";
import { describe, expect, it, vi } from "vitest";

const spotlight = vi.fn();
vi.mock("./spotlight", () => ({ spotlight: (...args: unknown[]) => spotlight(...args) }));

const { startTour, tourSteps } = await import("./tour");

const entry = (id: string, extra = {}) => ({
  id,
  type: "new" as const,
  area: "chat" as const,
  title: { en: `${id} en`, sv: `${id} sv` },
  body: { en: `${id} body`, sv: `${id} kropp` },
  ...extra
});

const release: Release = {
  version: "2.2.0",
  entries: [
    entry("a", { showMe: { href: "/a", anchor: "a" } }),
    entry("b"),
    entry("c", { audience: "admin", showMe: { href: "/c", anchor: "c" } }),
    entry("d", { showMe: { href: "/d", anchor: "d" } })
  ]
};

const labels = { done: "Done" };

describe("what's new walkthrough", () => {
  it("derives steps from the visible Show me entries in order", () => {
    expect(tourSteps(release, false, "sv").map((s) => [s.anchor, s.title])).toEqual([
      ["a", "a sv"],
      ["d", "d sv"]
    ]);
    expect(tourSteps(release, true, "en").map((s) => s.anchor)).toEqual(["a", "c", "d"]);
  });

  it("walks forward and back through the steps and resolves at the end", async () => {
    const order: string[] = [];
    // Scripted clicks: a → next, c → previous (first time), a → next, c → next, d → next.
    const clicks: Array<"next" | "previous"> = ["next", "previous", "next", "next", "next"];
    spotlight.mockImplementation(async (step, options) => {
      order.push(`${step.anchor}:${options.progress.index + 1}/${options.progress.total}`);
      const click = clicks.shift();
      if (click === "next") options.onNext();
      else if (click === "previous") options.onPrevious();
      return true;
    });

    await startTour(tourSteps(release, true, "en"), labels);
    expect(order).toEqual(["a:1/3", "c:2/3", "a:1/3", "c:2/3", "d:3/3"]);
  });

  it("skips a step whose anchor is missing, in the direction of travel", async () => {
    const order: string[] = [];
    spotlight.mockImplementation(async (step, options) => {
      order.push(step.anchor);
      if (step.anchor === "c") return false;
      options.onNext();
      return true;
    });

    await startTour(tourSteps(release, true, "en"), labels);
    expect(order).toEqual(["a", "c", "d"]);
  });

  it("ends when the user closes the walkthrough", async () => {
    const order: string[] = [];
    spotlight.mockImplementation(async (step, options) => {
      order.push(step.anchor);
      options.onClose();
      return true;
    });

    await startTour(tourSteps(release, true, "en"), labels);
    expect(order).toEqual(["a"]);
  });

  it("resolves immediately without steps", async () => {
    spotlight.mockClear();
    await startTour([], labels);
    expect(spotlight).not.toHaveBeenCalled();
  });
});
