// @vitest-environment jsdom
import { createRoute } from "@tanstack/react-router";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderWithRouter } from "@/test/router";
import { testQueryClient } from "@/test/render";
import messages from "@/lib/i18n/messages/sv.json";
import { FLOW_SETTINGS_KEY } from "./flow-settings";
import { flowSettingsFixture } from "./flow-settings-fixtures";
import { FlowSettingsPage } from "./flow-settings-page";

vi.mock("@/lib/navigation", () => import("@/lib/navigation.tanstack"));
vi.mock("@/lib/link", () => import("@/lib/link.tanstack"));
const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

beforeEach(() => {
  api.GET.mockResolvedValue({
    data: {
      completion_models: [],
      embedding_models: [],
      transcription_models: [],
      image_models: []
    },
    response: new Response("{}")
  });
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

async function show() {
  const queryClient = testQueryClient();
  queryClient.setQueryData(FLOW_SETTINGS_KEY, flowSettingsFixture());
  const view = await renderWithRouter(null, {
    queryClient,
    route: "/admin/flow-settings",
    routes: (root) => [
      createRoute({
        getParentRoute: () => root,
        path: "/admin/flow-settings",
        component: FlowSettingsPage
      }),
      createRoute({
        getParentRoute: () => root,
        path: "/admin/audit-logs",
        component: () => <h1>Granskningslogg</h1>
      })
    ]
  });
  const field = await screen.findByLabelText("Antal filer per körning");
  fireEvent.focus(field);
  fireEvent.change(field, { target: { value: "40" } });
  fireEvent.blur(field);
  return view;
}

it("keeps unsaved settings after staying, then follows the original audit link after leaving", async () => {
  const { router } = await show();
  const audit = screen.getByRole("link", { name: "Ändringar loggas i granskningsloggen" });
  fireEvent.click(audit);
  const dialog = await screen.findByRole("alertdialog", {
    name: messages.unsaved_navigation_title
  });
  await expectNoAxeViolations(document.body);
  fireEvent.click(within(dialog).getByRole("button", { name: messages.cancel }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(router.state.location.pathname).toBe("/admin/flow-settings");
  expect(screen.getByText("1 osparad ändring")).toBeTruthy();

  fireEvent.click(audit);
  fireEvent.click(
    within(await screen.findByRole("alertdialog")).getByRole("button", {
      name: messages.unsaved_navigation_leave
    })
  );
  await screen.findByRole("heading", { name: "Granskningslogg" });
  expect(router.state.location.href).toBe("/admin/audit-logs?actions=tenant_settings_updated");
});

it("completes a pending navigation once the settings have been saved", async () => {
  let finish!: () => void;
  const saving = new Promise<void>((resolve) => {
    finish = resolve;
  });
  api.PATCH.mockImplementation(async () => {
    await saving;
    return {
      data: { ...flowSettingsFixture().inputLimits, max_files_per_run: 40 },
      response: new Response("{}")
    };
  });
  const { router } = await show();
  fireEvent.click(screen.getByRole("button", { name: "Spara ändringar" }));
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledOnce());
  fireEvent.click(screen.getByRole("link", { name: "Ändringar loggas i granskningsloggen" }));
  await screen.findByRole("alertdialog");
  await act(async () => {
    finish();
  });
  await screen.findByRole("heading", { name: "Granskningslogg" });
  expect(router.state.location.href).toBe("/admin/audit-logs?actions=tenant_settings_updated");
});
