// @vitest-environment jsdom
import { focusManager } from "@tanstack/react-query";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import type { Permission } from "@/lib/auth/permissions";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { resetNavigation, setRoute } from "@/test/navigation";
import { setViewport } from "@/test/setup-dom";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { makeAssistant, makeKindOption, makeKindPlace } from "./editor/testing/fixtures";
import { flowPermissions, makeFlow, makeStep } from "./flow-fixtures";
import { flowKeys, type FlowPublic } from "./flows-api";
import messages from "@/lib/i18n/messages/sv.json";
import { FlowPage } from "./flow-page";

type Reply = { data?: unknown; error?: unknown; response: Response };

const ok = (data: unknown): Reply => ({ data, response: new Response(null, { status: 200 }) });
const refused = (status: number, body: Record<string, unknown>): Reply => ({
  error: { eneo_error_code: 9007, ...body },
  response: new Response(null, { status })
});

const state = vi.hoisted(() => ({
  announce: vi.fn(),
  flow: null as unknown,
  chat: null as unknown,
  editor: null as unknown,
  publish: null as unknown,
  runs: null as unknown,
  unpublish: null as unknown,
  mode: null as unknown,
  kinds: null as unknown,
  suggestions: null as unknown,
  // The suggestions measured over the latest runs (`?runs=`).
  measured: null as unknown,
  apply: null as unknown,
  // The answers to a dismissal (`POST .../dismissal/`) and to taking one back (`DELETE`).
  dismiss: null as unknown,
  restore: null as unknown,
  dirty: false,
  // What went into the chat's composer, text and pills (by the value they send) in order.
  inserted: [] as string[],
  composer: {
    insertText: (text: string) => state.inserted.push(text),
    insertToken: (token: { value: string }) => state.inserted.push(token.value)
  },
  /** The step assistants' prompts by assistant id; null leaves the reads unanswered. */
  prompts: null as Record<string, string> | null
}));

const ASSISTANT = "/api/v1/flows/{id}/assistants/{assistant_id}/";

const api = vi.hoisted(() => ({
  GET: vi.fn(
    async (
      path: string,
      init?: { params?: { query?: { runs?: number }; path?: { assistant_id?: string } } }
    ) => {
      if (path === "/api/v1/flows/{id}/") return state.flow;
      if (path === "/api/v1/flows/{id}/assistants/{assistant_id}/" && state.prompts) {
        const id = init?.params?.path?.assistant_id ?? "";
        return {
          data: makeAssistant({
            id,
            prompt: { text: state.prompts[id] ?? "" } as ReturnType<typeof makeAssistant>["prompt"]
          }),
          response: new Response(null, { status: 200 })
        };
      }
      if (path === "/api/v1/flows/{id}/runs/") return state.runs;
      if (path === "/api/v1/flows/{id}/step-kinds/") return state.kinds;
      if (path === "/api/v1/flows/{id}/suggestions/") {
        return init?.params?.query?.runs ? state.measured : state.suggestions;
      }
      if (path === "/api/v1/assistants/{id}/") {
        return {
          data: { id: "assistant-chat", name: "Medborgarbrev", mcp_servers: [] },
          response: new Response()
        };
      }
      if (path === "/api/v1/conversations/{session_id}/") {
        return { data: { id: "session-1", name: "", messages: [] }, response: new Response() };
      }
      return { data: undefined, response: new Response() };
    }
  ),
  POST: vi.fn(async (path: string) => {
    if (path === "/api/v1/flows/{id}/authoring-chat/") return state.chat;
    if (path === "/api/v1/flows/{id}/publish/") return state.publish;
    if (path === "/api/v1/flows/{id}/unpublish/") return state.unpublish;
    if (path === "/api/v1/flows/{id}/suggestions/apply/") return state.apply;
    if (path === "/api/v1/flows/{id}/suggestions/{fingerprint}/dismissal/") return state.dismiss;
    return { data: undefined, response: new Response() };
  }),
  PATCH: vi.fn(async (path: string) => {
    if (path === "/api/v1/flows/{id}/editor/") return state.editor;
    if (path === "/api/v1/flows/{id}/authoring-chat/{session_id}/") return state.mode;
    return { data: undefined, response: new Response() };
  }),
  PUT: vi.fn(),
  DELETE: vi.fn(async (path: string) => {
    if (path === "/api/v1/flows/{id}/suggestions/{fingerprint}/dismissal/") return state.restore;
    return { data: undefined, response: new Response(null, { status: 204 }) };
  })
}));

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => state.announce
}));
// The conversation itself is the chat feature's; the page only follows what it reports.
vi.mock("@/features/chat/chat-view", async () => {
  const { useEffect } = await import("react");
  return {
    // The stub shows what the flow page puts in the composer's footer (the
    // Fråga/Redigera picker) and its placeholder, and offers the callbacks.
    // It reports a composer that records what is put into it, as the real
    // one does through `references.onComposer`.
    ChatView: function ChatView({
      onToolCallFinished,
      onAnswerFinished,
      footerActions,
      placeholder,
      references
    }: {
      onToolCallFinished: (call: { serverName: string; isInternal: boolean }) => void;
      onAnswerFinished: () => void;
      footerActions?: React.ReactNode;
      placeholder?: string;
      references?: { onComposer?: (input: unknown) => void };
    }) {
      useEffect(() => {
        references?.onComposer?.(state.composer);
        return () => references?.onComposer?.(null);
      }, [references]);
      return (
        <div>
          <button
            type="button"
            onClick={() => onToolCallFinished({ serverName: "flows", isInternal: true })}
          >
            Verktyg klart
          </button>
          <button type="button" onClick={onAnswerFinished}>
            Svar klart
          </button>
          {footerActions}
          <p>{placeholder}</p>
        </div>
      );
    }
  };
});
// The editor is its own tests'; the page owns where it is (?step=) and what
// leaving it asks. The stub reports `state.dirty` as unsaved changes and asks
// as the editor does, with "Lämna utan att spara" to go on.
vi.mock("./editor/flow-step-editor", async () => {
  const { useImperativeHandle, useState } = await import("react");
  return {
    FlowStepEditor: function FlowStepEditor({
      stepId,
      onCancel,
      leaveRef,
      navigation,
      suggestionFix,
      suggestionRuns
    }: {
      stepId: string;
      onCancel: () => void;
      leaveRef: React.Ref<{ isDirty: () => boolean; requestLeave: (go: () => void) => void }>;
      navigation: { next: { id: string } | null; onGo: (id: string) => void };
      suggestionFix?: {
        onFix: (fingerprints: string[]) => Promise<boolean>;
        pending: boolean;
      };
      suggestionRuns?: number;
    }) {
      const [asking, setAsking] = useState<(() => void) | null>(null);
      const leave = (go: () => void) => (state.dirty ? setAsking(() => go) : go());
      useImperativeHandle(leaveRef, () => ({ isDirty: () => state.dirty, requestLeave: leave }));
      const next = navigation.next;
      return (
        <div>
          <p>Redigerar {stepId}</p>
          {suggestionRuns ? <p>Förslagen räknas med {suggestionRuns} körningar</p> : null}
          {suggestionFix ? (
            <button
              type="button"
              disabled={suggestionFix.pending}
              onClick={() => void suggestionFix.onFix(["e".repeat(64)])}
            >
              Åtgärda i steget
            </button>
          ) : null}
          <button type="button" onClick={() => leave(onCancel)}>
            Alla steg
          </button>
          <button
            type="button"
            disabled={!next}
            onClick={() => next && leave(() => navigation.onGo(next.id))}
          >
            Nästa
          </button>
          {asking ? (
            <button
              type="button"
              onClick={() => {
                state.dirty = false;
                setAsking(null);
                asking();
              }}
            >
              Lämna utan att spara
            </button>
          ) : null}
        </div>
      );
    }
  };
});
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const { makeSpace: space } = await import("@/features/spaces/testing/space-fixture");
  return {
    useSpace: () => useSpaceFromQuery(() => space({})),
    // The step editor's own provider; the page's space serves it here.
    SpaceProvider: ({ children }: { children: React.ReactNode }) => children
  };
});

const steps = [
  makeStep(1, { user_description: "Sammanfatta" }),
  makeStep(2, { user_description: "Skriv svar" })
];

/** One `duplicate_read` on step 2, reading step 1 as its input and in its prompt. */
const DUPLICATE_READ = {
  code: "duplicate_read",
  fingerprint: "f".repeat(64),
  steps: ["step-2", "step-1"],
  params: {
    producer_step_order: 1,
    producer_step_id: "step-1",
    contained: false,
    reads: [
      { channel: "input", site: "input_source", selector: [] },
      { channel: "prompt", site: "assistant_prompt:step_1.output.text", selector: [] }
    ]
  },
  message: "Step 2 reads step 1 twice.",
  impact: { basis: "definition", level: "high" },
  fix: { kind: "patch" }
};

const suggestions = (revision: number, items: unknown[]) =>
  ok({ flow_id: "flow-1", draft_revision: revision, items });

/** The duplicate once an editor of the flow dismissed it, as the core lists it. */
const DISMISSED_DUPLICATE = {
  ...DUPLICATE_READ,
  dismissed: { dismissed_by: "user-1", dismissed_at: "2026-10-25T09:30:00Z" }
};
const withDismissed = (revision: number, items: unknown[]) =>
  ok({ flow_id: "flow-1", draft_revision: revision, dismissed_count: 1, items });
/** The core's answer to a dismissal. */
const DISMISSAL = ok({
  flow_id: "flow-1",
  fingerprint: DUPLICATE_READ.fingerprint,
  code: "duplicate_read",
  dismissed_by: "user-1",
  dismissed_at: "2026-10-25T09:30:00Z"
});

/** What the page posted to dismiss suggestions: the path's fingerprint and the body. */
function dismissals() {
  return api.POST.mock.calls
    .filter(([path]) => path === "/api/v1/flows/{id}/suggestions/{fingerprint}/dismissal/")
    .map((call) => {
      const init = (call as unknown as [string, { params: { path: unknown }; body: unknown }])[1];
      return { path: init.params.path, body: init.body };
    });
}

/** "Ignorera" of the suggestion on step 2's card, its list and row opened. */
async function cardDismiss() {
  const second = screen.getByRole("article", { name: "Steg 2 Skriv svar" });
  fireEvent.click(await within(second).findByRole("button", { name: /^\d+ förslag/ }));
  fireEvent.click(within(second).getByRole("button", { name: /^Mer om/ }));
  const button = within(second).getByRole("button", { name: /^Ignorera ”/ });
  button.focus();
  return button;
}

/** Another patch suggestion on step 2, for "Åtgärda alla". */
const SECOND_DUPLICATE = { ...DUPLICATE_READ, fingerprint: "d".repeat(64) };

/** The core's answer to a fix: the flow at its new revision and what became of each. */
const fixed = (applied: string[], skipped: string[] = []) =>
  ok({ flow: makeFlow({ draft_revision: 5, steps }), applied, skipped });

function applyBodies() {
  return api.POST.mock.calls
    .filter(([path]) => path === "/api/v1/flows/{id}/suggestions/apply/")
    .map((call) => (call as unknown as [string, { body: unknown }])[1].body);
}

const suggestionReads = () =>
  api.GET.mock.calls.filter(([path]) => path === "/api/v1/flows/{id}/suggestions/").length;

/** The suggestion reads by the runs they measured: 0 for the definition alone. */
const suggestionRuns = () =>
  api.GET.mock.calls
    .filter(([path]) => path === "/api/v1/flows/{id}/suggestions/")
    .map(([, init]) => init?.params?.query?.runs ?? 0);

/** The revision's suggestions measured over the latest runs: the duplicate, with its cost. */
const measuredSuggestions = (revision: number) =>
  ok({
    flow_id: "flow-1",
    draft_revision: revision,
    runs: { requested: 10, counted: 8, left_out: 0 },
    items: [
      {
        ...DUPLICATE_READ,
        impact: {
          basis: "runs",
          level: "high",
          tokens_per_run: 1840,
          run_count: 8,
          version: 3,
          step_changed_since: false
        }
      }
    ]
  });

/** The "Åtgärda" of the suggestion on step 2's card, by its role and name, its list opened. */
async function cardFix() {
  const second = screen.getByRole("article", { name: "Steg 2 Skriv svar" });
  fireEvent.click(await within(second).findByRole("button", { name: /^\d+ förslag/ }));
  return within(second).findByRole("button", { name: /^Åtgärda ”/ });
}

/** The step list, with the suggestions summary at its top. */
const stepsRegion = () => screen.getByRole("region", { name: "Steg" });
/** "Före publicering". */
const draftCheck = () => screen.getByRole("region", { name: "Före publicering" });

/** The flow's chat, opened for someone who may edit. */
const CHAT = { flow_id: "flow-1", assistant_id: "assistant-chat", session_id: "session-1" };

/** Posts that open the chat and check the draft; anything else would be news. */
const OPENING_POSTS = [
  "/api/v1/flows/{id}/authoring-chat/",
  "/api/v1/flows/{id}/security-classification/preview"
];

/** What the page posted, by path. */
const posted = () => api.POST.mock.calls.map(([path]) => path);

beforeEach(() => {
  state.flow = ok(makeFlow({ steps }));
  state.suggestions = suggestions(4, []);
  state.inserted = [];
  state.dirty = false;
  // Without edit access the chat is not offered; most tests are about the definition.
  state.chat = refused(403, { code: "insufficient_space_permission", message: "No." });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  resetNavigation();
  window.history.replaceState(null, "", "/");
  vi.useRealTimers();
  state.prompts = null;
});

function assistantReads() {
  return api.GET.mock.calls.filter(([path]) => path === ASSISTANT).length;
}

function renderPage(
  flow: FlowPublic = makeFlow({ steps }),
  permissions: Permission[] = ["flows_view", "flows_manage"],
  space = makeSpace({})
) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(flowKeys.flow(flow.id), flow);
  queryClient.setQueryData(["spaces", "space-1"], space);
  return renderInApp(
    <Suspense>
      <FlowPage flowId={flow.id} />
    </Suspense>,
    {
      queryClient,
      appContext: testAppContext({ permissions })
    }
  );
}

function editorBody() {
  const call = api.PATCH.mock.calls.find(([path]) => path === "/api/v1/flows/{id}/editor/");
  return (call as unknown as [string, { body: unknown }] | undefined)?.[1].body;
}

describe("FlowPage", () => {
  it("shows the definition beside the chat", async () => {
    const { container } = renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Medborgarbrev" })).toBeTruthy();
    expect(screen.getByText("Utkast")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Flödet" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Definition", selected: true })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Steg" })).toBeTruthy();
    expect(await screen.findByText("Chatten är inte tillgänglig")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("offers a handle to resize the chat beside the definition, not on a phone", async () => {
    renderPage();
    const handle = screen.getByRole("separator", { name: "Ändra storlek på chatten" });
    expect(handle.getAttribute("aria-orientation")).toBe("vertical");
    expect(handle.getAttribute("aria-valuemin")).toBe("352");
    expect(handle.tabIndex).toBe(0);

    act(() => setViewport("phone"));
    expect(screen.queryByRole("separator", { name: "Ändra storlek på chatten" })).toBeNull();
    // The chat is one of the tabbed views there, laid out by the stylesheet alone.
    expect(screen.getByRole("region", { name: "Chatt om flödet" }).style.width).toBe("");
  });

  it("moves a step through the editor, fenced on the revision on screen", async () => {
    state.editor = ok(
      makeFlow({
        draft_revision: 5,
        steps: [
          { ...steps[1]!, step_order: 1 },
          { ...steps[0]!, step_order: 2 }
        ]
      })
    );
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Flytta ner Steg 1: Sammanfatta" }));

    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith("Steg 1: Sammanfatta flyttades till plats 2")
    );
    expect(editorBody()).toEqual({
      step_order: [{ step_id: "step-2" }, { step_id: "step-1" }],
      definition: {},
      expected_revision: 4
    });
    const firstStep = screen.getAllByRole("article")[0]!;
    expect(within(firstStep).getByText("Skriv svar")).toBeTruthy();
  });

  it("saves the draft check's repair of a read of a removed step as a step edit", async () => {
    const broken = {
      ...steps[1]!,
      input_bindings: { question: "Om {{step_3_deleted.output.text}}" }
    };
    const repaired = { ...steps[1]!, input_bindings: { question: "Om {{step_1.output.text}}" } };
    state.editor = ok(makeFlow({ draft_revision: 5, steps: [steps[0]!, repaired] }));
    renderPage(makeFlow({ steps: [steps[0]!, broken] }));

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Välj vad som ska användas i stället för {{step_3_deleted.output.text}} i Steg 2: Skriv svar"
      })
    );
    fireEvent.click(await screen.findByRole("menuitem", { name: /Steg 1: Sammanfatta/ }));

    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith("Hänvisningen i Steg 2: Skriv svar är ersatt.")
    );
    expect(editorBody()).toEqual({
      step_edits: [
        {
          step_id: "step-2",
          changes: { input_bindings: { question: "Om {{step_1.output.text}}" } }
        }
      ],
      definition: {},
      expected_revision: 4
    });
  });

  it("adds the step that names the speakers from the shortcut after the transcription", async () => {
    const transcribe = makeStep(1, {
      user_description: "Transkribera",
      input_type: "audio",
      output_mode: "transcribe_only"
    });
    const wizard = { transcription_enabled: true, transcription_speaker_service: { id: "svc-1" } };
    const flow = makeFlow({ steps: [transcribe], metadata_json: { wizard } });
    state.editor = ok(
      makeFlow({
        draft_revision: 5,
        steps: [transcribe, makeStep(2, { output_mode: "speaker_mapping", output_type: "json" })],
        metadata_json: { wizard }
      })
    );
    const space = makeSpace({
      overrides: {
        transcription_services: [
          {
            id: "svc-1",
            name: "Talare",
            available: true,
            meets_security_classification: true,
            is_default: true
          }
        ]
      }
    });
    // The core allows the speaker step after the transcription, configured to read it.
    const speakers = makeKindOption("speakers", {
      configuration: {
        output_mode: "speaker_mapping",
        output_type: "json",
        review_policy: { mode: "edit" },
        output_config: { speaker_mapping: { participants_field: null } }
      }
    });
    state.kinds = ok({
      flow_id: "flow-1",
      draft_revision: 4,
      insertions: [makeKindPlace(2, [speakers])],
      steps: []
    });
    renderPage(flow, undefined, space);

    expect(await screen.findByText("Vill du granska transkriptet?")).toBeTruthy();
    expect(api.GET).toHaveBeenCalledWith("/api/v1/flows/{id}/step-kinds/", {
      params: { path: { id: "flow-1" }, query: { position: 2 } }
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Lägg till ett steg som granskar transkriptet efter Steg 1: Transkribera"
      })
    );

    await waitFor(() => expect(state.announce).toHaveBeenCalledWith("Steget lades till"));
    expect(editorBody()).toMatchObject({
      expected_revision: 4,
      step_order: [{ step_id: "step-1" }, { new_step: 0 }],
      new_steps: [
        {
          name: "Granska transkript",
          configuration: {
            output_mode: "speaker_mapping",
            output_config: { speaker_mapping: { participants_field: "deltagare" } }
          }
        }
      ],
      definition: {
        metadata_json: {
          form_schema: { fields: [{ name: "deltagare", label: "Deltagare", type: "list" }] }
        }
      }
    });
    expect(screen.queryByText("Vill du granska transkriptet?")).toBeNull();
  });

  it("explains a refused removal by the step that reads the removed one", async () => {
    state.editor = refused(400, {
      code: "flow_step_read_lost_producer",
      message: "Skriv svar (step 2) reads a step this change removes: step 1 in its prompt.",
      context: { step_id: "step-2", step_order: 2, site: "prompt", reads_step: 1 }
    });
    renderPage();
    const trigger = screen.getByRole("button", { name: "Fler åtgärder för Steg 1: Sammanfatta" });
    fireEvent.click(trigger);
    const menu = document.getElementById(trigger.getAttribute("aria-controls") ?? "")!;
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Ta bort steg" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort steget?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort steg" }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Ändringen sparades inte")).toBeTruthy();
    expect(
      within(alert).getByText(/Steg 2: Skriv svar läser Steg 1: Sammanfatta i sin instruktion/)
    ).toBeTruthy();
    expect(editorBody()).toMatchObject({ step_order: [{ step_id: "step-2" }] });
  });

  it("reloads a draft that changed elsewhere and says so", async () => {
    state.editor = refused(400, { code: "stale_revision", message: "Stale." });
    state.flow = ok(makeFlow({ draft_revision: 7, steps }));
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Flytta upp Steg 2: Skriv svar" }));

    expect(await screen.findByText("Flödet hade ändrats")).toBeTruthy();
    await waitFor(() =>
      expect(api.GET).toHaveBeenCalledWith("/api/v1/flows/{id}/", expect.anything())
    );
  });

  it("publishes the revision on screen and puts a refusal on the step it names", async () => {
    state.publish = refused(400, {
      code: "typed_io_tool_not_allowed",
      message: "Tool not allowed.",
      context: { step_order: 2, refusal: "space" }
    });
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Publicera" }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Flödet publicerades inte")).toBeTruthy();
    expect(within(alert).getByText(/^Steg 2: Skriv svar: /)).toBeTruthy();
    expect(api.POST).toHaveBeenCalledWith("/api/v1/flows/{id}/publish/", {
      params: { path: { id: "flow-1" }, query: { expected_revision: 4 } }
    });
  });

  it("keeps a published flow read only until it is unpublished", async () => {
    const published = makeFlow({ steps, published_version: 3 });
    state.unpublish = ok({ ...published, published_version: null });
    renderPage(published);
    expect(screen.getByText("Publicerad, version 3")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Flytta/ })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Avpublicera för att ändra" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Avpublicera flödet?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Avpublicera" }));

    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith("Flödet avpublicerades. Nu kan du ändra det.")
    );
    expect(api.POST).toHaveBeenCalledWith("/api/v1/flows/{id}/unpublish/", {
      params: { path: { id: "flow-1" }, query: { expected_revision: 4 } }
    });
    expect(
      await screen.findByRole("button", { name: "Flytta ner Steg 1: Sammanfatta" })
    ).toBeTruthy();
  });

  it("offers a run of a published flow to someone who may run it", async () => {
    const published = makeFlow({
      steps,
      published_version: 3,
      permissions: flowPermissions({ can_edit: false, can_publish: false, can_delete: false })
    });
    renderPage(published);
    fireEvent.click(screen.getByRole("button", { name: "Kör flödet" }));
    expect(await screen.findByRole("dialog", { name: "Kör Medborgarbrev" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Avpublicera" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Avpublicera för att ändra" })).toBeNull();
    expect(screen.getByText("Ett publicerat flöde kan inte ändras.")).toBeTruthy();
  });

  it("offers no run of a draft, nor to someone who may not run the flow", () => {
    renderPage(makeFlow({ steps }));
    expect(screen.queryByRole("button", { name: "Kör flödet" })).toBeNull();
    cleanup();
    renderPage(
      makeFlow({ steps, published_version: 3, permissions: flowPermissions({ can_run: false }) })
    );
    expect(screen.queryByRole("button", { name: "Kör flödet" })).toBeNull();
  });

  it("shows a draft read only to someone the core lets read it, whatever their role", () => {
    const viewOnly = flowPermissions({
      can_edit: false,
      can_publish: false,
      can_delete: false,
      can_run: false,
      can_view_runs: false
    });
    renderPage(makeFlow({ steps, permissions: viewOnly }), ["flows_view", "flows_manage"]);

    expect(screen.getByRole("button", { name: "Visa Steg 1: Sammanfatta" })).toBeTruthy();
    for (const name of [/Flytta/, "Publicera", "Exportera", "Lägg till steg"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    // Without the runs to read there is one view, so no tabs.
    expect(screen.queryByRole("tab", { name: "Körningar" })).toBeNull();
    // The chat needs edit access, so it is not asked for.
    expect(screen.getByText(messages.flows_chat_no_access)).toBeTruthy();
    expect(api.POST).not.toHaveBeenCalledWith(
      "/api/v1/flows/{id}/authoring-chat/",
      expect.anything()
    );
  });

  it("offers publishing by the flag, not by role", () => {
    renderPage(makeFlow({ steps, permissions: flowPermissions({ can_publish: false }) }));
    expect(screen.queryByRole("button", { name: "Publicera" })).toBeNull();
    expect(screen.getByRole("button", { name: "Flytta ner Steg 1: Sammanfatta" })).toBeTruthy();
    cleanup();
    renderPage(makeFlow({ steps }), ["flows_view"]);
    expect(screen.getByRole("button", { name: "Publicera" })).toBeTruthy();
  });

  it("lists the flow's runs in their own tab and remembers it in the address", async () => {
    const run = {
      id: "run-1",
      flow_id: "flow-1",
      flow_version: 3,
      tenant_id: "tenant-1",
      trace_id: "trace-1",
      status: "completed",
      purpose: "production",
      principal_type: "user",
      revision: 3,
      dispatch_attempt_count: 1,
      created_at: "2026-10-21T08:00:00Z",
      started_at: "2026-10-21T08:00:02Z",
      finished_at: "2026-10-21T08:01:07Z",
      updated_at: "2026-10-21T08:01:07Z"
    };
    state.runs = ok({ count: 1, items: [run], has_more: false });
    const { container } = renderPage(makeFlow({ steps, published_version: 3 }));

    fireEvent.click(screen.getByRole("tab", { name: "Körningar" }));

    expect(screen.getByRole("tab", { name: "Körningar", selected: true })).toBeTruthy();
    const table = await screen.findByRole("table", { name: "Körningar" });
    expect(within(table).getByText("Klar")).toBeTruthy();
    expect(window.location.search).toBe("?tab=runs");
    await expectNoAxeViolations(container);
    window.history.replaceState(null, "", "/");
  });

  it("shows what the chat's tools changed and says so", async () => {
    const chat = { flow_id: "flow-1", assistant_id: "assistant-chat", session_id: "session-1" };
    state.chat = ok({ ...chat, editing: true });
    state.flow = ok(
      makeFlow({
        draft_revision: 5,
        steps: [...steps, makeStep(3, { user_description: "Granska svaret" })]
      })
    );
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Verktyg klart" }));

    expect(await screen.findByText("Granska svaret")).toBeTruthy();
    expect(state.announce).toHaveBeenCalledWith("Chatten lade till Steg 3: Granska svaret.");
    // The new card is marked, for a while.
    expect(screen.getByText("Tillagt av chatten")).toBeTruthy();

    // An answer that changed nothing is not news.
    state.announce.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Svar klart" }));
    await waitFor(() =>
      expect(api.GET.mock.calls.filter(([path]) => path === "/api/v1/flows/{id}/")).toHaveLength(2)
    );
    expect(state.announce).not.toHaveBeenCalled();
  });

  it("turns on the chat's edit mode, fenced on the revision on screen", async () => {
    const chat = { flow_id: "flow-1", assistant_id: "assistant-chat", session_id: "session-1" };
    state.chat = ok({ ...chat, editing: false });
    state.mode = ok({ ...chat, editing: true });
    renderPage();

    // The mode is picked beside the send button, in the composer's footer.
    fireEvent.click(await screen.findByRole("button", { name: "Läge: Fråga" }));
    fireEvent.click(await screen.findByRole("menuitemradio", { name: /Redigera/ }));

    expect(await screen.findByRole("button", { name: "Läge: Redigera" })).toBeTruthy();
    expect(screen.getByText("Beskriv ändringen…")).toBeTruthy();
    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith(
        "Redigeringsläget är på. Chatten kan nu ändra flödet."
      )
    );
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/flows/{id}/authoring-chat/{session_id}/", {
      params: { path: { id: "flow-1", session_id: "session-1" } },
      body: { editing: true, expected_revision: 4 }
    });
  });

  it("follows the new conversation edit mode starts after a pause, without a reload", async () => {
    const chat = { flow_id: "flow-1", assistant_id: "assistant-chat", session_id: "session-1" };
    state.chat = ok({ ...chat, editing: false });
    state.mode = ok({ ...chat, session_id: "session-2", editing: true });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Läge: Fråga" }));
    fireEvent.click(await screen.findByRole("menuitemradio", { name: /Redigera/ }));

    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith(
        "Redigeringsläget är på. Det var ett tag sedan sist, så chatten började en ny konversation."
      )
    );
    await waitFor(() =>
      expect(api.GET).toHaveBeenCalledWith("/api/v1/conversations/{session_id}/", {
        params: { path: { session_id: "session-2" } },
        signal: expect.anything()
      })
    );
    expect(await screen.findByRole("button", { name: "Ny konversation" })).toBeTruthy();
  });

  it("hands a suggestion to the chat, bringing the chat into view on a phone, unsent", async () => {
    state.chat = ok({ ...CHAT, editing: false });
    state.suggestions = suggestions(4, [DUPLICATE_READ]);
    setViewport("phone");
    const { container } = renderPage();
    const definition = screen.getByRole("region", { name: "Flödet" });
    const chat = screen.getByRole("region", { name: "Chatt om flödet" });
    expect(chat.className).toContain("max-lg:hidden");

    fireEvent.click(await screen.findByRole("button", { name: /^1 förslag/ }));
    fireEvent.click(screen.getByRole("button", { name: /^Mer om/ }));
    // Offered once the chat's composer is on the page.
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Fråga assistenten om ”Svaret från Steg 1: Sammanfatta skickas två gånger”"
      })
    );
    // Text as typed, each step a pill that carries its id (a pill brings its own space).
    await waitFor(() =>
      expect(state.inserted).toEqual([
        "Förklara förslaget ”Svaret från ",
        "@[Sammanfatta](step:step-1)",
        "skickas två gånger” (duplicate_read) och föreslå hur flödet kan ändras. Steg: ",
        "@[Skriv svar](step:step-2)",
        "@[Sammanfatta](step:step-1)"
      ])
    );
    expect(definition.className).toContain("max-lg:hidden");
    expect(chat.className).not.toContain("max-lg:hidden");
    // The chat was opened and the draft checked; nothing was sent, and the mode stayed.
    expect(posted().every((path) => OPENING_POSTS.includes(path))).toBe(true);
    expect(api.PATCH).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Läge: Fråga" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("offers no request to a chat that is not available", async () => {
    state.suggestions = suggestions(4, [DUPLICATE_READ]);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /^1 förslag/ }));
    fireEvent.click(screen.getByRole("button", { name: /^Mer om/ }));
    expect(screen.queryByRole("button", { name: /^Fråga assistenten/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Optimera flödet" })).toBeNull();
  });

  it("puts the review request in the chat from Optimera flödet, sending nothing", async () => {
    state.chat = ok({ ...CHAT, editing: false });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Optimera flödet" }));
    await waitFor(() => expect(state.inserted.join("")).toMatch(/^Gå igenom flödets förslag/));
    // Once, however often the page renders afterwards.
    expect(state.inserted).toHaveLength(1);
    expect(posted().every((path) => OPENING_POSTS.includes(path))).toBe(true);
    expect(api.PATCH).not.toHaveBeenCalled();
  });

  it("asks for the suggestions again when the chat's tools change the draft", async () => {
    state.chat = ok({ ...CHAT, editing: true });
    state.suggestions = suggestions(4, [DUPLICATE_READ]);
    renderPage();
    const second = screen.getByRole("article", { name: "Steg 2 Skriv svar" });
    expect(await within(second).findByRole("button", { name: /^1 förslag/ })).toBeTruthy();
    // The summary above the steps, and the line in "Före publicering", from the same read.
    expect(
      within(stepsRegion()).getByText("1 förslag kan göra flödet enklare eller billigare")
    ).toBeTruthy();
    expect(
      within(draftCheck()).getByText("1 förslag kan göra flödet enklare eller billigare")
    ).toBeTruthy();

    // The chat removed the duplicate: a new revision, and no suggestion on it.
    state.flow = ok(makeFlow({ draft_revision: 5, steps }));
    state.suggestions = suggestions(5, []);
    fireEvent.click(await screen.findByRole("button", { name: "Verktyg klart" }));

    await waitFor(() =>
      expect(within(second).queryByRole("button", { name: /^1 förslag/ })).toBeNull()
    );
    expect(screen.queryByText(/förslag kan göra flödet/)).toBeNull();
    // One request per revision.
    expect(
      api.GET.mock.calls.filter(([path]) => path === "/api/v1/flows/{id}/suggestions/")
    ).toHaveLength(2);
  });

  it("offers no measuring to someone who may not view flow traces, and reads no runs", async () => {
    state.suggestions = suggestions(4, [DUPLICATE_READ]);
    renderPage();
    expect(
      await within(stepsRegion()).findByText("1 förslag kan göra flödet enklare eller billigare")
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Räkna med de senaste körningarna" })).toBeNull();
    expect(suggestionRuns()).toEqual([0]);
  });

  it("measures the suggestions on a press for the visit, and again only for a new revision", async () => {
    state.chat = ok({ ...CHAT, editing: true });
    state.suggestions = suggestions(4, [DUPLICATE_READ]);
    state.measured = measuredSuggestions(4);
    const { container } = renderPage(makeFlow({ steps }), [
      "flows_view",
      "flows_manage",
      "flows_trace"
    ]);
    const measure = await screen.findByRole("button", { name: "Räkna med de senaste körningarna" });
    expect(suggestionRuns()).toEqual([0]);

    fireEvent.click(measure);
    await waitFor(() => expect(state.announce).toHaveBeenCalledWith("Baserat på 8 körningar."));
    expect(screen.getByText("Baserat på 8 körningar.")).toBeTruthy();
    expect(suggestionRuns()).toEqual([0, 10]);
    await expectNoAxeViolations(container);

    // The editor is given the same measured answer; back on the list, it is not read again.
    fireEvent.click(screen.getByRole("button", { name: "Redigera Steg 2: Skriv svar" }));
    expect(screen.getByText("Förslagen räknas med 10 körningar")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Alla steg" }));
    expect(await screen.findByText("Baserat på 8 körningar.")).toBeTruthy();
    expect(suggestionRuns()).toEqual([0, 10]);

    // The chat's tools changed the draft: the new revision is measured.
    state.flow = ok(makeFlow({ draft_revision: 5, steps }));
    state.suggestions = suggestions(5, []);
    state.measured = measuredSuggestions(5);
    fireEvent.click(await screen.findByRole("button", { name: "Verktyg klart" }));
    await waitFor(() => expect(suggestionRuns()).toEqual([0, 10, 10]));

    // The way back reads the revision's plain answer, and says so.
    fireEvent.click(screen.getByRole("button", { name: "Visa utan körningarna" }));
    await waitFor(() => expect(suggestionRuns()).toEqual([0, 10, 10, 0]));
    expect(state.announce).toHaveBeenCalledWith("Förslagen bygger nu bara på flödets definition.");
    await waitFor(() => expect(screen.queryByText(/Baserat på/)).toBeNull());
    expect(screen.getByRole("button", { name: "Räkna med de senaste körningarna" })).toBeTruthy();
  });

  it("keeps a measured answer out of a re-read after a stale fix", async () => {
    state.suggestions = suggestions(4, [DUPLICATE_READ]);
    state.measured = measuredSuggestions(4);
    state.apply = refused(409, { code: "flow_suggestion_stale", message: "Gone." });
    renderPage(makeFlow({ steps }), ["flows_view", "flows_manage", "flows_trace"]);
    fireEvent.click(
      await screen.findByRole("button", { name: "Räkna med de senaste körningarna" })
    );
    expect(await screen.findByText("Baserat på 8 körningar.")).toBeTruthy();

    fireEvent.click(await cardFix());
    expect(await screen.findByRole("alert")).toBeTruthy();
    // Each measured read writes an audit entry: a refused fix reads none.
    expect(suggestionRuns()).toEqual([0, 10]);
  });

  it("fixes a suggestion from its card on the revision on screen and takes the new draft", async () => {
    state.suggestions = suggestions(4, [DUPLICATE_READ]);
    state.apply = fixed([DUPLICATE_READ.fingerprint]);
    renderPage();
    const button = await cardFix();
    // The fixed draft has no suggestion left.
    state.suggestions = suggestions(5, []);

    fireEvent.click(button);

    await waitFor(() => expect(state.announce).toHaveBeenCalledWith("Förslaget är åtgärdat"));
    expect(applyBodies()).toEqual([
      { expected_revision: 4, fingerprints: [DUPLICATE_READ.fingerprint] }
    ]);
    // The flow came back with the answer: its revision asks for its suggestions.
    await waitFor(() => expect(screen.queryByRole("button", { name: /^Åtgärda ”/ })).toBeNull());
    expect(suggestionReads()).toBe(2);
    expect(api.GET).not.toHaveBeenCalledWith("/api/v1/flows/{id}/", expect.anything());
  });

  it("fixes every patch suggestion at once after Åtgärda alla is confirmed", async () => {
    state.suggestions = suggestions(4, [DUPLICATE_READ, SECOND_DUPLICATE]);
    state.apply = fixed([DUPLICATE_READ.fingerprint, SECOND_DUPLICATE.fingerprint]);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Åtgärda alla (2)" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Åtgärda 2 förslag?" });
    expect(applyBodies()).toEqual([]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Åtgärda" }));

    await waitFor(() => expect(state.announce).toHaveBeenCalledWith("2 förslag är åtgärdade"));
    expect(applyBodies()).toEqual([
      {
        expected_revision: 4,
        fingerprints: [DUPLICATE_READ.fingerprint, SECOND_DUPLICATE.fingerprint]
      }
    ]);
  });

  it("notes the suggestions an earlier fix made unnecessary", async () => {
    state.suggestions = suggestions(4, [DUPLICATE_READ, SECOND_DUPLICATE]);
    state.apply = fixed([DUPLICATE_READ.fingerprint], [SECOND_DUPLICATE.fingerprint]);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Åtgärda alla (2)" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Åtgärda 2 förslag?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Åtgärda" }));

    const title = await screen.findByText("Ett förslag behövdes inte längre");
    const note = title.closest("[role=status]");
    expect(note).not.toBeNull();
    expect(
      within(note as HTMLElement).getByText("De andra åtgärderna tog redan hand om det.")
    ).toBeTruthy();
    // The fix itself is announced once, where it was pressed.
    expect(state.announce).toHaveBeenCalledWith("2 förslag är åtgärdade");
  });

  it("explains a fix of a suggestion that no longer holds and asks for the suggestions again", async () => {
    state.suggestions = suggestions(4, [DUPLICATE_READ]);
    state.apply = refused(409, { code: "flow_suggestion_stale", message: "Gone." });
    renderPage();
    const button = await cardFix();
    expect(suggestionReads()).toBe(1);

    fireEvent.click(button);

    const notice = await screen.findByRole("alert");
    expect(within(notice).getByText("Inget förslag åtgärdades")).toBeTruthy();
    expect(within(notice).getByText(messages.flow_error_flow_suggestion_stale)).toBeTruthy();
    await waitFor(() => expect(suggestionReads()).toBe(2));
    expect(state.announce).not.toHaveBeenCalledWith("Förslaget är åtgärdat");
  });

  it("explains a fix that is not a patch with the catalogue's text", async () => {
    state.suggestions = suggestions(4, [DUPLICATE_READ]);
    state.apply = refused(409, { code: "flow_suggestion_not_patchable", message: "No." });
    renderPage();

    fireEvent.click(await cardFix());

    const notice = await screen.findByRole("alert");
    expect(
      within(notice).getByText(messages.flow_error_flow_suggestion_not_patchable)
    ).toBeTruthy();
  });

  it("makes one fix at a time: a press while one is saved is ignored", async () => {
    state.suggestions = suggestions(4, [DUPLICATE_READ]);
    let answer: (reply: Reply) => void = () => {};
    state.apply = new Promise<Reply>((resolve) => {
      answer = resolve;
    });
    renderPage();
    const button = await cardFix();

    fireEvent.click(button);
    await waitFor(() => expect(applyBodies()).toHaveLength(1));
    // The same button, now showing that it saves, and "Åtgärda alla".
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("button", { name: /^Åtgärda alla/ }));

    expect(applyBodies()).toHaveLength(1);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await act(async () => answer(fixed([DUPLICATE_READ.fingerprint])));
    await waitFor(() => expect(state.announce).toHaveBeenCalledWith("Förslaget är åtgärdat"));
  });

  it("fixes the open step's suggestion from its editor through the same call", async () => {
    setRoute("/?step=step-2");
    window.history.replaceState(null, "", "/?step=step-2");
    let answer: (reply: Reply) => void = () => {};
    state.apply = new Promise<Reply>((resolve) => {
      answer = resolve;
    });
    renderPage();
    const button = screen.getByRole("button", { name: "Åtgärda i steget" });

    fireEvent.click(button);

    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(true));
    expect(applyBodies()).toEqual([{ expected_revision: 4, fingerprints: ["e".repeat(64)] }]);
    await act(async () => answer(fixed(["e".repeat(64)])));
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
  });

  it("dismisses a suggestion with its code, reads the plain suggestions again and keeps focus", async () => {
    state.suggestions = suggestions(4, [DUPLICATE_READ]);
    state.dismiss = DISMISSAL;
    renderPage();
    const button = await cardDismiss();
    expect(within(draftCheck()).getByText(/^1 förslag kan göra flödet/)).toBeTruthy();
    // The core lists it as dismissed from now on.
    state.suggestions = withDismissed(4, [DISMISSED_DUPLICATE]);

    fireEvent.click(button);

    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith(messages.flow_suggestion_dismissed_done)
    );
    expect(dismissals()).toEqual([
      {
        path: { id: "flow-1", fingerprint: DUPLICATE_READ.fingerprint },
        body: { code: "duplicate_read" }
      }
    ]);
    // The revision stays: the suggestions on screen are read once more, measuring nothing.
    expect(suggestionRuns()).toEqual([0, 0]);
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", { name: "Redigera Steg 2: Skriv svar" })
      )
    );
    // Dismissed, it counts nowhere, before publishing included.
    expect(within(draftCheck()).queryByText(/förslag kan göra flödet/)).toBeNull();
    expect(screen.getByRole("button", { name: "Visa ignorerade (1)" })).toBeTruthy();
  });

  it("measures once more after a dismissal while the page measures, and never otherwise", async () => {
    state.suggestions = suggestions(4, [DUPLICATE_READ]);
    state.measured = measuredSuggestions(4);
    state.dismiss = DISMISSAL;
    renderPage(makeFlow({ steps }), ["flows_view", "flows_manage", "flows_trace"]);
    fireEvent.click(
      await screen.findByRole("button", { name: "Räkna med de senaste körningarna" })
    );
    expect(await screen.findByText("Baserat på 8 körningar.")).toBeTruthy();
    expect(suggestionRuns()).toEqual([0, 10]);

    fireEvent.click(await cardDismiss());

    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith(messages.flow_suggestion_dismissed_done)
    );
    // Exactly one measured read, and no plain one while the plain answer is off screen.
    expect(suggestionRuns()).toEqual([0, 10, 10]);
    // Back to the definition alone, its answer is read anew (it was dismissed since).
    fireEvent.click(screen.getByRole("button", { name: "Visa utan körningarna" }));
    await waitFor(() => expect(suggestionRuns()).toEqual([0, 10, 10, 0]));
  });

  it("explains a refused dismissal above the definition, and reads nothing again", async () => {
    state.suggestions = suggestions(4, [DUPLICATE_READ]);
    state.dismiss = refused(403, { code: "insufficient_space_permission", message: "No." });
    renderPage();

    fireEvent.click(await cardDismiss());

    const notice = await screen.findByRole("alert");
    expect(within(notice).getByText("Förslaget ignorerades inte")).toBeTruthy();
    expect(within(notice).getByText(messages.flows_refusal_no_permission)).toBeTruthy();
    expect(state.announce).not.toHaveBeenCalledWith(messages.flow_suggestion_dismissed_done);
    expect(suggestionRuns()).toEqual([0]);
  });

  it("reads the plain suggestions again when the draft no longer has the one dismissed", async () => {
    state.suggestions = suggestions(4, [DUPLICATE_READ]);
    state.dismiss = refused(409, { code: "flow_suggestion_stale", message: "Gone." });
    renderPage();

    fireEvent.click(await cardDismiss());

    const notice = await screen.findByRole("alert");
    expect(within(notice).getByText(messages.flow_error_flow_suggestion_stale)).toBeTruthy();
    await waitFor(() => expect(suggestionRuns()).toEqual([0, 0]));
  });

  it("shows the dismissed suggestions for the visit and takes a dismissal back", async () => {
    state.suggestions = withDismissed(4, [DISMISSED_DUPLICATE]);
    state.restore = { data: undefined, response: new Response(null, { status: 204 }) };
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Visa ignorerade (1)" }));
    // Held for the visit: the list remembers it after a step was open.
    fireEvent.click(screen.getByRole("button", { name: "Redigera Steg 2: Skriv svar" }));
    fireEvent.click(screen.getByRole("button", { name: "Alla steg" }));
    const hide = await screen.findByRole("button", { name: "Dölj ignorerade (1)" });
    expect(hide.getAttribute("aria-expanded")).toBe("true");
    expect(suggestionRuns()).toEqual([0]);

    state.suggestions = suggestions(4, [DUPLICATE_READ]);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Visa ”Svaret från Steg 1: Sammanfatta skickas två gånger” igen"
      })
    );

    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith(messages.flow_suggestion_restored_done)
    );
    expect(api.DELETE.mock.calls.map((call) => (call as unknown as [string, unknown])[1])).toEqual([
      { params: { path: { id: "flow-1", fingerprint: DUPLICATE_READ.fingerprint } } }
    ]);
    expect(suggestionRuns()).toEqual([0, 0]);
    // Back on the card, and before publishing counted again.
    expect(within(draftCheck()).getByText(/^1 förslag kan göra flödet/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /ignorerade/ })).toBeNull();
  });

  it("takes a dismissal back that someone else already took back, without a refusal", async () => {
    state.suggestions = withDismissed(4, [DISMISSED_DUPLICATE]);
    state.restore = refused(404, { message: "This suggestion is not dismissed." });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Visa ignorerade (1)" }));
    state.suggestions = suggestions(4, [DUPLICATE_READ]);

    fireEvent.click(screen.getByRole("button", { name: /^Visa ”.*” igen$/ }));

    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith(messages.flow_suggestion_restored_done)
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(suggestionRuns()).toEqual([0, 0]);
  });

  it("brings the suggestions summary into view and focus from Före publicering", async () => {
    state.suggestions = suggestions(4, [DUPLICATE_READ]);
    const { container } = renderPage();

    fireEvent.click(await within(draftCheck()).findByRole("button", { name: "Visa förslagen" }));

    const summary = within(stepsRegion())
      .getByText("1 förslag kan göra flödet enklare eller billigare")
      .closest("[tabindex='-1']");
    expect(summary).not.toBeNull();
    expect(document.activeElement).toBe(summary);
    // Advice only: publishing is offered as before.
    expect(screen.getByRole("button", { name: "Publicera" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("opens one reference card for both sides, and inserts from the definition into the chat", async () => {
    state.chat = ok({ ...CHAT, editing: false });
    state.suggestions = suggestions(4, [DUPLICATE_READ]);
    setViewport("phone");
    renderPage();
    const chat = screen.getByRole("region", { name: "Chatt om flödet" });

    const card = screen.getByRole("article", { name: "Steg 2 Skriv svar" });
    fireEvent.click(await within(card).findByRole("button", { name: /^1 förslag/ }));
    fireEvent.click(within(card).getByRole("button", { name: "Steg 1: Sammanfatta" }));
    const dialog = await screen.findByRole("dialog", { name: "Referens" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Infoga i meddelandet" }));

    expect(state.inserted).toEqual(["@[Sammanfatta](step:step-1)"]);
    expect(chat.className).not.toContain("max-lg:hidden");
    expect(screen.queryByRole("dialog", { name: "Referens" })).toBeNull();
  });

  it("opens a step in the address, and Back and Forward close and reopen it", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Redigera Steg 2: Skriv svar" }));
    expect(screen.getByText("Redigerar step-2")).toBeTruthy();
    expect(new URL(window.location.href).searchParams.get("step")).toBe("step-2");
    expect(document.activeElement).toBe(
      screen.getByRole("region", { name: "Inställningar för Steg 2: Skriv svar" })
    );

    window.history.back();
    const open = await screen.findByRole("button", { name: "Redigera Steg 2: Skriv svar" });
    await waitFor(() => expect(document.activeElement).toBe(open));
    expect(window.location.search).toBe("");

    window.history.forward();
    expect(await screen.findByText("Redigerar step-2")).toBeTruthy();
  });

  it("goes back to the list from the editor, through the history it opened", async () => {
    const { container } = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Redigera Steg 1: Sammanfatta" }));
    fireEvent.click(screen.getByRole("button", { name: "Nästa" }));
    expect(screen.getByText("Redigerar step-2")).toBeTruthy();
    expect(new URL(window.location.href).searchParams.get("step")).toBe("step-2");

    fireEvent.click(screen.getByRole("button", { name: "Alla steg" }));
    const open = await screen.findByRole("button", { name: "Redigera Steg 2: Skriv svar" });
    await waitFor(() => expect(document.activeElement).toBe(open));
    expect(window.location.search).toBe("");
    await expectNoAxeViolations(container);
  });

  it("walks Back through the steps visited before the list", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Redigera Steg 1: Sammanfatta" }));
    fireEvent.click(screen.getByRole("button", { name: "Nästa" }));
    window.history.back();
    expect(await screen.findByText("Redigerar step-1")).toBeTruthy();
    expect(new URL(window.location.href).searchParams.get("step")).toBe("step-1");
  });

  it("opens the step a link names, and the list for a step the flow does not have", () => {
    setRoute("/?step=step-2");
    window.history.replaceState(null, "", "/?step=step-2");
    renderPage();
    expect(screen.getByText("Redigerar step-2")).toBeTruthy();
    cleanup();

    setRoute("/?step=step-9");
    renderPage();
    expect(screen.getByRole("button", { name: "Redigera Steg 1: Sammanfatta" })).toBeTruthy();
  });

  it("asks before Back leaves unsaved changes, and stays on the step until told", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Redigera Steg 1: Sammanfatta" }));
    state.dirty = true;

    window.history.back();
    const leave = await screen.findByRole("button", { name: "Lämna utan att spara" });
    // The step went back into the address while the editor asks.
    expect(screen.getByText("Redigerar step-1")).toBeTruthy();
    expect(new URL(window.location.href).searchParams.get("step")).toBe("step-1");

    fireEvent.click(leave);
    expect(
      await screen.findByRole("button", { name: "Redigera Steg 1: Sammanfatta" })
    ).toBeTruthy();
    expect(window.location.search).toBe("");
  });

  it("asks before the back control or the next step leave unsaved changes", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Redigera Steg 1: Sammanfatta" }));
    state.dirty = true;

    fireEvent.click(screen.getByRole("button", { name: "Nästa" }));
    expect(screen.getByText("Redigerar step-1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Lämna utan att spara" }));
    expect(screen.getByText("Redigerar step-2")).toBeTruthy();

    state.dirty = true;
    fireEvent.click(screen.getByRole("button", { name: "Alla steg" }));
    expect(screen.getByText("Redigerar step-2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Lämna utan att spara" }));
    expect(await screen.findByRole("button", { name: "Redigera Steg 2: Skriv svar" })).toBeTruthy();
  });

  describe("step prompts", () => {
    const three = [
      makeStep(1, { user_description: "Sammanfatta" }),
      makeStep(2, { user_description: "Skriv svar" }),
      makeStep(3, { user_description: "Granska", input_source: "flow_input" })
    ];

    it("are not asked for by someone who may not edit the flow", async () => {
      state.prompts = {};
      renderPage(makeFlow({ steps, permissions: flowPermissions({ can_edit: false }) }));
      await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
      expect(assistantReads()).toBe(0);
    });

    it("are read once per AI step for an editor, not again on a refocus", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      state.prompts = {};
      renderPage();
      await waitFor(() => expect(assistantReads()).toBe(2));

      await act(() => vi.advanceTimersByTimeAsync(31_000));
      act(() => {
        focusManager.setFocused(false);
        focusManager.setFocused(true);
      });
      focusManager.setFocused(undefined);
      await act(() => vi.advanceTimersByTimeAsync(100));
      expect(assistantReads()).toBe(2);
    });

    it("are read again after a move, which may rewrite what a prompt names", async () => {
      state.prompts = { "assistant-3": "Jämför med {{step_2.output.text}}." };
      state.editor = ok(
        makeFlow({
          draft_revision: 5,
          steps: [{ ...three[1]!, step_order: 1 }, { ...three[0]!, step_order: 2 }, three[2]!]
        })
      );
      renderPage(makeFlow({ steps: three }));
      const granska = () => screen.getByRole("article", { name: "Steg 3 Granska" });
      expect(await within(granska()).findByText("Steg 2: Skriv svar")).toBeTruthy();
      expect(assistantReads()).toBe(3);

      // The core follows the moved step: the prompt now names it by its new place.
      state.prompts = { "assistant-3": "Jämför med {{step_1.output.text}}." };
      fireEvent.click(screen.getByRole("button", { name: "Flytta upp Steg 2: Skriv svar" }));
      expect(await within(granska()).findByText("Steg 1: Skriv svar")).toBeTruthy();
      expect(within(granska()).queryByText("Steg 2: Sammanfatta")).toBeNull();
      await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
      expect(assistantReads()).toBe(6);
    });

    it("applies the chat's change without a view transition in a hidden tab, and absorbs a skipped one", async () => {
      const chat = { flow_id: "flow-1", assistant_id: "assistant-chat", session_id: "session-1" };
      state.chat = ok({ ...chat, editing: true });
      state.prompts = {};
      state.flow = ok(makeFlow({ draft_revision: 5, steps }));
      // A browser whose transition is skipped (the tab hidden meanwhile): the
      // change applies, and the transition's promises reject, which the page
      // must take without an unhandled rejection.
      const skipped = () => Promise.reject(new Error("Document hidden"));
      const start = vi.fn((apply: () => void) => {
        apply();
        return { ready: skipped(), finished: skipped(), updateCallbackDone: Promise.resolve() };
      });
      Object.defineProperty(document, "startViewTransition", { value: start, configurable: true });
      const visibility = vi.spyOn(document, "visibilityState", "get");
      try {
        renderPage();
        await waitFor(() => expect(assistantReads()).toBe(2));

        visibility.mockReturnValue("hidden");
        state.flow = ok(
          makeFlow({
            draft_revision: 6,
            steps: [
              makeStep(1, { user_description: "Sammanfatta" }),
              makeStep(2, { user_description: "Skriv brev" })
            ]
          })
        );
        fireEvent.click(await screen.findByRole("button", { name: "Verktyg klart" }));
        await screen.findByRole("article", { name: "Steg 2 Skriv brev" });
        expect(start).not.toHaveBeenCalled();

        visibility.mockReturnValue("visible");
        state.flow = ok(makeFlow({ draft_revision: 7, steps }));
        fireEvent.click(await screen.findByRole("button", { name: "Verktyg klart" }));
        await screen.findByRole("article", { name: "Steg 2 Skriv svar" });
        expect(start).toHaveBeenCalledTimes(1);
      } finally {
        visibility.mockRestore();
        delete (document as { startViewTransition?: unknown }).startViewTransition;
      }
    });

    it("are read again after the chat's tools changed the flow", async () => {
      const chat = { flow_id: "flow-1", assistant_id: "assistant-chat", session_id: "session-1" };
      state.chat = ok({ ...chat, editing: true });
      state.prompts = {};
      state.flow = ok(makeFlow({ draft_revision: 5, steps }));
      renderPage();
      await waitFor(() => expect(assistantReads()).toBe(2));

      fireEvent.click(await screen.findByRole("button", { name: "Verktyg klart" }));
      await waitFor(() => expect(assistantReads()).toBe(4));
      await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
      expect(assistantReads()).toBe(4);
    });
  });
});
