// @vitest-environment jsdom
import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";

const api = vi.hoisted(() => ({
  GET: vi.fn(() => Promise.resolve({ data: { items: [] }, response: new Response("{}") })),
  POST: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const space = makeSpace();
  return { useSpace: () => useSpaceFromQuery(() => space as Space) };
});

import { SpaceMembers } from "./space-members";

// Radix Select scrolls its selected option into view; jsdom has no layout.
beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
});
afterEach(() => vi.clearAllMocks());

async function openDialog(trigger: string) {
  renderInApp(<SpaceMembers />);
  fireEvent.click(screen.getAllByRole("button", { name: trigger })[0]!);
  const dialog = await screen.findByRole("dialog", { name: trigger });
  return { dialog, add: within(dialog).getByRole("button", { name: trigger }) };
}

it("says a user must be picked when adding a member, at the search field", async () => {
  const { dialog, add } = await openDialog("Lägg till medlem");
  // Never disabled: a disabled button says nothing about what is missing.
  expect((add as HTMLButtonElement).disabled).toBe(false);

  fireEvent.click(add);

  const search = within(dialog).getByLabelText("E-post");
  expect(search.getAttribute("aria-invalid")).toBe("true");
  expect(document.getElementById(search.getAttribute("aria-describedby")!)?.textContent).toBe(
    "Välj en användare i listan."
  );
  expect(document.activeElement).toBe(search);
  expect(api.POST).not.toHaveBeenCalled();
  await expectNoAxeViolations(dialog);
});

it("searches users once typing pauses, and not below three characters", async () => {
  const { dialog } = await openDialog("Lägg till medlem");
  const search = within(dialog).getByLabelText("E-post");
  const searches = () =>
    api.GET.mock.calls.filter(
      (call) =>
        (call as unknown[])[0] === "/api/v1/users/" &&
        (call as { params: { query: { email?: string | null } } }[])[1]?.params.query.email
    );

  vi.useFakeTimers();
  try {
    for (const value of ["a", "an"]) fireEvent.change(search, { target: { value } });
    act(() => vi.advanceTimersByTime(1000));
    expect(searches()).toHaveLength(0);

    for (const value of ["ann", "anna", "anna."]) fireEvent.change(search, { target: { value } });
    act(() => vi.advanceTimersByTime(1000));
    expect(searches()).toHaveLength(1);
    expect(searches()[0]).toMatchObject([
      "/api/v1/users/",
      { params: { query: { email: "anna." } } }
    ]);
  } finally {
    vi.useRealTimers();
  }
});

it("says a group must be picked when adding a group, at its picker", async () => {
  const { dialog, add } = await openDialog("Lägg till grupp");

  fireEvent.click(add);

  const group = within(dialog).getByRole("combobox", { name: "Användargrupper" });
  expect(group.getAttribute("aria-invalid")).toBe("true");
  expect(document.activeElement).toBe(group);
  expect(api.POST).not.toHaveBeenCalled();
});
