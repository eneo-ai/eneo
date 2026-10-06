// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";
import type { IntegrationKnowledge } from "../knowledge";

const api = vi.hoisted(() => ({ PATCH: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/features/jobs/use-jobs", () => ({ useJobs: () => ({ trackJob: vi.fn() }) }));
vi.mock("@/features/spaces/use-space", async () => {
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const space = makeSpace();
  return { useSpace: () => useSpaceFromQuery(() => space as Space) };
});

import { IntegrationActions } from "./actions";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("shows an empty name at the field on rename, which takes focus", async () => {
  api.PATCH.mockReturnValue(new Promise(() => {}));
  renderInApp(
    <IntegrationActions
      item={
        {
          id: "i1",
          name: "Policydokument",
          permissions: ["edit", "delete"]
        } as IntegrationKnowledge
      }
    />
  );
  fireEvent.click(screen.getByRole("button", { name: /Policydokument/ }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "Byt namn" }));
  const dialog = await screen.findByRole("dialog", { name: "Byt namn på integration" });
  const name = within(dialog).getByLabelText("Namn");
  const save = within(dialog).getByRole("button", { name: "Spara" });
  fireEvent.change(name, { target: { value: " " } });
  // Never disabled: a disabled button says nothing about what is missing.
  expect((save as HTMLButtonElement).disabled).toBe(false);

  fireEvent.click(save);

  expect(name.getAttribute("aria-invalid")).toBe("true");
  expect(document.activeElement).toBe(name);
  expect(api.PATCH).not.toHaveBeenCalled();
  await expectNoAxeViolations(dialog);

  fireEvent.change(name, { target: { value: "Policyer 2026" } });
  fireEvent.click(save);
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
});

it("keeps focus on a busy full sync and starts one", async () => {
  api.POST.mockReturnValue(new Promise(() => {}));
  renderInApp(
    <IntegrationActions
      item={
        {
          id: "i1",
          name: "Policydokument",
          integration_type: "sharepoint",
          permissions: ["edit", "delete"]
        } as IntegrationKnowledge
      }
    />
  );
  fireEvent.click(screen.getByRole("button", { name: /Policydokument/ }));
  const syncItem = await screen.findByRole("menuitem", { name: "Fullständig synk" });
  // The menu moves focus into itself on the next frame; let it, as a user would.
  await act(() => new Promise((resolve) => requestAnimationFrame(resolve)));
  fireEvent.click(syncItem);
  const dialog = await screen.findByRole("alertdialog", { name: "Fullständig synk" });
  const start = within(dialog).getByRole("button", { name: "Starta fullständig synk" });
  start.focus();

  fireEvent.click(start);

  const busy = await within(dialog).findByRole("button", { name: "Synkroniserar..." });
  expect(busy).toBe(start);
  expect(busy.getAttribute("aria-busy")).toBe("true");
  expect(busy.hasAttribute("disabled")).toBe(false);
  expect(document.activeElement).toBe(busy);
  fireEvent.click(busy);
  expect(api.POST).toHaveBeenCalledTimes(1);
});
