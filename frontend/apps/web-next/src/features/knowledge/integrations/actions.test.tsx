// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";
import type { IntegrationKnowledge } from "../knowledge";

const api = vi.hoisted(() => ({ PATCH: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn()
}));
vi.mock("@/lib/toast", () => ({ toast }));
const jobs = vi.hoisted(() => ({ trackJob: vi.fn() }));
vi.mock("@/features/jobs/use-jobs", () => ({ useJobs: () => jobs }));
vi.mock("@/features/spaces/use-space", async () => {
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const space = makeSpace();
  return { useSpace: () => useSpaceFromQuery(() => space as Space) };
});

import { IntegrationActions, WrapperActions } from "./actions";
import { pendingSyncs, resetPendingSyncs } from "./pending-syncs";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  resetPendingSyncs();
});

const policies = {
  id: "i1",
  name: "Policydokument",
  integration_type: "sharepoint",
  permissions: ["edit", "delete"]
} as IntegrationKnowledge;

async function openMenu() {
  fireEvent.click(screen.getByRole("button", { name: /Policydokument/ }));
  await screen.findByRole("menuitem", { name: "Byt namn" });
}

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

it("saves a rename with Enter, without the spaces around the name", async () => {
  api.PATCH.mockReturnValue(new Promise(() => {}));
  renderInApp(<IntegrationActions item={policies} />);
  await openMenu();
  fireEvent.click(screen.getByRole("menuitem", { name: "Byt namn" }));
  const dialog = await screen.findByRole("dialog", { name: "Byt namn på integration" });
  const name = within(dialog).getByLabelText<HTMLInputElement>("Namn");
  const save = within(dialog).getByRole<HTMLButtonElement>("button", { name: "Spara" });
  // Enter in the field submits its form, which Spara belongs to.
  expect(name.form).not.toBeNull();
  expect(save.type).toBe("submit");
  expect(save.form).toBe(name.form);
  // The longest name the server takes.
  expect(name.maxLength).toBe(255);

  fireEvent.change(name, { target: { value: "  Policyer 2026 " } });
  fireEvent.submit(name.form!);

  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
  expect(api.PATCH.mock.calls[0]?.[1]).toMatchObject({ body: { name: "Policyer 2026" } });
});

it("renames a group without the spaces around its name", async () => {
  api.PATCH.mockReturnValue(new Promise(() => {}));
  renderInApp(
    <WrapperActions
      wrapperId="w1"
      wrapperName="Byggnad"
      items={[{ ...policies, wrapper_id: "w1" }]}
      canEdit
      canDelete={false}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: /Byggnad/ }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "Byt namn på grupp" }));
  const dialog = await screen.findByRole("dialog", { name: "Byt namn på grupp" });
  const name = within(dialog).getByLabelText<HTMLInputElement>("Namn");
  fireEvent.change(name, { target: { value: " Byggnader  " } });
  fireEvent.submit(name.form!);

  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
  expect(api.PATCH.mock.calls[0]?.[1]).toMatchObject({ body: { name: "Byggnader" } });
});

it("keeps focus on a busy full sync and starts one", async () => {
  api.POST.mockReturnValue(new Promise(() => {}));
  renderInApp(<IntegrationActions item={policies} />);
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

it("follows the full sync from the job it returned", async () => {
  const job = { id: "job-1", name: "Policydokument", status: "queued" };
  api.POST.mockResolvedValue({ data: job, response: new Response("{}", { status: 202 }) });
  renderInApp(<IntegrationActions item={policies} />);
  await openMenu();
  fireEvent.click(screen.getByRole("menuitem", { name: "Fullständig synk" }));
  const dialog = await screen.findByRole("alertdialog", { name: "Fullständig synk" });

  fireEvent.click(within(dialog).getByRole("button", { name: "Starta fullständig synk" }));

  // So a sync that is done before the first poll still counts as done.
  await waitFor(() => expect(jobs.trackJob).toHaveBeenCalledWith(job));
  // The item reads as queued until the worker reports on it or the job is over.
  expect(pendingSyncs()).toEqual([{ jobId: "job-1", knowledgeId: "i1" }]);
});

it("offers no second full sync while one is queued or running, and says why", async () => {
  renderInApp(<IntegrationActions item={policies} syncActive />);
  fireEvent.click(screen.getByRole("button", { name: /Policydokument/ }));

  const busy = await screen.findByRole("menuitem", { name: "En synk är redan köad eller pågår" });
  expect(busy.getAttribute("aria-disabled")).toBe("true");
  expect(screen.queryByRole("menuitem", { name: "Fullständig synk" })).toBeNull();
  fireEvent.click(busy);
  expect(screen.queryByRole("alertdialog")).toBeNull();
  expect(api.POST).not.toHaveBeenCalled();
});

it("offers a rename or full sync only of an item the user may edit", async () => {
  // The backend reports no edit for the organisation's SharePoint to non-admins.
  renderInApp(<IntegrationActions item={{ ...policies, permissions: ["read", "delete"] }} />);
  fireEvent.click(screen.getByRole("button", { name: /Policydokument/ }));

  expect(await screen.findByRole("menuitem", { name: "Ta bort" })).toBeTruthy();
  expect(screen.queryByRole("menuitem", { name: "Fullständig synk" })).toBeNull();
  expect(screen.queryByRole("menuitem", { name: "Byt namn" })).toBeNull();
});

it("resyncs a group's folders four at a time and names at most five it could not queue", async () => {
  const folders = Array.from(
    { length: 7 },
    (_, index) =>
      ({
        ...policies,
        id: `f${index}`,
        name: `Mapp ${index}`,
        wrapper_id: "w1"
      }) as IntegrationKnowledge
  );
  let inFlight = 0;
  let most = 0;
  api.POST.mockImplementation(
    async (_path: string, options: { params: { path: { integration_knowledge_id: string } } }) => {
      inFlight += 1;
      most = Math.max(most, inFlight);
      await new Promise((resolve) => setTimeout(resolve, 5));
      inFlight -= 1;
      const id = options.params.path.integration_knowledge_id;
      return id === "f0"
        ? { data: { id: "job-f0", name: "Mapp 0", status: "queued" }, response: new Response("{}") }
        : { error: { message: "Nej" }, response: new Response("{}", { status: 403 }) };
    }
  );
  renderInApp(
    <WrapperActions
      wrapperId="w1"
      wrapperName="Byggnad"
      items={folders}
      canEdit
      canDelete={false}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: /Byggnad/ }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "Synka om alla objekt" }));
  const dialog = await screen.findByRole("alertdialog", { name: "Synka om alla objekt" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Starta fullständig synk" }));

  await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
  expect(api.POST).toHaveBeenCalledTimes(7);
  expect(most).toBe(4);
  expect(toast.error.mock.calls[0]?.[0]).toBe(
    "6 av 7 objekt kunde inte köas: Mapp 1, Mapp 2, Mapp 3, Mapp 4, Mapp 5, …"
  );
});

it("says a source cannot be renamed while it syncs, in the viewer's words", async () => {
  api.PATCH.mockResolvedValue({
    error: {
      message: "Knowledge is syncing",
      eneo_error_code: 9007,
      code: "integration_knowledge_syncing"
    },
    response: new Response("{}", { status: 409 })
  });
  renderInApp(<IntegrationActions item={policies} />);
  await openMenu();
  fireEvent.click(screen.getByRole("menuitem", { name: "Byt namn" }));
  const dialog = await screen.findByRole("dialog", { name: "Byt namn på integration" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));

  await waitFor(() =>
    expect(toast.error).toHaveBeenCalledWith(
      "Källan synkas just nu. Försök igen när synken är klar.",
      expect.anything()
    )
  );
});
