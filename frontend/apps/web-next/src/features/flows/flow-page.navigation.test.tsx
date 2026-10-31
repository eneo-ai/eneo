// @vitest-environment jsdom
import {
  createBrowserHistory,
  createRoute,
  type AnyRootRoute,
  type RouterHistory
} from "@tanstack/react-router";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SpaceProvider } from "@/features/spaces/use-space";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { renderWithRouter } from "@/test/router";
import { testAppContext, testQueryClient } from "@/test/render";
import messages from "@/lib/i18n/messages/sv.json";
import { makeAssistant } from "./editor/testing/fixtures";
import { makeFlow } from "./flow-fixtures";
import { FlowPage } from "./flow-page";
import { flowKeys, type FlowPublic } from "./flows-api";
import { parseFlowSearch } from "./flow-search";

vi.unmock("@/lib/link");

const api = vi.hoisted(() => ({
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("./editor/testing/fixtures").apiStub>
}));
vi.mock("@/lib/api/browser", async () => {
  const { apiStub } = await import("./editor/testing/fixtures");
  api.stub = apiStub(new Proxy({}, { get: (_target, key: string) => api.routes[key] }));
  return { browserApi: api.stub.client };
});

const BASE = "/spaces/space-1/flows/flow-1";
let flow: FlowPublic;
let history: RouterHistory;

beforeEach(() => {
  flow = makeFlow();
  api.routes = {
    "GET /api/v1/flows/{id}/": () => ({ body: flow }),
    "GET /api/v1/flows/{id}/assistants/{assistant_id}/": () => ({ body: makeAssistant() }),
    "GET /api/v1/flows/{id}/suggestions/": () => ({ body: { draft_revision: 4, items: [] } }),
    "GET /api/v1/flows/{id}/step-kinds/": () => ({ body: { items: [] } }),
    "GET /api/v1/spaces/": () => ({ body: { items: [] } }),
    "GET /api/v1/security-classifications/": () => ({
      body: { security_classifications: [], security_enabled: false }
    }),
    "GET /api/v1/flows/{id}/tool-options": () => ({
      body: { items: [], security_classifications_enabled: false }
    }),
    "POST /api/v1/flows/{id}/security-classification/preview": () => ({ body: { steps: [] } })
  };
});
afterEach(() => {
  cleanup();
  history.destroy();
  api.stub.calls.length = 0;
});

async function renderPage(search = "") {
  window.history.replaceState(null, "", "/outside");
  window.history.pushState(null, "", BASE + search);
  history = createBrowserHistory();
  const queryClient = testQueryClient();
  queryClient.setQueryData(["spaces", "space-1"], makeSpace());
  queryClient.setQueryData(flowKeys.flow(flow.id), flow);
  return renderWithRouter(null, {
    queryClient,
    history,
    appContext: testAppContext({
      permissions: ["flows_view", "flows_manage"],
      featureFlags: { flows: true }
    }),
    routes: (root: AnyRootRoute) => [
      createRoute({
        getParentRoute: () => root,
        path: "/spaces/$spaceId/flows/$flowId",
        validateSearch: parseFlowSearch,
        component: () => (
          <SpaceProvider routeId="space-1">
            <FlowPage flowId="flow-1" />
          </SpaceProvider>
        )
      }),
      createRoute({
        getParentRoute: () => root,
        path: "/outside",
        component: () => <h1>Utanför flödet</h1>
      })
    ]
  });
}
const click = (name: string) =>
  act(async () => {
    fireEvent.click(await screen.findByRole("button", { name }));
  });
const openFirst = () => click("Redigera Steg 1: Sammanfatta");
const nameField = () => screen.findByLabelText(/^Stegnamn/);
async function changeName() {
  fireEvent.change(await nameField(), { target: { value: "Eget utkast" } });
}
async function chooseLeave() {
  const dialog = await screen.findByRole("alertdialog", {
    name: messages.unsaved_navigation_title
  });
  fireEvent.click(within(dialog).getByRole("button", { name: messages.unsaved_navigation_leave }));
}

it("uses native Back/Forward and All steps returns across the visited steps", async () => {
  const { router } = await renderPage();
  await openFirst();
  await nameField();
  expect(router.state.location.state.flowStepDepth).toBe(1);
  await click("Nästa steg: Skriv svar");
  await waitFor(() => expect(router.state.location.search).toEqual({ step: "step-2" }));
  expect(router.state.location.state.flowStepDepth).toBe(2);
  act(() => history.back());
  await waitFor(() => expect(router.state.location.search).toEqual({ step: "step-1" }));
  act(() => history.forward());
  await waitFor(() => expect(router.state.location.search).toEqual({ step: "step-2" }));
  await click("Alla steg");
  await screen.findByRole("button", { name: "Redigera Steg 2: Skriv svar" });
  expect(router.state.location.search).toEqual({});
  act(() => history.back());
  expect(await screen.findByRole("heading", { name: "Utanför flödet" })).toBeTruthy();
});

it("closes a direct step link in the same flow without traversing earlier history", async () => {
  const { router } = await renderPage("?step=step-2");
  await nameField();
  await click("Alla steg");
  await screen.findByRole("button", { name: "Redigera Steg 2: Skriv svar" });
  expect(router.state.location.href).toBe(BASE);
});

it.each(["Back", "Alla steg", "Nästa steg: Skriv svar"])(
  "can stay after %s, then leave without corrupting the history",
  async (action) => {
    const { router } = await renderPage();
    await openFirst();
    await changeName();
    const navigate = async () => {
      if (action === "Back") act(() => history.back());
      else await click(action);
    };
    await navigate();
    const dialog = await screen.findByRole("alertdialog", {
      name: messages.unsaved_navigation_title
    });
    fireEvent.click(within(dialog).getByRole("button", { name: messages.cancel }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(((await nameField()) as HTMLInputElement).value).toBe("Eget utkast");
    expect(router.state.location.search).toEqual({ step: "step-1" });
    await navigate();
    await chooseLeave();
    await waitFor(() =>
      expect(router.state.location.search).toEqual(
        action.startsWith("Nästa") ? { step: "step-2" } : {}
      )
    );
  }
);

it("releases a pending navigation after the current draft is saved", async () => {
  let saved!: () => void;
  const saving = new Promise<void>((resolve) => {
    saved = resolve;
  });
  const { router } = await renderPage();
  await openFirst();
  await changeName();
  // Hold this one real client call after its request, while navigation is attempted.
  const patch = vi.spyOn(api.stub.client, "PATCH").mockImplementationOnce(async () => {
    await saving;
    flow = makeFlow({
      draft_revision: 5,
      steps: flow.steps.map((step, index) =>
        index === 0 ? { ...step, user_description: "Eget utkast" } : step
      )
    });
    return { data: flow, response: new Response(JSON.stringify(flow)) };
  });
  await click(messages.flow_step_editor_save);
  await waitFor(() =>
    expect(patch).toHaveBeenCalledWith(expect.stringContaining("/editor/"), expect.anything())
  );
  act(() => history.back());
  await screen.findByRole("alertdialog", { name: messages.unsaved_navigation_title });
  await act(async () => saved());
  await waitFor(() => expect(router.state.location.search).toEqual({}));
  expect(screen.queryByRole("alertdialog")).toBeNull();
  patch.mockRestore();
});

it("keeps an unsaved upload on Stay and releases it only when leaving the editor", async () => {
  api.routes["GET /api/v1/flows/{id}/assistants/{assistant_id}/"] = () => ({
    body: makeAssistant({
      allowed_attachments: {
        accepted_file_types: [],
        limit: { max_files: 5, max_size: 10_000_000 }
      }
    })
  });
  api.routes["POST /api/v1/files/"] = () => ({
    body: { id: "file-new", name: "underlag.txt", size: 4, mimetype: "text/plain" }
  });
  api.routes["DELETE /api/v1/files/{id}/"] = () => ({ body: {} });
  const { container } = await renderPage();
  await openFirst();
  await nameField();
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("No attachment input");
  fireEvent.change(input, {
    target: { files: [new File(["text"], "underlag.txt", { type: "text/plain" })] }
  });
  await screen.findByText("underlag.txt");
  await click(messages.cancel);
  const dialog = await screen.findByRole("alertdialog", {
    name: messages.unsaved_navigation_title
  });
  fireEvent.click(within(dialog).getByRole("button", { name: messages.cancel }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(api.stub.calls.filter((call) => call.method === "DELETE")).toEqual([]);
  await click(messages.cancel);
  await chooseLeave();
  await screen.findByRole("button", { name: "Redigera Steg 1: Sammanfatta" });
  expect(api.stub.calls.filter((call) => call.method === "DELETE")).toEqual([
    expect.objectContaining({
      path: "/api/v1/files/{id}/",
      init: { params: { path: { id: "file-new" } } }
    })
  ]);
});
