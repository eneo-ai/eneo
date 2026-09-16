// Browser contract: exercise the controller with real DOM anchors and driver.js.
// Only the network/navigation boundary is replaced; spotlight is not mocked.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const { goto, preloadData } = vi.hoisted(() => ({
  goto: vi.fn<typeof import("$app/navigation").goto>(),
  preloadData: vi.fn<typeof import("$app/navigation").preloadData>()
}));
vi.mock("$app/navigation", () => ({ goto, preloadData }));
vi.mock("$lib/paraglide/runtime", () => ({ localizeHref: (href: string) => href }));

import { createWhatsNewTour } from "./tour";

const steps = ["a", "b"].map((anchor) => ({
  href: `/${anchor}`,
  anchor,
  title: `Feature ${anchor}`,
  description: `Description ${anchor}`
}));
const labels = { done: "Done", next: "Next", previous: "Previous", progress: "Step {{current}}" };
let tour: ReturnType<typeof createWhatsNewTour>;
let main: HTMLElement;
let result: ReturnType<typeof tour.start> | undefined;

function click(selector: string) {
  const button = document.querySelector<HTMLButtonElement>(selector);
  if (!button) throw new Error(`Missing spotlight button: ${selector}`);
  button.click();
}

beforeEach(() => {
  vi.resetAllMocks();
  result = undefined;
  main = document.createElement("main");
  document.body.append(main);
  tour = createWhatsNewTour();
  preloadData.mockResolvedValue({ type: "loaded", status: 200, data: {} });
  goto.mockImplementation(async (href) => {
    tour.beforeNavigation(new URL(href, window.location.href));
    main.replaceChildren();
    const anchor = document.createElement("section");
    anchor.dataset.tour = String(href).slice(1);
    const feature = document.createElement("button");
    feature.textContent = `Feature ${href}`;
    anchor.append(feature);
    main.append(anchor);
  });
});

afterEach(async () => {
  tour.stop();
  await result?.catch(() => undefined);
  main.remove();
});

describe("walkthrough navigation and spotlight contract", () => {
  it("reuses the current preload and waits for actual next/previous/done clicks", async () => {
    result = tour.start(steps, labels);
    await vi.waitFor(() =>
      expect(document.querySelector(".driver-popover-title")?.textContent).toBe("Feature a")
    );
    expect(preloadData).toHaveBeenCalledExactlyOnceWith("/a");
    expect(goto).toHaveBeenCalledExactlyOnceWith("/a");
    expect(document.activeElement).toBe(document.querySelector(".driver-popover-next-btn"));
    click(".driver-popover-next-btn");
    await vi.waitFor(() =>
      expect(document.querySelector(".driver-popover-title")?.textContent).toBe("Feature b")
    );
    expect(document.querySelector(".driver-popover-progress-text")?.textContent).toBe("Step 2");
    expect(document.querySelector<HTMLButtonElement>(".driver-popover-prev-btn")?.disabled).toBe(
      false
    );
    click(".driver-popover-prev-btn");
    await vi.waitFor(() =>
      expect(document.querySelector(".driver-popover-title")?.textContent).toBe("Feature a")
    );
    click(".driver-popover-next-btn");
    await vi.waitFor(() =>
      expect(document.querySelector(".driver-popover-next-btn")?.textContent).toBe("Done")
    );
    window.dispatchEvent(new KeyboardEvent("keyup", { key: "ArrowLeft" }));
    await vi.waitFor(() =>
      expect(document.querySelector(".driver-popover-title")?.textContent).toBe("Feature a")
    );
    window.dispatchEvent(new KeyboardEvent("keyup", { key: "ArrowRight" }));
    await vi.waitFor(() =>
      expect(document.querySelector(".driver-popover-title")?.textContent).toBe("Feature b")
    );
    click(".driver-popover-next-btn");
    expect(await result).toBe("completed");
    expect(document.querySelector(".driver-popover")).toBeNull();
    expect(preloadData.mock.calls).toEqual(goto.mock.calls);
    expect(get(tour.running)).toBe(false);
    expect(document.activeElement).toBe(main.querySelector("button"));
  });

  it("destroys the spotlight and stops navigation when the app leaves the tour", async () => {
    result = tour.start(steps, labels);
    await vi.waitFor(() => expect(document.querySelector(".driver-popover")).not.toBeNull());
    click(".driver-popover-close-btn");
    expect(await result).toBe("cancelled");
    expect(document.querySelector(".driver-popover")).toBeNull();
    goto.mockClear();
    result = tour.start(steps, labels);
    await vi.waitFor(() => expect(document.querySelector(".driver-popover")).not.toBeNull());
    tour.beforeNavigation(new URL("/account", window.location.href));
    expect(await result).toBe("cancelled");
    expect(document.querySelector(".driver-popover")).toBeNull();
    expect(document.querySelector(".driver-overlay")).toBeNull();
    expect(goto).toHaveBeenCalledOnce();
  });

  it("cancels an anchor wait without creating a late spotlight", async () => {
    goto.mockImplementation(async (href) =>
      tour.beforeNavigation(new URL(href, window.location.href))
    );
    result = tour.start(steps, labels);
    await vi.waitFor(() => expect(goto).toHaveBeenCalledOnce());
    tour.stop();
    expect(await result).toBe("cancelled");
    const late = document.createElement("section");
    late.dataset.tour = "a";
    main.append(late);
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    expect(document.querySelector(".driver-popover")).toBeNull();
    expect(goto).toHaveBeenCalledOnce();
  });
});
