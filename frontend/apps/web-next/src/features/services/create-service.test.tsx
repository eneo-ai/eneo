// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const space = makeSpace();
  return { useSpace: () => useSpaceFromQuery(() => space as Space) };
});

import { CreateServiceButton } from "./create-service";

afterEach(() => vi.clearAllMocks());

it("shows a missing name at the field on create, which takes focus", async () => {
  api.POST.mockReturnValue(new Promise(() => {}));
  renderInApp(<CreateServiceButton />);
  fireEvent.click(screen.getByRole("button", { name: "Skapa tjänst" }));
  const dialog = await screen.findByRole("dialog", { name: "Skapa en ny tjänst" });
  const create = within(dialog).getByRole("button", { name: "Skapa tjänst" });
  // Never disabled: a disabled button says nothing about what is missing.
  expect((create as HTMLButtonElement).disabled).toBe(false);

  fireEvent.click(create);
  const name = within(dialog).getByLabelText("Namn");
  expect(name.getAttribute("aria-invalid")).toBe("true");
  expect(document.activeElement).toBe(name);
  expect(api.POST).not.toHaveBeenCalled();
  await expectNoAxeViolations(dialog);

  fireEvent.change(name, { target: { value: "Diarieföring" } });
  fireEvent.click(create);
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
});
