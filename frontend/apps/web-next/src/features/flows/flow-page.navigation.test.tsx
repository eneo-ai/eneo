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
import { makeAssistant, makeKindOption, makeKindPlace } from "./editor/testing/fixtures";
import { makeFlow, makeStep } from "./flow-fixtures";
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
