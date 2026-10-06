// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
const space = vi.hoisted(() => ({ current: null as unknown }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => space.current as Space) };
});

import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { CreateCollectionButton } from "./collections";

// Radix Select scrolls its selected option into view; jsdom has no layout.
beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
});
afterEach(() => vi.clearAllMocks());

async function openDialog() {
  renderInApp(<CreateCollectionButton />);
  fireEvent.click(screen.getByRole("button", { name: "Skapa samling" }));
  const dialog = await screen.findByRole("dialog", { name: "Skapa en ny samling" });
  return { dialog, create: within(dialog).getByRole("button", { name: "Skapa samling" }) };
}

it("shows a missing name at the field on create, which takes focus", async () => {
  space.current = makeSpace();
  api.POST.mockReturnValue(new Promise(() => {}));
  const { dialog, create } = await openDialog();
  // Never disabled: a disabled button says nothing about what is missing.
  expect((create as HTMLButtonElement).disabled).toBe(false);

  fireEvent.click(create);
  const name = within(dialog).getByLabelText("Namn");
  expect(name.getAttribute("aria-invalid")).toBe("true");
  expect(document.activeElement).toBe(name);
  expect(api.POST).not.toHaveBeenCalled();
  await expectNoAxeViolations(dialog);

  fireEvent.change(name, { target: { value: "Upphandlingspolicyer" } });
  fireEvent.click(create);
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
});

it("moves focus to the warning when the space has no embedding model", async () => {
  space.current = makeSpace({ overrides: { embedding_models: [] } });
  const { dialog, create } = await openDialog();

  fireEvent.click(create);

  expect(document.activeElement?.textContent).toContain(
    "Denna yta har för närvarande inga inbäddningsmodeller aktiverade"
  );
  expect(dialog.contains(document.activeElement)).toBe(true);
  expect(api.POST).not.toHaveBeenCalled();
});
