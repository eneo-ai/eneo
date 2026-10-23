// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import type { Permission } from "@/lib/auth/permissions";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { makeKindOption, makeKindPlace } from "./editor/testing/fixtures";
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
  // What went into the chat's composer, text and pills (by the value they send) in order.
  inserted: [] as string[],
  composer: {
    insertText: (text: string) => state.inserted.push(text),
    insertToken: (token: { value: string }) => state.inserted.push(token.value)
  }
}));

const api = vi.hoisted(() => ({
  GET: vi.fn(async (path: string) => {
    if (path === "/api/v1/flows/{id}/") return state.flow;
    if (path === "/api/v1/flows/{id}/runs/") return state.runs;
    if (path === "/api/v1/flows/{id}/step-kinds/") return state.kinds;
    if (path === "/api/v1/flows/{id}/suggestions/") return state.suggestions;
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
  }),
  POST: vi.fn(async (path: string) => {
    if (path === "/api/v1/flows/{id}/authoring-chat/") return state.chat;
    if (path === "/api/v1/flows/{id}/publish/") return state.publish;
    if (path === "/api/v1/flows/{id}/unpublish/") return state.unpublish;
    return { data: undefined, response: new Response() };
  }),
  PATCH: vi.fn(async (path: string) => {
    if (path === "/api/v1/flows/{id}/editor/") return state.editor;
    if (path === "/api/v1/flows/{id}/authoring-chat/{session_id}/") return state.mode;
    return { data: undefined, response: new Response() };
  }),
  PUT: vi.fn(),
  DELETE: vi.fn()
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
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const { makeSpace: space } = await import("@/features/spaces/testing/space-fixture");
  return { useSpace: () => useSpaceFromQuery(() => space({})) };
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
  // Without edit access the chat is not offered; most tests are about the definition.
  state.chat = refused(403, { code: "insufficient_space_permission", message: "No." });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

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
    const { container } = renderPage();
    const definition = screen.getByRole("region", { name: "Flödet" });
    const chat = screen.getByRole("region", { name: "Chatt om flödet" });
    expect(chat.className).toContain("max-lg:hidden");

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Fråga assistenten om ”Svaret från steg 1 skickas två gånger” (Steg 2: Skriv svar)"
      })
    );
    // Text as typed, each step a pill that carries its id.
    await waitFor(() =>
      expect(state.inserted).toEqual([
        "Förklara förslaget ”Svaret från steg 1 skickas två gånger” (duplicate_read) och " +
          "föreslå hur flödet kan ändras. Steg: ",
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
    expect(await screen.findByText("Svaret från steg 1 skickas två gånger")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Fråga assistenten/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Optimera flödet" })).toBeNull();
  });

  it("puts the review request in the chat from Optimera flödet, sending nothing", async () => {
    state.chat = ok({ ...CHAT, editing: false });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Optimera flödet" }));
    await waitFor(() =>
      expect(state.inserted.join("")).toMatch(/^Granska flödet med read_flow_suggestions/)
    );
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
    expect(await within(second).findByText("1 förslag för Steg 2: Skriv svar")).toBeTruthy();
    expect(await screen.findByRole("heading", { level: 3, name: "Förslag (1)" })).toBeTruthy();

    // The chat removed the duplicate: a new revision, and no suggestion on it.
    state.flow = ok(makeFlow({ draft_revision: 5, steps }));
    state.suggestions = suggestions(5, []);
    fireEvent.click(screen.getByRole("button", { name: "Verktyg klart" }));

    await waitFor(() =>
      expect(within(second).queryByText("1 förslag för Steg 2: Skriv svar")).toBeNull()
    );
    expect(screen.queryByRole("heading", { level: 3, name: "Förslag (1)" })).toBeNull();
    // The panel and the marker share one request per revision.
    expect(
      api.GET.mock.calls.filter(([path]) => path === "/api/v1/flows/{id}/suggestions/")
    ).toHaveLength(2);
  });
});
