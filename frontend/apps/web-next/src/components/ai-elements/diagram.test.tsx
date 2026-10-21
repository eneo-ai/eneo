// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { MessageResponse } from "./message";

// jsdom has no viewport or SVG layout. Keep lazy diagrams outside the viewport
// here; browser checks cover SVG rendering. Dialog and focus behaviour are real.
beforeEach(() => {
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
    }
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("opens a named diagram dialog, moves focus inside and returns it on close", async () => {
  renderInApp(
    <MessageResponse isAnimating={false}>{"```mermaid\ngraph LR\nA --> B\n```"}</MessageResponse>
  );
  const expand = screen.getByRole("button", { name: "Visa i helskärm" });
  expand.focus();
  fireEvent.click(expand);
  const dialog = await screen.findByRole("dialog", { name: "Diagram" });
  await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
  await expectNoAxeViolations(dialog);
  fireEvent.click(within(dialog).getByRole("button", { name: "Stäng" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() => expect(document.activeElement).toBe(expand));
});

it("keeps unfinished diagrams as code without offering fullscreen", () => {
  const { container } = renderInApp(
    <MessageResponse isAnimating>{"```mermaid\ngraph LR\nA -->"}</MessageResponse>
  );
  expect(container.textContent).toContain("A -->");
  expect(screen.queryByRole("button", { name: "Visa i helskärm" })).toBeNull();
});
