// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ReleaseEntry } from "@eneo/whats-new";

const entry: ReleaseEntry = {
  id: "modules",
  type: "new",
  area: "admin",
  title: { en: "Modules", sv: "Moduler" },
  body: { en: "Modules", sv: "Moduler" },
  showMe: { href: "/admin/modules", anchor: "modules" }
};
const labels = {
  done: "Done",
  next: "Next",
  previous: "Previous",
  progress: "Step",
  version: "v2"
};
const navigate = () => {
  window.history.replaceState(null, "", "/admin/modules");
  document.body.innerHTML = '<section data-tour="modules"></section>';
};

beforeEach(() => {
  vi.resetModules();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 200 })));
});
afterEach(() => {
  vi.doUnmock("driver.js");
  vi.doUnmock("driver.js/dist/driver.css");
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

it("waits for the tour assets and does not open a cancelled tour when they arrive", async () => {
  let arrive!: () => void;
  const pending = new Promise<void>((resolve) => (arrive = resolve));
  const driver = vi.fn();
  const load = vi.fn(async () => ({ driver }));
  const loadStyles = vi.fn(async () => {
    await pending;
    return {};
  });
  vi.doMock("driver.js", load);
  vi.doMock("driver.js/dist/driver.css", loadStyles);
  const { runTour } = await import("./tour");
  expect(load).not.toHaveBeenCalled();
  expect(loadStyles).not.toHaveBeenCalled();
  const controller = new AbortController();
  const tour = runTour([entry], "en", labels, navigate, controller.signal);
  await vi.waitFor(() => expect(loadStyles).toHaveBeenCalledOnce());
  expect(driver).not.toHaveBeenCalled();
  controller.abort();
  arrive();
  await expect(tour).resolves.toBe("cancelled");
  expect(driver).not.toHaveBeenCalled();
});

it("passes an asset failure to the existing tour error feedback", async () => {
  vi.doMock("driver.js", () => {
    throw new Error("Tour assets unavailable");
  });
  const { runTour } = await import("./tour");
  await expect(
    runTour([entry], "en", labels, navigate, new AbortController().signal)
  ).rejects.toMatchObject({ cause: { message: "Tour assets unavailable" } });
});
