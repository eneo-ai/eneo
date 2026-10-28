// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const reload = vi.fn();

beforeEach(() => {
  vi.stubGlobal("location", { ...window.location, reload });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  reload.mockClear();
});

/** A browser tab: its own document, so its own instance of the module. */
async function openTab() {
  vi.resetModules();
  return import("./identity-broadcast");
}

/** Longer than a message takes between channels. */
const delivered = () => new Promise((resolve) => setTimeout(resolve, 20));

it("reloads every other tab when one tab's identity changes", async () => {
  const tabs = [await openTab(), await openTab()];
  const stops = tabs.map((tab) => tab.reloadOnIdentityChange());

  (await openTab()).announceIdentityChange();
  await delivered();

  expect(reload).toHaveBeenCalledTimes(2);
  stops.forEach((stop) => stop());
});

it("does not reload the tab that announces the change", async () => {
  const tab = await openTab();
  const stop = tab.reloadOnIdentityChange();

  tab.announceIdentityChange();
  await delivered();

  expect(reload).not.toHaveBeenCalled();
  stop();
});

it("stops reloading once the listener is removed", async () => {
  const stop = (await openTab()).reloadOnIdentityChange();
  stop();

  (await openTab()).announceIdentityChange();
  await delivered();

  expect(reload).not.toHaveBeenCalled();
});

it("tells the other tabs only that the identity changed, nothing about it", async () => {
  const post = vi.spyOn(BroadcastChannel.prototype, "postMessage");

  (await openTab()).announceIdentityChange();

  expect(post.mock.calls).toEqual([["identity-changed"]]);
});
