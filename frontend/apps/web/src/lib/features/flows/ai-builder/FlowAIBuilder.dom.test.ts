import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";

// The composer reads app-shell contexts (upload limits, API client) that only
// the real layout provides; stub the minimum it touches.
vi.mock("$lib/core/AppContext", () => ({
  getAppContext: () => ({
    limits: {
      attachments: {
        formats: [],
        ai_builder_max_count: 37,
        ai_builder_max_message_chars: 5000
      }
    }
  })
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({ files: { delete: vi.fn().mockResolvedValue(undefined) } })
}));

import FlowAIBuilderHarness from "./test-harnesses/FlowAIBuilderHarness.svelte";
import type { AIBuilderClientTransport } from "./FlowAIBuilderDriver";
import type { FlowAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
import type { AIBuilderSavedFlowStepScope, RequirementsSummary } from "./protocol";
import type { StructuredQuestion } from "./structuredQuestionAnswer";

// ---- Routes and fixtures ----------------------------------------------------

const SESSIONS_ROUTE = "/api/v1/flows/ai-builder/sessions";
// A published version with one run and nothing to point at: enough for the
// findings screen to own the phase.
const REVIEW_PACKET = {
  flow_id: "flow-1",
  flow_version: 2,
  definition_checksum: "sum-2",
  generated_at: "2026-09-04T12:00:00Z",
  evidence_classification_level: 0,
  steps: [{ step_id: "11111111-1111-4111-8111-111111111111", step_order: 1, label: "Steg" }],
  cohort: {
    completed_run_ids: ["r1"],
    failed_run_ids: [],
    omitted: { other_version: 0, not_viewable: 0, level_unknown: 0, overflow: 0 }
  },
  facts: [
    {
      kind: "evidence_completeness",
      finding_id: "cccccccccccccccc",
      runs_with_all_step_results: 1,
      runs_missing_step_results: 0,
      runs_without_lineage: 0
    }
  ]
};
const SESSION_ROUTE = "/api/v1/flows/ai-builder/sessions/{session_id}";
const PLAN_ROUTE = "/api/v1/flows/ai-builder/plans/{plan_id}";

const DEFAULT_MODEL_ID = "11111111-1111-4111-8111-111111111199";
const DEFAULT_MODEL_RESPONSE = {
  models: [
    { id: DEFAULT_MODEL_ID, name: "Test model", provider: "openai", reasoning_effort_options: [] }
  ],
  default_model_id: DEFAULT_MODEL_ID
};

// The stream schema requires a 64-hex requirements version.
const REQUIREMENTS_VERSION = "0123456789abcdef".repeat(4);
const PLAN_ID = "22222222-2222-4222-8222-222222222201";
const TURN_ID = "11111111-1111-4111-8111-111111111111";

interface FakeSession {
  session_id: string;
  space_id: string;
  status: "chatting" | "awaiting_approval";
  target_kind: "create" | "edit";
  flow_id: string | null;
  latest_plan_id: string | null;
  draft_title: string;
  created_at: string;
  updated_at: string;
  conversation: Record<string, unknown>[];
  latest_turn: Record<string, unknown> | null;
}

function makeSession(overrides: Partial<FakeSession> = {}): FakeSession {
  return {
    session_id: "s-1",
    space_id: "space-1",
    status: "chatting",
    target_kind: "create",
    flow_id: null,
    latest_plan_id: null,
    draft_title: "Utkast",
    created_at: "2026-07-11T09:00:00Z",
    updated_at: "2026-07-11T09:05:00Z",
    conversation: [],
    latest_turn: null,
    ...overrides
  };
}

function userMessage(id: string, content: string, extra: Record<string, unknown> = {}) {
  return { message_id: id, role: "user", content, timestamp: "2026-07-11T09:00:00Z", ...extra };
}

function assistantMessage(id: string, content: string, extra: Record<string, unknown> = {}) {
  return {
    message_id: id,
    role: "assistant",
    content,
    timestamp: "2026-07-11T09:00:05Z",
    ...extra
  };
}

function question(
  id: string,
  text: string,
  options: { id: string; label: string }[],
  overrides: Partial<StructuredQuestion> = {}
): StructuredQuestion {
  return {
    question_id: id,
    question: text,
    options,
    selection_mode: "single",
    allow_custom: false,
    ...overrides
  };
}

const FORMAT_QUESTION = question(
  "output_format",
  "Hur ska resultatet levereras?",
  [
    { id: "pdf", label: "Som PDF" },
    { id: "text", label: "Som text" }
  ],
  { question_index: 1, topic: "Slutresultat" }
);
const SOURCES_QUESTION = question(
  "sources",
  "Vilka källor ska ingå?",
  [
    { id: "docs", label: "Uppladdade dokument" },
    { id: "web", label: "Webbsidor" },
    { id: "mail", label: "E-post" }
  ],
  { selection_mode: "multi", question_index: 2 }
);
const CUSTOM_QUESTION = question(
  "audience",
  "Vem ska läsa resultatet?",
  [{ id: "managers", label: "Chefer" }],
  { allow_custom: true }
);

const SUMMARY: RequirementsSummary = {
  requirements_version: REQUIREMENTS_VERSION,
  summary: "Skapa ett beslutsunderlag som PDF.",
  key_decisions: [{ topic: "Slutresultat", decision: "PDF-dokument" }],
  input_description: "Text vid körning",
  output_description: "PDF med rekommendation",
  assumptions: [],
  manual_setup_notes: []
};

const PLAN_STREAM_PAYLOAD = {
  plan_id: PLAN_ID,
  proposal: {
    spec: {
      flow_name: "Sammanfatta till PDF",
      flow_description: "Tar emot text och levererar en PDF.",
      steps: [
        {
          plan_step_ref: "step_1",
          existing_step_ref: null,
          name: "Sammanfatta underlaget",
          assistant_spec: { instructions: "Sammanfatta.", model_ref: null, knowledge_refs: [] },
          input_source: "flow_input",
          input_type: "text",
          output_mode: "compose_text",
          output_type: "text",
          input_bindings: null,
          input_contract: null,
          output_contract: null,
          input_config: null,
          output_config: null,
          review_policy: null
        }
      ],
      form_fields: null
    },
    assumptions: [],
    lint_warnings: [],
    plan_rationale: null,
    description_override_manual: false,
    edit: null,
    execution_shape: {
      completion_model_step_count: 1,
      transcription_model_step_count: 0,
      deterministic_step_count: 0,
      schema_constrained_step_count: 0,
      mapped_step_upper_bounds: []
    }
  }
};
const PLAN_RESPONSE = { ...PLAN_STREAM_PAYLOAD, status: "proposed" };

/** A pending first question after the user's task. */
function questionSession(pending: StructuredQuestion = FORMAT_QUESTION): FakeSession {
  return makeSession({
    conversation: [
      userMessage("u1", "Sammanfatta rapporter till en PDF"),
      assistantMessage("a1", "Jag behöver veta formatet.", { question: pending })
    ]
  });
}

/** Question one answered "Som PDF", question two pending. */
function answeredThenPendingSession(): FakeSession {
  return makeSession({
    conversation: [
      userMessage("u1", "Sammanfatta rapporter till en PDF"),
      assistantMessage("a1", "Jag behöver veta formatet.", { question: FORMAT_QUESTION }),
      userMessage("u2", "Som PDF", {
        question_answer: {
          kind: "structured_question_answer",
          question_id: "output_format",
          selected_option_ids: ["pdf"]
        }
      }),
      assistantMessage("a2", "Och källorna?", { question: SOURCES_QUESTION })
    ]
  });
}

/** Confirmed requirements with a proposed plan: resuming lands in review. */
function planSession(): FakeSession {
  return makeSession({
    status: "awaiting_approval",
    latest_plan_id: PLAN_ID,
    conversation: [
      userMessage("u1", "Sammanfatta rapporter till en PDF"),
      assistantMessage("a1", "Här är min tolkning.", { requirements_summary: SUMMARY }),
      userMessage("u2", "", {
        requirements_confirmation: {
          requirements_confirmed: true,
          requirements_version: REQUIREMENTS_VERSION
        }
      })
    ]
  });
}

function turnSession(state: "processing" | "failed_before_provider" | "provider_outcome_unknown") {
  const base = makeSession({
    session_id: "s-turn",
    conversation: [userMessage("u1", "Build a flow")]
  });
  const latest_turn = {
    client_turn_id: TURN_ID,
    state,
    user_message_id: "11111111-1111-4111-8111-111111111112",
    error: null,
    requires_duplicate_provider_spend_acknowledgement: state === "provider_outcome_unknown",
    retry_request: {
      client_turn_id: TURN_ID,
      message: "Build a flow",
      ui_language: "sv",
      acknowledge_duplicate_provider_spend: false
    }
  };
  // The first read carries the recovery state; later reads report it committed.
  return [
    { ...base, latest_turn },
    { ...base, latest_turn: { ...latest_turn, state: "committed" } }
  ];
}

// ---- Transport doubles --------------------------------------------------------

interface FetchOptions {
  /** Sessions addressable by GET; an array is read in order, the last repeated. */
  sessions?: (FakeSession | FakeSession[])[];
  /** What POST /sessions returns. */
  created?: FakeSession;
  plans?: Record<string, unknown>;
  /** Session ids whose GET rejects once, then succeeds. */
  failOnce?: string[];
}

function makeFetch(options: FetchOptions = {}) {
  const byId = new Map<string, FakeSession | FakeSession[]>();
  for (const entry of options.sessions ?? []) {
    const id = Array.isArray(entry) ? entry[0]!.session_id : entry.session_id;
    byId.set(id, entry);
  }
  const reads = new Map<string, number>();
  const failOnce = new Set(options.failOnce ?? []);
  const posts: Record<string, unknown>[] = [];
  const fetch = vi.fn(
    async (
      path: string,
      init?: {
        method?: string;
        params?: { path?: { session_id?: string; plan_id?: string } };
        requestBody?: { "application/json": Record<string, unknown> };
      }
    ) => {
      if (path.endsWith("/models")) return DEFAULT_MODEL_RESPONSE;
      if (path.endsWith("/review-packet")) return REVIEW_PACKET;
      if (path === SESSIONS_ROUTE && init?.method === "get") return { sessions: [] };
      if (path === SESSIONS_ROUTE && init?.method === "post") {
        posts.push(init.requestBody!["application/json"]);
        const created = options.created ?? makeSession();
        // A pre-registered read sequence for the same id wins over the POST body,
        // so a test can script what later authoritative refreshes return.
        if (!byId.has(created.session_id)) byId.set(created.session_id, created);
        return created;
      }
      if (path === SESSION_ROUTE) {
        const id = init?.params?.path?.session_id ?? "";
        if (failOnce.delete(id)) throw new Error("The saved draft could not be loaded.");
        const entry = byId.get(id);
        if (!entry) throw new Error(`Unknown session ${id}`);
        const count = (reads.get(id) ?? 0) + 1;
        reads.set(id, count);
        return Array.isArray(entry) ? entry[Math.min(count, entry.length) - 1] : entry;
      }
      if (path === PLAN_ROUTE) {
        const plan = options.plans?.[init?.params?.path?.plan_id ?? ""];
        if (!plan) throw new Error("Unknown plan");
        return plan;
      }
      throw new Error(`Unexpected request: ${path}`);
    }
  );
  return { fetch, posts };
}

interface StreamEvent {
  event: string;
  data: string;
}
const textEvent = (text: string): StreamEvent => ({
  event: "text",
  data: JSON.stringify({ text })
});
const questionEvent = (q: StructuredQuestion): StreamEvent => ({
  event: "question",
  data: JSON.stringify(q)
});
const summaryEvent = (summary: RequirementsSummary): StreamEvent => ({
  event: "requirements_summary",
  data: JSON.stringify(summary)
});
const statusEvent = (status: string): StreamEvent => ({
  event: "status",
  data: JSON.stringify({ status })
});
const planEvent = (): StreamEvent => ({ event: "plan", data: JSON.stringify(PLAN_STREAM_PAYLOAD) });
const usageEvent = (): StreamEvent => ({
  event: "usage",
  data: JSON.stringify({ total_tokens_total: 10 })
});

interface StreamCall {
  body: Record<string, unknown>;
  emit: (events: StreamEvent[]) => void;
  finish: () => void;
}

/**
 * Every stream call is recorded with its request body. The script decides
 * what each call does: reply with events and finish, stay open ("hold") so
 * the test can emit later, or reject.
 */
function makeStream(
  script: (index: number) => StreamEvent[] | "hold" | Error = () => [textEvent("Tack.")]
) {
  const calls: StreamCall[] = [];
  const stream = vi.fn(
    (
      _path: string,
      init: { requestBody: { "application/json": Record<string, unknown> } },
      handlers: {
        onMessage?: (
          event: { id: string; event: string; data: string },
          c: AbortController
        ) => void;
        onClose?: () => void;
      }
    ) => {
      const controller = new AbortController();
      const emit = (events: StreamEvent[]) => {
        for (const event of events) handlers.onMessage?.({ id: "", ...event }, controller);
      };
      return new Promise<void>((resolve, reject) => {
        const call: StreamCall = {
          body: init.requestBody["application/json"],
          emit,
          finish: () => {
            emit([{ event: "done", data: "" }]);
            handlers.onClose?.();
            resolve();
          }
        };
        const outcome = script(calls.length);
        calls.push(call);
        if (outcome instanceof Error) reject(outcome);
        else if (outcome !== "hold") {
          call.emit(outcome);
          call.finish();
        }
      });
    }
  );
  return { stream, calls };
}

interface ShellProps {
  fetch: ReturnType<typeof makeFetch>["fetch"];
  stream: ReturnType<typeof makeStream>["stream"];
  targetKind?: "create" | "edit";
  flowId?: string | null;
  resumeSessionId?: string | null;
  canReview?: boolean;
}

function renderShell({ fetch, stream, ...props }: ShellProps) {
  let service: FlowAIBuilderService | undefined;
  let builder:
    | {
        focusSavedFlowStep: (scope: AIBuilderSavedFlowStepScope) => Promise<void>;
        openReview: () => Promise<void>;
      }
    | undefined;
  render(FlowAIBuilderHarness, {
    transport: { fetch, stream } as unknown as AIBuilderClientTransport,
    ...props,
    onservice: (instance: FlowAIBuilderService) => (service = instance),
    onbuilder: (instance: typeof builder) => (builder = instance)
  });
  return { service: () => service!, builder: () => builder! };
}

const textbox = () => screen.getByRole("textbox") as HTMLTextAreaElement;
const button = (name: string | RegExp) => screen.getByRole("button", { name }) as HTMLButtonElement;
const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const draftRecord = (sessionId: string) =>
  JSON.parse(localStorage.getItem(`eneo:ai-builder:draft:${sessionId}`) ?? "null");

/** Types the first task on the task screen and sends it. */
async function sendTask(text = "Sammanfatta rapporter till en PDF") {
  await screen.findByRole("heading", { name: m.ai_builder_task_title() });
  await fireEvent.input(textbox(), { target: { value: text } });
  await fireEvent.click(button(m.ai_builder_send()));
}

function railButton(name: string) {
  const nav = screen.getByRole("navigation", { name: m.ai_builder_progress_aria() });
  return within(nav).getByRole("button", { name }) as HTMLButtonElement;
}

const SAVED_STEP_SCOPE: AIBuilderSavedFlowStepScope = {
  stepNumber: 2,
  stepName: "Jämför likheter och skillnader",
  editContext: { kind: "saved_flow_step", flow_step_id: "22222222-2222-4222-8222-222222222222" }
};
const SAVED_STEP_LABEL = m.ai_builder_edit_context_step({
  step: 2,
  name: SAVED_STEP_SCOPE.stepName
});

// jsdom does not always provide rAF or the Web Animations API; the composer's
// focus() and the sheet/alert transitions go through them.
globalThis.requestAnimationFrame ??= ((cb: FrameRequestCallback) =>
  setTimeout(() => cb(0), 0)) as never;
Element.prototype.animate ??= (() => ({
  cancel() {},
  finished: Promise.resolve(),
  onfinish: null
})) as never;
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.setPointerCapture ??= () => undefined;
Element.prototype.releasePointerCapture ??= () => undefined;

beforeEach(() => {
  Object.defineProperty(Element.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn()
  });
});

afterEach(() => {
  cleanup();
  // Composer drafts persist per session id; tests share ids across cases.
  localStorage.clear();
});

// ---- Bootstrap and resume -----------------------------------------------------

describe("FlowAIBuilder bootstrap", () => {
  it("creates one new session in create mode and shows the task screen", async () => {
    const { fetch, posts } = makeFetch();
    renderShell({ fetch, stream: makeStream().stream });

    expect(await screen.findByRole("heading", { name: m.ai_builder_task_title() })).toBeTruthy();
    expect(posts).toEqual([expect.objectContaining({ target_kind: "create", force_new: false })]);

    const send = button(m.ai_builder_send());
    expect(send.disabled).toBe(true);
    await fireEvent.input(textbox(), { target: { value: "Sammanfatta rapporter" } });
    await waitFor(() => expect(send.disabled).toBe(false));
    expect(posts).toHaveLength(1);
  });

  it("initializes an edit session for edit mode", async () => {
    const { fetch, posts } = makeFetch({
      created: makeSession({ session_id: "e-1", target_kind: "edit", flow_id: "flow-1" })
    });
    renderShell({ fetch, stream: makeStream().stream, targetKind: "edit", flowId: "flow-1" });

    expect(
      await screen.findByRole("heading", { name: m.ai_builder_task_title_edit() })
    ).toBeTruthy();
    expect(posts).toEqual([expect.objectContaining({ target_kind: "edit", flow_id: "flow-1" })]);
    expect(fetch).toHaveBeenCalledWith(SESSIONS_ROUTE, expect.objectContaining({ method: "get" }));
  });

  it("shows the review entry only when the page grants the review permission", async () => {
    const withReview = makeFetch({
      created: makeSession({ session_id: "e-1", target_kind: "edit", flow_id: "flow-1" })
    });
    const granted = renderShell({
      fetch: withReview.fetch,
      stream: makeStream().stream,
      targetKind: "edit",
      flowId: "flow-1",
      canReview: true
    });
    void granted;
    expect(await screen.findByTestId("open-review")).toBeTruthy();
    cleanup();

    const withoutReview = makeFetch({
      created: makeSession({ session_id: "e-2", target_kind: "edit", flow_id: "flow-1" })
    });
    renderShell({
      fetch: withoutReview.fetch,
      stream: makeStream().stream,
      targetKind: "edit",
      flowId: "flow-1"
    });
    // Ordinary Builder editing stays available without the review feature.
    expect(
      await screen.findByRole("heading", { name: m.ai_builder_task_title_edit() })
    ).toBeTruthy();
    expect(screen.queryByTestId("open-review")).toBeNull();
  });

  it("resumes the chosen draft and lets its transcript pick the screen", async () => {
    const { fetch, posts } = makeFetch({ sessions: [questionSession()] });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    expect(await screen.findByRole("heading", { name: FORMAT_QUESTION.question })).toBeTruthy();
    expect(posts).toHaveLength(0);
    expect(fetch).toHaveBeenCalledWith(SESSION_ROUTE, {
      method: "get",
      params: { path: { session_id: "s-1" } }
    });
  });

  it("offers the list and a new task when the chosen draft cannot be opened", async () => {
    const { fetch, posts } = makeFetch({
      failOnce: ["s-1"],
      created: makeSession({ session_id: "s-2" })
    });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    expect(await screen.findByText(m.ai_builder_resume_failed_title())).toBeTruthy();
    expect(screen.getByRole("link", { name: m.ai_builder_resume_failed_back() })).toBeTruthy();
    expect(posts).toHaveLength(0);

    await fireEvent.click(button(m.ai_builder_resume_failed_new()));

    expect(await screen.findByRole("heading", { name: m.ai_builder_task_title() })).toBeTruthy();
    expect(posts).toEqual([expect.objectContaining({ target_kind: "create" })]);
  });
});

// ---- Discovery: task, reply, questions --------------------------------------------

describe("FlowAIBuilder planner controls", () => {
  const SECOND_MODEL_ID = "11111111-1111-4111-8111-111111111198";

  /** Same fixtures, but a space that offers a genuine model choice. */
  function withTwoModels(reasoning: string[] = []) {
    const { fetch } = makeFetch();
    return vi.fn(async (path: string, init?: Record<string, unknown>) =>
      path.endsWith("/models")
        ? {
            models: [
              {
                id: DEFAULT_MODEL_ID,
                name: "Test model",
                provider: "openai",
                reasoning_effort_options: reasoning
              },
              {
                id: SECOND_MODEL_ID,
                name: "Second model",
                provider: "openai",
                reasoning_effort_options: []
              }
            ],
            default_model_id: DEFAULT_MODEL_ID
          }
        : fetch(path as string, init as never)
    );
  }

  it("names the advertised model once the space offers a choice", async () => {
    renderShell({ fetch: withTwoModels(), stream: makeStream().stream });

    expect(
      await screen.findByRole("button", {
        name: `${m.ai_builder_model_label()}: Test model`
      })
    ).toBeTruthy();
  });

  it("stays out of the composer when the space has a single model", async () => {
    const { fetch } = makeFetch();
    const { service } = renderShell({ fetch, stream: makeStream().stream });

    await waitFor(() => expect(service().availableModels).toHaveLength(1));
    expect(screen.queryByRole("button", { name: /Test model/ })).toBeNull();
  });

  it("offers reasoning only for a model that advertises efforts", async () => {
    // The contract is explicit: an empty option list means no control at all.
    renderShell({ fetch: withTwoModels(["low", "high"]), stream: makeStream().stream });

    expect(
      await screen.findByRole("button", {
        name: `${m.reasoning_effort()}: ${m.default_behavior()}`
      })
    ).toBeTruthy();
  });

  it("has no reasoning control when the active model advertises none", async () => {
    const { service } = renderShell({ fetch: withTwoModels(), stream: makeStream().stream });

    await waitFor(() => expect(service().availableModels).toHaveLength(2));
    expect(screen.queryByRole("button", { name: new RegExp(m.reasoning_effort()) })).toBeNull();
  });

  it("says the space has no planner model rather than showing nothing", async () => {
    // A successful but empty read is not the same as an unread one: the turn
    // will fail at the server, so the composer says so first.
    const { fetch } = makeFetch();
    const empty = vi.fn(async (path: string, init?: Record<string, unknown>) =>
      path.endsWith("/models")
        ? { models: [], default_model_id: null }
        : fetch(path as string, init as never)
    );
    renderShell({ fetch: empty, stream: makeStream().stream });

    expect(await screen.findByText(m.no_completion_model_description())).toBeTruthy();
  });

  it("says so and retries when the model read fails, without blocking the send", async () => {
    const { fetch } = makeFetch();
    let failNext = true;
    const flaky = vi.fn(async (path: string, init?: Record<string, unknown>) => {
      if (!path.endsWith("/models")) return fetch(path as string, init as never);
      if (failNext) {
        failNext = false;
        throw new Error("models unavailable");
      }
      return {
        models: [
          {
            id: DEFAULT_MODEL_ID,
            name: "Test model",
            provider: "openai",
            reasoning_effort_options: []
          },
          {
            id: SECOND_MODEL_ID,
            name: "Second model",
            provider: "openai",
            reasoning_effort_options: []
          }
        ],
        default_model_id: DEFAULT_MODEL_ID
      };
    });
    const { service } = renderShell({ fetch: flaky, stream: makeStream().stream });

    expect(await screen.findByText(m.failed_to_load_models())).toBeTruthy();
    // The failure explains itself; it never reaches the send path.
    await waitFor(() => expect(service().canSendMessage).toBe(true));

    await fireEvent.click(button(m.retry()));

    expect(
      await screen.findByRole("button", {
        name: `${m.ai_builder_model_label()}: Test model`
      })
    ).toBeTruthy();
    expect(screen.queryByText(m.failed_to_load_models())).toBeNull();
  });

  it("retries the model read once however fast the button is clicked", async () => {
    // Two in-flight reads can land in either order, and a late failure would
    // erase an earlier success. The status leaves "failed" before awaiting.
    const { fetch } = makeFetch();
    let modelReads = 0;
    let release!: () => void;
    const held = new Promise<void>((resolve) => (release = resolve));
    const slow = vi.fn(async (path: string, init?: Record<string, unknown>) => {
      if (!path.endsWith("/models")) return fetch(path as string, init as never);
      modelReads += 1;
      if (modelReads === 1) throw new Error("models unavailable");
      await held;
      return { models: [], default_model_id: null };
    });
    renderShell({ fetch: slow, stream: makeStream().stream });

    await screen.findByText(m.failed_to_load_models());
    const retry = button(m.retry());
    await fireEvent.click(retry);
    await fireEvent.click(retry);

    expect(modelReads).toBe(2);

    // Settle the retry so the assertion covers where the second click landed,
    // not just how many reads started.
    release();
    expect(await screen.findByText(m.no_completion_model_description())).toBeTruthy();
    expect(modelReads).toBe(2);
  });

  it("carries a chosen model through to the request", async () => {
    const { stream, calls } = makeStream(() => "hold");
    const { service } = renderShell({ fetch: withTwoModels(["low", "high"]), stream });

    await fireEvent.click(
      await screen.findByRole("button", { name: `${m.ai_builder_model_label()}: Test model` })
    );
    await fireEvent.click(await screen.findByRole("option", { name: /Second model/ }));
    await waitFor(() => expect(service().effectiveModel?.id).toBe(SECOND_MODEL_ID));

    await sendTask();

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({ model_id: SECOND_MODEL_ID });
    calls[0]!.finish();
  });
});

describe("FlowAIBuilder discovery screens", () => {
  it("names the reading and understanding phases on the reply screen without leaving it", async () => {
    const { fetch } = makeFetch();
    const { stream, calls } = makeStream(() => "hold");
    renderShell({ fetch, stream });

    await sendTask();

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(await screen.findByText(m.ai_builder_reply_reading())).toBeTruthy();

    calls[0]!.emit([statusEvent("reading_sources")]);
    expect(await screen.findByText(m.ai_builder_reply_reading_sources())).toBeTruthy();

    calls[0]!.emit([statusEvent("understanding_request")]);
    expect(await screen.findByText(m.ai_builder_reply_understanding())).toBeTruthy();
    // Still the first phase: no build narration, and the composer's reply
    // screen is what the question will replace.
    expect(screen.queryByText(m.ai_builder_build_narration_reading())).toBeNull();

    calls[0]!.emit([textEvent("Jag behöver veta formatet."), questionEvent(FORMAT_QUESTION)]);
    expect(await screen.findByRole("heading", { name: FORMAT_QUESTION.question })).toBeTruthy();
    calls[0]!.finish();
  });

  it("sends the task, waits on the reply screen, then shows the first question", async () => {
    const { fetch } = makeFetch();
    const { stream, calls } = makeStream(() => "hold");
    renderShell({ fetch, stream });

    await sendTask();

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({ message: "Sammanfatta rapporter till en PDF" });
    expect(await screen.findByText(m.ai_builder_reply_reading())).toBeTruthy();

    calls[0]!.emit([textEvent("Jag behöver veta formatet."), questionEvent(FORMAT_QUESTION)]);

    expect(await screen.findByRole("heading", { name: FORMAT_QUESTION.question })).toBeTruthy();
    expect(screen.getByText(m.ai_builder_question_number({ number: "1" }))).toBeTruthy();
    expect(screen.getByText(m.ai_builder_question_why_lead())).toBeTruthy();
    expect(screen.getByText(/Jag behöver veta formatet\./)).toBeTruthy();
    calls[0]!.finish();
  });

  it("sends a single choice as a structured answer once confirmed", async () => {
    const { fetch } = makeFetch({ sessions: [questionSession()] });
    const { stream, calls } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    const confirm = (await screen.findByRole("button", {
      name: m.ai_builder_question_confirm()
    })) as HTMLButtonElement;
    expect(confirm.getAttribute("aria-disabled")).toBe("true");

    await fireEvent.click(screen.getByRole("radio", { name: "Som PDF" }));
    await waitFor(() => expect(confirm.getAttribute("aria-disabled")).toBe("false"));
    await fireEvent.click(confirm);

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      message: "Som PDF",
      question_answer: {
        kind: "structured_question_answer",
        question_id: "output_format",
        selected_option_ids: ["pdf"]
      }
    });
  });

  it("shows every attachment as a typed row and previews the run contract", async () => {
    const typed = {
      ...SUMMARY,
      assumptions: [
        ...(SUMMARY.assumptions ?? []),
        'Bilageunderlag – Bilaga "mall.docx" (id 00000000-0000-0000-0000-000000000801): vald roll Mall; läsbar text: ja.'
      ],
      attachment_rows: [
        {
          file_id: "00000000-0000-0000-0000-000000000801",
          filename: "mall.docx",
          role: "template",
          readable: true,
          coverage: "fully_seen",
          travels: true,
          placeholders: ["diarienummer", "datum", "namn", "adress", "beslutsfattare"]
        },
        {
          file_id: "00000000-0000-0000-0000-000000000802",
          filename: "underlag.pdf",
          role: "reference_material",
          readable: true,
          coverage: "fully_seen",
          travels: false,
          placeholders: null
        },
        // Same filename, only the inventory read: the card must keep the two apart.
        {
          file_id: "00000000-0000-0000-0000-000000000803",
          filename: "underlag.pdf",
          role: "reference_material",
          readable: true,
          coverage: "inventory_only",
          travels: false,
          placeholders: null
        }
      ],
      weak_role_file_ids: ["00000000-0000-0000-0000-000000000802"],
      run_preview: {
        runtime_input: "documents",
        runtime_input_label: "Dokument",
        max_files: 5,
        result_type: "docx_document",
        result_type_label: "Word-dokument",
        report_layout: null,
        report_layout_label: null,
        template: { filename: "mall.docx", placeholder_count: 2 }
      }
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Fyll i kommunens mall"),
            assistantMessage("a1", "Här är min tolkning.", { requirements_summary: typed })
          ]
        })
      ]
    });
    const { stream } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    const rows = await screen.findByTestId("attachment-rows");
    expect(rows.textContent).toContain("mall.docx");
    expect(rows.textContent).toContain(m.ai_builder_attachment_travels());
    expect(rows.textContent).toContain(m.ai_builder_attachment_placeholders({ count: "5" }));
    // Every placeholder is inspectable without a pointer: the long list sits in
    // a native disclosure the keyboard can open.
    const placeholderDetails = rows.querySelector("details") as HTMLDetailsElement;
    expect(placeholderDetails).toBeTruthy();
    // Collapsed: the list is in the DOM but not exposed until the user opens it.
    expect(placeholderDetails.open).toBe(false);
    await fireEvent.click(placeholderDetails.querySelector("summary") as HTMLElement);
    await waitFor(() => expect(placeholderDetails.open).toBe(true));
    const placeholderList = placeholderDetails.querySelector("span") as HTMLElement;
    expect(placeholderList.textContent).toContain("beslutsfattare");
    expect(rows.textContent).toContain(m.ai_builder_attachment_coverage_full());
    expect(rows.textContent).toContain(m.ai_builder_attachment_coverage_inventory());
    expect(rows.textContent).toContain("underlag.pdf (1)");
    expect(rows.textContent).toContain("underlag.pdf (2)");
    // The planner's attachment sentence is not shown beside the rows it duplicates.
    expect(screen.queryByText(/Bilageunderlag –/)).toBeNull();
    expect(rows.textContent).toContain(m.ai_builder_attachment_not_carried());
    expect(rows.textContent).toContain(m.ai_builder_attachment_role_unsure());

    const preview = screen.getByTestId("run-preview");
    expect(preview.textContent).toContain(m.ai_builder_run_preview_title());
    expect(preview.textContent).toContain("Dokument");
    // The per-run file limit is an assumption row, not repeated in the preview.
    expect(preview.textContent).not.toContain(m.ai_builder_run_preview_max_files({ count: "5" }));
    expect(preview.textContent).toContain("Word-dokument");
    expect(preview.textContent).toContain("mall.docx");
  });

  it("keeps the attachment sentences of a disclosure saved before the typed rows existed", async () => {
    const legacy = {
      ...SUMMARY,
      assumptions: [
        ...(SUMMARY.assumptions ?? []),
        'Bilageunderlag – Bilaga "mall.docx" (id 00000000-0000-0000-0000-000000000801): vald roll Mall; läsbar text: ja.'
      ]
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Fyll i kommunens mall"),
            assistantMessage("a1", "Här är min tolkning.", { requirements_summary: legacy })
          ]
        })
      ]
    });
    const { stream } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });
    await screen.findByText(m.ai_builder_requirements_title());
    expect(screen.queryByTestId("attachment-rows")).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: /Antaganden|Assumptions/ }));
    expect(await screen.findByText(/Bilageunderlag –/)).toBeTruthy();
  });

  it("shows an assumption as a row and reopens its question on the server", async () => {
    const assumed = {
      ...SUMMARY,
      assumption_rows: [
        {
          question_id: "document_material_scope",
          slot_name: "document_material_scope",
          value: "flexible_document_case",
          topic: "Dokumentomfång",
          label: "Ett eller flera dokument per körning"
        }
      ]
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter till en PDF"),
            assistantMessage("a1", "Här är min tolkning.", { requirements_summary: assumed })
          ]
        })
      ]
    });
    const { stream, calls } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    // The row lives under the collapsed assumptions heading; opening it shows
    // the topic and Eneo's default with one action to change it.
    await fireEvent.click(await screen.findByRole("button", { name: /Antaganden \(1\)/ }));
    expect(await screen.findByText("Ett eller flera dokument per körning")).toBeTruthy();
    await fireEvent.click(
      screen.getByRole("button", {
        name: m.ai_builder_assumption_change_aria({
          topic: "Dokumentomfång",
          label: "Ett eller flera dokument per körning"
        })
      })
    );

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      message: "",
      question_answer: {
        kind: "reopen_question",
        question_id: "document_material_scope",
        requirements_version: REQUIREMENTS_VERSION
      }
    });
  });

  it("shows a confirmed card's assumptions as rows without a reopen action", async () => {
    const assumed = {
      ...SUMMARY,
      assumption_rows: [
        {
          question_id: "document_material_scope",
          slot_name: "document_material_scope",
          value: "flexible_document_case",
          topic: "Dokumentomfång",
          label: "Ett eller flera dokument per körning"
        }
      ]
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          status: "awaiting_approval",
          latest_plan_id: PLAN_ID,
          conversation: [
            userMessage("u1", "Sammanfatta rapporter till en PDF"),
            assistantMessage("a1", "Här är min tolkning.", { requirements_summary: assumed }),
            userMessage("u2", "", {
              requirements_confirmation: {
                requirements_confirmed: true,
                requirements_version: REQUIREMENTS_VERSION
              }
            })
          ]
        })
      ]
    });
    const { stream } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    // Revisiting the confirmed card from the review phase still lists what Eneo
    // assumed, but like every other row it is a record now: changes go through
    // a change request.
    await fireEvent.click(
      await screen.findByRole("button", { name: new RegExp(m.ai_builder_rail_understanding()) })
    );
    await fireEvent.click(await screen.findByRole("button", { name: /Antaganden \(1\)/ }));
    expect(await screen.findByText("Ett eller flera dokument per körning")).toBeTruthy();
    expect(
      screen.queryByRole("button", {
        name: m.ai_builder_assumption_change_aria({
          topic: "Dokumentomfång",
          label: "Ett eller flera dokument per körning"
        })
      })
    ).toBeNull();
  });

  it("preselects Eneo's recommendation and can hand the question back", async () => {
    const recommended = question("output_format", "Hur ska resultatet levereras?", [
      { id: "pdf", label: "Som PDF" },
      { id: "text", label: "Som text" }
    ]);
    recommended.recommended_option_id = "text";
    const { fetch } = makeFetch({ sessions: [questionSession(recommended)] });
    const { stream, calls } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    // The recommendation is named on its option and already chosen, so
    // confirming is one click.
    expect(await screen.findByText(m.ai_builder_question_recommended())).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByRole("radio", { name: /Som text/ }).getAttribute("aria-checked")).toBe(
        "true"
      )
    );

    await fireEvent.click(button(m.ai_builder_question_delegate()));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      message: "",
      question_answer: { kind: "delegated_question_answer", question_id: "output_format" }
    });
  });

  it("reads a delegated answer back by the option Eneo chose", async () => {
    // A delegation sends no words, so the label can only come from the option
    // the server names on the replayed answer.
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter till en PDF"),
            assistantMessage("a1", "Jag behöver veta formatet.", { question: FORMAT_QUESTION }),
            userMessage("u2", "", {
              question_answer: {
                kind: "structured_question_answer",
                question_id: "output_format",
                selected_option_id: "pdf",
                selected_value: "pdf",
                delegated: true
              }
            }),
            assistantMessage("a2", "Och källorna?", { question: SOURCES_QUESTION })
          ]
        })
      ]
    });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: SOURCES_QUESTION.question });
    const chip = screen.getByText("Som PDF").closest("button")!;
    expect(within(chip).getByText(m.ai_builder_question_delegated_badge())).toBeTruthy();
  });

  it("does not offer to hand back an answered question that is reopened", async () => {
    const recommended = question("output_format", "Hur ska resultatet levereras?", [
      { id: "pdf", label: "Som PDF" },
      { id: "text", label: "Som text" }
    ]);
    recommended.recommended_option_id = "text";
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter till en PDF"),
            assistantMessage("a1", "Jag behöver veta formatet.", { question: recommended }),
            userMessage("u2", "Som PDF", {
              question_answer: {
                kind: "structured_question_answer",
                question_id: "output_format",
                selected_option_ids: ["pdf"]
              }
            }),
            assistantMessage("a2", "Och källorna?", { question: SOURCES_QUESTION })
          ]
        })
      ]
    });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: SOURCES_QUESTION.question });
    await fireEvent.click(screen.getByText("Som PDF").closest("button")!);

    // The server only accepts a delegation for the question it waits on.
    await screen.findByText(m.ai_builder_question_editing_note());
    expect(screen.queryByText(m.ai_builder_question_delegate())).toBeNull();
  });

  it("shows the user's own words behind Eneo's recommendation", async () => {
    const recommended = question("output_format", "Hur ska resultatet levereras?", [
      { id: "pdf", label: "Som PDF" },
      { id: "text", label: "Som text" }
    ]);
    recommended.recommended_option_id = "pdf";
    recommended.recommended_option_evidence = "en tydlig PDF-rapport";
    recommended.question_index = 2;
    const { fetch } = makeFetch({ sessions: [questionSession(recommended)] });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    // The number is the server's, not a client count.
    expect(await screen.findByText(m.ai_builder_question_number({ number: "2" }))).toBeTruthy();
    expect(
      screen.getByText(m.ai_builder_question_evidence({ quote: "en tydlig PDF-rapport" }))
    ).toBeTruthy();
  });

  it("leaves a question from before the server numbered them unnumbered", async () => {
    // Position in the transcript does not survive compaction, so a missing
    // index must stay missing rather than become a plausible number.
    const legacy = question("output_format", "Hur ska resultatet levereras?", [
      { id: "pdf", label: "Som PDF" },
      { id: "text", label: "Som text" }
    ]);
    const { fetch } = makeFetch({ sessions: [questionSession(legacy)] });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: legacy.question });
    expect(screen.queryByText(/^Fråga /)).toBeNull();
  });

  it("says what an option produces and how many questions are planned", async () => {
    const withExamples = question("output_format", "Hur ska resultatet levereras?", [
      { id: "pdf", label: "Som PDF" },
      { id: "text", label: "Som text" }
    ]);
    withExamples.options[0]!.example = "Ger till exempel Motesrapport.pdf";
    withExamples.question_index = 2;
    withExamples.questions_planned_remaining = 2;
    const { fetch } = makeFetch({ sessions: [questionSession(withExamples)] });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    expect(await screen.findByText("Ger till exempel Motesrapport.pdf")).toBeTruthy();
    expect(screen.getByText(m.ai_builder_question_planned_remaining({ count: "2" }))).toBeTruthy();
  });

  it("keeps quiet about what is left when the server has no plan behind the ask", async () => {
    const noPlan = question("output_format", "Hur ska resultatet levereras?", [
      { id: "pdf", label: "Som PDF" }
    ]);
    noPlan.question_index = 1;
    noPlan.questions_planned_remaining = 0;
    const { fetch } = makeFetch({ sessions: [questionSession(noPlan)] });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: noPlan.question });
    // 0 means nothing is queued behind this one, not that the interview ends.
    expect(screen.queryByText(/kvar/)).toBeNull();
  });

  it("does not offer to hand back a question Eneo has no recommendation for", async () => {
    const { fetch } = makeFetch({ sessions: [questionSession()] });
    const { stream } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    await screen.findByRole("button", { name: m.ai_builder_question_confirm() });
    expect(screen.queryByText(m.ai_builder_question_delegate())).toBeNull();
  });

  it("sends every selected option of a multi-select question", async () => {
    const { fetch } = makeFetch({ sessions: [questionSession(SOURCES_QUESTION)] });
    const { stream, calls } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    await fireEvent.click(await screen.findByRole("checkbox", { name: "Uppladdade dokument" }));
    await fireEvent.click(screen.getByRole("checkbox", { name: "Webbsidor" }));
    await fireEvent.click(button(m.ai_builder_question_confirm()));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      question_answer: { question_id: "sources", selected_option_ids: ["docs", "web"] }
    });
  });

  it("sends a typed answer as custom_value", async () => {
    const { fetch } = makeFetch({ sessions: [questionSession(CUSTOM_QUESTION)] });
    const { stream, calls } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    const customRow = (await screen.findByText(m.ai_builder_question_custom())).closest("button")!;
    await fireEvent.click(customRow);
    await fireEvent.input(
      await screen.findByRole("textbox", { name: m.ai_builder_question_custom() }),
      { target: { value: "Hela nämnden" } }
    );
    await fireEvent.click(button(m.ai_builder_question_confirm()));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      message: "Hela nämnden",
      question_answer: { question_id: "audience", custom_value: "Hela nämnden" }
    });
  });

  it("shows a question asked again after it was answered", async () => {
    const reasked = question(
      "output_format",
      "Vill du hellre ha PDF?",
      [
        { id: "pdf", label: "Som PDF" },
        { id: "text", label: "Som text" }
      ],
      { question_index: 2 }
    );
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter"),
            assistantMessage("a1", "Jag behöver veta formatet.", { question: FORMAT_QUESTION }),
            userMessage("u2", "Som text", {
              question_answer: {
                kind: "structured_question_answer",
                question_id: "output_format",
                selected_option_ids: ["text"]
              }
            }),
            assistantMessage("a2", "Jag frågar igen.", { question: reasked })
          ]
        })
      ]
    });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    // The earlier answer belongs to the earlier asking. Counting it as the
    // answer to this one would hide the question the server is waiting on.
    expect(await screen.findByRole("heading", { name: reasked.question })).toBeTruthy();
  });

  it("lets the user change an earlier answer from the answer chips", async () => {
    const reworded = question(
      "output_format",
      "Hur vill du ha resultatet levererat?",
      [
        { id: "pdf", label: "Som PDF" },
        { id: "text", label: "Som text" }
      ],
      { question_index: 1, topic: "Slutresultat, omformulerat" }
    );
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter till en PDF"),
            assistantMessage("a1", "Jag behöver veta formatet.", { question: FORMAT_QUESTION }),
            userMessage("u2", "Som text", {
              question_answer: {
                kind: "structured_question_answer",
                question_id: "output_format",
                selected_option_ids: ["text"]
              }
            }),
            assistantMessage("a2", "Jag omformulerar.", { question: reworded }),
            userMessage("u3", "Som PDF", {
              question_answer: {
                kind: "structured_question_answer",
                question_id: "output_format",
                selected_option_ids: ["pdf"]
              }
            }),
            assistantMessage("a3", "Och källorna?", { question: SOURCES_QUESTION })
          ]
        })
      ]
    });
    const { stream, calls } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: SOURCES_QUESTION.question });
    expect(screen.getByText(m.ai_builder_question_answers_label())).toBeTruthy();
    const chip = screen.getByText("Som PDF").closest("button")!;
    // The chip says what the answer settled, not just what was picked, and it
    // reads the newest asking of that question rather than the first.
    expect(within(chip).getByText("Slutresultat, omformulerat")).toBeTruthy();
    expect(within(chip).getByText(m.ai_builder_question_change())).toBeTruthy();

    await fireEvent.click(chip);

    expect(await screen.findByText(m.ai_builder_question_editing_note())).toBeTruthy();
    // Reopening lands on the same newest asking the chip described.
    expect(screen.getByRole("heading", { name: reworded.question })).toBeTruthy();
    await fireEvent.click(screen.getByRole("radio", { name: "Som text" }));
    await fireEvent.click(button(m.ai_builder_question_confirm()));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      question_answer: { question_id: "output_format", selected_option_ids: ["text"] }
    });
  });

  it("announces the screen that replaces the answered question", async () => {
    const { fetch } = makeFetch({ sessions: [questionSession()] });
    const { stream } = makeStream(() => [questionEvent(SOURCES_QUESTION)]);
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    const announcer = () => document.querySelector("[data-builder-announcer]")!;
    await screen.findByRole("heading", { name: FORMAT_QUESTION.question });
    // The screen the session opened on was not reached by a user action.
    expect(announcer().textContent?.trim()).toBe("");

    await fireEvent.click(screen.getByRole("radio", { name: "Som PDF" }));
    await fireEvent.click(button(m.ai_builder_question_confirm()));

    await screen.findByRole("heading", { name: SOURCES_QUESTION.question });
    await waitFor(() =>
      expect(announcer().textContent?.trim()).toBe(
        m.ai_builder_announce_question({ number: "2", question: SOURCES_QUESTION.question })
      )
    );
  });
});

// ---- Confirm, build, review, rail ---------------------------------------------------

/** Task sent, summary received: the confirm screen is showing. */
async function driveToConfirm(afterConfirm: () => StreamEvent[] | "hold") {
  const { fetch } = makeFetch();
  const { stream, calls } = makeStream((index) =>
    index === 0 ? [textEvent("Här är min tolkning."), summaryEvent(SUMMARY)] : afterConfirm()
  );
  renderShell({ fetch, stream });
  await sendTask();
  await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
  return { calls };
}

describe("FlowAIBuilder confirm, build and review", () => {
  it("shows the confirm screen on a summary and confirms with an empty message", async () => {
    const { calls } = await driveToConfirm(() => "hold");

    await fireEvent.click(button(m.ai_builder_confirm_action()));

    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1]!.body).toMatchObject({
      message: "",
      question_answer: {
        kind: "requirements_confirmation",
        requirements_version: REQUIREMENTS_VERSION
      }
    });
    calls[1]!.finish();
  });

  it("keeps a long original request compact until the user expands it", async () => {
    const longRequest = Array.from(
      { length: 18 },
      (_, index) => `${index + 1}. Bevara den här delen av den ursprungliga uppgiften.`
    ).join("\n");
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", longRequest),
            assistantMessage("a1", "", { requirements_summary: SUMMARY })
          ]
        })
      ]
    });

    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    const requestHeading = screen.getByRole("heading", {
      name: m.ai_builder_requirements_user_request()
    });
    const request = requestHeading.nextElementSibling as HTMLElement;
    const toggle = screen.getByRole("button", {
      name: m.ai_builder_requirements_show_full_request()
    });

    expect(request.textContent).toBe(longRequest);
    expect(request.classList.contains("line-clamp-5")).toBe(true);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    await fireEvent.click(toggle);

    expect(request.classList.contains("line-clamp-5")).toBe(false);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
  });

  it("changes an answer from the confirmation without leaving the card", async () => {
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter till en PDF"),
            assistantMessage("a1", "Jag behöver veta formatet.", { question: FORMAT_QUESTION }),
            userMessage("u2", "Som PDF", {
              question_answer: {
                kind: "structured_question_answer",
                question_id: "output_format",
                selected_option_ids: ["pdf"]
              }
            }),
            assistantMessage("a2", "", { requirements_summary: SUMMARY })
          ]
        })
      ]
    });
    const { stream, calls } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    await fireEvent.click(screen.getByText("Som PDF").closest("button")!);

    // The question opens above the summary; the contract stays on screen.
    expect(await screen.findByText(m.ai_builder_question_editing_note())).toBeTruthy();
    expect(screen.getByRole("heading", { name: m.ai_builder_requirements_title() })).toBeTruthy();
    await fireEvent.click(screen.getByRole("radio", { name: "Som text" }));
    await fireEvent.click(button(m.ai_builder_question_confirm()));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      question_answer: { question_id: "output_format", selected_option_ids: ["text"] }
    });
  });

  it("reopens the question that settled a decision, and lists the named content", async () => {
    const summary = {
      ...SUMMARY,
      key_decisions: [
        { topic: "Slutresultat", decision: "PDF-dokument", question_id: "output_format" },
        { topic: "Planerad bearbetning", decision: "Skapa PDF", is_derived: true }
      ],
      named_content_fields: [
        { id: "titel", label: "titel" },
        { id: "slutsatser", label: "slutsatser" }
      ]
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter till en PDF"),
            assistantMessage("a1", "Jag behöver veta formatet.", { question: FORMAT_QUESTION }),
            userMessage("u2", "Som PDF", {
              question_answer: {
                kind: "structured_question_answer",
                question_id: "output_format",
                selected_option_ids: ["pdf"]
              }
            }),
            assistantMessage("a2", "", { requirements_summary: summary })
          ]
        })
      ]
    });
    const { stream, calls } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    expect(screen.getByText(m.ai_builder_requirements_named_content({ count: "2" }))).toBeTruthy();
    expect(screen.getByText("slutsatser")).toBeTruthy();

    // Every requirement row is correctable, which is what the lead offers. The
    // row the user answered goes back into its question; the derived row has
    // no question to reopen, so it opens the change box naming that topic.
    await fireEvent.click(
      screen.getByRole("button", {
        name: m.ai_builder_confirm_change_row_aria({ topic: "Slutresultat" })
      })
    );
    expect(await screen.findByText(m.ai_builder_question_editing_note())).toBeTruthy();
    expect(screen.getByRole("heading", { name: FORMAT_QUESTION.question })).toBeTruthy();
    // Correcting a derived row closes the question editor: two open editors
    // would leave the user correcting one thing while reading another.
    await fireEvent.click(
      screen.getByRole("button", {
        name: m.ai_builder_confirm_change_row_aria({ topic: "Planerad bearbetning" })
      })
    );
    expect(screen.queryByText(m.ai_builder_question_editing_note())).toBeNull();
    // Closing the question editor must land back on the card, never on the
    // composer: the card is what the user stepped away from.
    expect(screen.getByRole("heading", { name: m.ai_builder_requirements_title() })).toBeTruthy();

    // The topic is named beside the box, never written into the user's draft,
    // so nothing is sendable until the user has actually said something.
    expect(screen.queryByRole("heading", { name: m.ai_builder_requirements_title() })).toBeTruthy();
    const clearScope = await screen.findByRole("button", {
      name: m.ai_builder_change_request_clear_scope()
    });
    expect(clearScope.parentElement?.textContent).toContain("Planerad bearbetning");
    const box = await screen.findByRole("textbox", {
      name: m.ai_builder_change_request_textarea_label()
    });
    expect((box as HTMLTextAreaElement).value).toBe("");
    expect(document.activeElement).toBe(box);
    expect(button(m.ai_builder_send()).disabled).toBe(true);

    // Words typed under one row stay with that row: moving away must neither
    // relabel them as another row's nor throw them away.
    await fireEvent.input(box, { target: { value: "något helt annat" } });
    await fireEvent.click(
      screen.getByRole("button", {
        name: m.ai_builder_confirm_change_row_aria({ topic: m.ai_builder_requirements_output() })
      })
    );
    const other = await screen.findByRole("textbox", {
      name: m.ai_builder_change_request_textarea_label()
    });
    expect((other as HTMLTextAreaElement).value).toBe("");

    await fireEvent.click(
      screen.getByRole("button", {
        name: m.ai_builder_confirm_change_row_aria({ topic: "Planerad bearbetning" })
      })
    );
    const reopened = await screen.findByRole("textbox", {
      name: m.ai_builder_change_request_textarea_label()
    });
    expect((reopened as HTMLTextAreaElement).value).toBe("något helt annat");
    await fireEvent.input(reopened, { target: { value: "" } });

    await fireEvent.input(reopened, { target: { value: "en PDF i stället" } });
    await fireEvent.click(button(m.ai_builder_send()));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      message: m.ai_builder_requirements_change_message_scoped({
        topic: "Planerad bearbetning",
        feedback: "en PDF i stället"
      })
    });
  });

  it("shows a correction going somewhere, and stops when the answer lands", async () => {
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter till en PDF"),
            assistantMessage("a1", "", { requirements_summary: SUMMARY })
          ]
        })
      ]
    });
    const { stream, calls } = makeStream(() => "hold");
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    // The collapsed composer bar is one button: its title, an example and "Skriv".
    await fireEvent.click(screen.getByText(m.ai_builder_change_request_write()).closest("button")!);
    const box = await screen.findByRole("textbox", {
      name: m.ai_builder_change_request_textarea_label()
    });
    await fireEvent.input(box, { target: { value: "en PDF i stället" } });
    await fireEvent.click(button(m.ai_builder_send()));

    // The editor closed, so the waiting state has to take its place: without
    // it, sending looks like nothing happened at all.
    // Announced, not just drawn: a screen reader has to hear that the
    // correction was sent, so the role is part of the contract.
    await waitFor(() =>
      expect(
        screen
          .getAllByRole("status")
          .some((node) => node.textContent?.includes(m.ai_builder_confirm_change_pending()))
      ).toBe(true)
    );
    expect(
      screen.queryByRole("textbox", { name: m.ai_builder_change_request_textarea_label() })
    ).toBeNull();

    // The new summary is what settles the wait, not the stream ending: assert
    // it while the stream is still open, or a status that hung around until
    // the stream closed would pass this too.
    const replacement = { ...SUMMARY, requirements_version: "b".repeat(64) };
    calls[0]!.emit([{ event: "requirements_summary", data: JSON.stringify(replacement) }]);

    await waitFor(() =>
      expect(
        screen
          .queryAllByRole("status")
          .some((node) => node.textContent?.includes(m.ai_builder_confirm_change_pending()))
      ).toBe(false)
    );
    calls[0]!.finish();
  });

  it("does not say it is working out the summary again while the first one arrives", async () => {
    const { fetch } = makeFetch({ sessions: [makeSession({ conversation: [] })] });
    const { stream, calls } = makeStream(() => "hold");
    renderShell({ fetch, stream });

    await waitFor(() => expect(screen.getByRole("textbox")).toBeTruthy());
    await fireEvent.input(textbox(), { target: { value: "Sammanfatta rapporter till en PDF" } });
    await fireEvent.click(button(m.ai_builder_send()));

    // The stream is still open when the first summary lands. There is nothing
    // to recalculate yet, so the card must not claim there is.
    calls[0]!.emit([{ event: "requirements_summary", data: JSON.stringify(SUMMARY) }]);

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    expect(screen.queryByText(m.ai_builder_confirm_change_pending())).toBeNull();
  });

  it("can show exactly what each runtime field does before it is signed", async () => {
    const fieldQuestion = question(
      "runtime_metadata_field_details",
      "Vad ska den som kör flödet fylla i?",
      [{ id: "interpret_input", label: "Använd för att förstå indata" }],
      { input_field_collection: true }
    );
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter"),
            assistantMessage("a1", "", { question: fieldQuestion }),
            userMessage("u2", "Ort (ort)", {
              question_answer: {
                kind: "structured_question_answer",
                question_id: "runtime_metadata_field_details",
                input_fields: [
                  {
                    value: {
                      name: "ort",
                      label: "Ort",
                      type: "select",
                      required: true,
                      options: ["Sundsvall", "Washington, D.C."]
                    },
                    purpose: "interpret_input"
                  }
                ]
              }
            }),
            assistantMessage("a2", "", {
              requirements_summary: {
                ...SUMMARY,
                runtime_input_fields: [
                  {
                    key: "ort",
                    label: "Ort",
                    type: "select",
                    required: true,
                    purpose: "Använd för att förstå indata",
                    options: ["Sundsvall", "Washington, D.C."]
                  }
                ]
              }
            })
          ]
        })
      ]
    });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    // The chip stays short; what the field actually does is one click away on
    // the card itself, not behind a screen change.
    expect(screen.getByText(m.ai_builder_requirements_runtime_fields())).toBeTruthy();
    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_requirements_fields_show_detail() })
    );

    // The purpose is worded by the question that offered it, never invented,
    // and an option containing a comma survives as one option.
    expect(await screen.findByText(/Använd för att förstå indata/)).toBeTruthy();
    expect(
      screen.getByText(
        m.ai_builder_requirements_field_options({ options: "Sundsvall · Washington, D.C." })
      )
    ).toBeTruthy();
  });

  it("opens the form on the answer that produced the summary being shown", async () => {
    // A turn that answered again without producing a new summary: the newer
    // answer belongs to a version the user is not looking at, so the editor
    // must not start from it.
    const fieldQuestion = question(
      "runtime_metadata_field_details",
      "Vad ska den som kör flödet fylla i?",
      [{ id: "interpret_input", label: "Använd för att förstå indata" }],
      { input_field_collection: true }
    );
    const answerWith = (id: string, label: string, name: string) =>
      userMessage(id, `${label} (${name})`, {
        question_answer: {
          kind: "structured_question_answer",
          question_id: "runtime_metadata_field_details",
          input_fields: [
            {
              value: { name, label, type: "text", required: false, options: [] },
              purpose: "interpret_input"
            }
          ]
        }
      });
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter"),
            assistantMessage("a1", "", { question: fieldQuestion }),
            answerWith("u2", "Ort", "ort"),
            assistantMessage("a2", "", {
              requirements_summary: {
                ...SUMMARY,
                runtime_input_fields: [
                  {
                    key: "ort",
                    label: "Ort",
                    type: "text",
                    required: false,
                    purpose: "Använd för att förstå indata"
                  }
                ]
              }
            }),
            assistantMessage("a3", "", { question: fieldQuestion }),
            answerWith("u3", "Handläggare", "handlaggare")
          ]
        })
      ]
    });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    expect(screen.getByText("Ort")).toBeTruthy();
    expect(screen.queryByText("Handläggare")).toBeNull();

    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_requirements_runtime_fields_change() })
    );
    const label = await screen.findByLabelText(m.ai_builder_question_field_label());
    expect((label as HTMLInputElement).value).toBe("Ort");
  });

  it("edits the content list against the version on screen", async () => {
    const summary = {
      ...SUMMARY,
      named_content_fields: [
        { id: "beslut", label: "Beslut" },
        { id: "handläggare", label: "Handläggare", origin: "card_edit" as const }
      ]
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter"),
            assistantMessage("a1", "", { requirements_summary: summary })
          ]
        })
      ]
    });
    const { stream, calls } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    // A field the user added says so; one Eneo found does not.
    expect(screen.getByText(m.ai_builder_requirements_field_added_by_you())).toBeTruthy();

    await fireEvent.click(
      screen.getByRole("button", {
        name: m.ai_builder_requirements_field_remove({ field: "Beslut" })
      })
    );

    // The resulting full set travels with the version it was read from, and
    // the message stays empty: the set says everything.
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      message: "",
      question_answer: {
        kind: "named_content_fields_edit",
        requirements_version: REQUIREMENTS_VERSION,
        field_names: ["handläggare"]
      }
    });
  });

  it("groups shaped containers at any depth, cascades removals, and places unplaced names", async () => {
    // Hierarchy keys on raw identities; labels deliberately carry shape
    // prose that must not participate in grouping.
    const summary = {
      ...SUMMARY,
      named_content_fields: [
        {
          id: "loc-doc",
          label: "documents (användaren skrev en lista)",
          name: "documents",
          segments: [],
          unplaced: false
        },
        {
          id: "loc-cp",
          label: "candidate_passages (användaren skrev en lista)",
          name: "candidate_passages",
          segments: ["documents"],
          unplaced: false
        },
        {
          id: "loc-page",
          label: "page_or_section",
          name: "page_or_section",
          segments: ["documents", "candidate_passages"],
          unplaced: false
        },
        {
          id: "loc-unp",
          label: "tidsstämpel",
          name: "tidsstämpel",
          segments: [],
          unplaced: true
        }
      ]
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter"),
            assistantMessage("a1", "", { requirements_summary: summary })
          ]
        })
      ]
    });
    const { stream, calls } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });

    // Two-level grouping renders each parent path, and the unplaced section.
    expect(
      screen.getByText(m.ai_builder_requirements_group_inside({ parent: "documents" }))
    ).toBeTruthy();
    expect(
      screen.getByText(
        m.ai_builder_requirements_group_inside({ parent: "documents › candidate_passages" })
      )
    ).toBeTruthy();
    expect(screen.getByText(m.ai_builder_requirements_group_unplaced())).toBeTruthy();

    // The unplaced name resolves through the placement affordance into a
    // group; the request re-adds the raw name placed under that parent id.
    await fireEvent.click(
      screen.getByRole("button", {
        name: m.ai_builder_requirements_field_place({ field: "tidsstämpel" })
      })
    );
    await fireEvent.click(
      await screen.findByRole("menuitem", { name: "documents › candidate_passages" })
    );
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      question_answer: {
        kind: "named_content_fields_edit",
        field_names: ["loc-doc", "loc-cp", "loc-page", "tidsstämpel"],
        added_field_placements: { tidsstämpel: "loc-cp" }
      }
    });

    // Removing the root container names and removes its whole subtree —
    // depth-independent, so the two-level descendant counts too.
    await fireEvent.click(
      screen.getByRole("button", {
        name: m.ai_builder_requirements_field_remove_with_children({
          field: "documents (användaren skrev en lista)",
          count: "2"
        })
      })
    );
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1]!.body).toMatchObject({
      question_answer: {
        kind: "named_content_fields_edit",
        field_names: ["loc-unp"]
      }
    });
  });

  it("offers a childless container as a placement target", async () => {
    // The central case: an attested empty events[] plus an unplaced
    // timestamp must offer "place inside events" even though no child
    // exists yet.
    const summary = {
      ...SUMMARY,
      named_content_fields: [
        {
          id: "loc-events",
          label: "events (användaren skrev en lista)",
          name: "events",
          segments: [],
          unplaced: false,
          can_contain_fields: true
        },
        {
          id: "loc-ts",
          label: "timestamp",
          name: "timestamp",
          segments: [],
          unplaced: true,
          can_contain_fields: false
        }
      ]
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter"),
            assistantMessage("a1", "", { requirements_summary: summary })
          ]
        })
      ]
    });
    const { stream, calls } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    await fireEvent.click(
      screen.getByRole("button", {
        name: m.ai_builder_requirements_field_place({ field: "timestamp" })
      })
    );
    await fireEvent.click(await screen.findByRole("menuitem", { name: "events" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      question_answer: {
        kind: "named_content_fields_edit",
        field_names: ["loc-events", "timestamp"],
        added_field_placements: { timestamp: "loc-events" }
      }
    });
  });

  it("never truncates a container out while its children render", async () => {
    // Eleven plain top-level fields exceed the chip cap; the container must
    // stay visible ahead of them.
    const filler = Array.from({ length: 11 }, (_, index) => ({
      id: `loc-f${index}`,
      label: `fält_${index}`,
      name: `falt_${index}`,
      segments: [],
      unplaced: false
    }));
    const summary = {
      ...SUMMARY,
      named_content_fields: [
        ...filler,
        {
          id: "loc-doc",
          label: "documents (användaren skrev en lista)",
          name: "documents",
          segments: [],
          unplaced: false
        },
        {
          id: "loc-title",
          label: "titel",
          name: "titel",
          segments: ["documents"],
          unplaced: false
        }
      ]
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter"),
            assistantMessage("a1", "", { requirements_summary: summary })
          ]
        })
      ]
    });
    const { stream } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    expect(screen.getByText("documents (användaren skrev en lista)")).toBeTruthy();
    expect(screen.getByText("titel")).toBeTruthy();
  });

  it("lets the user cancel adding report content and restores focus", async () => {
    const summary = {
      ...SUMMARY,
      named_content_fields: [{ id: "beslut", label: "Beslut" }]
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter"),
            assistantMessage("a1", "", { requirements_summary: summary })
          ]
        })
      ]
    });
    const { stream, calls } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_requirements_field_add() })
    );
    const input = screen.getByLabelText(m.ai_builder_requirements_field_add());
    const form = input.closest("form");
    if (!form) throw new Error("Expected the report-content form");

    await fireEvent.click(within(form).getByRole("button", { name: m.cancel() }));

    expect(screen.queryByLabelText(m.ai_builder_requirements_field_add())).toBeNull();
    const addButton = screen.getByRole("button", {
      name: m.ai_builder_requirements_field_add()
    });
    await waitFor(() => expect(document.activeElement).toBe(addButton));

    await fireEvent.click(addButton);
    const reopenedInput = screen.getByLabelText(m.ai_builder_requirements_field_add());
    await fireEvent.keyDown(reopenedInput, { key: "Escape" });

    expect(screen.queryByLabelText(m.ai_builder_requirements_field_add())).toBeNull();
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", { name: m.ai_builder_requirements_field_add() })
      )
    );
    expect(calls).toHaveLength(0);
  });

  it("does not claim answers on a run where nothing was asked", async () => {
    // The common live case: the description settles every slot, so the server
    // asks nothing and every row is derived.
    const summary = {
      ...SUMMARY,
      key_decisions: [
        { topic: "Syfte med bearbetningen", decision: "Strukturera materialet" },
        { topic: "Slutresultat", decision: "PDF-dokument" }
      ]
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter till en PDF"),
            assistantMessage("a1", "", { requirements_summary: summary })
          ]
        })
      ]
    });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    expect(screen.getByText(m.ai_builder_requirements_decisions_derived())).toBeTruthy();
    // Nothing was answered, so no row claims to be the user's answer — and
    // every row still offers a way to correct it.
    expect(screen.queryByText(m.ai_builder_requirements_answered())).toBeNull();
    for (const topic of ["Syfte med bearbetningen", "Slutresultat"]) {
      expect(
        screen.getByRole("button", { name: m.ai_builder_confirm_change_row_aria({ topic }) })
      ).toBeTruthy();
    }
  });

  it("marks a question the user answered after handing it to Eneo as the user's own", async () => {
    // Delegate, reopen, answer: the newest answer decides the provenance the
    // card shows, so the old delegation must not stick to the row.
    const summary = {
      ...SUMMARY,
      key_decisions: [{ topic: "Slutresultat", decision: "Som PDF", question_id: "output_format" }]
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter till en PDF"),
            assistantMessage("a1", "Jag behöver veta formatet.", { question: FORMAT_QUESTION }),
            userMessage("u2", "", {
              question_answer: {
                kind: "structured_question_answer",
                question_id: "output_format",
                selected_option_id: "text",
                selected_value: "text",
                delegated: true
              }
            }),
            assistantMessage("a2", "Jag frågar igen.", { question: FORMAT_QUESTION }),
            userMessage("u3", "Som PDF", {
              question_answer: {
                kind: "structured_question_answer",
                question_id: "output_format",
                selected_option_ids: ["pdf"]
              }
            }),
            assistantMessage("a3", "", { requirements_summary: summary })
          ]
        })
      ]
    });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    expect(screen.getByText(m.ai_builder_requirements_answered())).toBeTruthy();
    expect(screen.queryByText(m.ai_builder_question_delegated_badge())).toBeNull();
  });

  it("starts an edited answer from the option the user chose before", async () => {
    // Reopening an answered row must show the current answer selected, not
    // an empty form the user has to re-read from scratch.
    const summary = {
      ...SUMMARY,
      key_decisions: [{ topic: "Slutresultat", decision: "Som PDF", question_id: "output_format" }]
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter till en PDF"),
            assistantMessage("a1", "Jag behöver veta formatet.", { question: FORMAT_QUESTION }),
            userMessage("u2", "Som PDF", {
              question_answer: {
                kind: "structured_question_answer",
                question_id: "output_format",
                selected_option_ids: ["pdf"]
              }
            }),
            assistantMessage("a3", "", { requirements_summary: summary })
          ]
        })
      ]
    });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    await fireEvent.click(
      screen.getByRole("button", {
        name: m.ai_builder_confirm_change_row_aria({ topic: "Slutresultat" })
      })
    );

    const chosen = await screen.findByRole("radio", { name: "Som PDF" });
    expect(chosen.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radio", { name: "Som text" }).getAttribute("aria-checked")).toBe(
      "false"
    );
  });

  it("starts an edited answer from the text the user typed instead of an option", async () => {
    // A typed answer is a real answer: reopening it must show that text in
    // the custom lane, not the recommended option.
    const summary = {
      ...SUMMARY,
      key_decisions: [{ topic: "Läsare", decision: "Hela nämnden", question_id: "audience" }]
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter till en PDF"),
            assistantMessage("a1", "Vem läser resultatet?", { question: CUSTOM_QUESTION }),
            userMessage("u2", "Hela nämnden", {
              question_answer: {
                kind: "structured_question_answer",
                question_id: "audience",
                custom_value: "Hela nämnden"
              }
            }),
            assistantMessage("a3", "", { requirements_summary: summary })
          ]
        })
      ]
    });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    await fireEvent.click(
      screen.getByRole("button", {
        name: m.ai_builder_confirm_change_row_aria({ topic: "Läsare" })
      })
    );

    const typed = await screen.findByRole("textbox", { name: m.ai_builder_question_custom() });
    expect((typed as HTMLTextAreaElement | HTMLInputElement).value).toBe("Hela nämnden");
  });

  it("keeps the option an edited flow runs on today when a question is reopened here", async () => {
    const editQuestion = {
      ...FORMAT_QUESTION,
      // The server never recommends away from what an edited flow runs on, so
      // the running option is the only thing that can drive the preselection.
      recommended_option_id: null,
      current_option_id: "text"
    };
    const summary = {
      ...SUMMARY,
      key_decisions: [{ topic: "Slutresultat", decision: "Text", question_id: "output_format" }]
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          target_kind: "edit",
          flow_id: "flow-1",
          conversation: [
            userMessage("u1", "Byt format"),
            assistantMessage("a1", "Hur ska resultatet levereras?", { question: editQuestion }),
            userMessage("u2", "Som text", {
              question_answer: {
                kind: "structured_question_answer",
                question_id: "output_format",
                selected_option_ids: ["text"]
              }
            }),
            assistantMessage("a2", "", { requirements_summary: summary })
          ]
        })
      ]
    });
    renderShell({
      fetch,
      stream: makeStream().stream,
      resumeSessionId: "s-1",
      targetKind: "edit",
      flowId: "flow-1"
    });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title_edit() });
    await fireEvent.click(
      screen.getByRole("button", {
        name: m.ai_builder_confirm_change_row_aria({ topic: "Slutresultat" })
      })
    );

    // Reopened from the card, the question still knows it is editing a live
    // flow: the running option stays selected instead of the recommendation.
    const running = await screen.findByRole("radio", { name: /Som text/ });
    expect(running.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText(m.ai_builder_question_in_use_today())).toBeTruthy();
  });

  it("reopens the newest wording when a question was asked twice", async () => {
    const first = question("output_format", "Hur ska resultatet levereras?", [
      { id: "pdf", label: "Som PDF" },
      { id: "text", label: "Som text" }
    ]);
    const reasked = question("output_format", "Vill du hellre ha en annan leverans?", [
      { id: "pdf", label: "Som PDF" },
      { id: "docx", label: "Som Word" }
    ]);
    const summary = {
      ...SUMMARY,
      key_decisions: [
        { topic: "Slutresultat", decision: "PDF-dokument", question_id: "output_format" }
      ]
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter till en PDF"),
            assistantMessage("a1", "Första gången.", { question: first }),
            userMessage("u2", "Som PDF", {
              question_answer: {
                kind: "structured_question_answer",
                question_id: "output_format",
                selected_option_ids: ["pdf"]
              }
            }),
            assistantMessage("a2", "Jag frågar igen.", { question: reasked }),
            userMessage("u3", "Som PDF", {
              question_answer: {
                kind: "structured_question_answer",
                question_id: "output_format",
                selected_option_ids: ["pdf"]
              }
            }),
            assistantMessage("a3", "", { requirements_summary: summary })
          ]
        })
      ]
    });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    await fireEvent.click(
      screen.getByRole("button", {
        name: m.ai_builder_confirm_change_row_aria({ topic: "Slutresultat" })
      })
    );

    expect(await screen.findByRole("heading", { name: reasked.question })).toBeTruthy();
  });

  it("re-arms the confirmation when a newer requirements version replaces a confirmed one", async () => {
    const rearmed = makeSession({
      session_id: "s-rearm",
      latest_plan_id: null,
      conversation: [
        userMessage("u1", "Sammanfatta rapporter till en PDF"),
        assistantMessage("a1", "", { requirements_summary: SUMMARY }),
        userMessage("u2", "", {
          requirements_confirmation: {
            requirements_confirmed: true,
            requirements_version: REQUIREMENTS_VERSION
          }
        }),
        userMessage("u3", "Nej, en PDF per rapport."),
        assistantMessage("a2", "", {
          requirements_summary: { ...SUMMARY, requirements_version: "f".repeat(64) }
        })
      ]
    });
    const { fetch } = makeFetch({ sessions: [rearmed] });
    const { stream } = makeStream(() => "hold");
    renderShell({ fetch, stream, resumeSessionId: "s-rearm" });

    expect(await screen.findByText(m.ai_builder_confirm_stale_title())).toBeTruthy();
    expect(button(m.ai_builder_confirm_action()).disabled).toBe(false);
  });

  it("narrates the build from backend status and marks phase two current", async () => {
    const { calls } = await driveToConfirm(() => "hold");
    await fireEvent.click(button(m.ai_builder_confirm_action()));
    await waitFor(() => expect(calls).toHaveLength(2));

    calls[1]!.emit([statusEvent("architecture_committed")]);

    expect(await screen.findByRole("heading", { name: m.ai_builder_build_title() })).toBeTruthy();
    expect(screen.getByText(new RegExp(escape(m.ai_builder_build_narration_steps())))).toBeTruthy();
    const current = railButton(m.ai_builder_rail_planning());
    expect(current.getAttribute("aria-current")).toBe("step");
    calls[1]!.finish();
  });

  it("shows one failure surface with recovery when generation fails without a plan", async () => {
    // The authoritative refresh after a stream error must return the real
    // transcript (task, summary, confirmation), as the server does.
    const confirmedSession = makeSession({
      latest_plan_id: null,
      conversation: planSession().conversation
    });
    const { fetch } = makeFetch({ sessions: [[makeSession(), confirmedSession]] });
    const { stream, calls } = makeStream((index) =>
      index === 0 ? [textEvent("Här är min tolkning."), summaryEvent(SUMMARY)] : "hold"
    );
    renderShell({ fetch, stream });
    await sendTask();
    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    await fireEvent.click(button(m.ai_builder_confirm_action()));
    await waitFor(() => expect(calls).toHaveLength(2));

    calls[1]!.emit([
      statusEvent("architecture_committed"),
      {
        event: "error",
        data: JSON.stringify({
          schema_version: 2,
          code: "planner_stream_failed",
          category: "upstream",
          message: "Modellen svarade inte i tid.",
          phase: "planner",
          eneo_error_code: 9000,
          request_id: "req-1"
        })
      }
    ]);
    calls[1]!.finish();

    // The skeleton must never hide a failed generation: exactly one surface names it.
    expect(
      await screen.findByText(new RegExp(escape(m.ai_builder_generation_failed_title())))
    ).toBeTruthy();
    expect(screen.queryByRole("heading", { name: m.ai_builder_build_title() })).toBeNull();
    expect(screen.getAllByText("Modellen svarade inte i tid.")).toHaveLength(1);
  });

  it("opens the review surface when the plan arrives", async () => {
    await driveToConfirm(() => [planEvent(), usageEvent()]);

    await fireEvent.click(button(m.ai_builder_confirm_action()));

    expect(await screen.findByRole("heading", { name: "Sammanfatta till PDF" })).toBeTruthy();
    expect(railButton(m.ai_builder_rail_reviewing()).getAttribute("aria-current")).toBe("step");
  });

  it("lets the rail revisit the confirmed requirements and return to the plan", async () => {
    const { fetch } = makeFetch({
      sessions: [planSession()],
      plans: { [PLAN_ID]: PLAN_RESPONSE }
    });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });
    await screen.findByRole("heading", { name: "Sammanfatta till PDF" });

    await fireEvent.click(railButton(m.ai_builder_rail_understanding()));
    expect(
      await screen.findByRole("heading", { name: m.ai_builder_requirements_title() })
    ).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Sammanfatta till PDF" })).toBeNull();

    await fireEvent.click(railButton(m.ai_builder_rail_reviewing()));
    expect(await screen.findByRole("heading", { name: "Sammanfatta till PDF" })).toBeTruthy();

    // The build phase has nothing to revisit once it is done.
    expect(railButton(m.ai_builder_rail_planning()).disabled).toBe(true);
  });
});

// ---- Conversation sheet ------------------------------------------------------------

describe("FlowAIBuilder conversation screen", () => {
  const openConversation = async () => {
    await fireEvent.click(button(new RegExp(escape(m.ai_builder_conversation_button()))));
    return await screen.findByRole("heading", { name: m.ai_builder_conversation_title() });
  };

  it("replaces the phase screen with the transcript and goes back again", async () => {
    const { fetch } = makeFetch();
    renderShell({ fetch, stream: makeStream().stream });
    await screen.findByRole("heading", { name: m.ai_builder_task_title() });

    await openConversation();

    // The transcript is a screen, not a layer over one.
    expect(screen.queryByRole("heading", { name: m.ai_builder_task_title() })).toBeNull();
    expect(screen.getByText(m.ai_builder_conversation_empty())).toBeTruthy();

    // The screen change moves the caret with it, like every other screen.
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("heading", { name: m.ai_builder_conversation_title() })
      )
    );

    await fireEvent.click(button(m.ai_builder_conversation_back()));
    expect(await screen.findByRole("heading", { name: m.ai_builder_task_title() })).toBeTruthy();
  });

  it("keeps the pending question read-only and reopens an answered one from the transcript", async () => {
    const { fetch } = makeFetch({ sessions: [answeredThenPendingSession()] });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });
    await screen.findByRole("heading", { name: SOURCES_QUESTION.question });

    await openConversation();

    expect(screen.getByText("Sammanfatta rapporter till en PDF")).toBeTruthy();
    expect(screen.getByText(m.ai_builder_question_answer_in_view())).toBeTruthy();

    await fireEvent.click(button(m.ai_builder_conversation_edit_answer()));

    expect(await screen.findByText(m.ai_builder_question_editing_note())).toBeTruthy();
    expect(screen.getByRole("heading", { name: FORMAT_QUESTION.question })).toBeTruthy();
  });
});

// ---- Edit host contract ------------------------------------------------------------

describe("FlowAIBuilder edit host contract", () => {
  const editSession = () =>
    makeSession({ session_id: "e-1", target_kind: "edit", flow_id: "flow-1" });

  it("scopes the next message to the focused saved Flow step", async () => {
    const { fetch } = makeFetch({ created: editSession() });
    const { stream, calls } = makeStream();
    const { service, builder } = renderShell({
      fetch,
      stream,
      targetKind: "edit",
      flowId: "flow-1"
    });

    await waitFor(() => expect(service().hasSession).toBe(true));
    await waitFor(() => expect(builder()).toBeDefined());
    await builder().focusSavedFlowStep(SAVED_STEP_SCOPE);

    expect(await screen.findByText(SAVED_STEP_LABEL)).toBeTruthy();
    const input = screen.getByRole("textbox", {
      name: m.ai_builder_saved_step_prompt_placeholder()
    }) as HTMLTextAreaElement;
    await waitFor(() => expect(document.activeElement).toBe(input));
    await fireEvent.input(input, { target: { value: "Ändra bara det här steget" } });
    await fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      message: "Ändra bara det här steget",
      edit_context: SAVED_STEP_SCOPE.editContext
    });
  });

  it("delivers a cold saved-step launch to the composer once the session exists", async () => {
    // The flow editor calls in right after mounting the host, before the
    // session round-trip has finished; the focus must wait for the real composer.
    let releaseCreate!: () => void;
    const created = editSession();
    const held = new Promise<void>((resolve) => {
      releaseCreate = resolve;
    });
    const { fetch } = makeFetch({ created });
    const baseFetch = fetch.getMockImplementation()!;
    fetch.mockImplementation(async (path, init) => {
      if (path === SESSIONS_ROUTE && init?.method === "post") await held;
      return baseFetch(path, init);
    });
    const { stream, calls } = makeStream();
    const { builder } = renderShell({ fetch, stream, targetKind: "edit", flowId: "flow-1" });

    await waitFor(() => expect(builder()).toBeDefined());
    const launched = builder().focusSavedFlowStep(SAVED_STEP_SCOPE);
    releaseCreate();
    await launched;

    const input = (await screen.findByRole("textbox", {
      name: m.ai_builder_saved_step_prompt_placeholder()
    })) as HTMLTextAreaElement;
    await waitFor(() => expect(document.activeElement).toBe(input));
    await fireEvent.input(input, { target: { value: "Byt rubrik" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({ edit_context: SAVED_STEP_SCOPE.editContext });
  });

  it("opens the run review from a cold launch once the session exists", async () => {
    let releaseCreate!: () => void;
    const held = new Promise<void>((resolve) => {
      releaseCreate = resolve;
    });
    const { fetch } = makeFetch({ created: editSession() });
    const baseFetch = fetch.getMockImplementation()!;
    fetch.mockImplementation(async (path, init) => {
      if (path === SESSIONS_ROUTE && init?.method === "post") await held;
      return baseFetch(path, init);
    });
    const { stream } = makeStream();
    const { builder } = renderShell({ fetch, stream, targetKind: "edit", flowId: "flow-1" });
    await waitFor(() => expect(builder()).toBeDefined());
    const launched = builder().openReview();
    releaseCreate();
    await launched;
    const heading = await screen.findByRole("heading", { name: m.ai_builder_review_title() });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(await screen.findByTestId("findings-none")).toBeTruthy();
  });

  it("asks before a run review replaces an ongoing edit and clears the saved-step scope", async () => {
    const ongoing = makeSession({
      session_id: "e-ongoing",
      target_kind: "edit",
      flow_id: "flow-1",
      conversation: [
        userMessage("u1", "Byt rubrik på rapporten"),
        assistantMessage("a1", "Vad ska rubriken vara?")
      ]
    });
    const fresh = editSession();
    let posts = 0;
    const { fetch } = makeFetch({ sessions: [ongoing, fresh] });
    const baseFetch = fetch.getMockImplementation()!;
    fetch.mockImplementation(async (path, init) => {
      if (path === SESSIONS_ROUTE && init?.method === "post") {
        posts += 1;
        return posts === 1 ? ongoing : fresh;
      }
      return baseFetch(path, init);
    });
    const { stream } = makeStream();
    const { service, builder } = renderShell({
      fetch,
      stream,
      targetKind: "edit",
      flowId: "flow-1"
    });
    await waitFor(() => expect(service().hasSession).toBe(true));
    await waitFor(() => expect(builder()).toBeDefined());
    service().setSavedFlowStepScope(SAVED_STEP_SCOPE);
    await builder().openReview();
    expect(await screen.findByText(m.ai_builder_replace_edit_description_review())).toBeTruthy();
    expect(screen.queryByRole("heading", { name: m.ai_builder_review_title() })).toBeNull();
    await fireEvent.click(button(m.ai_builder_replace_edit_action()));
    expect(await screen.findByRole("heading", { name: m.ai_builder_review_title() })).toBeTruthy();
    expect(service().savedFlowStepScope).toBeNull();
    expect(posts).toBe(2);
  });

  it("waits for edit bootstrap before deciding whether a cold launch replaces an ongoing edit", async () => {
    // Edit bootstrap resumes an ongoing session; a launch that arrives before
    // it settles must still get the replacement question, not silently join.
    let releaseCreate!: () => void;
    const held = new Promise<void>((resolve) => {
      releaseCreate = resolve;
    });
    const ongoing = makeSession({
      session_id: "e-ongoing",
      target_kind: "edit",
      flow_id: "flow-1",
      conversation: [
        userMessage("u1", "Byt rubrik på rapporten"),
        assistantMessage("a1", "Vad ska rubriken vara?")
      ]
    });
    const fresh = editSession();
    let posts = 0;
    const { fetch } = makeFetch({ sessions: [ongoing, fresh] });
    const baseFetch = fetch.getMockImplementation()!;
    fetch.mockImplementation(async (path, init) => {
      if (path === SESSIONS_ROUTE && init?.method === "post") {
        posts += 1;
        if (posts === 1) {
          await held;
          return ongoing;
        }
        return fresh;
      }
      return baseFetch(path, init);
    });
    const { stream, calls } = makeStream();
    const { builder } = renderShell({ fetch, stream, targetKind: "edit", flowId: "flow-1" });

    await waitFor(() => expect(builder()).toBeDefined());
    const launched = builder().focusSavedFlowStep(SAVED_STEP_SCOPE);
    releaseCreate();
    await launched;

    expect(await screen.findByText(m.ai_builder_replace_edit_title())).toBeTruthy();
    expect(screen.queryByText(SAVED_STEP_LABEL)).toBeNull();

    await fireEvent.click(button(m.ai_builder_replace_edit_action()));

    expect(await screen.findByText(SAVED_STEP_LABEL)).toBeTruthy();
    const secondPost = fetch.mock.calls.filter(
      ([path, init]) => path === SESSIONS_ROUTE && init?.method === "post"
    )[1];
    expect(secondPost?.[1]?.requestBody?.["application/json"]).toMatchObject({
      force_new: true,
      target_kind: "edit"
    });
    const input = (await screen.findByRole("textbox", {
      name: m.ai_builder_saved_step_prompt_placeholder()
    })) as HTMLTextAreaElement;
    await fireEvent.input(input, { target: { value: "Byt rubrik" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({ edit_context: SAVED_STEP_SCOPE.editContext });
  });

  it("treats a plan-only resumed edit session as ongoing before its plan has loaded", async () => {
    let releaseCreate!: () => void;
    const held = new Promise<void>((resolve) => {
      releaseCreate = resolve;
    });
    // Empty conversation but a latest plan: the plan fetch happens after the
    // session is published, so the launch decision must read the session fact.
    const planOnly = makeSession({
      session_id: "e-plan-only",
      target_kind: "edit",
      flow_id: "flow-1",
      status: "awaiting_approval",
      latest_plan_id: PLAN_ID,
      conversation: []
    });
    const fresh = editSession();
    let posts = 0;
    const { fetch } = makeFetch({
      sessions: [planOnly, fresh],
      plans: { [PLAN_ID]: PLAN_RESPONSE }
    });
    const baseFetch = fetch.getMockImplementation()!;
    fetch.mockImplementation(async (path, init) => {
      if (path === SESSIONS_ROUTE && init?.method === "post") {
        posts += 1;
        if (posts === 1) {
          await held;
          return planOnly;
        }
        return fresh;
      }
      return baseFetch(path, init);
    });
    const { stream } = makeStream();
    const { builder } = renderShell({ fetch, stream, targetKind: "edit", flowId: "flow-1" });

    await waitFor(() => expect(builder()).toBeDefined());
    const launched = builder().focusSavedFlowStep(SAVED_STEP_SCOPE);
    releaseCreate();
    await launched;

    expect(await screen.findByText(m.ai_builder_replace_edit_title())).toBeTruthy();
    expect(screen.queryByText(SAVED_STEP_LABEL)).toBeNull();
    await fireEvent.click(button(m.ai_builder_replace_edit_action()));
    expect(await screen.findByText(SAVED_STEP_LABEL)).toBeTruthy();
    const secondPost = fetch.mock.calls.filter(
      ([path, init]) => path === SESSIONS_ROUTE && init?.method === "post"
    )[1];
    expect(secondPost?.[1]?.requestBody?.["application/json"]).toMatchObject({ force_new: true });
  });

  it("asks before replacing an ongoing edit and starts fresh on confirm", async () => {
    const { fetch, posts } = makeFetch({ created: editSession() });
    const { service, builder } = renderShell({
      fetch,
      stream: makeStream().stream,
      targetKind: "edit",
      flowId: "flow-1"
    });

    await waitFor(() => expect(service().hasSession).toBe(true));
    await waitFor(() => expect(builder()).toBeDefined());
    service().seedState({
      messages: [{ role: "user", content: "Pågående ändring", timestamp: Date.now() }]
    });
    await waitFor(() => expect(service().messages).toHaveLength(1));

    await builder().focusSavedFlowStep(SAVED_STEP_SCOPE);
    expect(await screen.findByText(m.ai_builder_replace_edit_title())).toBeTruthy();
    await fireEvent.click(button(m.ai_builder_replace_edit_cancel()));
    await waitFor(() => expect(screen.queryByText(m.ai_builder_replace_edit_title())).toBeNull());
    expect(posts).toHaveLength(1);

    await builder().focusSavedFlowStep(SAVED_STEP_SCOPE);
    await fireEvent.click(
      await screen.findByRole("button", { name: m.ai_builder_replace_edit_action() })
    );

    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1]).toMatchObject({ target_kind: "edit", force_new: true });
    expect(await screen.findByText(SAVED_STEP_LABEL)).toBeTruthy();
  });
});

// ---- Turn recovery and errors -------------------------------------------------------

describe("FlowAIBuilder turn recovery", () => {
  it("offers a safe exact retry when no provider work started", async () => {
    const { fetch } = makeFetch({ sessions: [turnSession("failed_before_provider")] });
    const { stream, calls } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-turn" });

    expect(await screen.findByText(m.ai_builder_turn_failed_before_provider_title())).toBeTruthy();
    await fireEvent.click(button(m.ai_builder_turn_retry()));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      client_turn_id: TURN_ID,
      message: "Build a flow",
      acknowledge_duplicate_provider_spend: false
    });
  });

  it("requires explicit cost acknowledgement for an unknown provider outcome", async () => {
    const { fetch } = makeFetch({ sessions: [turnSession("provider_outcome_unknown")] });
    const { stream, calls } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-turn" });

    expect(
      await screen.findByText(m.ai_builder_turn_provider_outcome_unknown_description())
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: m.ai_builder_turn_retry() })).toBeNull();
    await fireEvent.click(button(m.ai_builder_turn_retry_with_cost_acknowledgement()));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      client_turn_id: TURN_ID,
      acknowledge_duplicate_provider_spend: true
    });
  });

  it("explains an active durable turn and refreshes before enabling another message", async () => {
    const { fetch } = makeFetch({ sessions: [turnSession("processing")] });
    const { stream, calls } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-turn" });

    expect(await screen.findByText(m.ai_builder_turn_active_title())).toBeTruthy();
    // A turn the server is still working on is a wait: the screen reads as
    // waiting rather than offering a composer that refuses what is typed.
    expect(screen.getByText(m.ai_builder_reply_reading())).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();

    await fireEvent.click(button(m.refresh()));

    await waitFor(() => expect(textbox().disabled).toBe(false));
    expect(calls).toHaveLength(0);
  });

  it("offers a fresh session after an unsupported architecture in create mode", async () => {
    const { fetch, posts } = makeFetch({
      sessions: [questionSession()],
      created: makeSession({ session_id: "s-fresh" })
    });
    const { service } = renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });
    await screen.findByRole("heading", { name: FORMAT_QUESTION.question });

    service().seedState({
      streamState: "idle",
      error: {
        schema_version: 2,
        code: "unsupported_architecture",
        category: "bad_request",
        message: "Server fallback message",
        phase: "planner",
        eneo_error_code: 9007,
        request_id: "request-unsupported-architecture",
        diagnostic_context: null,
        details: {}
      }
    });

    expect(await screen.findByText(m.ai_builder_unsupported_architecture_title())).toBeTruthy();
    expect(screen.queryByText("Server fallback message")).toBeNull();
    await fireEvent.click(button(m.ai_builder_start_fresh()));

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({ target_kind: "create", force_new: true });
    expect(await screen.findByRole("heading", { name: m.ai_builder_task_title() })).toBeTruthy();
  });
});

// ---- Composer draft persistence ------------------------------------------------------

describe("FlowAIBuilder composer drafts", () => {
  it("persists the draft per session and restores it on remount", async () => {
    renderShell({ fetch: makeFetch().fetch, stream: makeStream().stream });
    await screen.findByRole("heading", { name: m.ai_builder_task_title() });

    await fireEvent.input(textbox(), { target: { value: "Utkast som ska överleva" } });
    await waitFor(() => expect(draftRecord("s-1")?.text).toBe("Utkast som ska överleva"));

    cleanup();
    renderShell({ fetch: makeFetch().fetch, stream: makeStream().stream });

    expect(await screen.findByDisplayValue("Utkast som ska överleva")).toBeTruthy();
  });

  it("keeps the draft in the composer and in storage when the send fails", async () => {
    const { fetch } = makeFetch();
    const { stream, calls } = makeStream(() => new Error("stream transport down"));
    renderShell({ fetch, stream });

    await sendTask("Får inte försvinna");

    await waitFor(() => expect(calls).toHaveLength(1));
    await waitFor(() => expect(textbox().value).toBe("Får inte försvinna"));
    expect(draftRecord("s-1")?.text).toBe("Får inte försvinna");
  });

  it("never leaks a draft across a live session switch (A→B→A)", async () => {
    const { fetch } = makeFetch({
      sessions: [makeSession({ session_id: "s-a" }), makeSession({ session_id: "s-b" })]
    });
    const { service } = renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-a" });
    await screen.findByRole("heading", { name: m.ai_builder_task_title() });

    await fireEvent.input(textbox(), { target: { value: "Utkast för session A" } });
    await waitFor(() => expect(draftRecord("s-a")?.text).toBe("Utkast för session A"));

    await service().resumeSession("s-b");
    await waitFor(() => expect(textbox().value).toBe(""));
    expect(draftRecord("s-b")).toBeNull();
    expect(draftRecord("s-a")?.text).toBe("Utkast för session A");

    await fireEvent.input(textbox(), { target: { value: "Utkast för session B" } });
    await service().resumeSession("s-a");
    await waitFor(() => expect(textbox().value).toBe("Utkast för session A"));
    expect(draftRecord("s-b")?.text).toBe("Utkast för session B");
  });
});
