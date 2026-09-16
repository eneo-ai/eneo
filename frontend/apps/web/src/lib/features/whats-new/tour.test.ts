import type { Release } from "@eneo/whats-new";
import type { SpotlightOutcome } from "./spotlight";
import { get } from "svelte/store";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { goto, preloadData, spotlight } = vi.hoisted(() => ({
  goto: vi.fn<typeof import("$app/navigation").goto>(),
  preloadData: vi.fn<typeof import("$app/navigation").preloadData>(),
  spotlight: vi.fn<typeof import("./spotlight").spotlight>()
}));
vi.mock("$app/navigation", () => ({ goto, preloadData }));
vi.mock("$lib/paraglide/runtime", () => ({ localizeHref: (href: string) => href }));
vi.mock("./spotlight", () => ({ spotlight }));

import { createWhatsNewTour, tourSteps } from "./tour";

const entry = (id: string, audience: "all" | "admin" = "all") => ({
  id,
  type: "new" as const,
  area: "chat" as const,
  audience,
  title: { en: `${id} en`, sv: `${id} sv` },
  body: { en: `${id} body`, sv: `${id} kropp` },
  showMe: { href: `/${id}`, anchor: id }
});
const release: Release = {
  version: "2.2.0",
  entries: [entry("a"), { ...entry("b"), showMe: undefined }, entry("c", "admin"), entry("d")]
};
const steps = tourSteps(release, true, "en");
const labels = { done: "Done", progress: "Step {{current}} of {{total}}" };
let tour: ReturnType<typeof createWhatsNewTour>;

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubGlobal(
    "window",
    Object.assign(new EventTarget(), { location: { href: "https://eneo.test/whats-new" } })
  );
  tour = createWhatsNewTour();
  preloadData.mockResolvedValue({ type: "loaded", status: 200, data: {} });
  goto.mockImplementation(async (href) => {
    const destination = new URL(href, window.location.href);
    tour.beforeNavigation(destination);
    window.location.href = destination.href;
  });
  spotlight.mockResolvedValue("next");
});

afterEach(() => {
  tour.stop();
  vi.unstubAllGlobals();
});

describe("what's new walkthrough", () => {
  it("derives localized steps from visible entries only", () => {
    expect(tourSteps(release, false, "sv").map((step) => [step.anchor, step.title])).toEqual([
      ["a", "a sv"],
      ["d", "d sv"]
    ]);
    expect(steps.map((step) => step.anchor)).toEqual(["a", "c", "d"]);
  });

  it("walks forward and back, preloading only the page it navigates to", async () => {
    for (const outcome of ["next", "previous", "next", "next", "next"] as const) {
      spotlight.mockResolvedValueOnce(outcome);
    }
    expect(await tour.start(steps, labels)).toBe("completed");
    expect(goto.mock.calls.map(([href]) => href)).toEqual(["/a", "/c", "/a", "/c", "/d"]);
    expect(preloadData.mock.calls).toEqual(goto.mock.calls);
    expect(get(tour.running)).toBe(false);
  });

  it("does not load future pages while the user is reading the current stop", async () => {
    let next = (_outcome: SpotlightOutcome) => {};
    spotlight.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          next = resolve;
        })
    );
    const result = tour.start(steps, labels);
    await vi.waitFor(() => expect(spotlight).toHaveBeenCalledOnce());
    expect(preloadData).toHaveBeenCalledExactlyOnceWith("/a");
    expect(goto).toHaveBeenCalledExactlyOnceWith("/a");
    next("next");
    await result;
  });

  it.each([
    { type: "redirect" as const, location: "/" },
    { type: "loaded" as const, status: 403, data: {} },
    { type: "loaded" as const, status: 503, data: {} }
  ])("skips a denied or failed page before navigation: %j", async (result) => {
    preloadData.mockResolvedValueOnce(result);
    await tour.start(steps, labels);
    expect(goto.mock.calls.map(([href]) => href)).toEqual(["/c", "/d"]);
    expect(spotlight.mock.calls.map(([, options]) => options.progress)).toEqual([
      { index: 0, total: 2 },
      { index: 1, total: 2 }
    ]);
  });

  it("skips missing anchors in the direction of travel", async () => {
    for (const outcome of ["next", "next", "previous", "no-anchor", "next", "next"] as const) {
      spotlight.mockResolvedValueOnce(outcome);
    }
    await tour.start(steps, labels);
    expect(goto.mock.calls.map(([href]) => href)).toEqual(["/a", "/c", "/d", "/c", "/a", "/d"]);
    // The total shrinks once a stop is found unreachable.
    expect(spotlight.mock.calls.map(([, options]) => options.progress?.total)).toEqual([
      3, 3, 3, 3, 2, 2
    ]);
    expect(spotlight.mock.calls.at(-1)?.[1].progress?.index).toBe(1);
  });

  it("reports when no candidate can be shown", async () => {
    preloadData.mockRejectedValue(new Error("offline"));
    expect(await tour.start(steps, labels)).toBe("unavailable");
    expect(goto).not.toHaveBeenCalled();
    expect(await tour.start([], labels)).toBe("unavailable");
  });

  it("ends immediately when the user closes the spotlight", async () => {
    spotlight.mockResolvedValueOnce("closed");
    expect(await tour.start(steps, labels)).toBe("cancelled");
    expect(preloadData).toHaveBeenCalledOnce();
  });

  it("cancels a pending preload and ignores its late result", async () => {
    let complete = () => {};
    preloadData.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          complete = () => resolve({ type: "loaded", status: 200, data: {} });
        })
    );
    const result = tour.start(steps, labels);
    tour.stop();
    expect(await result).toBe("cancelled");
    expect(get(tour.running)).toBe(false);
    complete();
    await Promise.resolve();
    expect(goto).not.toHaveBeenCalled();
  });

  it("replaces an older run without letting its completion stop the new run", async () => {
    preloadData.mockImplementationOnce(() => new Promise(() => {}));
    const old = tour.start(steps, labels);
    const current = tour.start([steps[2]], labels);
    expect(await old).toBe("cancelled");
    expect(await current).toBe("completed");
    expect(goto).toHaveBeenCalledExactlyOnceWith("/d");
  });

  it("aborts on external navigation while waiting for user input", async () => {
    spotlight.mockImplementationOnce(() => new Promise(() => {}));
    const result = tour.start(steps, labels);
    await vi.waitFor(() => expect(spotlight).toHaveBeenCalledOnce());
    tour.beforeNavigation(new URL("https://eneo.test/account"));
    expect(await result).toBe("cancelled");
    expect(spotlight.mock.calls[0][1].signal.aborted).toBe(true);
    expect(preloadData).toHaveBeenCalledOnce();
  });

  it("supports Escape before a page finishes loading", async () => {
    preloadData.mockImplementationOnce(() => new Promise(() => {}));
    const result = tour.start(steps, labels);
    const event = Object.assign(new Event("keydown"), { key: "Escape" });
    window.dispatchEvent(event);
    expect(await result).toBe("cancelled");
    expect(goto).not.toHaveBeenCalled();
  });

  it("clears the active run when navigation or spotlight fails", async () => {
    goto.mockRejectedValueOnce(new Error("navigation failed"));
    await expect(tour.start(steps, labels)).rejects.toThrow("navigation failed");
    expect(get(tour.running)).toBe(false);
    spotlight.mockRejectedValueOnce(new Error("driver failed"));
    await expect(tour.start(steps, labels)).rejects.toThrow("driver failed");
    expect(get(tour.running)).toBe(false);
  });
});
