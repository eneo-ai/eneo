// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import messages from "@/lib/i18n/messages/sv.json";
import type { SuggestionDismissal, SuggestionFix } from "../flow-suggestion-item";
import { flowEditorKeys } from "./editor-api";
import type { FlowPublic } from "./step-types";
import { makeAssistant, makeFlow, makeStep } from "./testing/fixtures";

const api = vi.hoisted(() => ({
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("./testing/fixtures").apiStub>
}));

vi.mock("@/lib/api/browser", async () => {
  const { apiStub: makeStub } = await import("./testing/fixtures");
  api.stub = makeStub(new Proxy({}, { get: (_target, key: string) => api.routes[key] }));
  return { browserApi: api.stub.client };
});

import { FlowStepEditor, type StepNavigation } from "./flow-step-editor";

const EDITOR = "PATCH /api/v1/flows/{id}/editor/";
const ASSISTANT = "GET /api/v1/flows/{id}/assistants/{assistant_id}/";

function routeBasics(assistant = makeAssistant()) {
  api.routes = {
    [ASSISTANT]: () => ({ body: assistant }),
    "GET /api/v1/spaces/": () => ({ body: { items: [] } }),
    "GET /api/v1/security-classifications/": () => ({
      body: { security_classifications: [], security_enabled: false }
    }),
    "GET /api/v1/flows/{id}/tool-options": () => ({
      body: { items: [], security_classifications_enabled: false }
    }),
    "POST /api/v1/flows/{id}/security-classification/preview": () => ({
      body: {
        steps: [
          {
            step_id: "step-1",
            step_order: 1,
            input_level: null,
            reads: [],
            knowledge_level: null,
            external_source_level: null,
            model_level: null,
            required_model_level: null,
            qualifying_model_ids: ["model-1", "model-2"],
            effective_output_level: null,
            output_floor: null,
            violation: null
          }
        ]
      }
    })
  };
}

function patchBodies() {
  return api.stub.calls
    .filter((call) => `${call.method} ${call.path}` === EDITOR)
    .map((call) => call.init.body);
}

function renderEditor(
  flow: FlowPublic,
  overrides: {
    readOnly?: boolean;
    space?: ReturnType<typeof makeSpace>;
    onAskChat?: (text: string) => void;
    suggestionFix?: SuggestionFix;
    suggestionDismissal?: SuggestionDismissal;
    suggestionRuns?: number;
    navigation?: StepNavigation;
    /** The step assistant as the step list already read it. */
    cachedAssistant?: ReturnType<typeof makeAssistant>;
  } = {}
) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["spaces", "space-1"], overrides.space ?? makeSpace());
  if (overrides.cachedAssistant) {
    queryClient.setQueryData(
      flowEditorKeys.assistant(flow.id, "assistant-1"),
      overrides.cachedAssistant
    );
  }
  const onSaved = vi.fn();
  const onCancel = vi.fn();
  const view = renderInApp(
    <FlowStepEditor
      flow={flow}
      stepId="step-1"
      readOnly={overrides.readOnly ?? false}
      onSaved={onSaved}
      onCancel={onCancel}
      onAskChat={overrides.onAskChat}
      suggestionFix={overrides.suggestionFix}
      suggestionDismissal={overrides.suggestionDismissal}
      suggestionRuns={overrides.suggestionRuns}
      navigation={overrides.navigation}
    />,
    { queryClient }
  );
  return { ...view, onSaved, onCancel };
}

function httpFlow(auth: Record<string, unknown> = { mode: "none" }) {
  return makeFlow({
    steps: [
      makeStep({
        input_source: "http_get",
        output_mode: "compose_text",
        input_config: {
          url: "https://api.example.org/a",
          auth,
          timeout_seconds: 30,
          body: { mode: "none" },
          custom_headers: [],
          response_format: "text"
        }
      })
    ]
  });
}

async function nameField() {
  return (await screen.findByLabelText(/^Stegnamn/)) as HTMLInputElement;
}

beforeEach(() => routeBasics());
afterEach(() => {
  cleanup();
  api.stub.calls.length = 0;
});

describe("FlowStepEditor", () => {
  it("saves manual upload format and MIME restrictions, and reads them when reopened", async () => {
    const original = makeFlow({
      steps: [
        makeStep({
          input_config: {
            future: 1,
            runtime_input: { enabled: true, required: true, max_files: 3, input_format: "document" }
          }
        })
      ]
    });
    let stored = original;
    api.routes[EDITOR] = (init) => {
      const body = (init as { body: { step_edits: { changes: Record<string, unknown> }[] } }).body;
      stored = makeFlow({
        draft_revision: 5,
        steps: [makeStep({ ...body.step_edits[0]!.changes })]
      });
      return { body: stored };
    };
    const { unmount, container } = renderEditor(original);
    fireEvent.click(await screen.findByRole("combobox", { name: "Vad som laddas upp" }));
    fireEvent.click(
      within(await screen.findByRole("listbox", { name: "Vad som laddas upp" })).getByRole(
        "option",
        { name: "Ljud" }
      )
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "MP3" }));
    const custom = screen.getByRole("textbox", { name: /^Egna MIME-typer/ });
    fireEvent.change(custom, { target: { value: "audio/x-custom," } });
    expect((custom as HTMLInputElement).value).toBe("audio/x-custom,");
    fireEvent.change(custom, { target: { value: "audio/mpeg, audio/x-custom, audio/x-second" } });
    fireEvent.blur(custom);
    expect((custom as HTMLInputElement).value).toBe("audio/x-custom, audio/x-second");
    await expectNoAxeViolations(container);
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    await screen.findByText(messages.flow_step_editor_saved);
    expect(patchBodies()[0]).toMatchObject({
      step_edits: [
        {
          changes: {
            input_config: {
              future: 1,
              runtime_input: {
                enabled: true,
                required: true,
                max_files: 3,
                input_format: "audio",
                accepted_mimetypes_override: ["audio/mpeg", "audio/x-custom", "audio/x-second"]
              }
            }
          }
        }
      ]
    });
    unmount();
    renderEditor(stored);
    expect(
      (await screen.findByRole("combobox", { name: "Vad som laddas upp" })).textContent
    ).toContain("Ljud");
    expect((screen.getByRole("checkbox", { name: "MP3" }) as HTMLInputElement).checked).toBe(true);
    expect(
      (screen.getByRole("textbox", { name: /^Egna MIME-typer/ }) as HTMLInputElement).value
    ).toBe("audio/x-custom, audio/x-second");
    fireEvent.click(screen.getByRole("button", { name: "Använd standardtyper" }));
    expect(
      (screen.getByRole("textbox", { name: /^Egna MIME-typer/ }) as HTMLInputElement).value
    ).toBe("");
  });

  it("shows the organisation's default step time limit and ceiling at the control", async () => {
    api.routes["GET /api/v1/flows/execution-limits/"] = () => ({
      body: { default_step_timeout_seconds: 900, max_step_timeout_seconds: 1800 }
    });
    renderEditor(makeFlow());
    const field = (await screen.findByLabelText(
      new RegExp(`^${messages.flow_step_editor_timeout}`)
    )) as HTMLInputElement;
    await waitFor(() => expect(field.placeholder).toBe("900"));
    expect(field.getAttribute("aria-valuemax") ?? field.max).toBe("1800");
    expect(screen.getByText(/1800/)).toBeTruthy();
    // A flow editor reads the Flows route, never the administrators' settings.
    expect(api.stub.calls.some((call) => call.path.startsWith("/api/v1/settings/"))).toBe(false);
  });

  it("keeps a working time limit control when the limits cannot be read", async () => {
    renderEditor(makeFlow());
    const field = (await screen.findByLabelText(
      new RegExp(`^${messages.flow_step_editor_timeout}`)
    )) as HTMLInputElement;
    await waitFor(() =>
      expect(api.stub.calls.some((call) => call.path === "/api/v1/flows/execution-limits/")).toBe(
        true
      )
    );
    expect(field.placeholder).toBe(messages.flow_step_editor_timeout_default);
    expect(field.getAttribute("aria-valuemax") ?? field.max).toBeFalsy();
  });

  it("shows an AI step's task, input, result and control as labelled sections", async () => {
    const { container } = renderEditor(makeFlow());
    await nameField();
    for (const heading of [
      messages.flow_step_editor_ai_title,
      messages.flow_step_editor_input_title,
      messages.flow_step_editor_output_title,
      messages.flow_step_editor_control_title,
      messages.flow_step_editor_advanced_title
    ]) {
      expect(screen.getByRole("heading", { level: 3, name: heading })).toBeTruthy();
    }
    expect((screen.getByLabelText(/^Instruktion/) as HTMLTextAreaElement).value).toBe(
      "Sammanfatta ärendet."
    );
    await expectNoAxeViolations(container);
  }, 20_000);

  it("saves a renamed step as one fenced edit with only the name", async () => {
    const saved = makeFlow({
      draft_revision: 5,
      steps: [makeStep({ user_description: "Sammanfatta ärendet" })]
    });
    api.routes[EDITOR] = () => ({ body: saved });
    const { onSaved } = renderEditor(makeFlow());
    fireEvent.change(await nameField(), { target: { value: "Sammanfatta ärendet" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved));
    expect(patchBodies()).toEqual([
      {
        expected_revision: 4,
        definition: {},
        step_edits: [{ step_id: "step-1", changes: { user_description: "Sammanfatta ärendet" } }]
      }
    ]);
  });

  it("shows the open step's suggestions at the top, and asks for them again after a save", async () => {
    const SUGGESTIONS = "GET /api/v1/flows/{id}/suggestions/";
    const about = (stepId: string, code: string, fingerprint: string) => ({
      code,
      fingerprint,
      steps: [stepId, "step-1"],
      params: { producer_step_order: 1, reads: [] },
      message: "A suggestion.",
      impact: { basis: "definition", level: "high" },
      fix: { kind: "assisted" }
    });
    api.routes[SUGGESTIONS] = () => ({
      body: {
        flow_id: "flow-1",
        draft_revision: 4,
        items: [
          about("step-2", "duplicate_read", "a".repeat(64)),
          about("step-1", "some_later_code", "b".repeat(64))
        ]
      }
    });
    const second = makeStep({
      id: "step-2",
      assistant_id: "assistant-2",
      step_order: 2,
      user_description: "Skriv svar",
      input_source: "previous_step"
    });
    const flow = makeFlow({ steps: [makeStep(), second] });
    api.routes[EDITOR] = () => ({
      body: makeFlow({ draft_revision: 5, steps: [makeStep(), second] })
    });
    const onAskChat = vi.fn();
    const { container } = renderEditor(flow, { onAskChat });

    // The person opened the step on purpose: its suggestions start open.
    const toggle = await screen.findByRole("button", { name: "1 förslag" });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const section = document.getElementById(toggle.getAttribute("aria-controls") ?? "")!;
    expect(section.hidden).toBe(false);
    expect(screen.queryByText("Svaret från steg 1 skickas två gånger")).toBeNull();
    await expectNoAxeViolations(container);
    fireEvent.click(within(section).getByRole("button", { name: "Mer om ”Förslag”" }));
    fireEvent.click(
      within(section).getByRole("button", {
        name: "Fråga assistenten om ”Förslag”"
      })
    );
    expect(onAskChat).toHaveBeenCalledWith(expect.stringContaining("(some_later_code)"));
    // Only the open step is open: no way to open it again from here.
    expect(within(section).queryByRole("button", { name: /^Öppna/ })).toBeNull();
    // Without a way to fix it, nothing offers to.
    expect(within(section).queryByRole("button", { name: /^Åtgärda/ })).toBeNull();

    const fetched = () =>
      api.stub.calls.filter((call) => `${call.method} ${call.path}` === SUGGESTIONS).length;
    expect(fetched()).toBe(1);
    fireEvent.change(await nameField(), { target: { value: "Sammanfatta ärendet" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    // The saved revision keys the suggestions anew.
    await waitFor(() => expect(fetched()).toBe(2));
  });

  it("shows the open step's suggestions measured while the page measures them", async () => {
    const SUGGESTIONS = "GET /api/v1/flows/{id}/suggestions/";
    api.routes[SUGGESTIONS] = () => ({
      body: {
        flow_id: "flow-1",
        draft_revision: 4,
        runs: { requested: 10, counted: 8, left_out: 0 },
        items: [
          {
            code: "format_fallback",
            fingerprint: "c".repeat(64),
            steps: ["step-1"],
            params: { fallback_runs: 6, step_runs: 8 },
            message: "A suggestion.",
            impact: {
              basis: "runs",
              level: "medium",
              tokens_per_run: null,
              run_count: 8,
              version: 3,
              step_changed_since: false
            },
            fix: { kind: "advice" }
          }
        ]
      }
    });
    const { container } = renderEditor(makeFlow(), { suggestionRuns: 10 });

    const toggle = await screen.findByRole("button", { name: "1 förslag" });
    const section = document.getElementById(toggle.getAttribute("aria-controls") ?? "")!;
    expect(within(section).getByText("Steget behöver ofta två anrop till modellen")).toBeTruthy();
    expect(within(section).getByText("Mätt i 8 körningar.")).toBeTruthy();
    const reads = api.stub.calls.filter((call) => `${call.method} ${call.path}` === SUGGESTIONS);
    expect(
      reads.map((call) => (call.init as { params: { query?: unknown } }).params.query)
    ).toEqual([{ runs: 10, include_dismissed: true }]);
    await expectNoAxeViolations(container);
  });

  it("offers Åtgärda on the open step, and holds it while the step has unsaved changes", async () => {
    api.routes["GET /api/v1/flows/{id}/suggestions/"] = () => ({
      body: {
        flow_id: "flow-1",
        draft_revision: 4,
        items: [
          {
            code: "some_later_code",
            fingerprint: "b".repeat(64),
            steps: ["step-1"],
            params: {},
            message: "A suggestion.",
            impact: { basis: "definition", level: "high" },
            fix: { kind: "patch", patch: {} }
          }
        ]
      }
    });
    const fix = { onFix: vi.fn(async () => true), pending: false };
    const { container } = renderEditor(makeFlow(), { suggestionFix: fix });

    const button = await screen.findByRole("button", { name: "Åtgärda ”Förslag”" });
    expect((button as HTMLButtonElement).disabled).toBe(false);
    fireEvent.change(await nameField(), { target: { value: "Sammanfatta ärendet" } });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(true));
    const reason = screen.getByText(messages.flow_suggestions_fix_blocked_unsaved);
    expect(button.getAttribute("aria-describedby")).toBe(reason.id);
    fireEvent.click(button);
    expect(fix.onFix).not.toHaveBeenCalled();
    await expectNoAxeViolations(container);

    // Undone, it is offered again and fixes the one suggestion.
    fireEvent.change(await nameField(), { target: { value: "Sammanfatta" } });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);
    await waitFor(() => expect(fix.onFix).toHaveBeenCalledWith(["b".repeat(64)]));
  });

  it("dismisses the open step's suggestion, and keeps focus in the editor", async () => {
    const SUGGESTIONS = "GET /api/v1/flows/{id}/suggestions/";
    const suggestion = {
      code: "unread_result",
      fingerprint: "b".repeat(64),
      steps: ["step-1"],
      params: {},
      message: "A suggestion.",
      impact: { basis: "definition", level: "medium" },
      fix: { kind: "advice" }
    };
    let dismissed = false;
    api.routes[SUGGESTIONS] = () => ({
      body: {
        flow_id: "flow-1",
        draft_revision: 4,
        dismissed_count: dismissed ? 1 : 0,
        items: [
          dismissed
            ? {
                ...suggestion,
                dismissed: { dismissed_by: "user-1", dismissed_at: "2026-10-25T09:30:00Z" }
              }
            : suggestion
        ]
      }
    });
    const queryClient = { current: null as ReturnType<typeof testQueryClient> | null };
    const onDismiss = vi.fn(async () => {
      dismissed = true;
      await queryClient.current!.invalidateQueries({
        queryKey: ["flows", "flow-1", "suggestions"]
      });
      return true;
    });
    const { queryClient: client } = renderEditor(makeFlow(), {
      suggestionDismissal: {
        onDismiss,
        onRestore: vi.fn(async () => true),
        busy: null,
        showDismissed: false,
        onShowDismissed: vi.fn()
      }
    });
    queryClient.current = client;

    fireEvent.click(
      await screen.findByRole("button", { name: "Mer om ”Inget senare steg läser stegets svar”" })
    );
    const ignore = screen.getByRole("button", {
      name: "Ignorera ”Inget senare steg läser stegets svar”"
    });
    ignore.focus();
    fireEvent.click(ignore);

    await waitFor(() =>
      expect(onDismiss).toHaveBeenCalledWith(expect.objectContaining({ code: "unread_result" }))
    );
    // Dismissed, the step shows it no more; focus stays in the editor, never on <body>.
    await waitFor(() => expect(screen.queryByRole("button", { name: "1 förslag" })).toBeNull());
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    expect(document.activeElement?.closest("form")).toBeTruthy();
  });

  it("leads back to all steps and on to the neighbouring ones from the top", async () => {
    const onGo = vi.fn();
    const navigation: StepNavigation = {
      position: 1,
      count: 2,
      previous: null,
      next: { id: "step-2", name: "Skriv svar" },
      steps: [
        {
          id: "step-1",
          label: "Steg 1: Sammanfatta",
          kind: "Text, bearbetas med AI",
          suggestions: 0
        },
        {
          id: "step-2",
          label: "Steg 2: Skriv svar",
          kind: "Text, bearbetas med AI",
          suggestions: 1
        }
      ],
      onGo
    };
    const { onCancel, container } = renderEditor(makeFlow(), { navigation });
    await nameField();
    const bar = screen.getByRole("navigation", { name: "Stegen" });
    // Disabled at the first step, so the bar does not move.
    expect(
      (within(bar).getByRole("button", { name: "Föregående steg" }) as HTMLButtonElement).disabled
    ).toBe(true);
    fireEvent.click(within(bar).getByRole("button", { name: "Nästa steg: Skriv svar" }));
    expect(onGo).toHaveBeenCalledWith("step-2");

    // The step menu names the open step and lists every step, with what it
    // does and the suggestions about it; the open step goes nowhere.
    const trigger = within(bar).getByRole("button", { name: "Steg 1 av 2: Steg 1: Sammanfatta" });
    fireEvent.click(trigger);
    const menu = document.getElementById(trigger.getAttribute("aria-controls") ?? "")!;
    const current = within(menu).getByRole("menuitem", { name: /Steg 1: Sammanfatta/ });
    expect(within(current).getByText("Visas nu")).toBeTruthy();
    const other = within(menu).getByRole("menuitem", { name: /Steg 2: Skriv svar/ });
    expect(within(other).getByText("Text, bearbetas med AI")).toBeTruthy();
    expect(within(other).getByText("1 förslag")).toBeTruthy();
    onGo.mockClear();
    fireEvent.click(current);
    expect(onGo).not.toHaveBeenCalled();
    fireEvent.click(trigger);
    fireEvent.click(within(menu).getByRole("menuitem", { name: /Steg 2/ }));
    expect(onGo).toHaveBeenCalledWith("step-2");

    fireEvent.click(within(bar).getByRole("button", { name: "Alla steg" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    await expectNoAxeViolations(container);
  });

  it("docks a save bar that says what is unsaved, then that the save landed", async () => {
    const saved = makeFlow({
      draft_revision: 5,
      steps: [makeStep({ user_description: "Sammanfatta ärendet" })]
    });
    api.routes[EDITOR] = () => ({ body: saved });
    renderEditor(makeFlow());
    const field = await nameField();
    // Nothing to save: the way out is "Stäng" and the save button is quiet.
    expect(screen.getByText(messages.flow_step_editor_no_changes)).toBeTruthy();
    expect(screen.getByRole("button", { name: messages.close })).toBeTruthy();
    expect(screen.queryByRole("button", { name: messages.cancel })).toBeNull();

    fireEvent.change(field, { target: { value: "Sammanfatta ärendet" } });
    expect(screen.getByText("1 ändring som inte är sparad")).toBeTruthy();
    expect(screen.getByRole("button", { name: messages.cancel })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    await screen.findByText(messages.flow_step_editor_saved);
    expect(screen.getByRole("button", { name: messages.close })).toBeTruthy();
  });

  it("reads long material in parts as one step setting, and explains what it costs", async () => {
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    const { onSaved, container } = renderEditor(makeFlow());
    await nameField();
    const toggle = screen.getByRole("switch", { name: messages.flow_editor_tools_long_material });
    expect(screen.getByText(messages.flow_editor_tools_long_material_description)).toBeTruthy();
    fireEvent.click(toggle);
    await expectNoAxeViolations(container);
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(patchBodies()).toEqual([
      {
        expected_revision: 4,
        definition: {},
        step_edits: [
          { step_id: "step-1", changes: { input_config: { long_material: { mode: "digest" } } } }
        ]
      }
    ]);
  }, 20_000);

  it("shows what the step would send, its references named and no credential", async () => {
    routeBasics(
      makeAssistant({
        prompt: {
          id: "prompt-1",
          text: "Sammanfatta {{flow_input.diarienummer}} kort.",
          description: null
        } as never,
        completion_model_kwargs: { temperature: 0.2 }
      })
    );
    const { container } = renderEditor(
      makeFlow({
        metadata_json: {
          form_schema: { fields: [{ name: "diarienummer", label: "Diarienummer", type: "text" }] }
        }
      })
    );
    await nameField();
    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_editor_tools_preview_button })
    );
    const dialog = await screen.findByRole("dialog", {
      name: messages.flow_editor_tools_preview_title
    });
    expect(dialog.textContent).toContain("Diarienummer");
    expect(dialog.textContent).toContain("Haiku 4.5");
    expect(dialog.textContent).toContain("temperature: 0.2");
    await expectNoAxeViolations(container);
  }, 20_000);

  it("names a stored credential as stored in the preview, never its value", async () => {
    renderEditor(httpFlow({ mode: "bearer_token", token: { $secret: "stored" } }));
    await nameField();
    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_editor_tools_preview_button })
    );
    const dialog = await screen.findByRole("dialog", {
      name: messages.flow_editor_tools_preview_title
    });
    expect(dialog.textContent).toContain("https://api.example.org/a");
    expect(dialog.textContent).toContain(messages.flow_step_editor_secret_stored);
    expect(dialog.textContent).not.toContain("$secret");
  });

  it("proposes an output contract from an example answer, for the author to accept", async () => {
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    const { onSaved, container } = renderEditor(
      makeFlow({ steps: [makeStep({ output_type: "json" })] })
    );
    await nameField();
    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_editor_tools_contract_example_button })
    );
    const dialog = await screen.findByRole("dialog", {
      name: messages.flow_editor_tools_contract_example_title
    });
    fireEvent.change(screen.getByLabelText(/^Exempel på svar/), {
      target: { value: '{"beslut": "Bifall", "belopp": 4500}' }
    });
    expect(dialog.textContent).toContain("beslut");
    expect(dialog.textContent).toContain("Tal");
    await expectNoAxeViolations(container);
    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_editor_tools_contract_example_accept })
    );
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(patchBodies()[0]).toMatchObject({
      step_edits: [
        {
          step_id: "step-1",
          changes: {
            output_contract: {
              type: "object",
              properties: { beslut: { type: "string" }, belopp: { type: "number" } },
              required: ["beslut", "belopp"]
            }
          }
        }
      ]
    });
  }, 20_000);

  it("explains an example that gives no contract at the field", async () => {
    renderEditor(makeFlow({ steps: [makeStep({ output_type: "json" })] }));
    await nameField();
    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_editor_tools_contract_example_button })
    );
    const field = await screen.findByLabelText(/^Exempel på svar/);
    fireEvent.change(field, { target: { value: "[1, 2]" } });
    expect(
      await screen.findByText(messages.flow_editor_tools_contract_example_problem_not_object)
    ).toBeTruthy();
    expect(field.getAttribute("aria-invalid")).toBe("true");
  });

  it("names classification levels from the space when the list is refused", async () => {
    api.routes["GET /api/v1/security-classifications/"] = () => ({
      status: 403,
      body: { message: "Forbidden", code: "forbidden" }
    });
    api.routes["POST /api/v1/flows/{id}/security-classification/preview"] = () => ({
      body: {
        steps: [
          {
            step_id: "step-1",
            step_order: 1,
            input_level: 1,
            reads: [],
            knowledge_level: null,
            external_source_level: null,
            model_level: 2,
            required_model_level: 1,
            qualifying_model_ids: ["model-1"],
            effective_output_level: 2,
            output_floor: 1,
            violation: null
          }
        ]
      }
    });
    const space = makeSpace({
      overrides: {
        security_classification: {
          id: "c-1",
          name: "Intern",
          description: null,
          security_level: 1
        },
        completion_models: [
          {
            id: "model-1",
            name: "snabb-modell",
            nickname: "Haiku 4.5",
            security_classification: {
              id: "c-2",
              name: "Känslig",
              description: null,
              security_level: 2
            }
          }
        ]
      }
    });
    renderEditor(makeFlow(), { space });
    await nameField();
    const facts = await screen.findByText(messages.flow_step_editor_classification_facts);
    const list = facts.closest("div")?.parentElement ?? document.body;
    await waitFor(() => expect(list.textContent).toContain("Känslig"));
    expect(list.textContent).toContain("Intern");
    expect(list.textContent).not.toContain("Nivå 2");
  });

  function attachFile(container: HTMLElement, name = "underlag.txt") {
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("no file input");
    fireEvent.change(input, {
      target: { files: [new File(["text"], name, { type: "text/plain" })] }
    });
  }

  const uploadable = makeAssistant({
    allowed_attachments: { accepted_file_types: [], limit: { max_files: 5, max_size: 10_000_000 } }
  } as never);

  it("keeps a file the saved step uses when the editor closes", async () => {
    const withFile = makeAssistant({
      ...uploadable,
      attachments: [{ id: "file-new", name: "underlag.txt", size: 4 }]
    } as never);
    let saved = false;
    api.routes[ASSISTANT] = () => ({ body: saved ? withFile : uploadable });
    api.routes["POST /api/v1/files/"] = () => ({
      body: { id: "file-new", name: "underlag.txt", size: 4, mimetype: "text/plain" }
    });
    api.routes[EDITOR] = () => {
      saved = true;
      return { body: makeFlow({ draft_revision: 5 }) };
    };
    const { container, onSaved, unmount } = renderEditor(makeFlow());
    await nameField();
    attachFile(container);
    expect(await screen.findByText("underlag.txt")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());

    unmount();
    expect(api.stub.calls.filter((call) => call.method === "DELETE")).toEqual([]);
  });

  it("offers no long material where the step does not let a model answer", async () => {
    renderEditor(makeFlow({ steps: [makeStep({ output_mode: "compose_text" })] }));
    await nameField();
    expect(
      screen.queryByRole("switch", { name: messages.flow_editor_tools_long_material })
    ).toBeNull();
  });

  it("reads its assistant again when it opens, though the step list read it", async () => {
    renderEditor(makeFlow(), { cachedAssistant: makeAssistant() });
    await nameField();
    await waitFor(() =>
      expect(
        api.stub.calls.filter((call) => `${call.method} ${call.path}` === ASSISTANT)
      ).toHaveLength(1)
    );
  });

  it("saves an instruction with the step assistant only, and reads the assistant back", async () => {
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    const { onSaved } = renderEditor(makeFlow());
    await nameField();
    fireEvent.change(screen.getByLabelText(/^Instruktion/), {
      target: { value: "Sammanfatta i tre punkter." }
    });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(patchBodies()).toEqual([
      {
        expected_revision: 4,
        definition: {},
        assistants: [
          {
            assistant_id: "assistant-1",
            step_id: "step-1",
            changes: { prompt: { text: "Sammanfatta i tre punkter.", description: null } }
          }
        ]
      }
    ]);
    const assistantReads = api.stub.calls.filter(
      (call) => `${call.method} ${call.path}` === ASSISTANT
    );
    expect(assistantReads.length).toBeGreaterThanOrEqual(2);
  });

  it("keeps the edits when the draft moved on, and saves them on the reloaded revision", async () => {
    let attempts = 0;
    api.routes[EDITOR] = () =>
      attempts++ === 0
        ? { status: 400, body: { message: "Stale", code: "stale_revision", eneo_error_code: 9000 } }
        : { body: makeFlow({ draft_revision: 9 }) };
    api.routes["GET /api/v1/flows/{id}/"] = () => ({ body: makeFlow({ draft_revision: 8 }) });
    const { onSaved } = renderEditor(makeFlow());
    fireEvent.change(await nameField(), { target: { value: "Nytt namn" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    expect(await screen.findByText(messages.flow_step_editor_stale_title)).toBeTruthy();
    expect((await nameField()).value).toBe("Nytt namn");
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_reload }));
    await waitFor(() =>
      expect(screen.queryByText(messages.flow_step_editor_stale_title)).toBeNull()
    );
    expect((await nameField()).value).toBe("Nytt namn");

    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(patchBodies()[1]).toMatchObject({
      expected_revision: 8,
      step_edits: [{ step_id: "step-1", changes: { user_description: "Nytt namn" } }]
    });
  }, 20_000);

  it("shows a refusal at the field it names and moves focus there", async () => {
    const http = httpFlow();
    api.routes[EDITOR] = () => ({
      status: 400,
      body: {
        message: "Step 1: input_config.url is not valid",
        code: "typed_io_http_invalid_config",
        context: { field: "input_config.url", step_order: 1 },
        eneo_error_code: 9000
      }
    });
    renderEditor(http);
    const url = (await screen.findByLabelText(/^Adress att hämta från/)) as HTMLInputElement;
    fireEvent.change(url, { target: { value: "https://api.example.org/{{flow_input.id}}" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    expect(await screen.findByText(messages.flow_error_typed_io_http_invalid_config)).toBeTruthy();
    expect(document.activeElement).toBe(url);
    expect(screen.queryByText(/input_config\.url is not valid/)).toBeNull();
  });

  it("explains a missing name at the field instead of saving", async () => {
    renderEditor(makeFlow());
    const field = await nameField();
    fireEvent.change(field, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    expect(await screen.findByText(messages.flow_step_editor_name_required)).toBeTruthy();
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(field);
    expect(patchBodies()).toEqual([]);
  });

  it("shows a stored credential as saved, never as a value, and offers to replace it", async () => {
    const http = httpFlow({ mode: "bearer_token", token: { $secret: "stored" } });
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    const { container, onSaved } = renderEditor(http);
    expect(await screen.findByText(messages.flow_step_editor_secret_stored)).toBeTruthy();
    expect(container.querySelector("input[type=password]")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Ersätt: Token" }));
    const token = container.querySelector("input[type=password]") as HTMLInputElement;
    expect(token.value).toBe("");
    fireEvent.change(token, { target: { value: "ny-hemlighet" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(patchBodies()[0]).toMatchObject({
      step_edits: [
        {
          changes: {
            input_config: { auth: { mode: "bearer_token", token: "ny-hemlighet" } }
          }
        }
      ]
    });
    await expectNoAxeViolations(container);
  }, 20_000);

  it("tests the HTTP call with the step's settings as they stand, credentials kept as stored", async () => {
    api.routes["POST /api/v1/flows/{id}/http-test"] = () => ({
      body: { success: true, status_code: 200, response_preview: '{"ok": true}' }
    });
    renderEditor(httpFlow({ mode: "bearer_token", token: { $secret: "stored" } }));
    fireEvent.click(await screen.findByRole("button", { name: messages.http_test_button }));

    expect(await screen.findByText(`${messages.http_test_success} (200)`)).toBeTruthy();
    const call = api.stub.calls.find((item) => item.path === "/api/v1/flows/{id}/http-test");
    expect(call?.init.body).toMatchObject({
      step_id: "step-1",
      direction: "input",
      method: "GET",
      config: { auth: { mode: "bearer_token", token: { $secret: "stored" } } }
    });
  }, 20_000);

  it("sets a tool step's arguments, one whole reference or a typed value each", async () => {
    api.routes["GET /api/v1/flows/{id}/tool-options"] = () => ({
      body: {
        security_classifications_enabled: false,
        items: [
          {
            mcp_server_id: "server-1",
            mcp_server_name: "Ärendesystem",
            mcp_server_security_level: null,
            tool_id: "tool-1",
            tool_name: "sok_arende",
            tool_description: "Söker ett ärende",
            input_schema: {
              type: "object",
              properties: { q: { type: "string" }, limit: { type: "integer" } },
              required: ["q"]
            },
            refusal: null
          }
        ]
      }
    });
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    const tool = makeFlow({
      steps: [
        makeStep({
          input_source: "tool",
          output_mode: "compose_text",
          input_config: {
            tool: { mcp_server_id: "server-1", tool_id: "tool-1", arguments: { q: "{{datum}}" } }
          }
        })
      ]
    });
    const { container, onSaved } = renderEditor(tool);
    const limit = (await screen.findByLabelText(/^limit/)) as HTMLInputElement;
    expect((screen.getByLabelText(/^q/) as HTMLInputElement).value).toBe("{{datum}}");
    fireEvent.change(limit, { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(patchBodies()[0]).toMatchObject({
      step_edits: [
        {
          changes: {
            input_config: {
              tool: {
                mcp_server_id: "server-1",
                tool_id: "tool-1",
                arguments: { q: "{{datum}}", limit: 5 }
              }
            }
          }
        }
      ]
    });
    await expectNoAxeViolations(container);
  }, 20_000);

  it("binds a Word template's fields to values of the run", async () => {
    api.routes["GET /api/v1/flows/{id}/template-files/"] = () => ({
      body: [
        {
          id: "asset-1",
          flow_id: "flow-1",
          file_id: "file-1",
          name: "Beslut.docx",
          checksum: "abc",
          status: "ready",
          placeholders: ["namn"]
        }
      ]
    });
    api.routes["GET /api/v1/flows/{id}/template-inspect/"] = () => ({
      body: {
        asset_id: "asset-1",
        file_id: "file-1",
        file_name: "Beslut.docx",
        placeholders: [{ name: "namn", label: "Namn", kind: "text", location: "body" }]
      }
    });
    const template = makeFlow({
      metadata_json: { form_schema: { fields: [{ name: "namn", label: "Namn", type: "text" }] } },
      steps: [
        makeStep({
          output_mode: "template_fill",
          output_type: "docx",
          output_config: {
            template_asset_id: "asset-1",
            template_name: "Beslut.docx",
            placeholders: ["namn"],
            bindings: {}
          }
        })
      ]
    });
    const { container } = renderEditor(template);
    expect(await screen.findByText(messages.flow_step_editor_template_field_missing)).toBeTruthy();
    expect(screen.getByText("0 av 1 fält är kopplade.")).toBeTruthy();
    await expectNoAxeViolations(container);
  }, 20_000);

  it("releases a Word template uploaded in an edit that is closed without saving", async () => {
    api.routes["GET /api/v1/flows/{id}/template-files/"] = () => ({ body: [] });
    api.routes["POST /api/v1/flows/{id}/template-files/"] = () => ({
      body: {
        id: "asset-new",
        flow_id: "flow-1",
        file_id: "file-9",
        name: "Ny.docx",
        checksum: "x",
        status: "ready",
        placeholders: []
      }
    });
    api.routes["GET /api/v1/flows/{id}/template-inspect/"] = () => ({
      body: { asset_id: "asset-new", file_id: "file-9", file_name: "Ny.docx", placeholders: [] }
    });
    api.routes["DELETE /api/v1/flows/{id}/template-files/{file_id}/"] = () => ({ body: {} });
    const { container, unmount } = renderEditor(
      makeFlow({
        steps: [makeStep({ output_mode: "template_fill", output_type: "docx", output_config: {} })]
      })
    );
    await nameField();
    const input = await waitFor(() => {
      const found = container.querySelector<HTMLInputElement>('input[type="file"]');
      if (!found) throw new Error("no template input yet");
      return found;
    });
    fireEvent.change(input, {
      target: {
        files: [
          new File(["docx"], "Ny.docx", {
            type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          })
        ]
      }
    });
    await waitFor(() =>
      expect(
        api.stub.calls.some((call) => call.path === "/api/v1/flows/{id}/template-inspect/")
      ).toBe(true)
    );

    unmount();
    expect(
      api.stub.calls
        .filter((call) => call.method === "DELETE")
        .map((call) => call.init.params?.path)
    ).toEqual([{ id: "flow-1", file_id: "asset-new" }]);
  });

  it("shows a read-only step as text, without inputs", async () => {
    const { container } = renderEditor(makeFlow(), { readOnly: true });
    expect(await screen.findByText("Sammanfatta ärendet.")).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: messages.flow_step_editor_save })).toBeNull();
    // The result's mode is told in the header and in the list of settings.
    expect(screen.getByText(messages.flow_step_output_mode)).toBeTruthy();
    expect(screen.getAllByText(messages.flow_output_mode_pass_through)).toHaveLength(2);
    await expectNoAxeViolations(container);
  }, 20_000);
});
