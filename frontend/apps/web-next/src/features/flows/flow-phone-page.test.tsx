// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Suspense } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import type { Permission } from "@/lib/auth/permissions";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { flowPermissions, makeFlow } from "./flow-fixtures";
import { flowKeys, type FlowPublic } from "./flows-api";
import { FlowPage } from "./flow-page";

const router = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }));
const api = vi.hoisted(() => ({
  GET: vi.fn(async (path: string) => {
    if (path === "/api/v1/flows/{id}/runs/") {
      return {
        data: {
          count: 0,
          items: [],
          has_more: false,
          status_counts: {
            queued: 0,
            running: 0,
            awaiting_review: 0,
            completed: 0,
            failed: 0,
            cancelled: 0
          }
        },
        response: new Response()
      };
    }
    if (path === "/api/v1/flows/{id}/run-contract/") {
      const { makeContract: contract } = await import("./runs/run-fixtures");
      return { data: contract(), response: new Response() };
    }
    return { data: undefined, response: new Response() };
  }),
  POST: vi.fn(),
  PATCH: vi.fn(),
  PUT: vi.fn(),
  DELETE: vi.fn()
}));

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
  useSpaceSegments: () => []
}));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const { makeSpace: space } = await import("@/features/spaces/testing/space-fixture");
  return { useSpace: () => useSpaceFromQuery(() => space({})) };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderPhonePage(
  overrides: Partial<FlowPublic> = {},
  permissions: Permission[] = ["flows_view", "flows_run"]
) {
  setViewport("phone");
  const flow = makeFlow({
    published_version: 2,
    description: "Skriver ut mötet och gör ett protokoll.",
    input_type: "audio",
    output_type: "docx",
    permissions: flowPermissions({ can_edit: true, can_run: true, can_view_runs: true }),
    ...overrides
  });
  const queryClient = testQueryClient();
  queryClient.setQueryData(flowKeys.flow(flow.id), flow);
  queryClient.setQueryData(["spaces", "space-1"], makeSpace({}));
  return renderInApp(
    <Suspense>
      <FlowPage flowId={flow.id} />
    </Suspense>,
    { queryClient, appContext: testAppContext({ permissions }) }
  );
}

describe("FlowPage on a phone", () => {
  it("shows what the flow is, what it takes and gives, its runs and a docked button to run it", async () => {
    const { container } = renderPhonePage();
    expect(await screen.findByRole("heading", { level: 1, name: "Medborgarbrev" })).toBeTruthy();
    expect(screen.getByText("Skriver ut mötet och gör ett protokoll.")).toBeTruthy();
    expect(screen.getByText("Indata: Ljud · Resultat: Word-dokument")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Körningar" })).toBeTruthy();
    const docked = screen.getByRole("group", { name: "Åtgärder för flödet" });
    expect(within(docked).getByRole("button", { name: "Kör flödet" })).toBeTruthy();
    expect(
      within(document.querySelector("[data-phone-page-bar]")!)
        .getByRole("link", { name: /Flöden/ })
        .getAttribute("href")
    ).toBe("/spaces/space-1/flows");
    await expectNoAxeViolations(container);
  });

  it("offers no editing, only where it is done", async () => {
    renderPhonePage();
    await screen.findByRole("heading", { level: 1, name: "Medborgarbrev" });
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.queryByRole("button", { name: /Publicera|Exportera/ })).toBeNull();
    expect(screen.getByText("Redigera flödet på dator.")).toBeTruthy();
    cleanup();
    renderPhonePage({
      permissions: flowPermissions({ can_edit: false, can_run: true, can_view_runs: true })
    });
    await screen.findByRole("heading", { level: 1, name: "Medborgarbrev" });
    expect(screen.queryByText("Redigera flödet på dator.")).toBeNull();
  });

  it("opens the start form from the docked button", async () => {
    renderPhonePage();
    fireEvent.click(await screen.findByRole("button", { name: "Kör flödet" }));
    expect(await screen.findByRole("dialog", { name: "Kör Medborgarbrev" })).toBeTruthy();
  });

  it("is still the lean page, with its start form and what was typed in it, when the phone is turned", async () => {
    renderPhonePage();
    fireEvent.click(await screen.findByRole("button", { name: "Kör flödet" }));
    const dialog = await screen.findByRole("dialog", { name: "Kör Medborgarbrev" });
    const name = await within(dialog).findByLabelText(/^Namn på körningen/);
    fireEvent.change(name, { target: { value: "Budgetmötet" } });

    // Sideways it is 844 px wide, but it is a phone still: nothing is swapped, nothing remounts.
    act(() => setViewport({ width: 844, height: 390, pointer: "coarse" }));
    expect(screen.getByRole("dialog", { name: "Kör Medborgarbrev" })).toBe(dialog);
    expect(within(dialog).getByLabelText(/^Namn på körningen/)).toBe(name);
    expect((name as HTMLInputElement).value).toBe("Budgetmötet");
    // A phone's layout held either way: the page bar leads back to Flöden and "Kör flödet" stays
    // docked, so the page brings no breadcrumbs of its own.
    expect(screen.getByRole("group", { name: "Åtgärder för flödet" })).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: "Sökväg" })).toBeNull();
    expect(screen.getAllByRole("button", { name: "Kör flödet" })).toHaveLength(1);
    expect(screen.queryByRole("tab", { hidden: true })).toBeNull();
  });

  it('docks "Kör flödet" and has no breadcrumbs of its own below 768 px', async () => {
    renderPhonePage();
    await screen.findByRole("heading", { level: 1, name: "Medborgarbrev" });
    expect(screen.getByRole("group", { name: "Åtgärder för flödet" })).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: "Sökväg" })).toBeNull();
  });

  it("keeps the start form, and what was typed in it, when a tablet is split down to a phone's width", async () => {
    setViewport("tablet-portrait");
    const flow = makeFlow({
      published_version: 2,
      permissions: flowPermissions({ can_edit: true, can_run: true, can_view_runs: true })
    });
    const queryClient = testQueryClient();
    queryClient.setQueryData(flowKeys.flow(flow.id), flow);
    queryClient.setQueryData(["spaces", "space-1"], makeSpace({}));
    renderInApp(
      <Suspense>
        <FlowPage flowId={flow.id} />
      </Suspense>,
      { queryClient, appContext: testAppContext({ permissions: ["flows_view", "flows_run"] }) }
    );
    // The workspace, with its tabs.
    await screen.findByRole("heading", { level: 1, name: "Medborgarbrev" });
    expect(screen.getAllByRole("tab").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Kör flödet" }));
    const dialog = await screen.findByRole("dialog", { name: "Kör Medborgarbrev" });
    fireEvent.change(await within(dialog).findByLabelText(/^Namn på körningen/), {
      target: { value: "Budgetmötet" }
    });

    act(() => setViewport({ width: 600, height: 900, pointer: "coarse" }));
    // The lean page takes the workspace's place; the form stays, as does what was typed.
    expect(await screen.findByRole("group", { name: "Åtgärder för flödet" })).toBeTruthy();
    expect(screen.getByRole("dialog", { name: "Kör Medborgarbrev" })).toBe(dialog);
    expect((within(dialog).getByLabelText(/^Namn på körningen/) as HTMLInputElement).value).toBe(
      "Budgetmötet"
    );
  });

  it("says a flow that is not published cannot be run, and does not offer to", async () => {
    renderPhonePage({ published_version: null });
    expect(
      await screen.findByText("Flödet är inte publicerat och kan inte köras ännu.")
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Kör flödet" })).toBeNull();
  });

  it("does not offer to run a flow the caller may not run", async () => {
    renderPhonePage({
      permissions: flowPermissions({ can_edit: false, can_run: false, can_view_runs: true })
    });
    await screen.findByRole("heading", { level: 1, name: "Medborgarbrev" });
    expect(screen.queryByRole("button", { name: "Kör flödet" })).toBeNull();
    await waitFor(() => expect(api.GET).toHaveBeenCalled());
  });
});
