// @vitest-environment jsdom
import { screen } from "@testing-library/react";
import { toast } from "sonner";
import { expect, it, vi } from "vitest";

// Vitest does not process CSS, so record that the Toaster imports it.
const stylesheet = vi.hoisted(() => ({ imported: false }));
vi.mock("sonner/dist/styles.css", () => {
  stylesheet.imported = true;
  return {};
});

import { renderInApp } from "@/test/render";
import { Toaster } from "./sonner";

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
  observe.mockRestore();
});
