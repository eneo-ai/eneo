// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import type { Permission } from "@/lib/auth/permissions";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { flowPermissions, makeFlow } from "./flow-fixtures";
import { flowKeys, type FlowSparse } from "./flows-api";
import messages from "@/lib/i18n/messages/sv.json";
import { FlowsPage } from "./flows-page";

const router = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
const api = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(),
  PATCH: vi.fn(),
  PUT: vi.fn(),
  DELETE: vi.fn()
}));

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));
vi.mock("@/lib/navigation", () => ({ useRouter: () => router, usePathname: () => "/" }));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const { makeSpace: space } = await import("@/features/spaces/testing/space-fixture");
  return { useSpace: () => useSpaceFromQuery(() => space({})) };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const sparse = (overrides: Partial<FlowSparse>): FlowSparse => {
  const flow: Partial<ReturnType<typeof makeFlow>> = makeFlow();
  delete flow.steps;
  return { ...(flow as FlowSparse), ...overrides };
};

function renderPage(
  flows: FlowSparse[],
  permissions: Permission[] = ["flows_view", "flows_manage"]
) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["spaces", "space-1"], makeSpace({}));
  queryClient.setQueryData(flowKeys.list("space-1"), flows);
  return renderInApp(<FlowsPage />, {
    queryClient,
    appContext: testAppContext({ permissions })
  });
}

describe("FlowsPage", () => {
  it("lists the space's flows with their state and links to each", async () => {
    const { container } = renderPage([
      sparse({ id: "f1", name: "Medborgarbrev", published_version: 2, step_count: 3 }),
      sparse({ id: "f2", name: "Remissvar", description: null, step_count: 1 })
    ]);
    const table = screen.getByRole("table", { name: "Flöden" });
    const link = within(table).getByRole("link", { name: "Medborgarbrev" });
    expect(link.getAttribute("href")).toBe("/spaces/space-1/flows/f1");
    expect(within(table).getByText("Publicerad, version 2")).toBeTruthy();
    expect(within(table).getByText("Utkast")).toBeTruthy();
    expect(within(table).getByText("3 steg")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("offers a first flow when the space has none, and only to those who manage flows", () => {
    renderPage([]);
    expect(screen.getByRole("heading", { name: "Inga flöden än" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Nytt flöde" })).toHaveLength(2);
    cleanup();
    renderPage([], ["flows_view"]);
    expect(screen.queryByRole("button", { name: "Nytt flöde" })).toBeNull();
  });

  it("creates a flow with a name and description and opens it", async () => {
    api.POST.mockResolvedValue({
      data: makeFlow({ id: "new-flow", name: "Bygglov", steps: [] }),
      response: new Response(null, { status: 201 })
    });
    renderPage([]);
    fireEvent.click(screen.getAllByRole("button", { name: "Nytt flöde" })[0]!);
    const dialog = await screen.findByRole("dialog", { name: "Nytt flöde" });

    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa flöde" }));
    const name = within(dialog).getByRole("textbox", { name: /Namn/ });
    await waitFor(() => expect(document.activeElement).toBe(name));
    expect(name.getAttribute("aria-invalid")).toBe("true");
    expect(api.POST).not.toHaveBeenCalled();

    fireEvent.change(name, { target: { value: " Bygglov " } });
    fireEvent.change(within(dialog).getByRole("textbox", { name: /Beskrivning/ }), {
      target: { value: "Granskar ansökningar." }
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa flöde" }));

    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/spaces/space-1/flows/new-flow"));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/flows/", {
      body: {
        space_id: "space-1",
        name: "Bygglov",
        description: "Granskar ansökningar."
      }
    });
  });

  it("says at the name when the space already has a flow by that name", async () => {
    api.POST.mockResolvedValue({
      error: { code: "flow_name_taken", message: "Taken.", eneo_error_code: 9017 },
      response: new Response(null, { status: 409 })
    });
    renderPage([]);
    fireEvent.click(screen.getAllByRole("button", { name: "Nytt flöde" })[0]!);
    const dialog = await screen.findByRole("dialog", { name: "Nytt flöde" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: /Namn/ }), {
      target: { value: "Medborgarbrev" }
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa flöde" }));

    expect(
      await within(dialog).findByText(
        "Det finns redan ett flöde med det namnet i ytan. Välj ett annat namn."
      )
    ).toBeTruthy();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("offers deletion only of the flows the core lets the caller delete", () => {
    renderPage([
      sparse({ id: "f1", name: "Medborgarbrev" }),
      sparse({ id: "f2", name: "Remissvar", permissions: flowPermissions({ can_delete: false }) })
    ]);
    expect(screen.getByRole("button", { name: "Ta bort Medborgarbrev" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Ta bort Remissvar" })).toBeNull();
    cleanup();
    renderPage([
      sparse({ id: "f2", name: "Remissvar", permissions: flowPermissions({ can_delete: false }) })
    ]);
    expect(screen.queryByRole("columnheader", { name: "Åtgärder" })).toBeNull();
  });

  it("says in words why a deletion was refused", async () => {
    api.DELETE.mockResolvedValue({
      error: { code: "insufficient_space_permission", message: "No.", eneo_error_code: 9007 },
      response: new Response(null, { status: 403 })
    });
    renderPage([sparse({ id: "f1", name: "Medborgarbrev" })]);
    fireEvent.click(screen.getByRole("button", { name: "Ta bort Medborgarbrev" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(messages.flows_refusal_no_permission)
    );
  });

  it("warns before deleting a flow whose runs' evidence could then never be downloaded", async () => {
    renderPage([
      sparse({ id: "f1", name: "Medborgarbrev", metadata_json: null }),
      sparse({
        id: "f2",
        name: "Remissvar",
        metadata_json: { evidence_policy: { allow_export: true } }
      })
    ]);

    fireEvent.click(screen.getByRole("button", { name: "Ta bort Medborgarbrev" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort ”Medborgarbrev”?" });
    expect(
      within(dialog).getByText(new RegExp(messages.flow_delete_evidence_export_off))
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Ta bort Remissvar" }));
    const allowed = await screen.findByRole("alertdialog", { name: "Ta bort ”Remissvar”?" });
    expect(within(allowed).getByText(messages.flows_delete_description)).toBeTruthy();
    expect(
      within(allowed).queryByText(new RegExp(messages.flow_delete_evidence_export_off))
    ).toBeNull();
  });
});
