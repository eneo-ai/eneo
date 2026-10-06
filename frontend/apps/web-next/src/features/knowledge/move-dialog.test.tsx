// @vitest-environment jsdom
import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: () =>
      Promise.resolve({
        data: { items: [{ id: "s2", name: "HR", personal: false, organization: false }] },
        response: new Response("{}")
      })
  }
}));
vi.mock("@/features/spaces/use-space", async () => {
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const space = makeSpace();
  return { useSpace: () => useSpaceFromQuery(() => space as Space) };
});

import { MoveResourceDialog } from "./move-dialog";

// Radix Select scrolls its selected option into view; jsdom has no layout.
beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
});
afterEach(() => vi.clearAllMocks());

it("shows a missing destination at its picker on move, which takes focus", async () => {
  const onMove = vi.fn();
  renderInApp(
    <MoveResourceDialog
      open
      onOpenChange={() => {}}
      title="Flytta samling"
      confirmLabel="Flytta"
      pending={false}
      onMove={onMove}
    />
  );
  const dialog = screen.getByRole("dialog", { name: "Flytta samling" });
  const move = within(dialog).getByRole("button", { name: "Flytta" });
  // Never disabled: a disabled button says nothing about what is missing.
  expect((move as HTMLButtonElement).disabled).toBe(false);

  fireEvent.click(move);

  const destination = within(dialog).getByRole("combobox", { name: "Destination" });
  expect(destination.getAttribute("aria-invalid")).toBe("true");
  expect(document.getElementById(destination.getAttribute("aria-describedby")!)?.textContent).toBe(
    "Välj en yta"
  );
  expect(document.activeElement).toBe(destination);
  expect(onMove).not.toHaveBeenCalled();
  await expectNoAxeViolations(dialog);
});
