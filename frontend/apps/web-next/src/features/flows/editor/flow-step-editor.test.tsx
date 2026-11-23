// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { expectNoAxeViolations } from "@/test/axe";
import { cachedText, renderInApp, testQueryClient } from "@/test/render";
import messages from "@/lib/i18n/messages/sv.json";
import type { SuggestionDismissal, SuggestionFix } from "../flow-suggestion-item";
import { flowEditorKeys } from "./editor-api";
import type { FlowPublic } from "./step-types";
import { makeAssistant, makeFlow, makeStep } from "./testing/fixtures";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));

const api = vi.hoisted(() => ({
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("./testing/fixtures").apiStub>
}));

vi.mock("@/lib/api/browser", async () => {
  const { apiStub: makeStub } = await import("./testing/fixtures");
  api.stub = makeStub(new Proxy({}, { get: (_target, key: string) => api.routes[key] }));
  return { browserApi: api.stub.client };
});

// The Prompt Guide's answers stream from the help assistant; the availability read is real.
const guide = vi.hoisted(() => ({ start: vi.fn(), next: vi.fn() }));
vi.mock("@/features/help-assistants/prompt-guide/helper-runs", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/help-assistants/prompt-guide/helper-runs")>()),
  startPromptGuideRun: guide.start,
  continuePromptGuideRun: guide.next,
  updateHelperRunStatus: vi.fn(async () => ({}))
}));

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
    onStepAdded?: (flow: FlowPublic) => void;
    /** The step assistant as the step list already read it. */
    cachedAssistant?: ReturnType<typeof makeAssistant>;
    stepId?: string;
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
      stepId={overrides.stepId ?? "step-1"}
      readOnly={overrides.readOnly ?? false}
      onSaved={onSaved}
      onCancel={onCancel}
      onAskChat={overrides.onAskChat}
      suggestionFix={overrides.suggestionFix}
      suggestionDismissal={overrides.suggestionDismissal}
      suggestionRuns={overrides.suggestionRuns}
      navigation={overrides.navigation}
      onStepAdded={overrides.onStepAdded}
    />,
    { queryClient }
  );
  return { ...view, onSaved, onCancel, queryClient };
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

/** The value beside a read-only row's label. */
async function rowValue(label: string) {
  return (await screen.findByText(label)).closest("dt")!.nextElementSibling!;
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

  it("keeps an HTTP time limit above the default ceiling: the deployment's own limit decides", async () => {
    const flow = httpFlow();
    const step = flow.steps[0]!;
    renderEditor({
      ...flow,
      steps: [{ ...step, input_config: { ...(step.input_config as object), timeout_seconds: 180 } }]
    });
    const field = (await screen.findByLabelText(
      new RegExp(`^${messages.flow_step_editor_http_timeout}`)
    )) as HTMLInputElement;
    expect(field.value).toBe("180");
    expect(field.getAttribute("aria-valuemax") ?? field.max).toBeFalsy();
    fireEvent.change(field, { target: { value: "240" } });
    expect(field.value).toBe("240");
  });

  it("keeps a webhook that sends the run's result when its time limit changes", async () => {
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    const output_config = {
      url: "https://hook.example.org/",
      auth: { mode: "none" },
      timeout_seconds: 45,
      body: { mode: "run_result" },
      custom_headers: [],
      response_format: null
    };
    renderEditor(makeFlow({ steps: [makeStep({ output_mode: "http_post", output_config })] }));
    const field = (await screen.findByLabelText(
      new RegExp(`^${messages.flow_step_editor_http_timeout}`)
    )) as HTMLInputElement;
    fireEvent.change(field, { target: { value: "60" } });
    fireEvent.blur(field);
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    await screen.findByText(messages.flow_step_editor_saved);
    expect(patchBodies()[0]).toMatchObject({
      step_edits: [
        {
          step_id: "step-1",
          changes: { output_config: { ...output_config, timeout_seconds: 60 } }
        }
      ]
    });
  });

  it("shows the step that sends the run's result as what it sends and to whom, untested", async () => {
    const { container } = renderEditor(
      makeFlow({
        steps: [
          makeStep({
            output_mode: "http_post",
            output_config: {
              url: "https://hook.example.org/",
              auth: { mode: "none" },
              timeout_seconds: 30,
              body: { mode: "run_result" },
              custom_headers: [],
              response_format: null
            }
          })
        ]
      })
    );
    expect(await screen.findByText(messages.flow_step_editor_run_result_description)).toBeTruthy();
    // What it sends is the step's kind, not a choice of body.
    expect(
      screen.queryByRole("combobox", {
        name: new RegExp(`^${messages.flow_step_editor_http_body}`)
      })
    ).toBeNull();
    expect(
      screen.getByRole("textbox", {
        name: new RegExp(`^${messages.flow_step_editor_http_url_run_result}`)
      })
    ).toBeTruthy();
    const headings = screen
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent);
    // No review, and the space does not classify: no empty control section.
    expect(headings).toEqual([
      messages.flow_step_editor_run_result_sends_title,
      messages.flow_step_editor_run_result_receiver_title
    ]);
    // Nothing it does not use: no input, AI, review, test, citations or the call's preview.
    expect(screen.queryByRole("button", { name: messages.http_test_button })).toBeNull();
    expect(
      screen.queryByRole("radiogroup", { name: new RegExp(messages.flow_step_review_policy) })
    ).toBeNull();
    expect(
      screen.queryByRole("switch", { name: new RegExp(`^${messages.flow_step_citation_mode}`) })
    ).toBeNull();
    expect(screen.queryByRole("button", { name: /Visa anropet/ })).toBeNull();
    await expectNoAxeViolations(container);
  }, 20_000);

  it("keeps the classification of the step that sends the run's result, headed without review", async () => {
    const space = makeSpace({
      overrides: {
        security_classification: {
          id: "c-1",
          name: "Intern",
          description: null,
          security_level: 1
        }
      }
    });
    renderEditor(
      makeFlow({
        steps: [
          makeStep({
            output_mode: "http_post",
            output_config: {
              url: "https://hook.example.org/",
              auth: { mode: "none" },
              body: { mode: "run_result" }
            }
          })
        ]
      }),
      { space }
    );
    expect(
      await screen.findByRole("heading", {
        level: 3,
        name: messages.flows_classification_heading
      })
    ).toBeTruthy();
    expect(
      screen.queryByRole("heading", { level: 3, name: messages.flow_step_editor_control_title })
    ).toBeNull();
    expect(
      screen.queryByRole("radiogroup", { name: new RegExp(messages.flow_step_review_policy) })
    ).toBeNull();
  }, 20_000);

  it("shows an AI step's task, input, result, delivery and control as labelled sections", async () => {
    const { container } = renderEditor(makeFlow());
    await nameField();
    // In this order: where the result goes comes right after what it is.
    expect(
      screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)
    ).toEqual([
      messages.flow_step_editor_ai_title,
      messages.flow_step_editor_input_title,
      messages.flow_step_editor_output_title,
      messages.flow_step_editor_delivery_title,
      messages.flow_step_editor_control_title
    ]);
    expect(
      screen.getByRole("region", { name: messages.flow_step_editor_advanced_title })
    ).toBeTruthy();
    // Where the organisation does not classify, the control section holds only the review choice.
    expect(screen.queryByText(/Säkerhetsklassning är inte påslagen/)).toBeNull();
    expect((screen.getByLabelText(/^Instruktion/) as HTMLTextAreaElement).value).toBe(
      "Sammanfatta ärendet."
    );
    await expectNoAxeViolations(container);
  }, 20_000);

  it("folds Avancerat while its settings are the defaults, and opens it on one in use", async () => {
    renderEditor(makeFlow());
    await nameField();
    const folded = screen.getByRole("button", {
      name: new RegExp(`^${messages.flow_step_editor_advanced_title}`)
    });
    expect(folded.getAttribute("aria-expanded")).toBe("false");
    expect(folded.textContent).toContain(messages.flow_step_editor_advanced_description);
    cleanup();

    renderEditor(makeFlow({ steps: [makeStep({ timeout_seconds: 120 })] }));
    await nameField();
    const open = screen.getByRole("button", {
      name: new RegExp(`^${messages.flow_step_editor_advanced_title}`)
    });
    expect(open.getAttribute("aria-expanded")).toBe("true");
    expect(open.textContent).toContain("1 egen inställning används");
  });

  it("folds the model's own settings until one is set, and keeps the behaviour in view", async () => {
    const tunable = {
      ...makeSpace(),
      completion_models: [
        {
          id: "model-1",
          name: "claude-haiku",
          nickname: "Haiku 4.5",
          supported_model_kwargs: {
            temperature: { supported: true, minimum: 0, maximum: 2, step: 0.05 },
            top_p: { supported: true, minimum: 0, maximum: 1, step: 0.05 }
          }
        }
      ]
    } as unknown as ReturnType<typeof makeSpace>;
    const more = () =>
      screen.getByRole("button", { name: new RegExp(`^${messages.flow_step_editor_model_more}`) });

    renderEditor(makeFlow(), { space: tunable });
    await nameField();
    expect(screen.getByText(messages.model_behaviour)).toBeTruthy();
    expect(more().getAttribute("aria-expanded")).toBe("false");
    expect(more().textContent).toContain(messages.flow_step_editor_model_more_description);
    fireEvent.click(more());
    expect(more().getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByLabelText(new RegExp(`^${messages.top_p}`))).toBeTruthy();
    cleanup();

    routeBasics(makeAssistant({ completion_model_kwargs: { top_p: 0.5 } }));
    renderEditor(makeFlow(), { space: tunable });
    await nameField();
    await waitFor(() => expect(more().getAttribute("aria-expanded")).toBe("true"));
    expect(more().textContent).toContain("1 ändrad inställning");
  });

  it("shows a model settings refusal without presets, opens the fold once and lets it close", async () => {
    const noPresets = {
      ...makeSpace(),
      completion_models: [
        {
          id: "model-1",
          name: "claude-haiku",
          nickname: "Haiku 4.5",
          supported_model_kwargs: { top_p: { supported: true, minimum: 0, maximum: 1, step: 0.05 } }
        }
      ]
    } as unknown as ReturnType<typeof makeSpace>;
    api.routes[EDITOR] = () => ({
      status: 400,
      body: {
        message: "Step 1: top_p is out of range",
        code: "flow_step_model_kwargs_invalid",
        context: { field: "completion_model_kwargs", step_order: 1 },
        eneo_error_code: 9000
      }
    });
    const more = () =>
      screen.getByRole("button", { name: new RegExp(`^${messages.flow_step_editor_model_more}`) });
    renderEditor(makeFlow(), { space: noPresets });
    fireEvent.change(await nameField(), { target: { value: "Sammanfatta ärendet" } });
    expect(more().getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    await waitFor(() => expect(more().getAttribute("aria-expanded")).toBe("true"));
    const message = await screen.findByText(/top_p is out of range/);
    fireEvent.click(more());
    expect(more().getAttribute("aria-expanded")).toBe("false");
    expect(message.isConnected).toBe(true);
  });

  it("opens Avancerat on a refusal inside it before focus moves to the field", async () => {
    api.routes[EDITOR] = () => ({
      status: 400,
      body: {
        message: "Step 1: timeout_seconds is too long",
        code: "flow_step_timeout_too_long",
        context: { field: "timeout_seconds", step_order: 1 },
        eneo_error_code: 9000
      }
    });
    renderEditor(makeFlow());
    fireEvent.change(await nameField(), { target: { value: "Sammanfatta ärendet" } });
    const trigger = screen.getByRole("button", {
      name: new RegExp(`^${messages.flow_step_editor_advanced_title}`)
    });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    const field = screen.getByLabelText(new RegExp(`^${messages.flow_step_editor_timeout}`));
    await waitFor(() => expect(document.activeElement).toBe(field));
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
  });

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
    expect(button.getAttribute("aria-disabled")).toBeNull();
    fireEvent.change(await nameField(), { target: { value: "Sammanfatta ärendet" } });
    await waitFor(() => expect(button.getAttribute("aria-disabled")).toBe("true"));
    const reason = screen.getByText(messages.flow_suggestions_fix_blocked_unsaved);
    expect(button.getAttribute("aria-describedby")).toBe(reason.id);
    fireEvent.click(button);
    expect(fix.onFix).not.toHaveBeenCalled();
    await expectNoAxeViolations(container);

    // Undone, it is offered again and fixes the one suggestion.
    fireEvent.change(await nameField(), { target: { value: "Sammanfatta" } });
    await waitFor(() => expect(button.getAttribute("aria-disabled")).toBeNull());
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
      within(bar).getByRole("button", { name: "Föregående steg" }).getAttribute("aria-disabled")
    ).toBe("true");
    fireEvent.click(within(bar).getByRole("button", { name: "Nästa steg: Skriv svar" }));
    expect(onGo).toHaveBeenCalledWith("step-2");

    // The step menu names the open step and lists every step, with what it
    // does and the suggestions about it; the open step goes nowhere.
    const trigger = within(bar).getByRole("button", { name: "Steg 1 av 2: Sammanfatta" });
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

  it("keeps the arrows together, and the save beside the way out, when a narrow bar wraps", async () => {
    renderEditor(makeFlow(), {
      navigation: {
        position: 1,
        count: 2,
        previous: null,
        next: { id: "step-2", name: "Skriv svar" },
        steps: [],
        onGo: vi.fn()
      }
    });
    await nameField();
    // A wrapping row moves groups, not their buttons: each pair is one group.
    const bar = screen.getByRole("navigation", { name: "Stegen" });
    const previous = within(bar).getByRole("button", { name: "Föregående steg" });
    const next = within(bar).getByRole("button", { name: "Nästa steg: Skriv svar" });
    expect(previous.parentElement).toBe(next.parentElement);
    expect(previous.parentElement).not.toBe(bar);
    const close = screen.getByRole("button", { name: messages.close });
    const save = screen.getByRole("button", { name: messages.flow_step_editor_save });
    expect(close.parentElement).toBe(save.parentElement);
    expect(close.parentElement?.textContent).not.toContain(messages.flow_step_editor_no_changes);
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
    expect(dialog.textContent).toContain("Token · sparad");
    expect(dialog.textContent).not.toContain("$secret");
  });

  it("reads the step's own answer in its webhook, in the field and in the preview", async () => {
    renderEditor(
      makeFlow({
        steps: [
          makeStep({
            output_mode: "http_post",
            output_config: {
              url: "https://api.example.org/a",
              auth: { mode: "none" },
              timeout_seconds: 30,
              body: { mode: "json_template", template: '{"svar": "{{step_1.output.text}}"}' },
              custom_headers: []
            }
          })
        ]
      })
    );
    await screen.findByRole("textbox", {
      name: new RegExp(`^${messages.flow_step_editor_http_body_template}`)
    });
    // A webhook is sent once the step has answered: the core reads it at step_order + 1.
    const reads = screen.getByRole("list", { name: messages.flow_step_editor_reads_heading });
    expect(reads.textContent).toContain("Steg 1: Sammanfatta › text");
    expect(screen.queryByText(messages.flow_step_editor_reference_warning_later)).toBeNull();
    // Its menus offer the step's own answer.
    fireEvent.click(
      screen.getAllByRole("button", { name: messages.flow_step_editor_insert_variable })[0]!
    );
    const offered = await screen.findAllByRole("menuitem");
    expect(offered.map((item) => item.textContent).join(" ")).toContain("{{step_1.output.text}}");
    fireEvent.keyDown(offered[0]!, { key: "Escape" });

    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_editor_tools_preview_button })
    );
    const dialog = await screen.findByRole("dialog", {
      name: messages.flow_editor_tools_preview_title
    });
    expect(dialog.textContent).toContain("Steg 1: Sammanfatta › text");
    expect(dialog.textContent).not.toContain(messages.flow_editor_tools_preview_read_self);
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
    const advanced = screen.getByRole("button", {
      name: new RegExp(`^${messages.flow_step_editor_advanced_title}`)
    });
    expect(advanced.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_editor_tools_contract_example_accept })
    );
    // The accepted contract shows in Avancerat, which opens on it.
    expect(advanced.getAttribute("aria-expanded")).toBe("true");
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

  it("puts an earlier instruction from the step assistant's history in the draft, to save with the step", async () => {
    const author = { id: "user-1", email: "anna.lind@example.se", username: "Anna Lind" };
    const versions = [
      {
        id: "prompt-1",
        text: "Sammanfatta ärendet.",
        description: null,
        is_selected: true,
        created_at: "2026-10-20T09:00:00Z",
        user: author
      },
      {
        id: "prompt-0",
        text: "Sammanfatta kort.",
        description: "Första utkastet",
        is_selected: false,
        created_at: "2026-10-01T09:00:00Z",
        user: author
      }
    ];
    api.routes["GET /api/v1/assistants/{id}/prompts/"] = () => ({
      body: { items: versions, count: versions.length }
    });
    api.routes["GET /api/v1/prompts/{id}/"] = (init: { params: { path: { id: string } } }) => ({
      body: versions.find((version) => version.id === init.params.path.id)
    });
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    const { onSaved } = renderEditor(makeFlow());
    await nameField();

    fireEvent.click(screen.getByRole("button", { name: messages.show_prompt_history }));
    const dialog = await screen.findByRole("dialog", { name: messages.prompt_history });
    fireEvent.click(await within(dialog).findByRole("button", { name: /Första utkastet/ }));
    await within(dialog).findByText("Sammanfatta kort.");
    fireEvent.click(within(dialog).getByRole("button", { name: messages.restore_this_version }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: messages.prompt_history })).toBeNull()
    );
    expect((screen.getByLabelText(/^Instruktion/) as HTMLTextAreaElement).value).toBe(
      "Sammanfatta kort."
    );
    expect(
      api.stub.calls.find((call) => call.path === "/api/v1/assistants/{id}/prompts/")?.init
    ).toMatchObject({ params: { path: { id: "assistant-1" } } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(patchBodies()).toEqual([
      expect.objectContaining({
        assistants: [
          expect.objectContaining({
            changes: { prompt: { text: "Sammanfatta kort.", description: null } }
          })
        ]
      })
    ]);
  });

  it("rewrites the instruction with the Prompt Guide into the draft, and its answers save no step", async () => {
    api.routes["GET /api/v1/help-assistants/availability"] = () => ({ body: { available: true } });
    guide.start.mockResolvedValue({ run: { id: "run-1" }, answer: "Vad ska steget göra?" });
    guide.next.mockResolvedValue({
      run: { id: "run-1" },
      answer: "```prompt\nSammanfatta i tre punkter.\n```"
    });
    renderEditor(makeFlow());
    await nameField();
    fireEvent.change(screen.getByLabelText(/^Instruktion/), { target: { value: "Mitt utkast." } });

    fireEvent.click(await screen.findByRole("button", { name: messages.prompt_guide_button }));
    const dialog = await screen.findByRole("dialog", { name: messages.prompt_guide_dialog_title });
    // The guide starts from the draft's instruction, for the step's own assistant.
    expect(guide.start.mock.calls[0]?.[0]).toMatchObject({ targetId: "assistant-1" });
    expect(guide.start.mock.calls[0]?.[0].question).toContain("Mitt utkast.");
    const answer = await within(dialog).findByRole("textbox", {
      name: messages.prompt_guide_input_placeholder
    });
    fireEvent.change(answer, { target: { value: "Tre punkter." } });
    fireEvent.click(
      within(dialog).getByRole("button", { name: messages.prompt_guide_question_send })
    );
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.prompt_guide_apply_button })
    );
    // The draft's own instruction is unsaved, so the guide asks before it replaces it.
    const confirm = await screen.findByRole("alertdialog", {
      name: messages.prompt_guide_apply_overwrite_title
    });
    fireEvent.click(
      within(confirm).getByRole("button", { name: messages.prompt_guide_apply_button })
    );

    await waitFor(() =>
      expect((screen.getByLabelText(/^Instruktion/) as HTMLTextAreaElement).value).toBe(
        "Sammanfatta i tre punkter."
      )
    );
    expect(patchBodies()).toEqual([]);
  });

  it("offers no Prompt Guide where the organisation has none for the caller", async () => {
    api.routes["GET /api/v1/help-assistants/availability"] = () => ({
      body: { available: false, disabled_reason: "no_assignment" }
    });
    renderEditor(makeFlow());
    await nameField();
    await waitFor(() =>
      expect(
        api.stub.calls.some((call) => call.path === "/api/v1/help-assistants/availability")
      ).toBe(true)
    );
    expect(screen.queryByRole("button", { name: messages.prompt_guide_button })).toBeNull();
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

  it.each([
    ["saved", () => ({ body: makeFlow({ draft_revision: 5 }) })],
    ["refused", () => ({ status: 500, body: { message: "Internal error", error_id: "error-1" } })]
  ])(
    "keeps a typed credential out of React Query and the classification preview when it is %s",
    async (_outcome, answer) => {
      const secret = "sk-synthetic-token-4711";
      const preview = "/api/v1/flows/{id}/security-classification/preview";
      api.routes[EDITOR] = answer;
      const { container, queryClient } = renderEditor(
        httpFlow({ mode: "bearer_token", token: { $secret: "stored" } })
      );
      fireEvent.click(await screen.findByRole("button", { name: "Ersätt: Token" }));
      const token = container.querySelector("input[type=password]") as HTMLInputElement;
      fireEvent.change(token, { target: { value: secret } });
      // A name change asks for a new classification preview, with the token in the draft.
      fireEvent.change(await nameField(), { target: { value: "Hämta ärendet" } });
      await waitFor(() =>
        expect(
          api.stub.calls.some(
            (call) => call.path === preview && JSON.stringify(call.init).includes("Hämta ärendet")
          )
        ).toBe(true)
      );
      fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

      await waitFor(() =>
        expect(
          queryClient
            .getMutationCache()
            .getAll()
            .some((mutation) => ["success", "error"].includes(mutation.state.status))
        ).toBe(true)
      );
      // The save sends it; the preview, which has no use for it, does not.
      expect(JSON.stringify(patchBodies())).toContain(secret);
      expect(JSON.stringify(api.stub.calls.filter((call) => call.path === preview))).not.toContain(
        secret
      );
      expect(cachedText(queryClient)).not.toContain(secret);
    },
    20_000
  );

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

  it.each([
    ["answered", () => ({ body: { success: false, status_code: 401, response_preview: null } })],
    ["refused", () => ({ status: 500, body: { message: "Internal error", error_id: "error-1" } })]
  ])(
    "sends a typed credential with the HTTP test but keeps it out of React Query when %s",
    async (_outcome, answer) => {
      const secret = "sk-synthetic-test-token-4711";
      const path = "/api/v1/flows/{id}/http-test";
      api.routes[`POST ${path}`] = answer;
      const { container, queryClient } = renderEditor(
        httpFlow({ mode: "bearer_token", token: { $secret: "stored" } })
      );
      fireEvent.click(await screen.findByRole("button", { name: "Ersätt: Token" }));
      const token = container.querySelector("input[type=password]") as HTMLInputElement;
      fireEvent.change(token, { target: { value: secret } });
      fireEvent.click(screen.getByRole("button", { name: messages.http_test_button }));

      await waitFor(() =>
        expect(
          queryClient
            .getMutationCache()
            .getAll()
            .some((mutation) => ["success", "error"].includes(mutation.state.status))
        ).toBe(true)
      );
      expect(JSON.stringify(api.stub.calls.filter((call) => call.path === path))).toContain(secret);
      expect(cachedText(queryClient)).not.toContain(secret);
    },
    20_000
  );

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
    expect(
      await screen.findByText(
        "0 av 1 fält är klara. Välj vad som ska stå i resten, eller Lämna tomt."
      )
    ).toBeTruthy();
    // The field is a combobox that names what fills it.
    const field = screen.getByRole("combobox", { name: "Namn" });
    expect(field.textContent).toContain(messages.flow_step_editor_template_field_unbound);
    await expectNoAxeViolations(container);
    // Today's date fills a field too; the core resolves it when the step runs.
    fireEvent.click(field);
    expect(
      within(await screen.findByRole("listbox", { name: "Namn" })).getByRole("option", {
        name: /^Dagens datum/
      })
    ).toBeTruthy();
  }, 20_000);

  it("lists what fills each Word template field in the read view, as the step itself reads it", async () => {
    const flow = makeFlow({
      metadata_json: { form_schema: { fields: [{ name: "namn", label: "Namn", type: "text" }] } },
      steps: [
        makeStep({
          output_mode: "template_fill",
          output_type: "docx",
          output_config: {
            template_asset_id: "asset-1",
            template_name: "Beslut.docx",
            placeholders: ["namn", "datum", "beslut", "senare"],
            bindings: { namn: "{{flow_input.namn}}", datum: "", senare: "{{step_2.output.text}}" }
          }
        }),
        makeStep({ id: "step-2", assistant_id: "assistant-2", step_order: 2 })
      ]
    });
    renderEditor(flow, { readOnly: true });
    expect(await screen.findByText("namn: Namn")).toBeTruthy();
    expect(
      screen.getByText(`datum: ${messages.flow_step_editor_template_field_left_empty}`)
    ).toBeTruthy();
    expect(
      screen.getByText(`beslut: ${messages.flow_step_editor_template_field_none}`)
    ).toBeTruthy();
    // A later step's answer is not there when this step runs.
    expect(screen.getByText("senare: Steg 2 kommer efter det här steget")).toBeTruthy();
  }, 20_000);

  it.each([
    { can_download: true, offered: true },
    { can_download: false, offered: false }
  ])(
    "downloads the chosen Word template through a link the core signs for it (may: $can_download)",
    async ({ can_download, offered }) => {
      api.routes["GET /api/v1/flows/{id}/template-files/"] = () => ({
        body: [
          {
            id: "asset-1",
            flow_id: "flow-1",
            file_id: "file-1",
            name: "Beslut.docx",
            checksum: "abc",
            status: "ready",
            placeholders: [],
            can_download
          }
        ]
      });
      api.routes["GET /api/v1/flows/{id}/template-inspect/"] = () => ({
        body: { asset_id: "asset-1", file_id: "file-1", file_name: "Beslut.docx", placeholders: [] }
      });
      api.routes["POST /api/v1/flows/{id}/template-files/{file_id}/signed-url/"] = () => ({
        body: {
          url: "http://backend:8000/api/v1/files/file-1/download/?token=signed",
          expires_at: 0
        }
      });
      const saved: string[] = [];
      const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
        this: HTMLAnchorElement
      ) {
        saved.push(`${this.getAttribute("href")} ${this.download}`);
      });
      renderEditor(
        makeFlow({
          steps: [
            makeStep({
              output_mode: "template_fill",
              output_type: "docx",
              output_config: {
                template_asset_id: "asset-1",
                template_name: "Beslut.docx",
                placeholders: [],
                bindings: {}
              }
            })
          ]
        })
      );
      // The template list has loaded and the chosen template shows.
      await screen.findAllByText("Beslut.docx");
      const download = () => screen.queryByRole("button", { name: "Ladda ner Beslut.docx" });
      if (!offered) {
        expect(download()).toBeNull();
        click.mockRestore();
        return;
      }
      fireEvent.click(await screen.findByRole("button", { name: "Ladda ner Beslut.docx" }));
      await waitFor(() =>
        expect(saved).toEqual(["/api/v1/files/file-1/download/?token=signed Beslut.docx"])
      );
      expect(
        api.stub.calls.find(
          (call) => call.path === "/api/v1/flows/{id}/template-files/{file_id}/signed-url/"
        )?.init
      ).toMatchObject({
        params: { path: { id: "flow-1", file_id: "asset-1" } },
        body: { content_disposition: "attachment" }
      });
      click.mockRestore();
    }
  );

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
    expect(screen.getAllByText(messages.flow_output_mode_pass_through)).toHaveLength(1);
    await expectNoAxeViolations(container);
  }, 20_000);

  it("reads the step that sends the run's result as what it sends and to whom", async () => {
    renderEditor(
      makeFlow({
        steps: [
          makeStep({ output_mode: "compose_text" }),
          makeStep({
            id: "step-2",
            step_order: 2,
            user_description: "Skicka körningens resultat",
            input_source: "previous_step",
            output_mode: "http_post",
            output_config: {
              url: "https://hook.example.org/",
              auth: { mode: "none" },
              timeout_seconds: 30,
              body: { mode: "run_result" },
              custom_headers: [],
              response_format: null
            }
          })
        ]
      }),
      { readOnly: true, stepId: "step-2" }
    );
    expect(await screen.findByText("https://hook.example.org/")).toBeTruthy();
    // The same sections as the editor: what is sent, and to whom.
    expect(screen.getByText(messages.flow_step_editor_run_result_sends_title)).toBeTruthy();
    expect(screen.getByText(messages.flow_step_editor_run_result_receiver_title)).toBeTruthy();
    expect((await rowValue("Sammanfatta")).textContent).toBe(messages.flow_output_type_text);
    expect(screen.queryByText(messages.flow_step_editor_run_result_empty_title)).toBeNull();
    // Nothing the step does not use: no input, no mode or body, no review.
    expect(screen.queryByText(messages.flow_step_editor_input_title)).toBeNull();
    expect(screen.queryByText(messages.flow_step_output_mode)).toBeNull();
    expect(screen.queryByText(messages.flow_step_editor_http_body)).toBeNull();
    expect(screen.queryByText(messages.flow_step_review_policy)).toBeNull();
    // Its classification is headed as what it is: there is no review to name.
    expect(screen.getByText(messages.flows_classification_heading)).toBeTruthy();
    expect(screen.queryByText(messages.flow_step_editor_control_title)).toBeNull();
  }, 20_000);

  it("shows the step that sends its timeout in the read view", async () => {
    renderEditor(
      makeFlow({
        steps: [
          makeStep({ output_mode: "compose_text" }),
          makeStep({
            id: "step-2",
            step_order: 2,
            output_mode: "http_post",
            timeout_seconds: 120,
            output_config: {
              url: "https://hook.example.org/",
              auth: { mode: "none" },
              timeout_seconds: 30,
              body: { mode: "run_result" },
              custom_headers: [],
              response_format: null
            }
          })
        ]
      }),
      { readOnly: true, stepId: "step-2" }
    );
    expect((await rowValue(messages.flow_step_editor_timeout)).textContent).toBe("120 sekunder");
  }, 20_000);

  it("reads what is published, not the form's unsaved edits, once a published version arrives", async () => {
    const sender = makeStep({
      id: "step-send",
      step_order: 2,
      user_description: "Skicka körningens resultat",
      output_mode: "http_post",
      output_config: {
        url: "https://hook.example.org/",
        auth: { mode: "none" },
        timeout_seconds: 30,
        body: { mode: "run_result" },
        custom_headers: [],
        response_format: null
      }
    });
    const start = makeFlow({
      steps: [
        makeStep({ id: "step-a", user_description: "Rapport A", output_mode: "compose_text" }),
        sender
      ]
    });
    const editor = (flow: FlowPublic) => (
      <FlowStepEditor
        flow={flow}
        stepId="step-send"
        readOnly={false}
        onSaved={() => {}}
        onCancel={() => {}}
      />
    );
    const { rerender } = renderEditor(start, { stepId: "step-send" });
    fireEvent.change(await screen.findByLabelText(/^Mottagarens adress/), {
      target: { value: "https://osparad.example.org/" }
    });
    rerender(
      editor(
        makeFlow({
          draft_revision: start.draft_revision + 1,
          published_version: 1,
          steps: [
            makeStep({ id: "step-b", user_description: "Rapport B", output_mode: "compose_text" }),
            sender
          ]
        })
      )
    );
    await screen.findByText(messages.flow_step_editor_published);
    expect(await screen.findByText("Rapport B")).toBeTruthy();
    expect(screen.getByText("https://hook.example.org/")).toBeTruthy();
    expect(screen.queryByText("Rapport A")).toBeNull();
    expect(screen.queryByText("https://osparad.example.org/")).toBeNull();
  }, 20_000);

  it("heads the read view with the saved name, and gives the unsaved one back when unpublished", async () => {
    const start = makeFlow();
    const editor = (flow: FlowPublic) => (
      <FlowStepEditor
        flow={flow}
        stepId="step-1"
        readOnly={false}
        onSaved={() => {}}
        onCancel={() => {}}
      />
    );
    const { rerender } = renderEditor(start);
    fireEvent.change(await nameField(), { target: { value: "Osparat namn" } });
    rerender(editor({ ...start, draft_revision: start.draft_revision + 1, published_version: 1 }));
    await screen.findByText(messages.flow_step_editor_published);
    expect(screen.getByRole("heading", { level: 2, name: "Sammanfatta" })).toBeTruthy();
    expect(screen.queryByText("Osparat namn")).toBeNull();

    rerender(
      editor({ ...start, draft_revision: start.draft_revision + 2, published_version: null })
    );
    expect((await nameField()).value).toBe("Osparat namn");
  }, 20_000);

  it("says in the read view of a draft step that sends the run's result that it has nothing to send yet", async () => {
    const { container } = renderEditor(
      makeFlow({
        steps: [
          makeStep({ output_type: "json" }),
          makeStep({
            id: "step-2",
            step_order: 2,
            user_description: "Skicka körningens resultat",
            input_source: "previous_step",
            output_mode: "http_post",
            output_config: {
              url: "https://hook.example.org/",
              auth: { mode: "none" },
              timeout_seconds: 30,
              body: { mode: "run_result" },
              custom_headers: [],
              response_format: null
            }
          })
        ]
      }),
      { readOnly: true, stepId: "step-2" }
    );
    expect(await screen.findByText("https://hook.example.org/")).toBeTruthy();
    expect(screen.getByText(messages.flow_step_editor_run_result_empty_title)).toBeTruthy();
    // The text stands under the heading instead of an empty list.
    expect(screen.getByText(messages.flow_step_editor_run_result_sends_title)).toBeTruthy();
    const lists = [...container.querySelectorAll("dl")];
    expect(lists.filter((list) => list.children.length === 0)).toEqual([]);
  }, 20_000);

  it("folds a long instruction under Visa hela and wraps a long address anywhere", async () => {
    const prompt = "Läs ärendet noga. ".repeat(170);
    const url = `https://api.example.org/${"a".repeat(180)}`;
    const assistant = makeAssistant();
    api.routes[ASSISTANT] = () => ({
      body: { ...assistant, prompt: { ...assistant.prompt!, text: prompt } }
    });
    renderEditor(
      makeFlow({
        steps: [
          makeStep({
            output_mode: "pass_through",
            input_source: "http_get",
            input_config: {
              url,
              auth: { mode: "none" },
              timeout_seconds: 30,
              body: { mode: "none" },
              custom_headers: [],
              response_format: "text"
            }
          })
        ]
      }),
      { readOnly: true }
    );
    const show = await screen.findByRole("button", { name: messages.flows_change_card_show_all });
    const text = document.getElementById(show.getAttribute("aria-controls")!)!;
    expect(text.textContent).toBe(prompt.trim());
    expect(text.className).toContain("line-clamp-6");
    expect(show.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(show);
    expect(text.className).not.toContain("line-clamp-6");
    expect(
      screen
        .getByRole("button", { name: messages.flows_change_card_show_less })
        .getAttribute("aria-expanded")
    ).toBe("true");
    expect(screen.getByText(url).className).toContain("[overflow-wrap:anywhere]");
  });

  it("does not inspect a Word template for a reader who may not edit the flow", async () => {
    // The core lets only an editor inspect; a reader sees the field's tag.
    api.routes["GET /api/v1/flows/{id}/template-inspect/"] = () => ({
      status: 403,
      body: { message: "Forbidden" }
    });
    renderEditor(
      makeFlow({
        permissions: {
          can_edit: false,
          can_publish: false,
          can_delete: false,
          can_run: true,
          can_view_runs: true
        },
        steps: [
          makeStep({
            output_mode: "template_fill",
            output_type: "docx",
            output_config: {
              template_asset_id: "asset-1",
              template_name: "Protokoll.docx",
              placeholders: ["beslut_och_atgarder"],
              bindings: {}
            }
          })
        ]
      }),
      { readOnly: true }
    );
    expect(
      await screen.findByText(
        `beslut_och_atgarder: ${messages.flow_step_editor_template_field_none}`
      )
    ).toBeTruthy();
    expect(
      api.stub.calls.some((call) => call.path === "/api/v1/flows/{id}/template-inspect/")
    ).toBe(false);
  });

  it("names a Word step's fields by their titles, and lists a fixed-format answer's fields", async () => {
    api.routes["GET /api/v1/flows/{id}/template-inspect/"] = () => ({
      body: {
        asset_id: "asset-1",
        file_id: "file-1",
        file_name: "Protokoll.docx",
        placeholders: [
          {
            name: "beslut_och_atgarder",
            label: "Beslut och åtgärder",
            kind: "text",
            location: "body"
          }
        ]
      }
    });
    renderEditor(
      makeFlow({
        steps: [
          makeStep({
            output_mode: "template_fill",
            output_type: "docx",
            output_config: {
              template_asset_id: "asset-1",
              template_name: "Protokoll.docx",
              placeholders: ["beslut_och_atgarder"],
              bindings: {}
            }
          })
        ]
      }),
      { readOnly: true }
    );
    expect(
      await screen.findByText(
        `Beslut och åtgärder: ${messages.flow_step_editor_template_field_none}`
      )
    ).toBeTruthy();
    expect(screen.queryByText(/beslut_och_atgarder/)).toBeNull();
    cleanup();

    renderEditor(
      makeFlow({
        steps: [
          makeStep({
            output_mode: "pass_through",
            output_type: "json",
            output_contract: {
              type: "object",
              properties: {
                diarienummer: { type: "string", description: "Ärendets nummer" },
                beslut: { type: "string" }
              }
            }
          })
        ]
      }),
      { readOnly: true }
    );
    const fields = await rowValue(messages.flow_step_editor_answer_fields);
    expect(fields.textContent).toContain("diarienummer · Ärendets nummer");
    expect(fields.textContent).toContain("beslut");
  });

  it("says a step reads what was chosen for it, not its source, in both views", async () => {
    const twoSteps = (readsChosen: boolean) =>
      makeFlow({
        steps: [
          makeStep(),
          makeStep({
            id: "step-2",
            assistant_id: "assistant-2",
            step_order: 2,
            user_description: "Skriv svar",
            input_source: "previous_step",
            input_bindings: readsChosen
              ? { source_refs: [{ step_ref: "step_1", output: "text" }] }
              : null
          })
        ]
      });
    const open = (flow: FlowPublic, readOnly: boolean) => {
      const queryClient = testQueryClient();
      queryClient.setQueryData(["spaces", "space-1"], makeSpace());
      return renderInApp(
        <FlowStepEditor
          flow={flow}
          stepId="step-2"
          readOnly={readOnly}
          onSaved={() => {}}
          onCancel={() => {}}
        />,
        { queryClient }
      );
    };
    api.routes[ASSISTANT] = () => ({ body: makeAssistant() });

    open(twoSteps(false), false);
    expect(await screen.findByText("Steget läser svaret från Steg 1: Sammanfatta.")).toBeTruthy();
    cleanup();

    open(twoSteps(true), false);
    expect(
      await screen.findByText("Steget läser Steg 1: Sammanfatta, som du valt nedan.")
    ).toBeTruthy();
    expect(screen.queryByText(/läser svaret från/)).toBeNull();
    cleanup();

    open(twoSteps(true), true);
    const source = await rowValue(messages.flow_step_editor_input_source);
    expect(source.textContent).toContain(messages.flow_step_editor_source_chosen);
    expect(source.textContent).not.toContain(messages.flow_input_source_previous_step);
  });

  it("lists each chosen result on its own line, since a name can hold a comma", async () => {
    const queryClient = testQueryClient();
    queryClient.setQueryData(["spaces", "space-1"], makeSpace());
    const flow = makeFlow({
      steps: [
        makeStep(),
        makeStep({
          id: "step-2",
          assistant_id: "assistant-2",
          step_order: 2,
          user_description: "Granska",
          input_bindings: {
            source_refs: [{ step_ref: "step_1", output: "structured", field_path: "beslut" }]
          }
        }),
        makeStep({
          id: "step-3",
          assistant_id: "assistant-3",
          step_order: 3,
          input_bindings: {
            source_refs: [
              { step_ref: "step_1", output: "structured", field_path: "beslut" },
              { step_ref: "step_2", output: "text" }
            ]
          }
        })
      ]
    });
    const open = (readOnly: boolean) =>
      renderInApp(
        <FlowStepEditor
          flow={flow}
          stepId="step-3"
          readOnly={readOnly}
          onSaved={() => {}}
          onCancel={() => {}}
        />,
        { queryClient }
      );
    open(true);
    const results = await rowValue(messages.flow_step_editor_underlag_results);
    expect(
      within(results as HTMLElement)
        .getAllByRole("listitem")
        .map((item) => item.textContent)
    ).toEqual(["Steg 1: Sammanfatta, fältet beslut", "Steg 2: Granska"]);
    cleanup();

    // In a sentence, a semicolon parts them.
    open(false);
    expect(
      await screen.findByText(
        "Steget läser Steg 1: Sammanfatta, fältet beslut; Steg 2: Granska, som du valt nedan."
      )
    ).toBeTruthy();
  });

  it("heads the step with its name alone: no step number above it, no chips repeating its rows", async () => {
    renderEditor(makeFlow(), { readOnly: true });
    const heading = await screen.findByRole("heading", { level: 2, name: "Sammanfatta" });
    const header = heading.closest("header")!;
    expect(within(header).queryByText("Steg 1")).toBeNull();
    // "Källa" and "Vad steget gör" say these in the list below.
    expect(within(header).queryByText(messages.flow_input_source_flow_input)).toBeNull();
    expect(within(header).queryByText(messages.flow_output_mode_pass_through)).toBeNull();
  });

  it("forgets a save it reported once the step was published and unpublished", async () => {
    const saved = makeFlow({
      draft_revision: 5,
      steps: [makeStep({ user_description: "Sammanfatta ärendet" })]
    });
    api.routes[EDITOR] = () => ({ body: saved });
    const { rerender } = renderEditor(makeFlow());
    fireEvent.change(await nameField(), { target: { value: "Sammanfatta ärendet" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    await screen.findByText(messages.flow_step_editor_saved);

    const editor = (flow: FlowPublic) => (
      <FlowStepEditor
        flow={flow}
        stepId="step-1"
        readOnly={false}
        onSaved={() => {}}
        onCancel={() => {}}
      />
    );
    rerender(editor({ ...saved, draft_revision: 6, published_version: 1 }));
    await screen.findByText(messages.flow_step_editor_published);
    rerender(editor({ ...saved, draft_revision: 7, published_version: null }));
    await nameField();
    // The save bar, not the live region that once announced the save.
    expect(
      screen.queryByText(messages.flow_step_editor_saved, {
        ignore: "script, style, [data-astryx-live-region]"
      })
    ).toBeNull();
    expect(screen.getByText(messages.flow_step_editor_no_changes)).toBeTruthy();
  });

  it("says which of the edits a newer version changed too, and lets the person take that version", async () => {
    const { rerender } = renderEditor(makeFlow());
    const name = await nameField();
    fireEvent.change(name, { target: { value: "Mitt namn" } });
    // The assistant renames the step in the chat: a newer draft reaches the editor.
    const newer = makeFlow({
      draft_revision: 5,
      steps: [makeStep({ user_description: "Chattens namn" })]
    });
    rerender(
      <FlowStepEditor
        flow={newer}
        stepId="step-1"
        readOnly={false}
        onSaved={() => {}}
        onCancel={() => {}}
      />
    );
    const newerBanner = await screen.findByText(messages.flow_step_editor_newer_title);
    fireEvent.click(
      within(newerBanner.closest(".astryx-banner") ?? document.body).getByRole("button", {
        name: messages.flow_step_editor_reload
      })
    );

    // Not settled silently: the field keeps the person's value and the conflict is named.
    const conflict = await screen.findByText(
      messages.flow_step_editor_conflict_title.replace("{fields}", messages.flow_step_name)
    );
    expect((await nameField()).value).toBe("Mitt namn");
    fireEvent.click(
      within(conflict.closest(".astryx-banner") ?? document.body).getByRole("button", {
        name: messages.flow_step_editor_conflict_take_theirs
      })
    );
    await waitFor(async () => expect((await nameField()).value).toBe("Chattens namn"));
    // The banner went with its buttons: focus stays in the editor, where it was.
    expect(document.activeElement?.closest("form")).toBeTruthy();
    expect(
      screen.queryByText(
        messages.flow_step_editor_conflict_title.replace("{fields}", messages.flow_step_name)
      )
    ).toBeNull();
  });

  it("shows the newer contract once the person takes that version over their typed one", async () => {
    const { rerender } = renderEditor(makeFlow());
    await nameField();
    fireEvent.click(
      screen.getByRole("button", {
        name: new RegExp(`^${messages.flow_step_editor_advanced_title}`)
      })
    );
    const contract = () =>
      screen.getByRole("textbox", {
        name: new RegExp(`^${messages.flow_step_input_contract}`)
      }) as HTMLTextAreaElement;
    fireEvent.change(contract(), { target: { value: '{"type": "object"}' } });
    rerender(
      <FlowStepEditor
        flow={makeFlow({
          draft_revision: 5,
          steps: [makeStep({ input_contract: { type: "string" } })]
        })}
        stepId="step-1"
        readOnly={false}
        onSaved={() => {}}
        onCancel={() => {}}
      />
    );
    fireEvent.click(await screen.findByRole("button", { name: messages.flow_step_editor_reload }));
    fireEvent.click(
      await screen.findByRole("button", { name: messages.flow_step_editor_conflict_take_theirs })
    );
    // The field shows what will be saved, not the text the person typed before.
    await waitFor(() => expect(JSON.parse(contract().value)).toEqual({ type: "string" }));
    expect(screen.getByText(messages.flow_step_editor_no_changes)).toBeTruthy();
  });

  it("says nothing about a newer version that left the edited fields alone", async () => {
    const { rerender } = renderEditor(makeFlow());
    fireEvent.change(await nameField(), { target: { value: "Mitt namn" } });
    rerender(
      <FlowStepEditor
        flow={makeFlow({
          draft_revision: 5,
          steps: [makeStep({ timeout_seconds: 120 })]
        })}
        stepId="step-1"
        readOnly={false}
        onSaved={() => {}}
        onCancel={() => {}}
      />
    );
    fireEvent.click(await screen.findByRole("button", { name: messages.flow_step_editor_reload }));
    await waitFor(() =>
      expect(screen.queryByText(messages.flow_step_editor_newer_title)).toBeNull()
    );
    expect(
      screen.queryByRole("button", { name: messages.flow_step_editor_conflict_take_theirs })
    ).toBeNull();
    expect((await nameField()).value).toBe("Mitt namn");
  });
});

describe("FlowStepEditor deliverables", () => {
  const TEMPLATE_CONFIG = {
    template_asset_id: "asset-1",
    template_name: "Standup.docx",
    placeholders: ["namn"],
    bindings: { namn: "{{flow_input.team}}" },
    future: { kept: true }
  };

  /** Two documents, then a text step last; the form has a team and the run's day. */
  function deliveryFlow() {
    return makeFlow({
      metadata_json: {
        form_schema: {
          fields: [
            { name: "team", label: "Team", type: "text" },
            { name: "motesdag", label: "Mötesdag", type: "date", role: "run_date" }
          ]
        }
      },
      steps: [
        makeStep({
          user_description: "Standup för Eneo",
          output_mode: "render_verbatim",
          output_type: "docx"
        }),
        makeStep({
          id: "step-2",
          step_order: 2,
          user_description: "Standup för webbplatsen",
          input_source: "previous_step",
          output_mode: "template_fill",
          output_type: "docx",
          output_config: TEMPLATE_CONFIG
        }),
        makeStep({
          id: "step-3",
          step_order: 3,
          user_description: "Sammanfatta",
          input_source: "previous_step"
        })
      ]
    });
  }

  function routeTemplate() {
    api.routes["GET /api/v1/flows/{id}/template-files/"] = () => ({
      body: [
        {
          id: "asset-1",
          flow_id: "flow-1",
          file_id: "file-1",
          name: "Standup.docx",
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
        file_name: "Standup.docx",
        placeholders: [{ name: "namn", label: "Namn", kind: "text", location: "body" }]
      }
    });
  }

  /** The editor PATCH applied to the step it names; the flow as stored after each save. */
  function storeEdits(start: FlowPublic) {
    let stored = start;
    api.routes[EDITOR] = (init) => {
      const body = (
        init as { body: { step_edits?: { step_id: string; changes: Record<string, unknown> }[] } }
      ).body;
      const edit = body.step_edits?.[0];
      stored = {
        ...stored,
        draft_revision: stored.draft_revision + 1,
        steps: stored.steps.map((step) =>
          edit && step.id === edit.step_id ? { ...step, ...edit.changes } : step
        )
      };
      return { body: stored };
    };
    return () => stored;
  }

  const deliverySwitch = () =>
    screen.findByRole("switch", {
      name: new RegExp(`^${messages.flow_step_editor_deliverable_switch}`)
    });
  const labelField = () =>
    screen.findByRole("textbox", {
      name: new RegExp(`^${messages.flow_step_editor_deliverable_label}`)
    }) as Promise<HTMLInputElement>;
  const fileNameField = () =>
    screen.getByRole("textbox", {
      name: new RegExp(`^${messages.flow_step_editor_deliverable_file_name}`)
    }) as HTMLInputElement;
  const isOn = (toggle: HTMLElement) =>
    toggle.getAttribute("aria-checked") === "true" || (toggle as HTMLInputElement).checked;

  async function saveStep() {
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    await screen.findByText(messages.flow_step_editor_saved);
  }

  it("marks two documents, keeps them when reopened, and turns one off with its template kept", async () => {
    routeTemplate();
    const current = storeEdits(deliveryFlow());

    let view = renderEditor(current(), { stepId: "step-1" });
    const first = await deliverySwitch();
    expect(isOn(first)).toBe(false);
    fireEvent.click(first);
    fireEvent.change(await labelField(), { target: { value: "Till Eneo" } });
    fireEvent.change(fileNameField(), { target: { value: "Standup " } });
    const insert = screen.getByRole("button", {
      name: messages.flow_step_editor_deliverable_insert_field
    });
    fireEvent.click(insert);
    const menu = await screen.findByRole("menu", { name: insert.textContent ?? "" });
    const offered = within(menu).getAllByRole("menuitem");
    const texts = offered.map((item) => item.textContent).join(" ");
    // Only form fields; the run's day is added to every name already.
    expect(texts).toContain("{{flow_input.team}}");
    expect(texts).not.toContain("motesdag");
    expect(texts).not.toContain("{{datum}}");
    fireEvent.click(offered.find((item) => item.textContent?.includes("{{flow_input.team}}"))!);
    expect(fileNameField().value).toBe("Standup {{flow_input.team}}");
    await expectNoAxeViolations(view.container);
    await saveStep();
    expect(patchBodies()[0]).toMatchObject({
      expected_revision: 4,
      step_edits: [
        {
          step_id: "step-1",
          changes: {
            output_config: {
              deliverable: { label: "Till Eneo", file_name: "Standup {{flow_input.team}}" }
            }
          }
        }
      ]
    });
    view.unmount();

    view = renderEditor(current(), { stepId: "step-2" });
    fireEvent.click(await deliverySwitch());
    fireEvent.change(await labelField(), { target: { value: "Till webbplatsen" } });
    await saveStep();
    expect(patchBodies()[1]).toMatchObject({
      expected_revision: 5,
      step_edits: [
        {
          step_id: "step-2",
          changes: {
            output_config: { ...TEMPLATE_CONFIG, deliverable: { label: "Till webbplatsen" } }
          }
        }
      ]
    });
    view.unmount();

    // Reopened, both read as saved.
    view = renderEditor(current(), { stepId: "step-1" });
    expect(isOn(await deliverySwitch())).toBe(true);
    expect((await labelField()).value).toBe("Till Eneo");
    expect(fileNameField().value).toBe("Standup {{flow_input.team}}");
    // An edit changed back sends nothing.
    fireEvent.change(await labelField(), { target: { value: "Till Eneo och fler" } });
    fireEvent.change(await labelField(), { target: { value: "Till Eneo" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    expect(await screen.findByText(messages.flow_step_editor_no_changes)).toBeTruthy();
    expect(patchBodies()).toHaveLength(2);
    view.unmount();

    view = renderEditor(current(), { stepId: "step-2" });
    const second = await deliverySwitch();
    expect((await labelField()).value).toBe("Till webbplatsen");
    fireEvent.click(second);
    await waitFor(() =>
      expect(
        screen.queryByRole("textbox", {
          name: new RegExp(`^${messages.flow_step_editor_deliverable_label}`)
        })
      ).toBeNull()
    );
    await saveStep();
    const off = patchBodies()[2] as {
      step_edits: { changes: { output_config: Record<string, unknown> } }[];
    };
    expect(off.step_edits[0]!.changes.output_config).toEqual(TEMPLATE_CONFIG);
    expect(current().steps[0]!.output_config).toEqual({
      deliverable: { label: "Till Eneo", file_name: "Standup {{flow_input.team}}" }
    });
  }, 30_000);

  it("includes the last document by its place, unmarked until it is kept or renamed", async () => {
    const current = storeEdits(
      makeFlow({
        steps: [
          makeStep({
            user_description: "Protokoll",
            output_mode: "render_verbatim",
            output_type: "pdf"
          })
        ]
      })
    );
    const view = renderEditor(current());
    expect(await screen.findByText(messages.flow_step_editor_deliverable_included)).toBeTruthy();
    expect(screen.getByText(messages.flow_step_editor_deliverable_place_last)).toBeTruthy();
    // No locked switch.
    expect(
      screen.queryByRole("switch", {
        name: new RegExp(`^${messages.flow_step_editor_deliverable_switch}`)
      })
    ).toBeNull();
    fireEvent.change(await nameField(), { target: { value: "Protokoll till nämnden" } });
    await saveStep();
    expect(current().steps[0]!.output_config).toBeNull();

    // Opening the fields marks nothing: the name follows the step's until it is changed.
    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_step_editor_deliverable_customise })
    );
    const label = await labelField();
    expect(document.activeElement).toBe(label);
    expect(label.value).toBe("Protokoll till nämnden");
    expect(screen.queryByText(/ändring som inte är sparad/)).toBeNull();
    fireEvent.change(label, { target: { value: "Till nämnden" } });
    expect(screen.getByText("1 ändring som inte är sparad")).toBeTruthy();
    expect(screen.getByText(messages.flow_step_editor_deliverable_kept)).toBeTruthy();
    // Its own name goes with the choice, and the step stays in by its place.
    expect(
      screen.getByText(messages.flow_step_editor_deliverable_reset_named_document_last)
    ).toBeTruthy();
    await expectNoAxeViolations(view.container);

    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_step_editor_deliverable_reset })
    );
    const keep = await screen.findByRole("button", {
      name: messages.flow_step_editor_deliverable_keep
    });
    expect(document.activeElement).toBe(keep);
    expect(screen.queryByText(/ändring som inte är sparad/)).toBeNull();

    // "Behåll" marks it under the step's name.
    fireEvent.click(keep);
    expect(screen.getByText(messages.flow_step_editor_deliverable_reset_last)).toBeTruthy();
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: messages.flow_step_editor_deliverable_reset })
    );
    await saveStep();
    expect(current().steps[0]!.output_config).toEqual({
      deliverable: { label: "Protokoll till nämnden" }
    });
  }, 30_000);

  it("undoes the choice with a button that says so", async () => {
    renderEditor(
      makeFlow({
        steps: [
          makeStep({
            user_description: "Protokoll",
            output_mode: "render_verbatim",
            output_type: "pdf",
            output_config: { deliverable: { label: "Protokoll" } }
          })
        ]
      })
    );
    expect(await screen.findByRole("button", { name: "Ångra valet" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Ta bort valet" })).toBeNull();
  }, 20_000);

  it("keeps the name field where it is on the first keystroke after opening it", async () => {
    renderEditor(
      makeFlow({
        steps: [
          makeStep({
            user_description: "Protokoll",
            output_mode: "render_verbatim",
            output_type: "pdf"
          })
        ]
      })
    );
    fireEvent.click(
      await screen.findByRole("button", { name: messages.flow_step_editor_deliverable_customise })
    );
    const label = await labelField();
    // Every button above the field: none may come or go while the name is typed.
    const above = () =>
      screen
        .getAllByRole("button")
        .filter(
          (button) => button.compareDocumentPosition(label) & Node.DOCUMENT_POSITION_FOLLOWING
        );
    const before = above();
    fireEvent.change(label, { target: { value: "Protokoll till nämnden" } });
    expect(document.activeElement).toBe(label);
    const after = above();
    expect(after).toHaveLength(before.length);
    after.forEach((button, index) => expect(button).toBe(before[index]));
  }, 20_000);

  it("offers no Behåll once a name is typed: the name marks the step, and Ångra valet takes it back", async () => {
    renderEditor(
      makeFlow({
        steps: [
          makeStep({
            user_description: "Protokoll",
            output_mode: "render_verbatim",
            output_type: "pdf"
          })
        ]
      })
    );
    fireEvent.click(
      await screen.findByRole("button", { name: messages.flow_step_editor_deliverable_customise })
    );
    const label = await labelField();
    fireEvent.change(label, { target: { value: "P" } });
    expect(
      screen.queryByRole("button", { name: messages.flow_step_editor_deliverable_keep })
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: messages.flow_step_editor_deliverable_reset })
    ).toBeTruthy();
    expect(document.activeElement).toBe(label);
  }, 20_000);

  it("names a text step by its place right before the step that sends, without a file name", async () => {
    renderEditor(
      makeFlow({
        steps: [
          makeStep({ user_description: "Sammanfatta" }),
          makeStep({
            id: "step-2",
            step_order: 2,
            user_description: "Skicka",
            input_source: "previous_step",
            output_mode: "http_post",
            output_config: {
              url: "https://receiver.example.org/eneo",
              auth: { mode: "none" },
              body: { mode: "run_result" }
            }
          })
        ]
      })
    );
    expect(
      await screen.findByText(messages.flow_step_editor_deliverable_place_before_send)
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_step_editor_deliverable_customise_text })
    );
    expect((await labelField()).value).toBe("Sammanfatta");
    expect(
      screen.queryByRole("textbox", {
        name: new RegExp(`^${messages.flow_step_editor_deliverable_file_name}`)
      })
    ).toBeNull();
  }, 20_000);

  it("removes a saved customisation of the last document, which restores the default", async () => {
    const current = storeEdits(
      makeFlow({
        steps: [
          makeStep({
            output_mode: "render_verbatim",
            output_type: "pdf",
            output_config: { deliverable: { label: "Protokoll" }, future: 1 }
          })
        ]
      })
    );
    renderEditor(current());
    expect((await labelField()).value).toBe("Protokoll");
    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_step_editor_deliverable_reset })
    );
    await saveStep();
    expect(patchBodies()[0]).toMatchObject({
      step_edits: [{ step_id: "step-1", changes: { output_config: { future: 1 } } }]
    });
  }, 20_000);

  it("focuses an empty label instead of saving, and holds the label and file name to their limits", async () => {
    renderEditor(deliveryFlow());
    fireEvent.click(await deliverySwitch());
    // The switch names the result after the step.
    expect((await labelField()).value).toBe("Standup för Eneo");
    fireEvent.change(await labelField(), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    expect(
      await screen.findByText(messages.flow_step_editor_deliverable_label_required)
    ).toBeTruthy();
    const label = await labelField();
    expect(document.activeElement).toBe(label);
    expect(label.getAttribute("aria-invalid")).toBe("true");

    fireEvent.change(label, { target: { value: "a".repeat(121) } });
    fireEvent.change(fileNameField(), { target: { value: "b".repeat(201) } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    expect(
      await screen.findByText(
        messages.flow_step_editor_deliverable_label_too_long.replace("{max}", "120")
      )
    ).toBeTruthy();
    expect(
      screen.getByText(
        messages.flow_step_editor_deliverable_file_name_too_long.replace("{max}", "200")
      )
    ).toBeTruthy();

    fireEvent.change(label, { target: { value: "a".repeat(120) } });
    fireEvent.change(fileNameField(), { target: { value: "b".repeat(200) } });
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    await saveStep();
    expect(patchBodies()).toHaveLength(1);
  }, 20_000);

  // The same labels as the core's own test (test_flow_validators.py, a deliverable
  // label with braces), so the editor refuses what the core would refuse on save.
  it.each<[string, boolean]>([
    ["Report {{ flow_input.text }}", false],
    ["Report {{", false],
    ["Report }}", false],
    ["Rapport: vecka 47 (utkast) – 50 %", true]
  ])(
    "holds the label %j to the core's rule on braces (saved: %s)",
    async (value, saved) => {
      const error =
        "Namnet visas som det står och kan inte innehålla {{ eller }}. Skriv det som vanlig text.";
      api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
      renderEditor(deliveryFlow());
      fireEvent.click(await deliverySwitch());
      fireEvent.change(await labelField(), { target: { value } });
      fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
      if (saved) {
        await waitFor(() => expect(patchBodies()).toHaveLength(1));
        expect(screen.queryByText(error)).toBeNull();
        return;
      }
      expect(await screen.findByText(error)).toBeTruthy();
      expect(document.activeElement).toBe(await labelField());
      expect(patchBodies()).toHaveLength(0);
    },
    20_000
  );

  it.each([
    {
      form: "the field the refusal names",
      answer: {
        status: 400,
        body: {
          message: "Step 2: the file name reads a field the form does not have",
          code: "flow_step_invalid",
          context: { field: "output_config.deliverable.file_name", step_order: 2 },
          eneo_error_code: 9000
        }
      }
    },
    {
      form: "the request validation error",
      answer: {
        status: 422,
        body: {
          message: "Request validation failed",
          code: "request_validation_error",
          details: {
            errors: [
              {
                location: [
                  "body",
                  "step_edits",
                  0,
                  "changes",
                  "output_config",
                  "deliverable",
                  "file_name"
                ],
                message: "x"
              }
            ]
          }
        }
      }
    }
  ])(
    "puts a refused file name at its field on a Word template step ($form)",
    async ({ answer }) => {
      routeTemplate();
      api.routes[EDITOR] = () => answer;
      renderEditor(deliveryFlow(), { stepId: "step-2" });
      fireEvent.click(await deliverySwitch());
      fireEvent.change(await labelField(), { target: { value: "Till webbplatsen" } });
      fireEvent.change(fileNameField(), { target: { value: "Standup {{flow_input.saknas}}" } });
      fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
      await waitFor(() => expect(document.activeElement).toBe(fileNameField()));
      expect(fileNameField().getAttribute("aria-invalid")).toBe("true");
    },
    20_000
  );

  it("reads empty output settings as none: a switch turned on and off sends nothing", async () => {
    const flow = deliveryFlow();
    const current = storeEdits({
      ...flow,
      steps: flow.steps.map((step) =>
        step.id === "step-1" ? { ...step, output_config: {} } : step
      )
    });
    renderEditor(current());
    fireEvent.click(await deliverySwitch());
    await labelField();
    fireEvent.click(await deliverySwitch());
    await waitFor(() =>
      expect(
        screen.queryByRole("textbox", {
          name: new RegExp(`^${messages.flow_step_editor_deliverable_label}`)
        })
      ).toBeNull()
    );
    expect(screen.queryByText(/ändring som inte är sparad/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    expect(await screen.findByText(messages.flow_step_editor_no_changes)).toBeTruthy();
    expect(patchBodies()).toHaveLength(0);

    // Another edit leaves the output settings out.
    fireEvent.change(await nameField(), { target: { value: "Standup för alla" } });
    await saveStep();
    expect(
      (patchBodies()[0] as { step_edits: { changes: Record<string, unknown> }[] }).step_edits[0]!
        .changes
    ).toEqual({ user_description: "Standup för alla" });
  }, 20_000);

  it("keeps a switch turned on and off out of the edits, so a newer version's deliverable stays", async () => {
    const flow = deliveryFlow();
    const start = {
      ...flow,
      steps: flow.steps.map((step) =>
        step.id === "step-1" ? { ...step, output_config: {} } : step
      )
    };
    // Someone else marks the document as a deliverable meanwhile.
    const newer = {
      ...start,
      draft_revision: start.draft_revision + 1,
      steps: start.steps.map((step) =>
        step.id === "step-1"
          ? { ...step, output_config: { deliverable: { label: "Till ledningen" } } }
          : step
      )
    };
    storeEdits(newer);
    const { rerender } = renderEditor(start);
    fireEvent.click(await deliverySwitch());
    await labelField();
    fireEvent.click(await deliverySwitch());
    await waitFor(() =>
      expect(
        screen.queryByRole("textbox", {
          name: new RegExp(`^${messages.flow_step_editor_deliverable_label}`)
        })
      ).toBeNull()
    );
    rerender(
      <FlowStepEditor
        flow={newer}
        stepId="step-1"
        readOnly={false}
        onSaved={() => {}}
        onCancel={() => {}}
      />
    );

    expect((await labelField()).value).toBe("Till ledningen");
    fireEvent.change(await nameField(), { target: { value: "Standup för alla" } });
    await saveStep();
    expect(
      (patchBodies()[0] as { step_edits: { changes: Record<string, unknown> }[] }).step_edits[0]!
        .changes
    ).toEqual({ user_description: "Standup för alla" });
  }, 20_000);

  it("names the result after a long step name cut to the bound, so the step can be saved", async () => {
    const long = `${"Möte ".repeat(24)}och mer`;
    const flow = deliveryFlow();
    const current = storeEdits({
      ...flow,
      steps: flow.steps.map((step) =>
        step.id === "step-1" ? { ...step, user_description: long } : step
      )
    });
    renderEditor(current());
    fireEvent.click(await deliverySwitch());
    const label = await labelField();
    expect(Array.from(label.value)).toHaveLength(119);
    expect(label.value).toBe("Möte ".repeat(24).trimEnd());
    await saveStep();
    expect(current().steps[0]!.output_config).toEqual({
      deliverable: { label: "Möte ".repeat(24).trimEnd() }
    });
  }, 20_000);

  it("makes the label and file name one line when the field is left and when the step is saved", async () => {
    const current = storeEdits(deliveryFlow());
    renderEditor(current());
    fireEvent.click(await deliverySwitch());
    const label = await labelField();
    fireEvent.change(label, { target: { value: " Till  Eneo\n" } });
    fireEvent.blur(label);
    expect(label.value).toBe("Till Eneo");
    fireEvent.change(fileNameField(), { target: { value: "Standup\t{{flow_input.team}} " } });
    await saveStep();
    expect(current().steps[0]!.output_config).toEqual({
      deliverable: { label: "Till Eneo", file_name: "Standup {{flow_input.team}}" }
    });
  }, 20_000);

  it("counts the label and file name in characters, and refuses a label of only spaces", async () => {
    renderEditor(deliveryFlow());
    fireEvent.click(await deliverySwitch());
    const label = await labelField();
    fireEvent.change(label, { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    expect(
      await screen.findByText(messages.flow_step_editor_deliverable_label_required)
    ).toBeTruthy();

    // An emoji is one character, as the core counts it, though it is two UTF-16 units.
    fireEvent.change(label, { target: { value: `${"a".repeat(120)}😀` } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    expect(
      await screen.findByText(
        messages.flow_step_editor_deliverable_label_too_long.replace("{max}", "120")
      )
    ).toBeTruthy();
    fireEvent.change(label, { target: { value: `${"a".repeat(119)}😀` } });
    fireEvent.change(fileNameField(), { target: { value: `${"b".repeat(199)}😀` } });
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    await saveStep();
    expect(patchBodies()[0]).toMatchObject({
      step_edits: [
        {
          changes: {
            output_config: {
              deliverable: { label: `${"a".repeat(119)}😀`, file_name: `${"b".repeat(199)}😀` }
            }
          }
        }
      ]
    });
  }, 20_000);

  it("does not check a stale deliverable on a step that cannot be delivered", async () => {
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    renderEditor(
      makeFlow({
        steps: [makeStep({ output_type: "json", output_config: { deliverable: { label: "" } } })]
      })
    );
    fireEvent.change(await nameField(), { target: { value: "Sammanfatta mötet" } });
    await saveStep();
    expect(patchBodies()).toHaveLength(1);
  }, 20_000);

  it("keeps a marked document's name when it is turned to text, and drops its file name", async () => {
    const flow = deliveryFlow();
    const current = storeEdits({
      ...flow,
      steps: flow.steps.map((step) =>
        step.id === "step-1"
          ? {
              ...step,
              output_config: {
                deliverable: { label: "Till Eneo", file_name: "Standup" },
                future: 1
              }
            }
          : step
      )
    });
    renderEditor(current());
    expect((await labelField()).value).toBe("Till Eneo");
    // An AI step's result is text.
    fireEvent.click(
      screen.getByRole("combobox", { name: new RegExp(`^${messages.flow_step_output_mode}`) })
    );
    fireEvent.click(
      within(
        await screen.findByRole("listbox", {
          name: new RegExp(`^${messages.flow_step_output_mode}`)
        })
      ).getByRole("option", { name: messages.flow_output_mode_pass_through })
    );
    await saveStep();
    const changes = (patchBodies()[0] as { step_edits: { changes: Record<string, unknown> }[] })
      .step_edits[0]!.changes;
    expect(changes).toMatchObject({ output_type: "text" });
    expect(changes.output_config).toEqual({ deliverable: { label: "Till Eneo" }, future: 1 });
  }, 20_000);

  /** A marked document, then a step that sends its call last. */
  function resultFlow(
    http: Record<string, unknown>,
    deliverable: unknown = { label: "Till webbplatsen" }
  ) {
    return makeFlow({
      steps: [
        makeStep({
          user_description: "Protokoll",
          output_mode: "render_verbatim",
          output_type: "docx",
          output_config: deliverable ? { deliverable } : null
        }),
        makeStep({
          id: "step-2",
          step_order: 2,
          user_description: "Skicka till webbplatsen",
          input_source: "previous_step",
          output_mode: "http_post",
          output_config: {
            url: "https://receiver.example.org/eneo/results",
            auth: { mode: "none" },
            timeout_seconds: 30,
            body: { mode: "auto" },
            custom_headers: [],
            response_format: null,
            ...http
          }
        })
      ]
    });
  }

  const bodyChoice = () =>
    screen.findByRole("combobox", { name: new RegExp(`^${messages.flow_step_editor_http_body}`) });

  it("offers a plain POST no body that sends the run's result, and the step that sends it keeps its body", async () => {
    let view = renderEditor(resultFlow({ body: { mode: "auto" } }), { stepId: "step-2" });
    fireEvent.click(await bodyChoice());
    const options = within(
      await screen.findByRole("listbox", {
        name: new RegExp(`^${messages.flow_step_editor_http_body}`)
      })
    ).getAllByRole("option");
    expect(options.map((option) => option.textContent)).not.toContain(
      messages.flow_step_editor_http_body_run_result
    );
    view.unmount();

    const current = storeEdits(resultFlow({ body: { mode: "run_result" } }));
    view = renderEditor(current(), { stepId: "step-2" });
    fireEvent.change(await nameField(), { target: { value: "Skicka till intranätet" } });
    await saveStep();
    // Only the name changes: nothing in the editor turns the step into a plain POST.
    const changes = (patchBodies()[0] as { step_edits: { changes: Record<string, unknown> }[] })
      .step_edits[0]!.changes;
    expect(changes).toMatchObject({ user_description: "Skicka till intranätet" });
    expect(changes).not.toHaveProperty("output_config");
  }, 30_000);

  it("lists the step before the send by its name when nothing is marked", async () => {
    renderEditor(resultFlow({ body: { mode: "run_result" } }, null), { stepId: "step-2" });
    const sends = await screen.findByRole("region", {
      name: messages.flow_step_editor_run_result_sends_title
    });
    expect(within(sends).getByText("Protokoll")).toBeTruthy();
    expect(within(sends).getByText("Steg 1 · Word-dokument")).toBeTruthy();
  }, 20_000);

  it("opens a step it sends from the row, with a short button whose name starts the same", async () => {
    const onGo = vi.fn();
    renderEditor(resultFlow({ body: { mode: "run_result" } }), {
      stepId: "step-2",
      navigation: { position: 2, count: 2, previous: null, next: null, steps: [], onGo }
    });
    const sends = await screen.findByRole("region", {
      name: messages.flow_step_editor_run_result_sends_title
    });
    const row = within(sends).getByRole("listitem");
    expect(within(row).getByText("Till webbplatsen")).toBeTruthy();
    expect(within(row).getByText("Steg 1 · Word-dokument")).toBeTruthy();
    // The visible word begins the name a voice user says (WCAG 2.5.3).
    const open = within(row).getByRole("button", { name: "Öppna steg 1 – Protokoll" });
    expect(open.textContent).toBe("Öppna");
    // No tooltip to cover the row above it.
    expect(
      screen
        .queryAllByRole("tooltip", { hidden: true })
        .filter((tooltip) => tooltip.textContent?.includes("Protokoll"))
    ).toEqual([]);
    fireEvent.click(open);
    expect(onGo).toHaveBeenCalledWith("step-1");
  }, 20_000);

  /** Text, then JSON (or only JSON), then the step that sends: nothing is sent. */
  function nothingFlow(withText: boolean) {
    const sender = (order: number) =>
      makeStep({
        id: "step-send",
        step_order: order,
        user_description: "Skicka",
        input_source: "previous_step",
        output_mode: "http_post",
        output_config: {
          url: "https://receiver.example.org/eneo",
          auth: { mode: "none" },
          body: { mode: "run_result" }
        }
      });
    const json = (order: number) =>
      makeStep({
        id: "step-json",
        step_order: order,
        user_description: "Plocka ut",
        input_source: order === 1 ? "flow_input" : "previous_step",
        output_type: "json"
      });
    return makeFlow({
      steps: withText
        ? [makeStep({ user_description: "Sammanfatta" }), json(2), sender(3)]
        : [json(1), sender(2)]
    });
  }

  const navigationTo = (onGo: (id: string) => void): StepNavigation => ({
    position: 3,
    count: 3,
    previous: null,
    next: null,
    steps: [],
    onGo
  });

  it("says nothing is sent yet, without a warning, and opens a step that can be included", async () => {
    const onGo = vi.fn();
    const view = renderEditor(nothingFlow(true), {
      stepId: "step-send",
      navigation: navigationTo(onGo)
    });
    expect(await screen.findByText(messages.flow_step_editor_run_result_empty_title)).toBeTruthy();
    expect(screen.getByText(messages.flow_step_editor_run_result_empty_candidates)).toBeTruthy();
    // No warning while the author is still building: the draft check names it before publishing.
    expect(screen.queryByText(messages.flow_error_flow_run_result_no_deliverables)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Öppna steg 1 – Sammanfatta" }));
    expect(onGo).toHaveBeenCalledWith("step-1");
    await expectNoAxeViolations(view.container);
  }, 20_000);

  it("offers to add a step before the send when no step before it can be included", async () => {
    renderEditor(nothingFlow(false), { stepId: "step-send", onStepAdded: vi.fn() });
    expect(await screen.findByText(messages.flow_step_editor_run_result_empty_none)).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_step_editor_run_result_add_before })
    );
    const dialog = await screen.findByRole("dialog", { name: messages.flow_step_editor_add_title });
    expect(
      within(dialog).getByText("Hamnar efter Steg 1: Plocka ut, före Steg 2: Skicka")
    ).toBeTruthy();
  }, 20_000);

  it("names the steps that could be included too, under what is sent", async () => {
    const onGo = vi.fn();
    const flow = resultFlow({ body: { mode: "run_result" } }, null);
    renderEditor(
      {
        ...flow,
        steps: [
          makeStep({ id: "step-0", step_order: 0, user_description: "Anteckningar" }),
          ...flow.steps
        ]
      },
      { stepId: "step-2", navigation: navigationTo(onGo) }
    );
    expect(await screen.findByText(messages.flow_step_editor_run_result_more_title)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Öppna steg 0 – Anteckningar" }));
    expect(onGo).toHaveBeenCalledWith("step-0");
  }, 20_000);

  it("holds the run's result to a fixed https address and its own Content-Type before saving", async () => {
    let view = renderEditor(
      resultFlow({
        url: "https://receiver.example.org/{{flow_input.team}}",
        body: { mode: "run_result" }
      }),
      { stepId: "step-2" }
    );
    fireEvent.change(await nameField(), { target: { value: "Skicka resultatet" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    // What is wrong first: the scheme, then the variables.
    expect(
      await screen.findByText(
        "Adressen ska börja med https:// och får inte innehålla variabler. Körningens data får inte välja vart resultatet skickas."
      )
    ).toBeTruthy();
    const address = screen.getByRole("textbox", {
      name: new RegExp(`^${messages.flow_step_editor_http_url_run_result}`)
    }) as HTMLInputElement;
    expect(document.activeElement).toBe(address);
    // A phone shows the keyboard for addresses; the form checks the address itself.
    expect(address.type).toBe("url");
    view.unmount();

    view = renderEditor(
      resultFlow({
        body: { mode: "run_result" },
        custom_headers: [{ name: "content-type", value: "text/plain", secret: false }]
      }),
      { stepId: "step-2" }
    );
    fireEvent.change(await nameField(), { target: { value: "Skicka resultatet" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    expect(
      await screen.findByText(messages.flow_step_editor_http_run_result_content_type)
    ).toBeTruthy();
    expect(patchBodies()).toHaveLength(0);
  }, 20_000);

  it("names the sender's own address rule, not the general one, for an address that is not valid", async () => {
    renderEditor(
      resultFlow({
        url: "https://anna:hemligt@receiver.example.org/eneo/results",
        body: { mode: "run_result" }
      }),
      { stepId: "step-2" }
    );
    fireEvent.change(await nameField(), { target: { value: "Skicka resultatet" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    expect(
      await screen.findByText(messages.flow_step_editor_http_run_result_url_fixed)
    ).toBeTruthy();
    expect(screen.queryByText(messages.flow_step_editor_http_url_invalid)).toBeNull();
    expect(patchBodies()).toHaveLength(0);
  }, 20_000);

  it("puts the core's refusal of a host at the address, without the https rule", async () => {
    // What the core answers a save of the step that sends the run's result whose
    // host it refuses (`https://a..b.example/in`, `draft_step_refusals`): no `http_error`.
    api.routes[EDITOR] = () => ({
      status: 400,
      body: {
        message:
          "Step 2: output_config.url is not an absolute http or https URL without userinfo (HTTP_INVALID_URL).",
        code: "typed_io_http_invalid_config",
        context: { field: "output_config.url", issue_code: "flow_step_invalid", step_order: 2 },
        eneo_error_code: 9000
      }
    });
    renderEditor(resultFlow({ url: "https://a..b.example/in", body: { mode: "run_result" } }), {
      stepId: "step-2"
    });
    fireEvent.change(await nameField(), { target: { value: "Skicka resultatet" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("textbox", {
          name: new RegExp(`^${messages.flow_step_editor_http_url_run_result}`)
        })
      )
    );
    expect(
      screen.getAllByText(messages.flow_validation_msg_flow_step_invalid).length
    ).toBeGreaterThan(0);
    expect(screen.queryByText(messages.flow_step_editor_http_run_result_url_fixed)).toBeNull();
  }, 20_000);

  it.each([
    {
      field: "output_config.url",
      httpError: "HTTP_RUN_RESULT_REQUIRES_FIXED_HTTPS_URL",
      message: messages.flow_step_editor_http_run_result_url_fixed,
      focused: () =>
        screen.getByRole("textbox", {
          name: new RegExp(`^${messages.flow_step_editor_http_url_run_result}`)
        })
    },
    {
      field: "output_config.custom_headers[0]",
      httpError: "HTTP_CONTENT_TYPE_SET_BY_BODY",
      message: messages.flow_step_editor_http_run_result_content_type,
      // The headers' fold opens with focus on its button, as for a refused header name.
      focused: () =>
        screen.getByRole("button", {
          name: new RegExp(messages.flow_step_editor_http_more_title)
        })
    }
  ])(
    "puts the core's refusal of a body that sends the run's result at its field ($field)",
    async ({ field, httpError, message, focused }) => {
      // The context the core raises (`flow_validators_http.py`, `test_validator.py`).
      api.routes[EDITOR] = () => ({
        status: 400,
        body: {
          message: "Step 2: output_config validation failed",
          code: "typed_io_http_invalid_config",
          context: { field, http_error: httpError },
          eneo_error_code: 9000
        }
      });
      renderEditor(
        resultFlow({
          body: { mode: "run_result" },
          custom_headers: [{ name: "X-Trace", value: "1", secret: false }]
        }),
        { stepId: "step-2" }
      );
      fireEvent.change(await nameField(), { target: { value: "Skicka resultatet" } });
      fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
      await waitFor(() => expect(document.activeElement).toBe(focused()));
      expect(screen.getAllByText(message).length).toBeGreaterThan(0);
    },
    20_000
  );

  it("shows a deliverable's label and file name when the step is read only", async () => {
    renderEditor(
      makeFlow({
        steps: [
          makeStep({
            output_mode: "render_verbatim",
            output_type: "docx",
            output_config: {
              deliverable: { label: "Till webbplatsen", file_name: "Standup {{flow_input.team}}" }
            }
          })
        ]
      }),
      { readOnly: true }
    );
    expect((await rowValue(messages.flow_step_editor_deliverable_label)).textContent).toBe(
      "Till webbplatsen"
    );
    expect((await rowValue(messages.flow_step_editor_deliverable_file_name)).textContent).toBe(
      "Standup {{flow_input.team}}"
    );
  });
});

describe("FlowStepEditor Leverans", () => {
  const RECEIVER = "https://mottagare.example.org/in";

  /** Each step's assistant answered by its id, with the prompt given for it (else a plain one). */
  function routeAssistants(prompts: Record<string, string> = {}) {
    api.routes[ASSISTANT] = (init) => {
      const id = (init as { params: { path: { assistant_id: string } } }).params.path.assistant_id;
      const assistant = makeAssistant();
      return {
        body: makeAssistant({
          id,
          prompt: { ...assistant.prompt!, text: prompts[id] ?? "Gör ditt jobb." }
        })
      };
    };
  }

  const sender = (order: number, url = RECEIVER) =>
    makeStep({
      id: `step-${order}`,
      step_order: order,
      assistant_id: `assistant-${order}`,
      user_description: "Skicka",
      input_source: "previous_step",
      output_mode: "http_post",
      output_config: { url, auth: { mode: "none" }, body: { mode: "run_result" } }
    });
  const text = (order: number, name: string, overrides: Parameters<typeof makeStep>[0] = {}) =>
    makeStep({
      id: `step-${order}`,
      step_order: order,
      assistant_id: `assistant-${order}`,
      user_description: name,
      input_source: order === 1 ? "flow_input" : "previous_step",
      ...overrides
    });
  const word = (order: number, name: string) =>
    text(order, name, { output_mode: "render_verbatim", output_type: "docx" });

  const section = () =>
    screen.findByRole("region", { name: messages.flow_step_editor_delivery_title });

  it("names the next step that reads the result", async () => {
    routeAssistants();
    renderEditor(makeFlow({ steps: [text(1, "Sammanfatta"), text(2, "Skriv svar")] }));
    expect(
      await within(await section()).findByText("Går vidare till nästa steg: Steg 2: Skriv svar.")
    ).toBeTruthy();
  }, 20_000);

  it("says nothing about readers when only a later prompt names the step, by alias or by name", async () => {
    for (const prompt of ["Jämför med {{step_1}}.", "Jämför med {{Sammanfatta}}."]) {
      routeAssistants({ "assistant-3": prompt });
      const flow = makeFlow({
        steps: [
          text(1, "Sammanfatta"),
          text(2, "Granska", { input_source: "flow_input" }),
          text(3, "Skriv svar", { input_source: "flow_input" })
        ]
      });
      const view = renderEditor(flow);
      // The prompt is at hand, as the step list would have read it.
      view.queryClient.setQueryData(
        flowEditorKeys.assistant(flow.id, "assistant-3"),
        makeAssistant({ id: "assistant-3", prompt: { ...makeAssistant().prompt!, text: prompt } })
      );
      const delivery = await section();
      await within(delivery).findByRole("switch", {
        name: new RegExp(`^${messages.flow_step_editor_deliverable_switch}`)
      });
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(within(delivery).queryByText(/^Läses av /)).toBeNull();
      expect(within(delivery).queryByText(/^Går vidare till nästa steg/)).toBeNull();
      expect(within(delivery).queryByText(/^Läses inte av senare steg/)).toBeNull();
      view.unmount();
    }
  }, 20_000);

  it("names a Word step only as a reader of the steps its fields name", async () => {
    routeAssistants();
    const flow = makeFlow({
      steps: [
        text(1, "Sammanfatta"),
        text(2, "Granska"),
        text(3, "Mall", {
          output_mode: "template_fill",
          output_type: "docx",
          output_config: {
            placeholders: ["sammanfattning"],
            bindings: { sammanfattning: "{{step_1.output.text}}" }
          }
        })
      ]
    });
    renderEditor(flow);
    expect(await within(await section()).findByText(/Steg 3: Mall/)).toBeTruthy();
    cleanup();

    // The core never reads a Word step's input: the step before it is not read.
    renderEditor(flow, { stepId: "step-2" });
    const delivery = await section();
    expect(within(delivery).queryByText(/^Läses av /)).toBeNull();
    expect(within(delivery).queryByText(/^Går vidare till nästa steg/)).toBeNull();
  }, 20_000);

  it("names a tool step with bindings that sends the result to its tool in an argument", async () => {
    routeAssistants();
    renderEditor(
      makeFlow({
        steps: [
          text(1, "Sammanfatta"),
          text(2, "Granska", { input_source: "flow_input" }),
          text(3, "Slå upp", {
            input_source: "tool",
            input_bindings: { question: "{{Granska}}" },
            input_config: { tool: { arguments: { fråga: "{{step_1.output.text}}" } } }
          })
        ]
      })
    );
    expect(await within(await section()).findByText("Läses av Steg 3: Slå upp.")).toBeTruthy();
  }, 20_000);

  it("says whether a result no saved field reads is included, by its switch and on the line about the receiver", async () => {
    routeAssistants();
    renderEditor(
      makeFlow({
        steps: [
          text(1, "Sammanfatta"),
          text(2, "Granska", { input_source: "flow_input" }),
          sender(3)
        ]
      })
    );
    const delivery = await section();
    const toggle = within(delivery).getByRole("switch", {
      name: new RegExp(`^${messages.flow_step_editor_deliverable_switch}`)
    }) as HTMLInputElement;
    const noReaderLine = () => {
      expect(within(delivery).queryByText(/^Läses av /)).toBeNull();
      expect(within(delivery).queryByText(/^Går vidare till nästa steg/)).toBeNull();
    };
    expect(toggle.checked).toBe(false);
    expect(
      await within(delivery).findByText(
        "Ingår inte i körningens resultat som skickas till mottagare.example.org. Slå på Ta med i körningens resultat ovan om det ska följa med."
      )
    ).toBeTruthy();
    // How to send it is said once, on the line about the receiver.
    expect(within(delivery).getAllByText(/Slå på Ta med i körningens resultat/)).toHaveLength(1);
    noReaderLine();
    fireEvent.click(toggle);
    expect(toggle.checked).toBe(true);
    expect(
      within(delivery).getByText("Skickas till mottagare.example.org när körningen är klar.")
    ).toBeTruthy();
    noReaderLine();
  }, 20_000);

  it("names the step that sends the run's result as a reader when one of its headers names the step", async () => {
    routeAssistants();
    const inHeader =
      "Skickas till mottagare.example.org i en header i steget som skickar körningens resultat.";
    const reading = (order: number, value = "{{Sammanfatta}}") =>
      makeStep({
        ...sender(order),
        output_config: {
          url: RECEIVER,
          auth: { mode: "none" },
          body: { mode: "run_result" },
          custom_headers: [{ name: "X-Fall", value, secret: false }]
        }
      });
    const view = renderEditor(
      makeFlow({
        steps: [
          text(1, "Sammanfatta"),
          text(2, "Granska", { input_source: "flow_input" }),
          reading(3)
        ]
      }),
      {
        navigation: { position: 1, count: 3, previous: null, next: null, steps: [], onGo: vi.fn() }
      }
    );
    let delivery = await section();
    expect(await within(delivery).findByText("Läses av Steg 3: Skicka.")).toBeTruthy();
    // What it sends is said apart from what it reads.
    expect(
      within(delivery).getByText(
        "Ingår inte i körningens resultat som skickas till mottagare.example.org. Slå på Ta med i körningens resultat ovan om det ska följa med."
      )
    ).toBeTruthy();
    // Its text still goes to the receiver, in the header: said right under the
    // line about the result, before the button that opens the step that sends.
    const headerLine = within(delivery).getByText(inHeader);
    const follows = (a: Node, b: Node) =>
      (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    expect(
      follows(
        within(delivery).getByText(/^Ingår inte i körningens resultat som skickas till/),
        headerLine
      )
    ).toBe(true);
    expect(
      follows(
        headerLine,
        within(delivery).getByRole("button", {
          name: messages.flow_step_editor_delivery_open_sender
        })
      )
    ).toBe(true);
    view.unmount();

    // A header that names another step sends nothing of this one.
    const other = renderEditor(
      makeFlow({
        steps: [
          text(1, "Sammanfatta"),
          text(2, "Granska", { input_source: "flow_input" }),
          reading(3, "{{Granska}}")
        ]
      })
    );
    delivery = await section();
    expect(
      await within(delivery).findByText(
        "Ingår inte i körningens resultat som skickas till mottagare.example.org. Slå på Ta med i körningens resultat ovan om det ska följa med."
      )
    ).toBeTruthy();
    expect(within(delivery).queryByText(inHeader)).toBeNull();
    other.unmount();

    // The last working step: the step that sends is its only later step, and reads it.
    renderEditor(makeFlow({ steps: [text(1, "Sammanfatta"), reading(2)] }));
    delivery = await section();
    expect(
      await within(delivery).findByText("Går vidare till nästa steg: Steg 2: Skicka.")
    ).toBeTruthy();
    expect(
      within(delivery).getByText("Skickas till mottagare.example.org när körningen är klar.")
    ).toBeTruthy();
    // Part of the result, it is said once: no header line beside it.
    expect(within(delivery).queryByText(inHeader)).toBeNull();
  }, 20_000);

  it("names a later step that reads the result through a saved binding, also while the step is renamed unsaved", async () => {
    routeAssistants();
    renderEditor(
      makeFlow({
        steps: [
          text(1, "Sammanfatta"),
          text(2, "Granska", { input_source: "flow_input" }),
          text(3, "Skriv svar", { input_bindings: { question: "{{Sammanfatta}}" } })
        ]
      })
    );
    const delivery = await section();
    await within(delivery).findByText("Läses av Steg 3: Skriv svar.");
    fireEvent.change(await nameField(), { target: { value: "Kort sammanfattning" } });
    expect(within(delivery).getByText("Läses av Steg 3: Skriv svar.")).toBeTruthy();
  }, 20_000);

  it("says nothing about readers on the last working step, which is included by its place", async () => {
    routeAssistants();
    renderEditor(makeFlow({ steps: [text(1, "Sammanfatta"), sender(2)] }));
    const delivery = await section();
    // Only the step that sends comes after it, and that step reads no result.
    expect(
      await within(delivery).findByText("Skickas till mottagare.example.org när körningen är klar.")
    ).toBeTruthy();
    expect(within(delivery).queryByText(/^Läses /)).toBeNull();
  }, 20_000);

  it("says no step sends the run's result in a flow without one", async () => {
    routeAssistants();
    renderEditor(makeFlow({ steps: [text(1, "Sammanfatta")] }));
    const delivery = await section();
    expect(
      await within(delivery).findByText(messages.flow_step_editor_delivery_no_sender)
    ).toBeTruthy();
    expect(
      within(delivery).queryByRole("button", {
        name: messages.flow_step_editor_delivery_open_sender
      })
    ).toBeNull();
  }, 20_000);

  it("says where a document is sent, at once as its switch turns, and opens the step that sends", async () => {
    routeAssistants();
    const onGo = vi.fn();
    renderEditor(makeFlow({ steps: [word(1, "Protokoll"), word(2, "Bilaga"), sender(3)] }), {
      navigation: { position: 1, count: 3, previous: null, next: null, steps: [], onGo }
    });
    const delivery = await section();
    expect(
      await within(delivery).findByText(
        "Ingår inte i körningens resultat som skickas till mottagare.example.org. Slå på Ta med i körningens resultat ovan om det ska följa med."
      )
    ).toBeTruthy();
    const saveFirst = "Spara först för att se ändringen i utskicket.";
    expect(within(delivery).queryByText(saveFirst)).toBeNull();
    fireEvent.click(
      within(delivery).getByRole("switch", {
        name: new RegExp(`^${messages.flow_step_editor_deliverable_switch}`)
      })
    );
    expect(
      within(delivery).getByText("Skickas till mottagare.example.org när körningen är klar.")
    ).toBeTruthy();
    // The step that sends shows the saved flow: an unsaved change is not there yet.
    expect(within(delivery).getByText(saveFirst)).toBeTruthy();
    fireEvent.click(
      within(delivery).getByRole("button", { name: messages.flow_step_editor_delivery_open_sender })
    );
    expect(onGo).toHaveBeenCalledWith("step-3");
  }, 20_000);

  it("says nothing is sent while the step that sends has no address", async () => {
    routeAssistants();
    renderEditor(makeFlow({ steps: [text(1, "Sammanfatta"), sender(2, "")] }));
    expect(
      await within(await section()).findByText(messages.flow_step_editor_delivery_no_address)
    ).toBeTruthy();
  }, 20_000);

  it("gives a JSON step one line instead of the section, and a request it sends neither", async () => {
    routeAssistants();
    let view = renderEditor(
      makeFlow({ steps: [text(1, "Plocka ut", { output_type: "json" }), text(2, "Skriv")] })
    );
    expect(await screen.findByText(messages.flow_step_editor_delivery_json)).toBeTruthy();
    expect(
      screen.queryByRole("heading", { level: 3, name: messages.flow_step_editor_delivery_title })
    ).toBeNull();
    view.unmount();

    for (const output_type of ["text", "json"] as const) {
      view = renderEditor(
        makeFlow({
          steps: [
            text(1, "Anropa", {
              output_type,
              output_mode: "http_post",
              output_config: { url: RECEIVER, auth: { mode: "none" }, body: { mode: "auto" } }
            })
          ]
        })
      );
      await nameField();
      expect(screen.queryByText(messages.flow_step_editor_delivery_json)).toBeNull();
      expect(
        screen.queryByRole("heading", { level: 3, name: messages.flow_step_editor_delivery_title })
      ).toBeNull();
      view.unmount();
    }
  }, 30_000);
});
