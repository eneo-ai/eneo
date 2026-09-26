// @vitest-environment jsdom
import { act, cleanup, screen } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, expect, it, vi } from "vitest";

// Vitest does not process CSS, so record that the Toaster imports it.
const stylesheet = vi.hoisted(() => ({ imported: false }));
vi.mock("sonner/dist/styles.css", () => {
  stylesheet.imported = true;
  return {};
});

import { renderInApp } from "@/test/render";
import { Toaster } from "./sonner";

afterEach(() => {
  // Unmount the toasters: each unsubscribes from sonner's store and its
  // toasts' timers stop, so no React work runs after the test.
  cleanup();
  // Sonner's store is module-wide and replays the toasts still showing to
  // the next Toaster that subscribes: dismiss them, so none outlives its test.
  toast.dismiss();
  vi.restoreAllMocks();
});

it("styles toasts from the bundled stylesheet instead of an injected <style>", async () => {
  // The Toaster reads its labels from next-intl, so render it in the app providers.
  renderInApp(<Toaster theme="light" />);
  toast("Sparat");

  expect(await screen.findByText("Sparat")).toBeTruthy();
  expect(stylesheet.imported).toBe(true);
  // The nonce-based style-src CSP (src/proxy.ts) blocks and reports every
  // <style> without the request nonce, so Sonner must not inject one. After a
  // sonner upgrade bun silently skips the stale frontend/patches/sonner@*.patch;
  // recreate it for the new version with `bun patch sonner`.
  expect(document.querySelectorAll("style")).toHaveLength(0);
});

it("finds open dialogs without watching every DOM change on the page", () => {
  // A body-wide MutationObserver ran on each streamed chat token; dialogs
  // report themselves instead (open-modals.ts).
  const observe = vi.spyOn(MutationObserver.prototype, "observe");
  renderInApp(<Toaster theme="light" />);
  expect(observe).not.toHaveBeenCalledWith(
    document.body,
    expect.objectContaining({ subtree: true })
  );
});

it("leaves no toaster or toast behind for the next test", async () => {
  // Runs after the tests above, which showed "Sparat".
  expect(screen.queryByRole("region", { name: /Aviseringar/ })).toBeNull();
  renderInApp(<Toaster theme="light" />);
  // A new Toaster takes over the toasts still in sonner's store a task later.
  await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
  expect(screen.queryByText("Sparat")).toBeNull();
});
