// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { toast } from "sonner";
import { expect, it, vi } from "vitest";

// Vitest does not process CSS, so record that the Toaster imports it.
const stylesheet = vi.hoisted(() => ({ imported: false }));
vi.mock("sonner/dist/styles.css", () => {
  stylesheet.imported = true;
  return {};
});

import { Toaster } from "./sonner";

it("styles toasts from the bundled stylesheet instead of an injected <style>", async () => {
  render(<Toaster theme="light" />);
  toast("Sparat");

  expect(await screen.findByText("Sparat")).toBeTruthy();
  expect(stylesheet.imported).toBe(true);
  // The nonce-based style-src CSP (src/proxy.ts) blocks and reports every
  // <style> without the request nonce, so Sonner must not inject one. After a
  // sonner upgrade bun silently skips the stale frontend/patches/sonner@*.patch;
  // recreate it for the new version with `bun patch sonner`.
  expect(document.querySelectorAll("style")).toHaveLength(0);
});
