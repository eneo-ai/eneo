// @vitest-environment jsdom
import {
  createBrowserHistory,
  createRoute,
  type AnyRootRoute,
  type RouterHistory
} from "@tanstack/react-router";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { SpaceProvider } from "@/features/spaces/use-space";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { renderWithRouter } from "@/test/router";
import { testAppContext, testQueryClient } from "@/test/render";
import messages from "@/lib/i18n/messages/sv.json";
import { toast } from "@/lib/toast";
import type { QueryClient } from "@tanstack/react-query";
import { flowEditorKeys } from "./editor/editor-api";
import { makeAssistant, makeKindOption, makeKindPlace } from "./editor/testing/fixtures";
import { makeFlow, makeStep } from "./flow-fixtures";
import { FlowPage } from "./flow-page";
import { flowKeys, type FlowPublic } from "./flows-api";
import { parseFlowSearch } from "./flow-search";

vi.unmock("@/lib/link");
// The conversation is the chat feature's; the page only follows what it reports.
vi.mock("@/features/chat/chat-view", () => ({
  ChatView: ({
    onToolCallFinished
  }: {
    onToolCallFinished: (call: { serverName: string; isInternal: boolean }) => void;
  }) => (
    <button
      type="button"
      onClick={() => onToolCallFinished({ serverName: "flows", isInternal: true })}
    >
      Verktyg klart
    </button>
  )
}));

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
  const view = await renderWithRouter(null, {
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
  return { ...view, queryClient };
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
    name: messages.flow_step_editor_discard_title
  });
  fireEvent.click(within(dialog).getByRole("button", { name: messages.flow_step_editor_discard }));
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

// These two are here, not in flow-page.test.tsx: an empty step list and a field's error announce
// themselves, and Astryx's live regions outlive a test, so the empty role="alert" one would answer
// that file's later alert queries.
it("opens the settings at the field that fixes what the check found", async () => {
  flow = makeFlow({
    steps: [makeStep(1, { input_type: "audio", output_mode: "transcribe_only" })],
    metadata_json: { wizard: { transcription_enabled: true } }
  });
  await renderPage();
  const check = await screen.findByRole("region", { name: "Före publicering" });
  fireEvent.click(
    await within(check).findByRole("button", {
      name: messages.flow_editor_tools_check_open_settings
    })
  );
  await screen.findByRole("button", { name: messages.flows_settings_save });
  await waitFor(() =>
    expect(
      document.activeElement?.closest('[data-settings-field="transcription_model"]')
    ).toBeTruthy()
  );
});

it("says what the check found once, in Före publicering, not again in the settings", async () => {
  flow = makeFlow({
    steps: [makeStep(1, { input_type: "audio", output_mode: "transcribe_only" })],
    metadata_json: { wizard: { transcription_enabled: true } }
  });
  await renderPage();
  const check = await screen.findByRole("region", { name: "Före publicering" });
  expect(await within(check).findByText("1 sak hindrar publicering")).toBeTruthy();
});

it("sends no publish the check already refuses: says so, and focus goes to what it found", async () => {
  flow = makeFlow({
    steps: [makeStep(1, { input_type: "audio", output_mode: "transcribe_only" })],
    metadata_json: { wizard: { transcription_enabled: true } }
  });
  await renderPage();
  const check = await screen.findByRole("region", { name: "Före publicering" });
  await within(check).findByText("1 sak hindrar publicering");
  await click(messages.publish);
  expect(document.activeElement).toBe(
    within(check).getByRole("heading", { name: "Före publicering" })
  );
  expect(api.stub.calls.some((call) => call.path === "/api/v1/flows/{id}/publish/")).toBe(false);
  // Said on screen, not only read out: a mouse user sees why nothing happened.
  const notice = screen.getByText(messages.flows_notice_not_published).closest('[role="alert"]');
  expect(notice?.textContent).toContain("1 sak hindrar publicering");
});

it("opens a flow without steps on its steps, and sends no publish of it", async () => {
  flow = makeFlow({ steps: [] });
  await renderPage();
  const steps = await screen.findByRole("region", { name: "Steg" });
  const settings = screen.getByRole("region", { name: messages.flows_settings_heading });
  expect(steps.compareDocumentPosition(settings) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  // Nothing to check before there is a step: the empty list says what to do, once.
  expect(screen.queryByRole("region", { name: "Före publicering" })).toBeNull();
  expect(screen.getAllByRole("button", { name: "Lägg till steg" })).toHaveLength(1);

  await click(messages.publish);
  expect(document.activeElement).toBe(within(steps).getByRole("heading", { name: "Steg" }));
  expect(api.stub.calls.some((call) => call.path === "/api/v1/flows/{id}/publish/")).toBe(false);
  const notice = screen.getByText(messages.flows_notice_not_published).closest('[role="alert"]');
  expect(notice?.textContent).toContain(messages.flows_publish_needs_steps);
});

it("adds the first step from the empty list and puts focus on it", async () => {
  flow = makeFlow({ steps: [] });
  const added = makeFlow({
    draft_revision: 5,
    steps: [makeStep(1, { user_description: "Sammanfatta" })]
  });
  api.routes["GET /api/v1/flows/{id}/step-kinds/"] = () => ({
    body: {
      flow_id: "flow-1",
      draft_revision: 4,
      insertions: [makeKindPlace(1, [makeKindOption("ai")])],
      steps: []
    }
  });
  api.routes["PATCH /api/v1/flows/{id}/editor/"] = () => ({ body: added });
  await renderPage();
  await click("Lägg till steg");
  const dialog = await screen.findByRole("dialog", { name: "Lägg till steg" });
  await within(dialog).findByRole("radio", { name: "Sammanfatta" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till Sammanfatta" }));
  const open = await screen.findByRole("button", { name: "Redigera Steg 1: Sammanfatta" });
  await waitFor(() => expect(document.activeElement).toBe(open));
});

/** A JSON step, then the step that sends the run's result: nothing to send yet. */
function senderFlow() {
  return makeFlow({
    steps: [
      makeStep(1, { id: "step-json", user_description: "Plocka ut", output_type: "json" }),
      makeStep(2, {
        id: "step-send",
        assistant_id: "assistant-send",
        user_description: "Skicka till Startsidan",
        output_mode: "http_post",
        output_config: {
          url: "https://startsidan.example.org/in",
          auth: { mode: "none" },
          timeout_seconds: 30,
          body: { mode: "run_result" },
          custom_headers: [],
          response_format: null
        }
      })
    ]
  });
}

/** `start` with a step put before the step that sends, as the core answers the add. */
function withStepBeforeSend(start: FlowPublic, step: Partial<FlowPublic["steps"][number]>) {
  const [first, sender] = start.steps;
  return makeFlow({
    draft_revision: start.draft_revision + 1,
    steps: [
      first!,
      makeStep(2, { id: "step-new", assistant_id: "assistant-new", ...step }),
      { ...sender!, step_order: 3 }
    ]
  });
}

/** Routes the add dialog's kinds at any place, and answers each editor PATCH in turn. */
function routeAddBeforeSend(answers: FlowPublic[]) {
  api.routes["GET /api/v1/flows/{id}/step-kinds/"] = (init) => {
    const position = (init as { params: { query: { position: number } } }).params.query.position;
    return {
      body: {
        flow_id: "flow-1",
        draft_revision: 4,
        insertions: [makeKindPlace(position, [makeKindOption("ai")])],
        steps: []
      }
    };
  };
  const queue = [...answers];
  api.routes["PATCH /api/v1/flows/{id}/editor/"] = () => ({ body: queue.shift() });
}

const editorPatches = () =>
  api.stub.calls
    .filter((call) => call.method === "PATCH" && call.path === "/api/v1/flows/{id}/editor/")
    .map((call) => call.init.body);

async function addSummaryBeforeSend() {
  await click(messages.flow_step_editor_run_result_add_before);
  const dialog = await screen.findByRole("dialog", { name: "Lägg till steg" });
  fireEvent.click(await within(dialog).findByRole("radio", { name: "Sammanfatta" }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till Sammanfatta" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Lägg till steg" })).toBeNull());
}

it("adds a step before the send from the sender with unsaved edits, and lists it there", async () => {
  flow = senderFlow();
  const added = withStepBeforeSend(flow, { user_description: "Sammanfatta" });
  routeAddBeforeSend([added, { ...added, draft_revision: 6 }]);
  const { queryClient } = await renderPage("?step=step-send");
  fireEvent.change(await nameField(), { target: { value: "Skicka till intranätet" } });
  await addSummaryBeforeSend();
  // The page holds the flow the add returned.
  expect(queryClient.getQueryData<FlowPublic>(flowKeys.flow(flow.id))?.draft_revision).toBe(5);

  const sends = await screen.findByRole("region", {
    name: messages.flow_step_editor_run_result_sends_title
  });
  // The step added lists where it is sent, focus goes to it, and the edits stay.
  const open = await within(sends).findByRole("button", { name: "Öppna steg 2 – Sammanfatta" });
  await waitFor(() => expect(document.activeElement).toBe(open));
  expect(within(sends).queryByText(messages.flow_step_editor_run_result_empty_title)).toBeNull();
  expect(screen.queryByText(messages.flow_step_editor_newer_title)).toBeNull();
  expect(((await nameField()) as HTMLInputElement).value).toBe("Skicka till intranätet");

  // The save is the edit alone, fenced on the revision the add returned: no order, no new step.
  await click(messages.flow_step_editor_save);
  await waitFor(() => expect(editorPatches()).toHaveLength(2));
  expect(editorPatches()[1]).toEqual({
    expected_revision: 5,
    definition: {},
    step_edits: [{ step_id: "step-send", changes: { user_description: "Skicka till intranätet" } }]
  });
});

const STALE = {
  status: 400,
  body: { message: "Stale", code: "stale_revision", eneo_error_code: 9000 }
};
const sendsRegion = () =>
  screen.findByRole("region", { name: messages.flow_step_editor_run_result_sends_title });
const sendsHeading = async () =>
  within(await sendsRegion()).getByRole("heading", {
    name: messages.flow_step_editor_run_result_sends_title
  });

it("keeps the banner and the edits' revision when the flow changed elsewhere, even with this step unchanged", async () => {
  flow = senderFlow();
  const { queryClient } = await renderPage("?step=step-send");
  fireEvent.change(await nameField(), { target: { value: "Skicka till intranätet" } });
  const newer = { ...flow, draft_revision: 5 };
  act(() => queryClient.setQueryData(flowKeys.flow(flow.id), newer));
  expect(await screen.findByText(messages.flow_step_editor_newer_title)).toBeTruthy();
  api.routes["PATCH /api/v1/flows/{id}/editor/"] = () => STALE;
  await click(messages.flow_step_editor_save);
  await waitFor(() => expect(editorPatches()).toHaveLength(1));
  expect(editorPatches()[0]).toMatchObject({ expected_revision: 4 });
});

it("keeps the banner when the add went through on a newer revision than the edits", async () => {
  flow = senderFlow();
  const { queryClient } = await renderPage("?step=step-send");
  fireEvent.change(await nameField(), { target: { value: "Skicka till intranätet" } });
  const newer = { ...flow, draft_revision: 5 };
  flow = newer;
  act(() => queryClient.setQueryData(flowKeys.flow(newer.id), newer));
  expect(await screen.findByText(messages.flow_step_editor_newer_title)).toBeTruthy();
  routeAddBeforeSend([]);
  const answers = [STALE, { body: withStepBeforeSend(newer, { user_description: "Sammanfatta" }) }];
  api.routes["PATCH /api/v1/flows/{id}/editor/"] = () => answers.shift()!;

  // The add is fenced on the edits' revision, refused, read again and added on the newer one.
  await click(messages.flow_step_editor_run_result_add_before);
  const dialog = await screen.findByRole("dialog", { name: "Lägg till steg" });
  fireEvent.click(await within(dialog).findByRole("radio", { name: "Sammanfatta" }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till Sammanfatta" }));
  fireEvent.click(
    await within(dialog).findByRole("button", { name: messages.flow_step_editor_reload })
  );
  // The kinds are read again for the newer revision before a row can be chosen.
  await waitFor(() =>
    expect(
      within(dialog).queryByRole("button", { name: messages.flow_step_editor_reload })
    ).toBeNull()
  );
  await waitFor(() => {
    fireEvent.click(within(dialog).getByRole("radio", { name: "Sammanfatta" }));
    expect(within(dialog).getByRole("button", { name: "Lägg till Sammanfatta" })).toBeTruthy();
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till Sammanfatta" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Lägg till steg" })).toBeNull());
  expect(
    editorPatches().map((body) => (body as { expected_revision: number }).expected_revision)
  ).toEqual([4, 5]);

  // Not this editor's own add on its revision: the edits stay under the banner.
  expect(screen.getByText(messages.flow_step_editor_newer_title)).toBeTruthy();
  expect(((await nameField()) as HTMLInputElement).value).toBe("Skicka till intranätet");
  const heading = await sendsHeading();
  await waitFor(() => expect(document.activeElement).toBe(heading));
});

/**
 * "Lägg till steg före utskicket" refused as stale while `reread` is what the core holds; the
 * dialog reads it again and the author asks for the same row once more.
 */
async function addBeforeSendAfterReload(reread: FlowPublic, answer: FlowPublic | null) {
  routeAddBeforeSend([]);
  const answers = [STALE, ...(answer ? [{ body: answer }] : [])];
  api.routes["PATCH /api/v1/flows/{id}/editor/"] = () => answers.shift()!;
  await click(messages.flow_step_editor_run_result_add_before);
  const dialog = await screen.findByRole("dialog", { name: "Lägg till steg" });
  fireEvent.click(await within(dialog).findByRole("radio", { name: "Sammanfatta" }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till Sammanfatta" }));
  flow = reread;
  fireEvent.click(
    await within(dialog).findByRole("button", { name: messages.flow_step_editor_reload })
  );
  await waitFor(() =>
    expect(
      within(dialog).queryByRole("button", { name: messages.flow_step_editor_reload })
    ).toBeNull()
  );
  return dialog;
}

it("puts a step added again after a reload directly before the step that sends, where it is now", async () => {
  flow = senderFlow();
  await renderPage("?step=step-send");
  await nameField();
  // Another author put a step before the step that sends: it is third now.
  const reread = withStepBeforeSend(flow, { id: "step-other", user_description: "Annat" });
  const added = makeFlow({
    draft_revision: 6,
    steps: [
      reread.steps[0]!,
      reread.steps[1]!,
      makeStep(3, {
        id: "step-new",
        assistant_id: "assistant-new",
        user_description: "Sammanfatta"
      }),
      { ...reread.steps[2]!, step_order: 4 }
    ]
  });
  const dialog = await addBeforeSendAfterReload(reread, added);
  await waitFor(() => {
    fireEvent.click(within(dialog).getByRole("radio", { name: "Sammanfatta" }));
    expect(within(dialog).getByRole("button", { name: "Lägg till Sammanfatta" })).toBeTruthy();
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till Sammanfatta" }));
  await waitFor(() => expect(editorPatches()).toHaveLength(2));
  expect(editorPatches()[1]).toMatchObject({
    expected_revision: 5,
    step_order: [
      { step_id: "step-json" },
      { step_id: "step-other" },
      { new_step: 0 },
      { step_id: "step-send" }
    ]
  });
  // Focus goes to the step added, directly before the step that sends where it is now.
  await waitFor(async () =>
    expect(document.activeElement).toBe(
      within(await sendsRegion()).getByRole("button", { name: "Öppna steg 3 – Sammanfatta" })
    )
  );
});

it("adds nothing after a reload in which the step that sends is gone, and says so", async () => {
  flow = senderFlow();
  await renderPage("?step=step-send");
  await nameField();
  const reread = makeFlow({ draft_revision: 5, steps: [flow.steps[0]!] });
  const dialog = await addBeforeSendAfterReload(reread, null);
  expect(
    await within(dialog).findByText(messages.flow_step_editor_add_before_sender_gone)
  ).toBeTruthy();
  expect(within(dialog).queryByRole("radio")).toBeNull();
  const submit = within(dialog).getByRole("button", {
    name: "Lägg till steg"
  }) as HTMLButtonElement;
  expect(submit.disabled || submit.getAttribute("aria-disabled") === "true").toBe(true);
  expect(editorPatches()).toHaveLength(1);
});

it("adds nothing after a reload in which the step that sends became a plain call, and says so", async () => {
  flow = senderFlow();
  await renderPage("?step=step-send");
  await nameField();
  // Another author made the same step a call with its own body: it no longer sends the result.
  const [first, sender] = flow.steps;
  const config = sender!.output_config as Record<string, unknown>;
  const reread = makeFlow({
    draft_revision: 5,
    steps: [first!, { ...sender!, output_config: { ...config, body: { mode: "auto" } } }]
  });
  const dialog = await addBeforeSendAfterReload(reread, null);
  expect(
    await within(dialog).findByText(messages.flow_step_editor_add_before_sender_gone)
  ).toBeTruthy();
  expect(within(dialog).queryByRole("radio")).toBeNull();
  expect(editorPatches()).toHaveLength(1);
});

it("keeps a newer version the page holds when the answer to its own add comes late", async () => {
  flow = senderFlow();
  const { queryClient } = await renderPage("?step=step-send");
  fireEvent.change(await nameField(), { target: { value: "Skicka till intranätet" } });
  const added = withStepBeforeSend(flow, { user_description: "Sammanfatta" });
  const [first, ...rest] = added.steps;
  const newer = makeFlow({
    draft_revision: 6,
    steps: [{ ...first!, user_description: "Plocka ut allt" }, ...rest]
  });
  routeAddBeforeSend([]);
  const answers = [{ body: added }, STALE];
  api.routes["PATCH /api/v1/flows/{id}/editor/"] = () => {
    // Revision 6 reaches the page before the add's own answer, revision 5.
    if (answers.length === 2) queryClient.setQueryData(flowKeys.flow(flow.id), newer);
    return answers.shift()!;
  };
  await addSummaryBeforeSend();

  expect(queryClient.getQueryData<FlowPublic>(flowKeys.flow(flow.id))?.draft_revision).toBe(6);
  expect(await screen.findByText(messages.flow_step_editor_newer_title)).toBeTruthy();
  expect(((await nameField()) as HTMLInputElement).value).toBe("Skicka till intranätet");
  // The save stays fenced on the revision the edits sit on, the add's answer.
  await click(messages.flow_step_editor_save);
  await waitFor(() => expect(editorPatches()).toHaveLength(2));
  expect(editorPatches()[1]).toMatchObject({ expected_revision: 5 });
});

it("keeps the banner when the add changed the step that sends", async () => {
  flow = senderFlow();
  await renderPage("?step=step-send");
  fireEvent.change(await nameField(), { target: { value: "Skicka till intranätet" } });
  const added = withStepBeforeSend(flow, { user_description: "Sammanfatta" });
  const sender = added.steps[2]!;
  added.steps[2] = { ...sender, timeout_seconds: 60 };
  routeAddBeforeSend([added]);
  await addSummaryBeforeSend();
  expect(await screen.findByText(messages.flow_step_editor_newer_title)).toBeTruthy();
  expect(((await nameField()) as HTMLInputElement).value).toBe("Skicka till intranätet");
});

it("keeps a credential being replaced across the add, and starts over after the save", async () => {
  const stored = senderFlow();
  const sender = stored.steps[1]!;
  stored.steps[1] = {
    ...sender,
    output_config: {
      ...(sender.output_config as Record<string, unknown>),
      auth: { mode: "bearer_token", token: { $secret: "stored" } }
    }
  };
  flow = stored;
  // JSON steps send nothing, so "Lägg till steg före utskicket" stays after each add.
  const added = withStepBeforeSend(stored, {
    user_description: "Sammanfatta",
    output_type: "json"
  });
  const [first, second, send] = added.steps;
  const addedAgain = makeFlow({
    draft_revision: 6,
    steps: [
      first!,
      second!,
      makeStep(3, {
        id: "step-new-2",
        assistant_id: "assistant-new-2",
        user_description: "Sammanfatta 2",
        output_type: "json"
      }),
      { ...send!, step_order: 4 }
    ]
  });
  routeAddBeforeSend([added, addedAgain, { ...addedAgain, draft_revision: 7 }]);
  await renderPage("?step=step-send");
  await click("Ersätt: Token");
  // Two adds in a row: the form stays through both, and the way back to the stored token with it.
  await addSummaryBeforeSend();
  await addSummaryBeforeSend();
  expect(
    await screen.findByRole("button", { name: messages.flow_step_editor_secret_keep })
  ).toBeTruthy();
  expect(screen.queryByText(messages.flow_step_editor_newer_title)).toBeNull();

  fireEvent.change(document.querySelector("input[type=password]")!, {
    target: { value: "ny-hemlighet" }
  });
  await click(messages.flow_step_editor_save);
  await waitFor(() => expect(editorPatches()).toHaveLength(3));
  expect(editorPatches()[2]).toMatchObject({ expected_revision: 6 });
  // After the save the form starts over on what is stored.
  expect(await screen.findByRole("button", { name: "Ersätt: Token" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: messages.flow_step_editor_secret_keep })).toBeNull();
});

it("puts focus on what is sent when the step added cannot be sent", async () => {
  flow = senderFlow();
  const added = withStepBeforeSend(flow, { user_description: "Sammanfatta", output_type: "json" });
  routeAddBeforeSend([added]);
  await renderPage("?step=step-send");
  await nameField();
  await addSummaryBeforeSend();
  const heading = await sendsHeading();
  await waitFor(() => expect(document.activeElement).toBe(heading));
  expect(screen.queryByText(messages.flow_step_editor_newer_title)).toBeNull();
});

it("agrees on the cards and in what the step that sends lists after the first of two Word documents is switched on and saved", async () => {
  const word = (order: number, name: string) =>
    makeStep(order, {
      user_description: name,
      output_type: "docx",
      output_mode: "render_verbatim"
    });
  const send = makeStep(3, {
    user_description: "Skicka",
    output_mode: "http_post",
    output_config: {
      url: "https://startsidan.example.org/in",
      auth: { mode: "none" },
      body: { mode: "run_result" }
    }
  });
  flow = makeFlow({ steps: [word(1, "Protokoll"), word(2, "Bilaga"), send] });
  const marked = makeFlow({
    draft_revision: 5,
    steps: [
      { ...flow.steps[0]!, output_config: { deliverable: { label: "Protokoll" } } },
      flow.steps[1]!,
      send
    ]
  });
  api.routes["PATCH /api/v1/flows/{id}/editor/"] = () => ({ body: marked });
  await renderPage();
  await click("Redigera Steg 1: Protokoll");
  const delivery = await screen.findByRole("region", {
    name: messages.flow_step_editor_delivery_title
  });
  fireEvent.click(
    within(delivery).getByRole("switch", {
      name: new RegExp(`^${messages.flow_step_editor_deliverable_switch}`)
    })
  );
  await click(messages.flow_step_editor_save);
  await waitFor(() => expect(editorPatches()).toHaveLength(1));
  // Read again from the saved flow: the destination line says the document is sent.
  expect(
    await within(
      await screen.findByRole("region", { name: messages.flow_step_editor_delivery_title })
    ).findByText("Skickas till startsidan.example.org när körningen är klar.")
  ).toBeTruthy();

  await click("Alla steg");
  const card = (name: string) => screen.findByRole("article", { name });
  expect(within(await card("Steg 1 Protokoll")).getByText("Leverans")).toBeTruthy();
  expect(within(await card("Steg 2 Bilaga")).getByText("Leverans")).toBeTruthy();

  await click("Redigera Steg 3: Skicka");
  const sends = await sendsRegion();
  expect(
    await within(sends).findByRole("button", { name: "Öppna steg 1 – Protokoll" })
  ).toBeTruthy();
  expect(within(sends).getByRole("button", { name: "Öppna steg 2 – Bilaga" })).toBeTruthy();
});

it("agrees in Leverans, on the card that sends and in the removal dialog that a step its API key's header name names is read", async () => {
  flow = makeFlow({
    steps: [
      makeStep(1, { user_description: "Sammanfatta" }),
      makeStep(2, { user_description: "Granska", input_source: "flow_input" }),
      makeStep(3, {
        user_description: "Skicka",
        output_mode: "http_post",
        output_config: {
          url: "https://startsidan.example.org/in",
          auth: { mode: "api_key", header_name: "X-{{Sammanfatta}}", key: "hemlig" },
          body: { mode: "run_result" }
        }
      })
    ]
  });
  await renderPage("?step=step-1");
  const delivery = await screen.findByRole("region", {
    name: messages.flow_step_editor_delivery_title
  });
  expect(await within(delivery).findByText("Läses av Steg 3: Skicka.")).toBeTruthy();
  expect(
    within(delivery).getByText(
      "Skickas till startsidan.example.org i en header i steget som skickar körningens resultat."
    )
  ).toBeTruthy();

  await click("Alla steg");
  const sending = await screen.findByRole("article", { name: "Steg 3 Skicka" });
  expect(within(sending).getByText(messages.flows_step_reads)).toBeTruthy();
  expect(within(sending).getByText("Steg 1: Sammanfatta")).toBeTruthy();
  const trigger = screen.getByRole("button", { name: "Fler åtgärder för Steg 1: Sammanfatta" });
  fireEvent.click(trigger);
  const menu = document.getElementById(trigger.getAttribute("aria-controls") ?? "")!;
  fireEvent.click(within(menu).getByRole("menuitem", { name: "Ta bort steg" }));
  const dialog = await screen.findByRole("alertdialog", { name: "Ta bort steget?" });
  expect(within(dialog).getByText(/^Steg 3: Skicka läser Steg 1: Sammanfatta\./)).toBeTruthy();
});

it("closes a direct step link in the same flow without traversing earlier history", async () => {
  const { router } = await renderPage("?step=step-2");
  await nameField();
  await click("Alla steg");
  await screen.findByRole("button", { name: "Redigera Steg 2: Skriv svar" });
  expect(router.state.location.href).toBe(BASE);
});

it("says whether one change or several are lost on leaving the step", async () => {
  await renderPage();
  await openFirst();
  await changeName();
  await click("Alla steg");
  let dialog = await screen.findByRole("alertdialog", {
    name: messages.flow_step_editor_discard_title
  });
  expect(
    within(dialog).getByText("Ändringen i steget är inte sparad och försvinner om du lämnar det.")
  ).toBeTruthy();
  fireEvent.click(
    within(dialog).getByRole("button", { name: messages.flow_step_editor_keep_editing })
  );
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  fireEvent.click(
    screen.getByRole("switch", {
      name: new RegExp(`^${messages.flow_step_editor_deliverable_switch}`)
    })
  );
  await click("Alla steg");
  dialog = await screen.findByRole("alertdialog", {
    name: messages.flow_step_editor_discard_title
  });
  expect(
    within(dialog).getByText(
      "Ändringarna i steget är inte sparade och försvinner om du lämnar det."
    )
  ).toBeTruthy();
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
      name: messages.flow_step_editor_discard_title
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: messages.flow_step_editor_keep_editing })
    );
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

it("publishes only what is saved: unsaved step edits hold Publicera back and say why", async () => {
  api.routes["POST /api/v1/flows/{id}/publish/"] = () => ({
    body: { ...flow, published_version: 1 }
  });
  const publishes = () =>
    api.stub.calls.filter((call) => call.path === "/api/v1/flows/{id}/publish/");
  await renderPage();
  await openFirst();
  await changeName();
  await click(messages.publish);
  expect(await screen.findByText(messages.flows_publish_unsaved)).toBeTruthy();
  expect(publishes()).toEqual([]);
  // The draft stays as it was typed, with the editor open.
  expect(((await nameField()) as HTMLInputElement).value).toBe("Eget utkast");
  await click(messages.cancel);
  await chooseLeave();
  await screen.findByRole("button", { name: "Redigera Steg 1: Sammanfatta" });
  // The edits are dropped, so "save or cancel first" is gone with them.
  await waitFor(() => expect(screen.queryByText(messages.flows_publish_unsaved)).toBeNull());
  await click(messages.publish);
  await waitFor(() => expect(publishes()).toHaveLength(1));
});

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
  await screen.findByRole("alertdialog", { name: messages.flow_step_editor_discard_title });
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
    name: messages.flow_step_editor_discard_title
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: messages.flow_step_editor_keep_editing })
  );
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

describe("the Leverans section's reader from a later prompt, while the prompts are read again", () => {
  const ASSISTANT = "/api/v1/flows/{id}/assistants/{assistant_id}/";
  const first = makeStep(1, { user_description: "Sammanfatta" });
  const second = makeStep(2, { user_description: "Granska", input_source: "flow_input" });
  const third = (order: number) =>
    makeStep(order, {
      id: "step-3",
      assistant_id: "assistant-3",
      user_description: "Skriv svar",
      input_source: "flow_input"
    });
  const reader = "Läses av Steg 3: Skriv svar.";

  /** The later step's prompt is `text()` when read; the others name no step. */
  function laterPrompt(text: () => string) {
    api.routes[`GET ${ASSISTANT}`] = (init: { params: { path: { assistant_id: string } } }) => {
      const id = init.params.path.assistant_id;
      const assistant = makeAssistant();
      return {
        body: makeAssistant({
          id,
          prompt: { ...assistant.prompt!, text: id === "assistant-3" ? text() : "Gör ditt jobb." }
        })
      };
    };
  }
  beforeEach(() => {
    flow = makeFlow({ steps: [first, second, third(3)] });
    laterPrompt(() => "Jämför med {{Sammanfatta}}.");
  });
  /** The chat panel, whose tools finishing make the page read the flow again. */
  function withChat() {
    api.routes["POST /api/v1/flows/{id}/authoring-chat/"] = () => ({
      body: {
        flow_id: "flow-1",
        assistant_id: "assistant-chat",
        session_id: "session-1",
        editing: true
      }
    });
    api.routes["GET /api/v1/assistants/{id}/"] = () => ({
      body: { id: "assistant-chat", name: "Flödesassistent", mcp_servers: [] }
    });
    api.routes["GET /api/v1/conversations/{session_id}/"] = () => ({
      body: { id: "session-1", name: "", messages: [] }
    });
  }

  /** Holds the later step's prompt read until released; the other reads answer at once. */
  function holdLaterPrompt() {
    const get = api.stub.client.GET;
    let release = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    api.stub.client.GET = ((
      path: string,
      init?: { params?: { path?: { assistant_id?: string } } }
    ) =>
      path === ASSISTANT && init?.params?.path?.assistant_id === "assistant-3"
        ? held.then(() => get(path, init))
        : get(path, init)) as typeof get;
    return () => {
      api.stub.client.GET = get;
      release();
    };
  }
  /**
   * Holds each read of the later step's prompt until it is let go, answered
   * with the prompt as it was when the read was made.
   */
  function holdLaterReads() {
    const get = api.stub.client.GET;
    const held: (() => void)[] = [];
    api.stub.client.GET = ((
      path: string,
      init?: { params?: { path?: { assistant_id?: string } } }
    ) => {
      if (path !== ASSISTANT || init?.params?.path?.assistant_id !== "assistant-3") {
        return get(path, init);
      }
      const answer = get(path, init);
      return new Promise<Awaited<typeof answer>>((resolve) => held.push(() => resolve(answer)));
    }) as typeof get;
    return {
      held,
      restore: () => {
        api.stub.client.GET = get;
        for (const release of held) release();
      }
    };
  }
  const delivery = () =>
    screen.findByRole("region", { name: messages.flow_step_editor_delivery_title });
  /** The later prompt's first read has landed, so what is held next is a read again. */
  const read = (queryClient: QueryClient) =>
    waitFor(() =>
      expect(
        queryClient.getQueryState(flowEditorKeys.assistant("flow-1", "assistant-3"))?.status
      ).toBe("success")
    );
  const rereading = (queryClient: QueryClient) =>
    waitFor(() =>
      expect(
        queryClient.getQueryState(flowEditorKeys.assistant("flow-1", "assistant-3"))?.fetchStatus
      ).toBe("fetching")
    );
  /** Neither a reader nor "no step reads it": the line waits for the read. */
  async function waits(section: HTMLElement, line: string) {
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(within(section).queryByText(line)).toBeNull();
    expect(within(section).queryByText(messages.flow_step_editor_delivery_unread_off)).toBeNull();
  }
  /** The editor's own save of a setting: the step list stays as it was. */
  async function saveSetting(revision: number) {
    api.routes["PATCH /api/v1/flows/{id}/editor/"] = () => ({
      body: makeFlow({ draft_revision: revision, steps: [first, second, third(3)] })
    });
    fireEvent.click(
      within(await delivery()).getByRole("switch", {
        name: new RegExp(`^${messages.flow_step_editor_deliverable_switch}`)
      })
    );
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    await screen.findByText(messages.flow_step_editor_saved);
  }

  it("waits after a move, and names no step until the prompt is read again", async () => {
    const { queryClient } = await renderPage();
    await screen.findByRole("button", { name: "Redigera Steg 1: Sammanfatta" });
    await read(queryClient);
    const release = holdLaterPrompt();
    try {
      api.routes["PATCH /api/v1/flows/{id}/editor/"] = () => ({
        body: makeFlow({
          draft_revision: 5,
          steps: [first, third(2), { ...second, step_order: 3 }]
        })
      });
      await click("Flytta upp Steg 3: Skriv svar");
      await screen.findByRole("button", { name: "Redigera Steg 2: Skriv svar" });
      await openFirst();
      const section = await delivery();
      await rereading(queryClient);
      await waits(section, "Går vidare till nästa steg: Steg 2: Skriv svar.");
    } finally {
      release();
    }
    expect(
      await within(await delivery()).findByText("Går vidare till nästa steg: Steg 2: Skriv svar.")
    ).toBeTruthy();
  });

  it("waits after a change from the chat with the same steps, also through an own save meanwhile", async () => {
    withChat();
    const { queryClient } = await renderPage("?step=step-1");
    expect(await within(await delivery()).findByText(reader)).toBeTruthy();
    // An own save first, settled: what it allowed does not outlast it.
    await saveSetting(5);
    expect(within(await delivery()).getByText(reader)).toBeTruthy();
    const release = holdLaterPrompt();
    try {
      // The chat rewrote a prompt: a new revision, the same steps.
      flow = makeFlow({ draft_revision: 6, steps: [first, second, third(3)] });
      fireEvent.click(await screen.findByRole("button", { name: "Verktyg klart" }));
      await rereading(queryClient);
      await waits(await delivery(), reader);
      // An own save while that read is under way does not bring the old prompt back.
      await saveSetting(7);
      await waits(await delivery(), reader);
    } finally {
      release();
    }
    expect(await within(await delivery()).findByText(reader)).toBeTruthy();
  });

  it("waits after a stale draft is read again", async () => {
    const { queryClient } = await renderPage();
    await screen.findByRole("button", { name: "Redigera Steg 1: Sammanfatta" });
    await read(queryClient);
    const release = holdLaterPrompt();
    try {
      api.routes["PATCH /api/v1/flows/{id}/editor/"] = () => ({
        status: 400,
        body: { message: "Stale.", code: "stale_revision", eneo_error_code: 9000 }
      });
      flow = makeFlow({ draft_revision: 5, steps: [first, second, third(3)] });
      await click("Flytta upp Steg 2: Granska");
      await screen.findByText(messages.flows_notice_stale_title);
      await waitFor(() =>
        expect(queryClient.getQueryData<FlowPublic>(flowKeys.flow("flow-1"))?.draft_revision).toBe(
          5
        )
      );
      await openFirst();
      const section = await delivery();
      await rereading(queryClient);
      await waits(section, reader);
    } finally {
      release();
    }
    expect(await within(await delivery()).findByText(reader)).toBeTruthy();
  });

  it("keeps the reader through the read that follows the editor's own save of a setting", async () => {
    const { queryClient } = await renderPage("?step=step-1");
    expect(await within(await delivery()).findByText(reader)).toBeTruthy();
    const release = holdLaterPrompt();
    try {
      await saveSetting(5);
      await rereading(queryClient);
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(within(await delivery()).getByText(reader)).toBeTruthy();
    } finally {
      release();
    }
    expect(within(await delivery()).getByText(reader)).toBeTruthy();
  });
  it("waits after a save that answers more than one revision past the one on screen", async () => {
    const { queryClient } = await renderPage("?step=step-1");
    expect(await within(await delivery()).findByText(reader)).toBeTruthy();
    const release = holdLaterPrompt();
    try {
      // From 4 to 6: a change made elsewhere came in between, which may have rewritten a prompt.
      await saveSetting(6);
      await rereading(queryClient);
      await waits(await delivery(), reader);
    } finally {
      release();
    }
    expect(await within(await delivery()).findByText(reader)).toBeTruthy();
  });

  it("waits after a rename from the step editor, also for a prompt that reads the step by place", async () => {
    laterPrompt(() => "Jämför med {{step_1}}.");
    const { queryClient } = await renderPage("?step=step-1");
    expect(await within(await delivery()).findByText(reader)).toBeTruthy();
    const release = holdLaterPrompt();
    try {
      api.routes["PATCH /api/v1/flows/{id}/editor/"] = () => ({
        body: makeFlow({
          draft_revision: 5,
          steps: [{ ...first, user_description: "Eget utkast" }, second, third(3)]
        })
      });
      await changeName();
      fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
      await screen.findByText(messages.flow_step_editor_saved);
      await rereading(queryClient);
      await waits(await delivery(), reader);
    } finally {
      release();
    }
    expect(await within(await delivery()).findByText(reader)).toBeTruthy();
  });

  /** The flow with a step put first, the later prompt rewritten to name this step at its new place. */
  const inserted = () =>
    makeFlow({
      draft_revision: 5,
      steps: [
        makeStep(1, { id: "step-0", assistant_id: "assistant-0", user_description: "Hämta" }),
        { ...first, step_order: 2 },
        { ...second, step_order: 3 },
        third(4)
      ]
    });
  /** The later prompt has been read again as `text`, and no read is under way. */
  const readAs = (queryClient: QueryClient, text: string) =>
    waitFor(() => {
      const state = queryClient.getQueryState<ReturnType<typeof makeAssistant>>(
        flowEditorKeys.assistant("flow-1", "assistant-3")
      );
      expect(state?.data?.prompt?.text).toBe(text);
      expect(state?.fetchStatus).toBe("idle");
    });
  /** No reader line: neither a reader nor "no later step reads it". */
  async function noReaderLine() {
    await new Promise((resolve) => setTimeout(resolve, 50));
    const section = await delivery();
    expect(within(section).queryByText(/^Läses av /)).toBeNull();
    expect(within(section).queryByText(/^Går vidare till nästa steg/)).toBeNull();
    expect(within(section).queryByText(messages.flow_step_editor_delivery_unread_off)).toBeNull();
    expect(
      within(section).queryByText(messages.flow_step_editor_delivery_unread_included)
    ).toBeNull();
  }

  it("names no reader while the form holds edits on an older version, and the right one on the newer", async () => {
    withChat();
    let prompt = "Jämför med {{step_1}}.";
    laterPrompt(() => prompt);
    const { queryClient } = await renderPage("?step=step-1");
    expect(await within(await delivery()).findByText(reader)).toBeTruthy();
    await changeName();
    prompt = "Jämför med {{step_2}}.";
    flow = inserted();
    fireEvent.click(await screen.findByRole("button", { name: "Verktyg klart" }));
    await screen.findByText(messages.flow_step_editor_newer_title);
    // The prompts are read for the page's version; the form's steps are the older ones.
    await readAs(queryClient, prompt);
    await noReaderLine();
    await click(messages.flow_step_editor_reload);
    expect(await within(await delivery()).findByText("Läses av Steg 4: Skriv svar.")).toBeTruthy();
  });

  it("names the reader right after a reload, which hands the version it read to the page", async () => {
    let prompt = "Jämför med {{step_1}}.";
    laterPrompt(() => prompt);
    const { queryClient } = await renderPage("?step=step-1");
    expect(await within(await delivery()).findByText(reader)).toBeTruthy();
    await changeName();
    api.routes["PATCH /api/v1/flows/{id}/editor/"] = () => ({
      status: 400,
      body: { message: "Stale.", code: "stale_revision", eneo_error_code: 9000 }
    });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    await screen.findByText(messages.flow_step_editor_stale_title);
    // Changed elsewhere: the reload reads it, and the page takes it from there.
    prompt = "Jämför med {{step_2}}.";
    flow = inserted();
    await click(messages.flow_step_editor_reload);
    expect(await within(await delivery()).findByText("Läses av Steg 4: Skriv svar.")).toBeTruthy();
    expect(queryClient.getQueryData<FlowPublic>(flowKeys.flow("flow-1"))?.draft_revision).toBe(5);
    await readAs(queryClient, prompt);
  });

  it("keeps the reader on screen through the editor's own save", async () => {
    await renderPage("?step=step-1");
    expect(await within(await delivery()).findByText(reader)).toBeTruthy();
    // The save's answer reaches the form a moment before the page: the line is
    // there each time the page has changed, from the save to its settling.
    let gone = false;
    const observer = new MutationObserver(() => {
      if (!document.body.textContent?.includes(reader)) gone = true;
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    try {
      await saveSetting(5);
      await new Promise((resolve) => setTimeout(resolve, 50));
    } finally {
      observer.disconnect();
    }
    expect(gone).toBe(false);
    expect(within(await delivery()).getByText(reader)).toBeTruthy();
  });

  /** The page has taken a new revision and marked the later prompt to be read again. */
  const laterInvalidated = (queryClient: QueryClient) =>
    waitFor(() =>
      expect(
        queryClient.getQueryState(flowEditorKeys.assistant("flow-1", "assistant-3"))?.isInvalidated
      ).toBe(true)
    );

  it("reads a later prompt again when the flow changes during its first read, and takes no answer from before the change", async () => {
    withChat();
    let prompt = "Jämför med {{step_1}}.";
    laterPrompt(() => prompt);
    const reads = holdLaterReads();
    try {
      const { queryClient } = await renderPage("?step=step-1");
      await waitFor(() => expect(reads.held).toHaveLength(1));
      // The chat put a step first: this one is at place 2 now, and the prompt names it there.
      prompt = "Jämför med {{step_2}}.";
      flow = inserted();
      fireEvent.click(await screen.findByRole("button", { name: "Verktyg klart" }));
      await laterInvalidated(queryClient);
      // The read from before the change answers, with the prompt from before it.
      reads.held[0]!();
      await waits(await delivery(), "Läses av Steg 4: Skriv svar.");
      expect(reads.held).toHaveLength(2);
    } finally {
      reads.restore();
    }
    expect(await within(await delivery()).findByText("Läses av Steg 4: Skriv svar.")).toBeTruthy();
  });

  it("shows the open step's own prompt as saved when the flow changes during its first read", async () => {
    withChat();
    let prompt = "Skriv ett svar.";
    laterPrompt(() => prompt);
    const failed = vi.spyOn(toast, "error");
    onTestFinished(() => failed.mockRestore());
    const reads = holdLaterReads();
    try {
      const { queryClient } = await renderPage("?step=step-3");
      await waitFor(() => expect(reads.held).toHaveLength(1));
      prompt = "Skriv ett kort svar.";
      flow = makeFlow({ draft_revision: 5, steps: [first, second, third(3)] });
      fireEvent.click(await screen.findByRole("button", { name: "Verktyg klart" }));
      await laterInvalidated(queryClient);
      expect(screen.queryByText(messages.flow_step_editor_assistant_failed)).toBeNull();
      // The read made after the change answers first, the one from before it last.
      reads.held[1]?.();
      reads.held[0]!();
      await new Promise((resolve) => setTimeout(resolve, 50));
    } finally {
      reads.restore();
    }
    expect(((await screen.findByLabelText(/^Instruktion/)) as HTMLTextAreaElement).value).toBe(
      "Skriv ett kort svar."
    );
    expect(screen.queryByText(messages.flow_step_editor_assistant_failed)).toBeNull();
    expect(failed).not.toHaveBeenCalled();
  });
});
