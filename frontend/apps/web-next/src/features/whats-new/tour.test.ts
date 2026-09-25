// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReleaseEntry } from "@eneo/whats-new";

const driverMock = vi.hoisted(() => vi.fn());
vi.mock("driver.js", () => ({ driver: driverMock }));

import { runTour } from "./tour";

const entry = (id: string, href: string): ReleaseEntry => ({
  id,
  type: "new",
  area: "admin",
  title: { en: id, sv: id },
  body: { en: `${id} body`, sv: `${id} text` },
  showMe: { href, anchor: id }
});
const labels = {
  done: "Done",
  next: "Next",
  previous: "Previous",
  progress: "Step {current} of {total}",
  version: "v2.2.0"
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 200 })));
  HTMLElement.prototype.scrollIntoView = vi.fn();
  driverMock.mockImplementation((options: { onNextClick: () => void }) => ({
    drive: () => options.onNextClick(),
    destroy: vi.fn()
  }));
  window.history.replaceState(null, "", "/whats-new");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetAllMocks();
  document.body.replaceChildren();
});

describe("What's new tour", () => {
  it("visits available entries in order and maps the combined governance page", async () => {
    const navigate = vi.fn((href: string) => {
      window.history.pushState(null, "", href);
      const anchor =
        href === "/admin/personal-assistant" ? "admin-personal-assistant" : "admin-modules";
      document.body.innerHTML = `<section data-tour="${anchor}"></section>`;
    });
    const outcome = await runTour(
      [
        entry("admin-personal-assistant", "/admin/personal-assistant/configuration"),
        entry("admin-modules", "/admin/modules")
      ],
      "en",
      labels,
      navigate,
      new AbortController().signal
    );
    expect(outcome).toBe("completed");
    expect(navigate.mock.calls.map(([href]) => href)).toEqual([
      "/admin/personal-assistant",
      "/admin/modules"
    ]);
  });

  it("skips a denied page before navigating", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response("", { status: 403 }))
      .mockResolvedValueOnce(new Response("", { status: 200 }));
    const navigate = vi.fn((href: string) => {
      window.history.pushState(null, "", href);
      document.body.innerHTML = '<section data-tour="admin-modules"></section>';
    });
    expect(
      await runTour(
        [entry("denied", "/admin/denied"), entry("admin-modules", "/admin/modules")],
        "en",
        labels,
        navigate,
        new AbortController().signal
      )
    ).toBe("completed");
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/admin/modules");
  });
});
