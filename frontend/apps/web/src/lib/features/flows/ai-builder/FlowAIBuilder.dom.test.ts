import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";

const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
vi.mock("$lib/components/toast", () => ({ toast: toastMock }));

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
import type { AIBuilderModel, AIBuilderSavedFlowStepScope, RequirementsSummary } from "./protocol";
import type { StructuredQuestion } from "./structuredQuestionAnswer";

// ---- Routes and fixtures ----------------------------------------------------

const SESSIONS_ROUTE = "/api/v1/flows/ai-builder/sessions";
const CLIENT_ERRORS_ROUTE = "/api/v1/flows/ai-builder/client-errors";
// A published version with one run and nothing to point at: enough for the
// findings screen to own the phase.
const RUN_FAILURE_LAUNCH = {
  reference: {
    kind: "run_failure",
    flow_version: 2,
    definition_checksum: "sum-2",
    run_id: "run-1",
    step_order: 1
  },
  evidence_classification_level: 0,
  step_number: 1,
  step_name: "Steg",
  attempt_no: 1,
  error_code: "typed_io_output_parse_failed"
};

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
    omitted: { other_version: 0, not_viewable: 0, level_unknown: 0, overflow: 0 },
    admission: []
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
    {
      id: DEFAULT_MODEL_ID,
      name: "Test model",
      provider: "openai",
      reasoning_effort_options: [],
      availability: { state: "ready" }
    }
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
  status: "chatting" | "awaiting_approval" | "applied";
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
  /** The client error endpoint rejects every report. */
  telemetryDown?: boolean;
  /** Session ids whose Nth GET (1-based) rejects. */
  failRead?: Record<string, number>;
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
  /** Client error observations, in the order the driver sent them. */
  const reports: Record<string, unknown>[] = [];
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
      if (path.includes("/run-failures/")) return RUN_FAILURE_LAUNCH;
      if (path === SESSIONS_ROUTE && init?.method === "get") return { sessions: [] };
      if (path === SESSIONS_ROUTE && init?.method === "post") {
        posts.push(init.requestBody!["application/json"]);
        const created = options.created ?? makeSession();
        // The server answers a create with the full session, so a scripted
        // read sequence for the same id starts at the POST: its first state is
        // the created session and later states are what authoritative
        // refreshes return.
        if (!byId.has(created.session_id)) byId.set(created.session_id, created);
        const entry = byId.get(created.session_id)!;
        reads.set(created.session_id, 1);
        return Array.isArray(entry) ? entry[0]! : entry;
      }
      if (path === SESSION_ROUTE) {
        const id = init?.params?.path?.session_id ?? "";
        if (failOnce.delete(id)) throw new Error("The saved draft could not be loaded.");
        const entry = byId.get(id);
        if (!entry) throw new Error(`Unknown session ${id}`);
        const count = (reads.get(id) ?? 0) + 1;
        reads.set(id, count);
        if (options.failRead?.[id] === count)
          throw new Error("The session could not be refreshed.");
        return Array.isArray(entry) ? entry[Math.min(count, entry.length) - 1] : entry;
      }
      if (path === PLAN_ROUTE) {
        const plan = options.plans?.[init?.params?.path?.plan_id ?? ""];
        if (!plan) throw new Error("Unknown plan");
        return plan;
      }
      if (path === CLIENT_ERRORS_ROUTE) {
        if (options.telemetryDown) throw new Error("telemetry down");
        reports.push(init?.requestBody?.["application/json"] ?? {});
        return undefined;
      }
      throw new Error(`Unexpected request: ${path}`);
    }
  );
  return { fetch, posts, reports };
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
  /** End the stream the way a dropped connection does: the transport rejects. */
  fail: (error: Error) => void;
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
          },
          fail: reject
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
  flowIsPublished?: boolean;
  stepChoices?: { id: string; name: string; order: number }[] | null;
  onpackage?: (detail: { file: File; text: string }) => void;
}

function renderShell({ fetch, stream, ...props }: ShellProps) {
  let service: FlowAIBuilderService | undefined;
  let builder:
    | {
        focusSavedFlowStep: (scope: AIBuilderSavedFlowStepScope) => Promise<void>;
        openReview: () => Promise<void>;
        launchFailureRepair: (target: { runId: string; stepOrder: number }) => Promise<void>;
        carryRequest: (request: { text: string; requireStepScope: boolean }) => void;
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

  it("retries a failed session bootstrap from the failure panel", async () => {
    const created = makeSession({ session_id: "e-1", target_kind: "edit", flow_id: "flow-1" });
    let posts = 0;
    const { fetch } = makeFetch({ created });
    const baseFetch = fetch.getMockImplementation()!;
    fetch.mockImplementation(async (path, init) => {
      if (path === SESSIONS_ROUTE && init?.method === "post") {
        posts += 1;
        if (posts === 1) throw new Error("create refused");
      }
      return baseFetch(path, init);
    });
    const { service } = renderShell({
      fetch,
      stream: makeStream().stream,
      targetKind: "edit",
      flowId: "flow-1"
    });

    // No skeleton and no dead end: the failure announces itself as an alert
    // with a heading and offers a retry.
    expect(
      await screen.findByRole("heading", { name: m.ai_builder_bootstrap_failed_title() })
    ).toBeTruthy();
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(service().isInitializing).toBe(false);
    expect(screen.getByRole("link", { name: m.ai_builder_resume_failed_back() })).toBeTruthy();

    await fireEvent.click(button(m.ai_builder_turn_retry()));

    await waitFor(() => expect(service().hasSession).toBe(true));
    expect(posts).toBe(2);
    expect(screen.queryByText(m.ai_builder_bootstrap_failed_title())).toBeNull();
  });

  it("keeps the failure panel when starting a new task from a failed draft is refused", async () => {
    let posts = 0;
    const { fetch } = makeFetch({ failOnce: ["s-1"], created: makeSession({ session_id: "s-2" }) });
    const baseFetch = fetch.getMockImplementation()!;
    fetch.mockImplementation(async (path, init) => {
      if (path === SESSIONS_ROUTE && init?.method === "post") {
        posts += 1;
        if (posts === 1) throw new Error("create refused");
      }
      return baseFetch(path, init);
    });
    const { service } = renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });
    await screen.findByRole("heading", { name: m.ai_builder_resume_failed_title() });

    await fireEvent.click(button(m.ai_builder_resume_failed_new()));

    // The escape failed too: the same panel, now for the session attempt. A
    // create is an unconditional insert, so no Retry is offered here (a lost
    // response may already have persisted a draft); the Flows list is the way
    // back, and no second create is sent.
    expect(
      await screen.findByRole("heading", { name: m.ai_builder_bootstrap_failed_title() })
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: m.ai_builder_resume_failed_back() })).toBeTruthy();
    expect(screen.queryByRole("button", { name: m.ai_builder_turn_retry() })).toBeNull();
    expect(screen.queryByRole("button", { name: m.ai_builder_resume_failed_new() })).toBeNull();
    expect(service().hasSession).toBe(false);
    expect(posts).toBe(1);
  });

  it("shows a failed bootstrap before the draft list refresh settles", async () => {
    let releaseDrafts!: () => void;
    const heldDrafts = new Promise<void>((resolve) => {
      releaseDrafts = resolve;
    });
    const { fetch } = makeFetch({});
    const baseFetch = fetch.getMockImplementation()!;
    let posts = 0;
    fetch.mockImplementation(async (path, init) => {
      if (path === SESSIONS_ROUTE && init?.method === "post") {
        posts += 1;
        throw new Error("create refused");
      }
      if (path === SESSIONS_ROUTE && init?.method === "get" && posts > 0) await heldDrafts;
      return baseFetch(path, init);
    });
    renderShell({ fetch, stream: makeStream().stream, targetKind: "edit", flowId: "flow-1" });

    expect(
      await screen.findByRole("heading", { name: m.ai_builder_bootstrap_failed_title() })
    ).toBeTruthy();
    releaseDrafts();
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
                reasoning_effort_options: reasoning,
                availability: { state: "ready" }
              },
              {
                id: SECOND_MODEL_ID,
                name: "Second model",
                provider: "openai",
                reasoning_effort_options: [],
                availability: { state: "ready" }
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
    // No choice to make, but the model that runs is still named.
    expect((await screen.findByTestId("ai-builder-shown-model")).textContent).toContain(
      "Test model"
    );
  });

  it("says the model list is loading instead of showing nothing", async () => {
    const { fetch } = makeFetch();
    const pending = vi.fn(async (path: string, init?: Record<string, unknown>) =>
      path.endsWith("/models") ? new Promise(() => {}) : fetch(path as string, init as never)
    );
    const { service } = renderShell({ fetch: pending, stream: makeStream().stream });

    expect(await screen.findByText(m.ai_builder_models_loading())).toBeTruthy();
    expect(service().modelSendBlock).toBe("models_loading");
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

  it("says so and retries when the model read fails, keeping typing open but starting no turn", async () => {
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
            reasoning_effort_options: [],
            availability: { state: "ready" }
          },
          {
            id: SECOND_MODEL_ID,
            name: "Second model",
            provider: "openai",
            reasoning_effort_options: [],
            availability: { state: "ready" }
          }
        ],
        default_model_id: DEFAULT_MODEL_ID
      };
    });
    const { service } = renderShell({ fetch: flaky, stream: makeStream().stream });

    expect(await screen.findByText(m.failed_to_load_models())).toBeTruthy();
    // The failure explains itself. Typing stays open, but no turn starts
    // until a listing names the model it would run.
    await waitFor(() => expect(service().canSendMessage).toBe(true));
    expect(service().modelSendBlock).toBe("models_failed");

    await fireEvent.click(button(m.retry()));

    expect(
      await screen.findByRole("button", {
        name: `${m.ai_builder_model_label()}: Test model`
      })
    ).toBeTruthy();
    expect(screen.queryByText(m.failed_to_load_models())).toBeNull();
    expect(service().modelSendBlock).toBeNull();
  });

  it("names the retained retry model while the model listing reload is pending", async () => {
    const sessions = turnSession("failed_before_provider").map((session) => ({
      ...session,
      latest_turn: {
        ...session.latest_turn,
        retry_request: { ...session.latest_turn.retry_request, model_id: DEFAULT_MODEL_ID }
      }
    }));
    const { fetch } = makeFetch({ sessions: [sessions] });
    let release!: () => void;
    const held = new Promise<void>((resolve) => (release = resolve));
    let modelReads = 0;
    const slow = vi.fn(async (path: string, init?: Record<string, unknown>) => {
      if (path.endsWith("/models") && ++modelReads > 1) await held;
      return fetch(path, init as never);
    });
    const { stream, calls } = makeStream(() => "hold");
    const { service } = renderShell({ fetch: slow, stream, resumeSessionId: "s-turn" });
    await waitFor(() => expect(service().effectiveModel?.id).toBe(DEFAULT_MODEL_ID));
    service().selectModel(DEFAULT_MODEL_ID);
    const modelName = service().effectiveModel!.name;
    service().seedState({ modelLoadStatus: "failed" });
    const failedListing = (await screen.findByText(m.failed_to_load_models())).closest(
      "[role=alert]"
    )! as HTMLElement;
    await fireEvent.click(within(failedListing).getByRole("button", { name: m.retry() }));
    try {
      expect(await screen.findByText(m.ai_builder_models_loading())).toBeTruthy();
      const retry = button(m.ai_builder_turn_retry());
      expect(retry.disabled).toBe(false);
      expect(screen.getByTestId("ai-builder-shown-model").textContent).toContain(modelName);
      await fireEvent.click(retry);
      await waitFor(() => expect(calls).toHaveLength(1));
      expect(calls[0]!.body).toMatchObject({ model_id: DEFAULT_MODEL_ID, client_turn_id: TURN_ID });
      calls[0]!.finish();
    } finally {
      release();
    }
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

  /** A space whose listing carries models without declared capacity. */
  function withUnreadyModels(
    defaultReady: boolean,
    availability: AIBuilderModel["availability"] = {
      state: "capacity_undeclared",
      missing_dimensions: ["max_input_tokens"]
    }
  ) {
    const { fetch } = makeFetch();
    const unready = {
      provider: "openai",
      reasoning_effort_options: [],
      availability
    };
    return vi.fn(async (path: string, init?: Record<string, unknown>) =>
      path.endsWith("/models")
        ? {
            models: [
              defaultReady
                ? {
                    id: DEFAULT_MODEL_ID,
                    name: "Test model",
                    provider: "openai",
                    reasoning_effort_options: [],
                    availability: { state: "ready" }
                  }
                : { ...unready, id: DEFAULT_MODEL_ID, name: "Test model" },
              { ...unready, id: SECOND_MODEL_ID, name: "Second model" }
            ],
            default_model_id: defaultReady ? DEFAULT_MODEL_ID : null
          }
        : fetch(path as string, init as never)
    );
  }

  it("lists a model without declared capacity as disabled, with the reason, and never selects it", async () => {
    const { service } = renderShell({
      fetch: withUnreadyModels(true),
      stream: makeStream().stream
    });

    await fireEvent.click(
      await screen.findByRole("button", { name: `${m.ai_builder_model_label()}: Test model` })
    );
    const option = await screen.findByRole("option", { name: /Second model/ });
    expect(option.getAttribute("aria-disabled")).toBe("true");
    expect(within(option).getByText(m.ai_builder_model_capacity_undeclared_short())).toBeTruthy();

    await fireEvent.click(option);

    expect(service().effectiveModel?.id).toBe(DEFAULT_MODEL_ID);
    expect(service().modelSendBlock).toBeNull();
  });

  it("lists a too-small model disabled with its reason and keeps the picker enabled", async () => {
    const { service } = renderShell({
      fetch: withUnreadyModels(true, { state: "capacity_too_small" }),
      stream: makeStream().stream
    });
    const trigger = (await screen.findByRole("button", {
      name: `${m.ai_builder_model_label()}: Test model`
    })) as HTMLButtonElement;
    expect(trigger.disabled).toBe(false);
    await fireEvent.click(trigger);
    const option = await screen.findByRole("option", { name: /Second model/ });
    expect(option.getAttribute("aria-disabled")).toBe("true");
    expect(within(option).getByText(m.ai_builder_model_capacity_too_small_short())).toBeTruthy();
    await fireEvent.click(option);
    expect(service().effectiveModel?.id).toBe(DEFAULT_MODEL_ID);
  });

  it("says why and starts no turn while no listed model is ready, with the picker and typing still open", async () => {
    const { stream, calls } = makeStream(() => "hold");
    renderShell({ fetch: withUnreadyModels(false), stream });

    expect(await screen.findByText(m.ai_builder_no_ready_model())).toBeTruthy();
    const trigger = screen.getByRole("button", {
      name: `${m.ai_builder_model_label()}: ${m.choose_a_completion_model()}`
    }) as HTMLButtonElement;
    expect(trigger.disabled).toBe(false);

    await screen.findByRole("heading", { name: m.ai_builder_task_title() });
    const input = textbox() as HTMLTextAreaElement;
    expect(input.disabled).toBe(false);
    await fireEvent.input(input, { target: { value: "Sammanfatta rapporter" } });
    const send = button(m.ai_builder_send());
    expect(send.disabled).toBe(true);
    await fireEvent.click(send);

    expect(calls).toHaveLength(0);
    expect(input.value).toBe("Sammanfatta rapporter");
  });
});

describe("FlowAIBuilder discovery screens", () => {
  it.each([
    ["question", "custom"],
    ["question", "fields"],
    ["confirm", "custom"],
    ["confirm", "fields"]
  ] as const)(
    "keeps %s %s answers editable while model submission is blocked",
    async (view, kind) => {
      const pending =
        kind === "custom"
          ? CUSTOM_QUESTION
          : question(
              "runtime_metadata_field_details",
              "Vad ska den som kör flödet fylla i?",
              [{ id: "interpret_input", label: "Använd för att förstå indata" }],
              {
                input_field_collection: true,
                options: [
                  {
                    id: "interpret_input",
                    label: "Använd för att förstå indata",
                    value: "interpret_input"
                  }
                ]
              }
            );
      const savedAnswer =
        kind === "custom"
          ? { custom_value: "Hela nämnden" }
          : {
              input_fields: [
                {
                  value: { name: "ort", label: "Ort", type: "text", required: false, options: [] },
                  purpose: "interpret_input"
                }
              ]
            };
      const session =
        view === "question"
          ? questionSession(pending)
          : makeSession({
              conversation: [
                userMessage("u1", "Sammanfatta rapporter"),
                assistantMessage("a1", "", { question: pending }),
                userMessage("u2", "Tidigare svar", {
                  question_answer: {
                    kind: "structured_question_answer",
                    question_id: pending.question_id,
                    ...savedAnswer
                  }
                }),
                assistantMessage("a2", "", {
                  requirements_summary: {
                    ...SUMMARY,
                    key_decisions: [
                      { topic: "Svar", decision: "Tidigare svar", question_id: pending.question_id }
                    ]
                  }
                })
              ]
            });
      const { fetch } = makeFetch({ sessions: [session] });
      const { stream, calls } = makeStream(() => "hold");
      const { service } = renderShell({ fetch, stream, resumeSessionId: "s-1" });
      await waitFor(() => expect(service().effectiveModel?.id).toBe(DEFAULT_MODEL_ID));
      service().selectModel(DEFAULT_MODEL_ID);
      const readyModel = service().effectiveModel!;
      service().seedState({
        availableModels: [{ ...readyModel, availability: { state: "capacity_too_small" } }]
      });
      if (view === "confirm") {
        const edit = (await screen.findByRole("button", {
          name: m.ai_builder_confirm_change_row_aria({ topic: "Svar" })
        })) as HTMLButtonElement;
        expect(edit.disabled).toBe(false);
        await fireEvent.click(edit);
      } else if (kind === "custom") {
        await fireEvent.click(
          (await screen.findByText(m.ai_builder_question_custom())).closest("label")!
        );
      }
      const input = await screen.findByRole("textbox", {
        name:
          kind === "custom" ? m.ai_builder_question_custom() : m.ai_builder_question_field_label()
      });
      await waitFor(() => expect(service().modelSendBlock).toBe("model_capacity_too_small"));
      expect((input as HTMLInputElement).disabled).toBe(false);
      await fireEvent.input(input, { target: { value: "Nytt svar" } });
      if (kind === "fields") {
        const purpose = screen.getByLabelText(
          m.ai_builder_question_field_purpose()
        ) as HTMLSelectElement;
        expect(purpose.disabled).toBe(false);
        await fireEvent.change(purpose, { target: { value: "interpret_input" } });
      }
      const confirm = button(m.ai_builder_question_confirm());
      expect(confirm.getAttribute("aria-disabled")).toBe("true");
      expect(screen.getAllByText(service().modelSendBlockMessage!).length).toBeGreaterThan(0);
      await fireEvent.click(confirm);
      await fireEvent.keyDown(input, { key: "Enter" });
      expect(calls).toHaveLength(0);
      expect((input as HTMLInputElement).value).toBe("Nytt svar");
      service().seedState({ availableModels: [readyModel] });
      await waitFor(() => expect(confirm.getAttribute("aria-disabled")).toBe("false"));
      await fireEvent.click(confirm);
      await waitFor(() => expect(calls).toHaveLength(1));
      expect(calls[0]!.body).toMatchObject({
        model_id: DEFAULT_MODEL_ID,
        question_answer:
          kind === "custom"
            ? { custom_value: "Nytt svar" }
            : { input_fields: [{ value: { label: "Nytt svar" }, purpose: "interpret_input" }] }
      });
      calls[0]!.finish();
    }
  );

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
    // Every placeholder is inspectable without a pointer: the long list sits
    // behind a disclosure button the keyboard can open.
    const placeholderToggle = within(rows).getByRole("button", {
      name: (name) => name.includes(m.ai_builder_attachment_placeholders({ count: "5" }))
    });
    expect(placeholderToggle.getAttribute("aria-expanded")).toBe("false");
    await fireEvent.click(placeholderToggle);
    await waitFor(() => expect(placeholderToggle.getAttribute("aria-expanded")).toBe("true"));
    expect(rows.textContent).toContain("beslutsfattare");
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

  it("leaves out run-preview lines that repeat a decision, and the preview when nothing is new", async () => {
    const preview = (runtime: string) => ({
      ...SUMMARY,
      run_preview: {
        runtime_input: "documents",
        runtime_input_label: runtime,
        max_files: null,
        result_type: "pdf_document",
        // The fixture's own decision: "Slutresultat: PDF-dokument".
        result_type_label: "PDF-dokument",
        report_layout: null,
        report_layout_label: null,
        template: null
      }
    });
    const render = (runtime: string) => {
      const { fetch } = makeFetch({
        sessions: [
          makeSession({
            conversation: [
              userMessage("u1", "Sammanfatta underlaget"),
              assistantMessage("a1", "Här är min tolkning.", {
                requirements_summary: {
                  ...preview(runtime),
                  key_decisions: [
                    ...SUMMARY.key_decisions,
                    { topic: "Indata vid körning", decision: "Text" }
                  ]
                }
              })
            ]
          })
        ]
      });
      const { stream } = makeStream();
      renderShell({ fetch, stream, resumeSessionId: "s-1" });
    };

    render("Dokument");
    const shown = await screen.findByTestId("run-preview");
    expect(shown.textContent).toContain("Dokument");
    expect(shown.textContent).not.toContain("PDF-dokument");
    cleanup();

    render("Text");
    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    expect(screen.queryByTestId("run-preview")).toBeNull();
  });

  it("names the edited flow's own template in the run preview with its origin", async () => {
    // An edit of a bound template-fill flow attaches nothing; the card still
    // shows the one template a run fills and says it comes from the flow.
    const typed = {
      ...SUMMARY,
      attachment_rows: [],
      run_preview: {
        runtime_input: "documents",
        runtime_input_label: "Dokument",
        max_files: null,
        result_type: "docx_document",
        result_type_label: "Word-dokument",
        report_layout: null,
        report_layout_label: null,
        template: { filename: "motesrapport.docx", placeholder_count: 2, origin: "flow" }
      }
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Döp om sammanfattningssteget"),
            assistantMessage("a1", "Här är min tolkning.", { requirements_summary: typed })
          ]
        })
      ]
    });
    const { stream } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    const preview = await screen.findByTestId("run-preview");
    expect(preview.textContent).toContain("motesrapport.docx");
    expect(preview.textContent).toContain(m.ai_builder_attachment_placeholders({ count: "2" }));
    expect(preview.textContent).toContain(m.ai_builder_run_preview_template_from_flow());
    expect(screen.queryByTestId("attachment-rows")).toBeNull();
  });

  it("says when a session template replaces the flow's own", async () => {
    const typed = {
      ...SUMMARY,
      attachment_rows: [
        {
          file_id: "00000000-0000-0000-0000-000000000801",
          filename: "ny-mall.docx",
          role: "template",
          readable: true,
          coverage: "fully_seen",
          travels: true,
          placeholders: ["datum"]
        }
      ],
      run_preview: {
        runtime_input: "documents",
        runtime_input_label: "Dokument",
        max_files: null,
        result_type: "docx_document",
        result_type_label: "Word-dokument",
        report_layout: null,
        report_layout_label: null,
        template: { filename: "ny-mall.docx", placeholder_count: 1, origin: "replacement" }
      }
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Byt mall"),
            assistantMessage("a1", "Här är min tolkning.", { requirements_summary: typed })
          ]
        })
      ]
    });
    const { stream } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    const rows = await screen.findByTestId("attachment-rows");
    expect(rows.textContent).toContain(m.ai_builder_attachment_replaces_flow_template());
    expect(rows.textContent).not.toContain(m.ai_builder_attachment_travels());
    const preview = screen.getByTestId("run-preview");
    expect(preview.textContent).toContain("ny-mall.docx");
    expect(preview.textContent).toContain(m.ai_builder_run_preview_template_replaces_flow());
  });

  it("names a flow template bound before publish generically", async () => {
    const typed = {
      ...SUMMARY,
      attachment_rows: [],
      run_preview: {
        runtime_input: "documents",
        runtime_input_label: "Dokument",
        max_files: null,
        result_type: "docx_document",
        result_type_label: "Word-dokument",
        report_layout: null,
        report_layout_label: null,
        template: { filename: null, placeholder_count: 1, origin: "flow" }
      }
    };
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Ändra steget"),
            assistantMessage("a1", "Här är min tolkning.", { requirements_summary: typed })
          ]
        })
      ]
    });
    const { stream } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    const preview = await screen.findByTestId("run-preview");
    expect(preview.textContent).toContain(m.ai_builder_run_preview_template_unnamed());
    expect(preview.textContent).toContain(m.ai_builder_run_preview_template_from_flow());
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
      ],
      plans: { [PLAN_ID]: PLAN_RESPONSE }
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

  it("blocks delegation with the model reason until the model is ready", async () => {
    const recommended = { ...FORMAT_QUESTION, recommended_option_id: "pdf" };
    const { fetch } = makeFetch({ sessions: [questionSession(recommended)] });
    const { stream, calls } = makeStream(() => "hold");
    const { service } = renderShell({ fetch, stream, resumeSessionId: "s-1" });
    const delegate = (await screen.findByRole("button", {
      name: m.ai_builder_question_delegate()
    })) as HTMLButtonElement;
    for (const modelLoadStatus of ["loading", "failed"] as const) {
      service().seedState({ modelLoadStatus });
      await waitFor(() => expect(delegate.disabled).toBe(true));
      expect(screen.getAllByText(service().modelSendBlockMessage!).length).toBeGreaterThan(0);
      await fireEvent.click(delegate);
      expect(calls).toHaveLength(0);
      expect((screen.getByRole("radio", { name: /Som text/ }) as HTMLButtonElement).disabled).toBe(
        false
      );
    }
    service().seedState({ modelLoadStatus: "loaded" });
    await waitFor(() => expect(delegate.disabled).toBe(false));
    await fireEvent.click(delegate);
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      question_answer: { kind: "delegated_question_answer", question_id: "output_format" }
    });
    calls[0]!.finish();
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

    const customRow = (await screen.findByText(m.ai_builder_question_custom())).closest("label")!;
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

  it("returns focus to the chip when a reopened answer is left unchanged", async () => {
    const { fetch } = makeFetch({ sessions: [answeredThenPendingSession()] });
    const { stream } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: SOURCES_QUESTION.question });
    const chip = screen.getByText("Som PDF").closest("button")!;
    await fireEvent.click(chip);

    // Opening hands the caret to the question being changed.
    const reopened = await screen.findByRole("heading", { name: FORMAT_QUESTION.question });
    await waitFor(() => expect(document.activeElement).toBe(reopened));

    // Cancelling hands it back to the chip, not to the top of the next screen.
    await fireEvent.click(button(m.cancel()));
    await screen.findByRole("heading", { name: SOURCES_QUESTION.question });
    await waitFor(() => expect(document.activeElement).toBe(chip));
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

  it("names the model on a resumed confirmation before it can be confirmed", async () => {
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter"),
            assistantMessage("a1", "", { requirements_summary: SUMMARY })
          ]
        })
      ]
    });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    const notice = await screen.findByTestId("ai-builder-model-notice");
    await waitFor(() =>
      expect(within(notice).getByTestId("ai-builder-shown-model").textContent).toContain(
        "Test model"
      )
    );
    expect(button(m.ai_builder_confirm_action()).disabled).toBe(false);
  });

  it("keeps the picker after a ready replacement is chosen and confirms with that model", async () => {
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter"),
            assistantMessage("a1", "", { requirements_summary: SUMMARY })
          ]
        })
      ]
    });
    const secondModelId = "11111111-1111-4111-8111-111111111198";
    const listing = vi.fn(async (path: string, init?: Record<string, unknown>) =>
      path.endsWith("/models")
        ? {
            models: [
              {
                id: DEFAULT_MODEL_ID,
                name: "Test model",
                provider: "openai",
                reasoning_effort_options: [],
                availability: {
                  state: "capacity_undeclared",
                  missing_dimensions: ["max_input_tokens"]
                }
              },
              {
                id: secondModelId,
                name: "Second model",
                provider: "openai",
                reasoning_effort_options: [],
                availability: { state: "ready" }
              }
            ],
            default_model_id: secondModelId
          }
        : fetch(path as string, init as never)
    );
    const { stream, calls } = makeStream(() => "hold");
    renderShell({ fetch: listing, stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    const notice = await screen.findByTestId("ai-builder-model-notice");
    await fireEvent.click(
      await within(notice).findByRole("button", {
        name: `${m.ai_builder_model_label()}: Second model`
      })
    );
    const option = await screen.findByRole("option", { name: /Second model/ });
    await fireEvent.click(option);

    expect(
      within(screen.getByTestId("ai-builder-model-notice")).getByRole("button", {
        name: `${m.ai_builder_model_label()}: Second model`
      })
    ).toBeTruthy();
    await fireEvent.click(button(m.ai_builder_confirm_action()));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({ model_id: secondModelId });
    calls[0]!.finish();
  });

  it("puts the model reason and picker on the confirmation and refuses its turn actions while no model can run", async () => {
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter"),
            assistantMessage("a1", "", { requirements_summary: SUMMARY })
          ]
        })
      ]
    });
    const unready = vi.fn(async (path: string, init?: Record<string, unknown>) =>
      path.endsWith("/models")
        ? {
            models: [
              {
                id: DEFAULT_MODEL_ID,
                name: "Test model",
                provider: "openai",
                reasoning_effort_options: [],
                availability: {
                  state: "capacity_undeclared",
                  missing_dimensions: ["max_input_tokens"]
                }
              }
            ],
            default_model_id: null
          }
        : fetch(path as string, init as never)
    );
    const { stream, calls } = makeStream(() => "hold");
    renderShell({ fetch: unready, stream, resumeSessionId: "s-1" });

    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    const notice = await screen.findByTestId("ai-builder-model-notice");
    expect(within(notice).getByText(m.ai_builder_no_ready_model())).toBeTruthy();
    expect(
      (
        within(notice).getByRole("button", {
          name: `${m.ai_builder_model_label()}: ${m.choose_a_completion_model()}`
        }) as HTMLButtonElement
      ).disabled
    ).toBe(false);

    const confirm = button(m.ai_builder_confirm_action());
    expect(confirm.disabled).toBe(true);
    await fireEvent.click(confirm);
    expect(calls).toHaveLength(0);
  });

  it("keeps an explicit too-small choice on the confirmation and preserves refused change-request text", async () => {
    const secondModelId = "11111111-1111-4111-8111-111111111198";
    const { fetch } = makeFetch({
      sessions: [
        makeSession({
          conversation: [
            userMessage("u1", "Sammanfatta rapporter"),
            assistantMessage("a1", "", { requirements_summary: SUMMARY })
          ]
        })
      ]
    });
    const { stream, calls } = makeStream(() => "hold");
    const { service } = renderShell({ fetch, stream, resumeSessionId: "s-1" });
    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    await waitFor(() => expect(service().effectiveModel?.id).toBe(DEFAULT_MODEL_ID));
    service().selectModel(DEFAULT_MODEL_ID);
    const model = service().effectiveModel!;
    service().seedState({
      availableModels: [
        { ...model, availability: { state: "capacity_too_small" } },
        { ...model, id: secondModelId, name: "Second model" }
      ],
      defaultModelId: secondModelId
    });
    const notice = await screen.findByTestId("ai-builder-model-notice");
    expect(await within(notice).findByText(m.ai_builder_model_capacity_too_small())).toBeTruthy();
    const trigger = within(notice).getByRole("button", {
      name: `${m.ai_builder_model_label()}: Test model`
    }) as HTMLButtonElement;
    expect(trigger.disabled).toBe(false);
    expect(button(m.ai_builder_confirm_action()).disabled).toBe(true);
    await fireEvent.click(screen.getByText(m.ai_builder_change_request_write()).closest("button")!);
    const box = (await screen.findByRole("textbox", {
      name: m.ai_builder_change_request_textarea_label()
    })) as HTMLTextAreaElement;
    expect(box.disabled).toBe(false);
    await fireEvent.input(box, { target: { value: "en PDF i stället" } });
    expect(button(m.ai_builder_send()).disabled).toBe(true);
    await fireEvent.click(button(m.ai_builder_send()));
    expect(box.value).toBe("en PDF i stället");
    expect(service().effectiveModel?.id).toBe(DEFAULT_MODEL_ID);
    expect(calls).toHaveLength(0);
    await fireEvent.click(trigger);
    await fireEvent.click(await screen.findByRole("option", { name: /Second model/ }));
    await fireEvent.click(button(m.ai_builder_send()));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({ model_id: secondModelId });
    expect(calls[0]!.body.message).toContain("en PDF i stället");
    calls[0]!.finish();
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

  it("hands focus to the reopened question and back to its chip when the edit closes", async () => {
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
    const { stream, calls } = makeStream(() => "hold");
    renderShell({ fetch, stream, resumeSessionId: "s-1" });

    const cardHeading = await screen.findByRole("heading", {
      name: m.ai_builder_requirements_title()
    });
    const chip = screen.getByText("Som PDF").closest("button")!;
    await fireEvent.click(chip);

    // The question opens above the card and takes the caret with it.
    const reopened = await screen.findByRole("heading", { name: FORMAT_QUESTION.question });
    await waitFor(() => expect(document.activeElement).toBe(reopened));

    // Cancelling returns to the chip, where the reader was.
    await fireEvent.click(button(m.cancel()));
    await waitFor(() => expect(document.activeElement).toBe(chip));

    // Answering locks the chip while the turn runs, so the card heading holds
    // the caret; the chip is still brought into view, never the top of the page.
    await fireEvent.click(chip);
    await fireEvent.click(await screen.findByRole("radio", { name: "Som text" }));
    await fireEvent.click(button(m.ai_builder_question_confirm()));
    await waitFor(() => expect(calls).toHaveLength(1));
    await waitFor(() => expect(document.activeElement).toBe(cardHeading));
    expect(chip.scrollIntoView).toHaveBeenLastCalledWith({ block: "nearest" });
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

  it("returns focus to the runtime-fields button that opened the editor, not the answer chip", async () => {
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
                      type: "text",
                      required: false,
                      options: []
                    },
                    purpose: "interpret_input"
                  }
                ]
              }
            }),
            assistantMessage("a2", "", {
              requirements_summary: {
                ...SUMMARY,
                runtime_input_fields: [{ key: "ort", label: "Ort", type: "text", required: false }]
              }
            })
          ]
        })
      ]
    });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-1" });
    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });

    // Both controls reopen the same question; the lower one is the origin here.
    const origins = document.querySelectorAll(
      '[data-edit-question="runtime_metadata_field_details"]'
    );
    expect(origins.length).toBeGreaterThan(1);
    // A pointer click: not every browser focuses a button on click, so the
    // origin must travel with the callback rather than be read from focus.
    const runtimeButton = button(m.ai_builder_requirements_runtime_fields_change());
    expect(document.activeElement).not.toBe(runtimeButton);
    await fireEvent.click(runtimeButton);
    await screen.findByLabelText(m.ai_builder_question_field_label());

    await fireEvent.click(button(m.cancel()));
    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    await waitFor(() => expect(document.activeElement).toBe(runtimeButton));
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

  // Every public failure class the server can report without a plan, plus the
  // one class only this client can see (a dropped connection). The card must
  // name what happened, offer the one step the driver allows, and observe
  // the failure once with the class shown and the user's first selection.
  const generationFailures: {
    name: string;
    error: Record<string, unknown> | Error;
    latestTurn: "committed" | "processing" | "provider_outcome_unknown";
    kind: string;
    heading: () => string;
    cause: () => string;
    primary: () => string;
    secondary: (() => string) | null;
    records: string;
  }[] = [
    {
      name: "a connection this client lost while the turn still runs",
      error: Object.assign(new Error("Failed to fetch"), { status: 0, stage: "CONNECTION" }),
      latestTurn: "processing",
      kind: "network_loss",
      heading: () => m.ai_builder_failure_heading_network_loss_generation(),
      cause: () => m.ai_builder_failure_cause_network_loss_turn_active(),
      primary: () => m.ai_builder_failure_action_refresh(),
      secondary: null,
      records: "refresh_requested"
    },
    {
      name: "a provider rejection",
      error: {
        code: "planner_upstream_error",
        category: "upstream",
        message: "The AI provider rejected this request. Start a new turn to try again.",
        details: {
          another_call_permitted: false,
          provider_disposition: "known_rejection",
          provider_exception_class: "bad_request",
          retry_scope: "new_turn"
        }
      },
      latestTurn: "committed",
      kind: "provider_rejected",
      heading: () => m.ai_builder_failure_heading_provider_rejected(),
      cause: () => m.ai_builder_failure_cause_provider_rejected(),
      primary: () => m.ai_builder_turn_retry(),
      secondary: () => m.ai_builder_failure_action_clarify(),
      records: "resend_requested"
    },
    {
      name: "an exhausted request budget",
      error: {
        code: "planner_context_limit_exceeded",
        category: "upstream",
        message: "The AI planner request exceeds its budget.",
        details: { another_call_permitted: false, retry_scope: "new_turn" }
      },
      latestTurn: "committed",
      kind: "request_budget_exhausted",
      heading: () => m.ai_builder_failure_heading_request_budget_exhausted(),
      cause: () => m.ai_builder_failure_cause_request_budget_exhausted(),
      primary: () => m.ai_builder_failure_action_shorten(),
      secondary: null,
      records: "conversation_opened"
    },
    {
      name: "a truncated model answer",
      error: {
        code: "planner_output_too_long",
        category: "upstream",
        message: "The AI planner output was cut off.",
        phase: "proposal"
      },
      latestTurn: "committed",
      kind: "output_too_long",
      heading: () => m.ai_builder_failure_heading_output_too_long(),
      cause: () => m.ai_builder_failure_cause_output_too_long(),
      primary: () => m.ai_builder_failure_action_shorten(),
      secondary: () => m.ai_builder_turn_retry(),
      records: "conversation_opened"
    },
    {
      name: "an invalid proposal after repairs",
      error: {
        code: "self_correction_invalid_plan",
        category: "internal",
        message: "The AI planner could not produce a valid plan.",
        phase: "self_correction"
      },
      latestTurn: "committed",
      kind: "invalid_proposal",
      heading: () => m.ai_builder_failure_heading_invalid_proposal(),
      cause: () => m.ai_builder_failure_cause_invalid_proposal(),
      primary: () => m.ai_builder_failure_action_clarify(),
      secondary: () => m.ai_builder_turn_retry(),
      records: "conversation_opened"
    },
    {
      name: "an unknown provider outcome",
      error: {
        code: "session_turn_provider_outcome_unknown",
        category: "upstream",
        message: "The provider outcome is unknown.",
        details: {
          another_call_permitted: false,
          provider_disposition: "provider_outcome_unknown",
          provider_exception_class: "timeout",
          retry_scope: "acknowledged_same_turn"
        }
      },
      latestTurn: "provider_outcome_unknown",
      kind: "provider_outcome_unknown",
      heading: () => m.ai_builder_failure_heading_provider_outcome_unknown(),
      cause: () => m.ai_builder_failure_cause_provider_outcome_unknown(),
      primary: () => m.ai_builder_turn_retry_with_cost_acknowledgement(),
      secondary: null,
      records: "retry_with_acknowledgement_requested"
    },
    {
      name: "any other server failure, quoted as sent",
      error: {
        code: "planner_stream_failed",
        category: "upstream",
        message: "Modellen svarade inte i tid."
      },
      latestTurn: "committed",
      kind: "other",
      heading: () => m.ai_builder_failure_heading_other_generation(),
      cause: () => "Modellen svarade inte i tid.",
      primary: () => m.ai_builder_turn_retry(),
      secondary: () => m.ai_builder_failure_action_clarify(),
      records: "resend_requested"
    }
  ];

  async function driveGenerationFailure(
    error: Record<string, unknown> | Error,
    latestTurn: "committed" | "processing" | "provider_outcome_unknown",
    fetchOptions: Partial<FetchOptions> = {}
  ) {
    // The authoritative refresh after the failure returns the real
    // transcript (task, summary, confirmation) and the turn's final state,
    // with the retained request the server can send again.
    const failedSession = makeSession({
      latest_plan_id: null,
      conversation: planSession().conversation,
      latest_turn: {
        client_turn_id: TURN_ID,
        state: latestTurn,
        user_message_id: "11111111-1111-4111-8111-111111111112",
        error: null,
        requires_duplicate_provider_spend_acknowledgement:
          latestTurn === "provider_outcome_unknown",
        retry_request: {
          client_turn_id: TURN_ID,
          message: "",
          ui_language: "sv",
          acknowledge_duplicate_provider_spend: false
        }
      }
    });
    const { fetch, reports } = makeFetch({
      sessions: [[makeSession(), failedSession]],
      ...fetchOptions
    });
    const { stream, calls } = makeStream((index) =>
      index === 0 ? [textEvent("Här är min tolkning."), summaryEvent(SUMMARY)] : "hold"
    );
    renderShell({ fetch, stream });
    await sendTask();
    await screen.findByRole("heading", { name: m.ai_builder_requirements_title() });
    await fireEvent.click(button(m.ai_builder_confirm_action()));
    await waitFor(() => expect(calls).toHaveLength(2));

    calls[1]!.emit([statusEvent("architecture_committed")]);
    if (error instanceof Error) {
      calls[1]!.fail(error);
    } else {
      calls[1]!.emit([
        {
          event: "error",
          data: JSON.stringify({
            schema_version: 2,
            phase: "planner",
            eneo_error_code: 9000,
            request_id: "req-1",
            ...error
          })
        }
      ]);
      calls[1]!.finish();
    }
    return { reports, calls };
  }

  it("names the model beside a failed generation whose retry runs it", async () => {
    await driveGenerationFailure(
      {
        code: "planner_stream_failed",
        category: "upstream",
        message: "Modellen svarade inte i tid."
      },
      "committed"
    );

    const notice = await screen.findByTestId("ai-builder-model-notice");
    await waitFor(() =>
      expect(within(notice).getByTestId("ai-builder-shown-model").textContent).toContain(
        "Test model"
      )
    );
  });

  it.each(generationFailures)(
    "shows one assistive failure card for $name",
    async ({ error, latestTurn, kind, heading, cause, primary, secondary, records }) => {
      const { reports } = await driveGenerationFailure(error, latestTurn);

      // The skeleton must never hide a failed generation: exactly one surface
      // names it, in the user's words, with the facts that still hold.
      const headingEl = await screen.findByRole("heading", { name: heading() });
      expect(screen.queryByRole("heading", { name: m.ai_builder_build_title() })).toBeNull();
      expect(screen.getAllByText(new RegExp(escape(cause())))).toHaveLength(1);
      expect(
        screen.getByText(new RegExp(escape(m.ai_builder_failure_preserved_create())))
      ).toBeTruthy();
      // The way back to the transcript is the header's, not a third button.
      expect(screen.queryByRole("button", { name: m.ai_builder_show_conversation() })).toBeNull();

      // Exactly the actions the driver allows, primary first.
      const card = headingEl.closest<HTMLElement>("[role='status']")!;
      const actions = within(card)
        .getAllByRole("button")
        .map((element) => element.textContent?.trim())
        .filter((label) => label !== m.ai_builder_copy_technical_details());
      expect(actions).toEqual([primary(), ...(secondary ? [secondary()] : [])]);

      // One observation, with the class the user saw, then the first
      // selection under the same identity, and nothing more.
      await waitFor(() => expect(reports).toHaveLength(1));
      const observed = reports[0]!;
      expect(observed.client_event_id).toMatch(/^[0-9a-f-]{36}$/);
      expect(observed).toMatchObject({ surface: "generation", presented_as: kind });
      expect(observed).not.toHaveProperty("message");

      await fireEvent.click(within(card).getByRole("button", { name: primary() }));
      // The same envelope again, with the first selection, and nothing else:
      // the retained turn is not shown or observed again while its retry
      // is in flight.
      await waitFor(() => expect(reports).toHaveLength(2));
      await new Promise((resolve) => setTimeout(resolve, 20));
      expect(reports).toHaveLength(2);
      const { first_action, ...envelope } = reports[1]!;
      expect(first_action).toBe(records);
      expect(envelope).toEqual(observed);
    }
  );

  it("observes a restored committed failure once, as what the card shows", async () => {
    // A failure the server persisted with the turn is displayed after a
    // resume: it gets its own observation identity when the card shows it.
    const restored = makeSession({
      session_id: "s-restored",
      latest_plan_id: null,
      conversation: planSession().conversation,
      latest_turn: {
        client_turn_id: TURN_ID,
        state: "committed",
        user_message_id: "11111111-1111-4111-8111-111111111112",
        error: {
          schema_version: 2,
          code: "planner_output_too_long",
          category: "upstream",
          message: "The AI planner output was cut off.",
          phase: "proposal",
          eneo_error_code: 9000,
          request_id: "req-restored"
        },
        requires_duplicate_provider_spend_acknowledgement: false,
        retry_request: {
          client_turn_id: TURN_ID,
          message: "",
          ui_language: "sv",
          acknowledge_duplicate_provider_spend: false
        }
      }
    });
    const { fetch, reports } = makeFetch({ sessions: [restored] });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-restored" });

    await screen.findByRole("heading", {
      name: m.ai_builder_failure_heading_output_too_long()
    });
    await waitFor(() => expect(reports).toHaveLength(1));
    expect(reports[0]).toMatchObject({
      code: "planner_output_too_long",
      request_id: "req-restored",
      surface: "generation",
      presented_as: "output_too_long"
    });
  });

  it("sends the missing-template fix to the attachment control, not the composer", async () => {
    // The pre-planning refusal: the action policy declines a template-fill
    // flow with no template chosen, and the code is the whole payload.
    await driveGenerationFailure(
      {
        code: "template_attachment_selection_invalid",
        category: "bad_request",
        phase: "proposal",
        message: "A template fill flow needs exactly one selected DOCX template."
      },
      "committed"
    );

    const fix = await screen.findByRole("button", {
      name: m.ai_builder_failure_problem_action_select_docx_template()
    });
    // Sending the same request again cannot fix a missing file, so the card
    // offers the one fix and nothing else.
    const card = fix.closest<HTMLElement>("[role='status']")!;
    expect(within(card).queryByRole("button", { name: m.ai_builder_turn_retry() })).toBeNull();

    await fireEvent.click(fix);

    // The transcript opened with the caret on the attach control: the card
    // named a file, so that is where the work is.
    const attach = await screen.findByRole("button", { name: m.attach_files() });
    await waitFor(() => expect(document.activeElement).toBe(attach));
  });

  it("keeps recovery responsive when the telemetry endpoint is down", async () => {
    const { reports, calls } = await driveGenerationFailure(
      {
        code: "planner_upstream_error",
        category: "upstream",
        message: "The AI provider rejected this request.",
        details: { provider_disposition: "known_rejection", retry_scope: "new_turn" }
      },
      "committed",
      { telemetryDown: true }
    );
    await screen.findByRole("heading", { name: m.ai_builder_failure_heading_provider_rejected() });

    await fireEvent.click(button(m.ai_builder_turn_retry()));

    // The resend went out as a new turn; no report ever landed.
    await waitFor(() => expect(calls).toHaveLength(3));
    expect(calls[2]!.body.client_turn_id).not.toBe(TURN_ID);
    expect(reports).toHaveLength(0);
    calls[2]!.finish();
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

  /** bits-ui opens on pointer, not on click alone. */
  const press = async (element: HTMLElement) => {
    await fireEvent.pointerDown(element, { pointerType: "mouse", button: 0 });
    await fireEvent.pointerUp(element, { pointerType: "mouse", button: 0 });
    await fireEvent.click(element);
  };
  const chooseStep = async (label: string) => {
    await press(screen.getByLabelText(m.ai_builder_step_choice_label()));
    await press(await screen.findByRole("option", { name: label }));
  };

  it("hands a dropped flow package to the importer with the request typed so far", async () => {
    const { fetch } = makeFetch();
    const { stream } = makeStream();
    const onpackage = vi.fn();
    renderShell({ fetch, stream, targetKind: "create", onpackage });
    await screen.findByRole("heading", { name: m.ai_builder_task_title() });
    await fireEvent.input(textbox(), {
      target: { value: "Vi vill ha detta flöde, men ändra steg 3" }
    });

    const pkg = new File(["zip"], "genomforandeplan.eneopkg", { type: "application/zip" });
    const composer = textbox().closest(".composer")!;
    await fireEvent.drop(composer, { dataTransfer: { files: [pkg] } });

    expect(onpackage).toHaveBeenCalledWith({
      file: pkg,
      text: "Vi vill ha detta flöde, men ändra steg 3"
    });
    // The package is not reference material: no attachment chip appears.
    expect(screen.queryByText("genomforandeplan.eneopkg")).toBeNull();
    // The request stays in the composer for the draft's own Builder.
    expect(textbox().value).toBe("Vi vill ha detta flöde, men ändra steg 3");
  });

  it("lets the first message be scoped to a saved step from the composer", async () => {
    const { fetch } = makeFetch({ created: editSession() });
    const { stream, calls } = makeStream();
    const { service } = renderShell({
      fetch,
      stream,
      targetKind: "edit",
      flowId: "flow-1",
      stepChoices: [
        { id: "flow-step-3", name: "Fördela källuppgifter", order: 3 },
        { id: "flow-step-14", name: "Skriv brukarversionen", order: 14 }
      ]
    });
    await waitFor(() => expect(service().hasSession).toBe(true));

    await chooseStep(m.ai_builder_step_choice_item({ step: 14, name: "Skriv brukarversionen" }));

    expect(
      await screen.findByText(
        m.ai_builder_edit_context_step({ step: 14, name: "Skriv brukarversionen" })
      )
    ).toBeTruthy();
    // The screen talks about the step now, not the whole flow's example.
    screen.getByRole("heading", { name: m.ai_builder_task_title_edit_step() });
    screen.getByRole("textbox", { name: m.ai_builder_saved_step_prompt_placeholder() });
    await fireEvent.input(textbox(), { target: { value: "Skriv i du-form" } });
    await fireEvent.keyDown(textbox(), { key: "Enter" });
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      message: "Skriv i du-form",
      edit_context: { kind: "saved_flow_step", flow_step_id: "flow-step-14" }
    });
  });

  it("keeps holding a carried request after a reload, from the persisted draft", async () => {
    localStorage.setItem(
      "eneo:ai-builder:draft:e-1",
      JSON.stringify({ text: "Ändra steg 3", files: [], requireStepScope: true })
    );
    const { fetch } = makeFetch({ created: editSession() });
    const { stream, calls } = makeStream();
    const { service } = renderShell({
      fetch,
      stream,
      targetKind: "edit",
      flowId: "flow-1",
      stepChoices: [{ id: "flow-step-3", name: "Fördela källuppgifter", order: 3 }]
    });
    await waitFor(() => expect(service().hasSession).toBe(true));
    await waitFor(() => expect(textbox().value).toBe("Ändra steg 3"));

    expect(await screen.findByText(m.ai_builder_step_choice_required())).toBeTruthy();
    expect(button(m.ai_builder_send()).disabled).toBe(true);
    await fireEvent.keyDown(textbox(), { key: "Enter" });
    expect(calls).toHaveLength(0);

    await chooseStep(m.ai_builder_step_choice_item({ step: 3, name: "Fördela källuppgifter" }));
    await waitFor(() => expect(button(m.ai_builder_send()).disabled).toBe(false));
  });

  it("lifts a carried requirement once the server holds the accepted turn, even after a retry", async () => {
    localStorage.setItem(
      "eneo:ai-builder:draft:e-1",
      JSON.stringify({ text: "Något nytt", files: [], requireStepScope: true })
    );
    const accepted = {
      ...editSession(),
      latest_turn: {
        client_turn_id: "turn-1",
        state: "committed",
        user_message_id: "u1",
        requires_duplicate_provider_spend_acknowledgement: false
      },
      conversation: [
        {
          message_id: "u1",
          role: "user",
          content: "Ändra steg 3",
          timestamp: "2026-07-11T09:00:00Z"
        }
      ]
    };
    const { fetch } = makeFetch({ created: accepted });
    const { stream } = makeStream();
    const { service } = renderShell({
      fetch,
      stream,
      targetKind: "edit",
      flowId: "flow-1",
      stepChoices: [{ id: "flow-step-3", name: "Fördela källuppgifter", order: 3 }]
    });
    await waitFor(() => expect(service().hasSession).toBe(true));
    await waitFor(() => expect(textbox().value).toBe("Något nytt"));
    expect(screen.queryByText(m.ai_builder_step_choice_required())).toBeNull();
    expect(button(m.ai_builder_send()).disabled).toBe(false);
  });

  it("refuses a package that arrives with other files instead of stranding them", async () => {
    const { fetch } = makeFetch();
    const { stream } = makeStream();
    const onpackage = vi.fn();
    renderShell({ fetch, stream, targetKind: "create", onpackage });
    await screen.findByRole("heading", { name: m.ai_builder_task_title() });

    const pkg = new File(["zip"], "flow.eneopkg", { type: "application/zip" });
    const pdf = new File(["pdf"], "underlag.pdf", { type: "application/pdf" });
    const composer = textbox().closest(".composer")!;
    await fireEvent.drop(composer, { dataTransfer: { files: [pkg, pdf] } });

    expect(onpackage).not.toHaveBeenCalled();
    expect(screen.queryByText("underlag.pdf")).toBeNull();
    expect(toastMock.error).toHaveBeenCalledWith(m.ai_builder_package_with_references_refused());
  });

  it("holds a request carried from a package until a step is chosen", async () => {
    const { fetch } = makeFetch({ created: editSession() });
    const { stream, calls } = makeStream();
    const { service, builder } = renderShell({
      fetch,
      stream,
      targetKind: "edit",
      flowId: "flow-1",
      stepChoices: [{ id: "flow-step-3", name: "Fördela källuppgifter", order: 3 }]
    });
    await waitFor(() => expect(service().hasSession).toBe(true));
    await waitFor(() => expect(builder()).toBeDefined());
    builder().carryRequest({
      text: "Ändra steg 3 så att den listar saknade uppgifter",
      requireStepScope: true
    });

    await waitFor(() =>
      expect(textbox().value).toBe("Ändra steg 3 så att den listar saknade uppgifter")
    );
    expect(await screen.findByText(m.ai_builder_step_choice_required())).toBeTruthy();
    // Unscoped, the request would rewrite prompts the model never saw.
    expect(button(m.ai_builder_send()).disabled).toBe(true);
    await fireEvent.keyDown(textbox(), { key: "Enter" });
    expect(calls).toHaveLength(0);

    await chooseStep(m.ai_builder_step_choice_item({ step: 3, name: "Fördela källuppgifter" }));
    await waitFor(() => expect(button(m.ai_builder_send()).disabled).toBe(false));
    await fireEvent.click(button(m.ai_builder_send()));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      edit_context: { kind: "saved_flow_step", flow_step_id: "flow-step-3" }
    });
  });

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

  it("says a generation failed when the phase falls back to the composer", async () => {
    // A step-scoped edit confirms no requirements summary, so a failed
    // generation without a plan drops the phase back to the composer and no
    // plan surface is mounted. The failure still has to be said: it used to
    // be claimed by a surface that was not on screen, and only a reload
    // revealed it.
    const started = editSession();
    const failed = {
      ...started,
      latest_plan_id: null,
      latest_turn: {
        client_turn_id: "33333333-3333-4333-8333-333333333333",
        state: "committed" as const,
        user_message_id: "33333333-3333-4333-8333-333333333334",
        error: null,
        requires_duplicate_provider_spend_acknowledgement: false,
        retry_request: null
      }
    };
    const { fetch } = makeFetch({ created: started, sessions: [[started, failed]] });
    const { stream, calls } = makeStream(() => "hold");
    const { service } = renderShell({ fetch, stream, targetKind: "edit", flowId: "flow-1" });
    await waitFor(() => expect(service().hasSession).toBe(true));

    await fireEvent.input(textbox(), { target: { value: "Ändra underlaget" } });
    await fireEvent.click(button(m.ai_builder_send()));
    await waitFor(() => expect(calls).toHaveLength(1));

    // Generation is under way, then the stream itself fails.
    calls[0]!.emit([statusEvent("architecture_committed")]);
    calls[0]!.fail(new Error("Planeringen avbröts."));

    // No plan and no summary: the composer owns the screen again, and the
    // plan surface that would have shown the failure is not mounted.
    await waitFor(() => expect(service().streamState).toBe("failed"));
    await waitFor(() => expect(service().phase).toBe("discovering"));
    expect(service().currentPlan).toBeNull();
    // The turn alert says it, because no plan surface is there to.
    expect(await screen.findByText(m.ai_builder_failure_heading_other())).toBeTruthy();
  });

  it("promises an unaffected published version only when the flow is published", async () => {
    // Starting over is offered only when there is work to discard.
    const openDiscard = async (flowIsPublished: boolean) => {
      const { service } = renderShell({
        fetch: makeFetch({ created: editSession() }).fetch,
        stream: makeStream().stream,
        targetKind: "edit",
        flowId: "flow-1",
        flowIsPublished
      });
      await waitFor(() => expect(service().hasSession).toBe(true));
      service().seedState({
        messages: [{ role: "user", content: "Byt rubrik", timestamp: 1 }]
      });
      await fireEvent.click(
        await screen.findByRole("button", { name: m.ai_builder_start_fresh() })
      );
      await screen.findByText(m.ai_builder_discard_change_title());
    };

    // A draft was never published, so nothing of it is running.
    await openDiscard(false);
    expect(screen.getByText(m.ai_builder_discard_change_body())).toBeTruthy();
    expect(screen.queryByText(m.ai_builder_discard_change_body_published())).toBeNull();
    cleanup();

    await openDiscard(true);
    expect(screen.getByText(m.ai_builder_discard_change_body_published())).toBeTruthy();
  });

  it("asks about the part of the step the menu chose, with quick picks for what it reads", async () => {
    const { fetch } = makeFetch({ created: editSession() });
    const { stream } = makeStream();
    const { service, builder } = renderShell({
      fetch,
      stream,
      targetKind: "edit",
      flowId: "flow-1",
      stepChoices: [
        { id: "step-one", name: "Ta fram fakta", order: 1 },
        {
          id: SAVED_STEP_SCOPE.editContext.flow_step_id,
          name: SAVED_STEP_SCOPE.stepName,
          order: 2
        },
        { id: "step-three", name: "Sammanfatta", order: 3 }
      ]
    });

    await waitFor(() => expect(service().hasSession).toBe(true));
    await waitFor(() => expect(builder()).toBeDefined());
    await builder().focusSavedFlowStep({
      ...SAVED_STEP_SCOPE,
      request: m.flow_step_ai_request_underlag(),
      intent: "underlag",
      current: "Läser föregående steg"
    });

    await screen.findByRole("heading", { name: m.ai_builder_task_title_step_reads({ step: "2" }) });
    expect(screen.getByText(m.ai_builder_task_now({ what: "läser föregående steg" }))).toBeTruthy();
    // What step 2 can read: the flow input and step 1; step 3 comes after it.
    const earlier = screen.getByRole("button", {
      name: m.ai_builder_step_choice_item({ step: 1, name: "Ta fram fakta" })
    });
    expect(screen.getByRole("button", { name: m.ai_builder_reads_flow_input() })).toBeTruthy();
    expect(
      screen.queryByRole("button", {
        name: m.ai_builder_step_choice_item({ step: 3, name: "Sammanfatta" })
      })
    ).toBeNull();

    // A pick finishes the open request the menu wrote.
    await fireEvent.click(earlier);
    const textbox = screen.getByRole("textbox", {
      name: m.ai_builder_saved_step_prompt_placeholder()
    }) as HTMLTextAreaElement;
    await waitFor(() =>
      expect(textbox.value).toBe(
        `${m.flow_step_ai_request_underlag()}${m.ai_builder_task_pick_step({ step: "1", name: "Ta fram fakta" })}`
      )
    );
  });

  it("drops the saved-step placeholder with the context when the chip is dismissed", async () => {
    const { fetch } = makeFetch({ created: editSession() });
    const { stream } = makeStream();
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
    screen.getByRole("textbox", { name: m.ai_builder_saved_step_prompt_placeholder() });
    screen.getByRole("heading", { name: m.ai_builder_task_title_edit_step() });
    // The flow header already says "Utkast" about the flow; the edit is not a draft.
    expect(screen.getByText(m.ai_builder_saved_state_new_edit())).toBeTruthy();
    expect(screen.queryByText(m.ai_builder_saved_state_new())).toBeNull();

    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_edit_context_clear_short() })
    );

    await waitFor(() => expect(screen.queryByText(SAVED_STEP_LABEL)).toBeNull());
    screen.getByRole("heading", { name: m.ai_builder_task_title_edit() });
    expect(
      screen.queryByRole("textbox", { name: m.ai_builder_saved_step_prompt_placeholder() })
    ).toBeNull();
    expect(service().savedFlowStepScope).toBeNull();
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

  it("hands a failed step over from a cold launch and sends the server's reference with the fix request", async () => {
    let releaseCreate!: () => void;
    const held = new Promise<void>((resolve) => {
      releaseCreate = resolve;
    });
    const repaired = {
      ...editSession(),
      edit_scope: {
        context: { kind: "saved_flow_step" as const, flow_step_id: "flow-step-1" },
        step_number: 1,
        step_name: "Steg",
        preserves_output_contract: true
      }
    };
    const { fetch } = makeFetch({
      created: editSession(),
      // The repair turn is read back: the server projects the failed step.
      sessions: [[editSession(), repaired]]
    });
    const baseFetch = fetch.getMockImplementation()!;
    fetch.mockImplementation(async (path, init) => {
      if (path === SESSIONS_ROUTE && init?.method === "post") await held;
      return baseFetch(path, init);
    });
    const { stream, calls } = makeStream();
    const { builder, service } = renderShell({
      fetch,
      stream,
      targetKind: "edit",
      flowId: "flow-1"
    });
    await waitFor(() => expect(builder()).toBeDefined());
    const launched = builder().launchFailureRepair({ runId: "run-1", stepOrder: 1 });
    releaseCreate();
    await launched;
    const heading = await screen.findByRole("heading", { name: m.ai_builder_repair_title() });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    // A launch on screen is not yet a repair: the composer names no step.
    expect(service().activeStepScope).toBeNull();

    await fireEvent.click(await screen.findByTestId("repair-prepare"));
    await waitFor(() => expect(calls).toHaveLength(1));
    // Once the fix request is sent and read back, the failed step is the
    // conversation's scope, locked to its output contract.
    await waitFor(() =>
      expect(service().activeStepScope).toEqual({ stepName: "Steg", stepNumber: 1 })
    );
    expect(service().activeStepScopeLocked).toBe(true);
    expect(calls[0]!.body).toMatchObject({
      message: m.ai_builder_repair_message({ step: "1" }),
      review_context: RUN_FAILURE_LAUNCH.reference
    });
    expect(calls[0]!.body).not.toHaveProperty("edit_context");
    await waitFor(() => expect(service().failureRepair).toEqual({ status: "closed" }));
  });

  it("keeps a refused repair launch on screen and names no step", async () => {
    const { fetch } = makeFetch({ created: editSession() });
    const { stream } = makeStream(() => new Error("The flow is no longer published."));
    const { builder, service } = renderShell({
      fetch,
      stream,
      targetKind: "edit",
      flowId: "flow-1"
    });
    await waitFor(() => expect(service().hasSession).toBe(true));
    await waitFor(() => expect(builder()).toBeDefined());
    await builder().launchFailureRepair({ runId: "run-1", stepOrder: 1 });
    await screen.findByRole("heading", { name: m.ai_builder_repair_title() });

    await fireEvent.click(await screen.findByTestId("repair-prepare"));
    await waitFor(() => expect(service().streamState).not.toBe("streaming"));

    // The server recorded no repair: the launch is still there to retry and
    // the composer does not claim a scope the conversation does not have.
    expect(service().failureRepair.status).toBe("ready");
    expect(screen.getByRole("heading", { name: m.ai_builder_repair_title() })).toBeTruthy();
    expect(service().activeStepScope).toBeNull();
  });

  it("asks before a failure repair replaces an ongoing edit", async () => {
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
    await builder().launchFailureRepair({ runId: "run-1", stepOrder: 1 });
    expect(
      await screen.findByText(m.ai_builder_replace_edit_description_repair({ step: "1" }))
    ).toBeTruthy();
    expect(screen.queryByRole("heading", { name: m.ai_builder_repair_title() })).toBeNull();
    await fireEvent.click(button(m.ai_builder_replace_edit_action()));
    expect(await screen.findByRole("heading", { name: m.ai_builder_repair_title() })).toBeTruthy();
    expect(posts).toBe(2);
    await waitFor(() => expect(screen.queryByText(m.ai_builder_replace_edit_title())).toBeNull());
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
    // The question is answered once: it must not linger over the fresh
    // session and ask again about a step nobody named.
    await waitFor(() => expect(screen.queryByText(m.ai_builder_replace_edit_title())).toBeNull());
    expect(
      screen.queryByText(m.ai_builder_replace_edit_description({ stepName: m.flow_step_unnamed() }))
    ).toBeNull();
  });

  it("starts a fresh session without asking when the last change is already applied", async () => {
    // An applied session takes no more turns; asking to "replace" a change that
    // is already in the flow was a question about nothing.
    const applied = makeSession({
      session_id: "e-applied",
      target_kind: "edit",
      flow_id: "flow-1",
      status: "applied",
      conversation: [
        userMessage("u1", "Förbättra instruktionen"),
        assistantMessage("a1", "Här är förslaget.")
      ]
    });
    const fresh = editSession();
    let posts = 0;
    const { fetch } = makeFetch({ sessions: [applied, fresh] });
    const baseFetch = fetch.getMockImplementation()!;
    fetch.mockImplementation(async (path, init) => {
      if (path === SESSIONS_ROUTE && init?.method === "post") {
        posts += 1;
        return posts === 1 ? applied : fresh;
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
    expect(service().hasOpenWork).toBe(false);

    await builder().focusSavedFlowStep(SAVED_STEP_SCOPE);

    await waitFor(() => expect(posts).toBe(2));
    expect(screen.queryByText(m.ai_builder_replace_edit_title())).toBeNull();
    await waitFor(() => expect(service().session?.session_id).toBe(fresh.session_id));
    await waitFor(() => expect(service().savedFlowStepScope?.stepNumber).toBe(2));
  });

  it("closes the replace question at once and opens the review only after the fresh session exists", async () => {
    const ongoing = makeSession({
      session_id: "e-ongoing",
      target_kind: "edit",
      flow_id: "flow-1",
      conversation: [userMessage("u1", "Byt rubrik på rapporten")]
    });
    const fresh = editSession();
    let releaseCreate!: () => void;
    const held = new Promise<void>((resolve) => {
      releaseCreate = resolve;
    });
    let posts = 0;
    const { fetch } = makeFetch({ sessions: [ongoing, fresh] });
    const baseFetch = fetch.getMockImplementation()!;
    fetch.mockImplementation(async (path, init) => {
      if (path === SESSIONS_ROUTE && init?.method === "post") {
        posts += 1;
        if (posts === 1) return ongoing;
        await held;
        return fresh;
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
    await builder().openReview();
    await screen.findByText(m.ai_builder_replace_edit_description_review());
    await fireEvent.click(button(m.ai_builder_replace_edit_action()));
    // The question is gone while the create is still pending, and the review
    // has not opened against the session being replaced.
    await waitFor(() => expect(screen.queryByText(m.ai_builder_replace_edit_title())).toBeNull());
    expect(screen.queryByRole("heading", { name: m.ai_builder_review_title() })).toBeNull();
    expect(posts).toBe(2);
    releaseCreate();
    expect(await screen.findByRole("heading", { name: m.ai_builder_review_title() })).toBeTruthy();
  });

  it("keeps the edit and its step scope when the header start over is refused", async () => {
    const ongoing = makeSession({
      session_id: "e-ongoing",
      target_kind: "edit",
      flow_id: "flow-1",
      conversation: [userMessage("u1", "Byt rubrik på rapporten")]
    });
    let releaseDrafts!: () => void;
    const heldDrafts = new Promise<void>((resolve) => {
      releaseDrafts = resolve;
    });
    let posts = 0;
    const { fetch } = makeFetch({ sessions: [ongoing] });
    const baseFetch = fetch.getMockImplementation()!;
    fetch.mockImplementation(async (path, init) => {
      if (path === SESSIONS_ROUTE && init?.method === "post") {
        posts += 1;
        if (posts === 1) return ongoing;
        throw new Error("create refused");
      }
      if (path === SESSIONS_ROUTE && init?.method !== "post" && posts > 1) {
        await heldDrafts;
      }
      return baseFetch(path, init);
    });
    const { service } = renderShell({
      fetch,
      stream: makeStream().stream,
      targetKind: "edit",
      flowId: "flow-1"
    });
    await waitFor(() => expect(service().hasSession).toBe(true));
    // The conversation screen owns the composer context the header clears, so
    // it has to be the screen in view for that rule to be under test.
    await fireEvent.click(button(new RegExp(escape(m.ai_builder_conversation_button()))));
    await screen.findByRole("heading", { name: m.ai_builder_conversation_title() });
    service().setSavedFlowStepScope(SAVED_STEP_SCOPE);

    await fireEvent.click(button(m.ai_builder_start_fresh()));
    await fireEvent.click(button(m.ai_builder_discard_change_action()));
    await waitFor(() => expect(posts).toBe(2));

    // The edit is back before the draft list answers - that request is not
    // what the user is waiting for - and the step it was scoped to survives a
    // replacement that never happened.
    await waitFor(() => expect(service().error).not.toBeNull());
    expect(service().hasSession).toBe(true);
    expect(service().session?.session_id).toBe("e-ongoing");
    expect(service().savedFlowStepScope).not.toBeNull();

    releaseDrafts();
    await waitFor(() => expect(service().hasSession).toBe(true));
    expect(service().savedFlowStepScope).not.toBeNull();
  });

  it("does not open the review when the replacement session cannot be created", async () => {
    const ongoing = makeSession({
      session_id: "e-ongoing",
      target_kind: "edit",
      flow_id: "flow-1",
      conversation: [userMessage("u1", "Byt rubrik på rapporten")]
    });
    let posts = 0;
    const { fetch } = makeFetch({ sessions: [ongoing] });
    const baseFetch = fetch.getMockImplementation()!;
    fetch.mockImplementation(async (path, init) => {
      if (path === SESSIONS_ROUTE && init?.method === "post") {
        posts += 1;
        if (posts === 1) return ongoing;
        throw new Error("create failed");
      }
      return baseFetch(path, init);
    });
    const { stream, calls } = makeStream();
    const { service, builder } = renderShell({
      fetch,
      stream,
      targetKind: "edit",
      flowId: "flow-1"
    });
    await waitFor(() => expect(service().hasSession).toBe(true));
    await waitFor(() => expect(builder()).toBeDefined());
    await builder().openReview();
    await screen.findByText(m.ai_builder_replace_edit_description_review());
    await fireEvent.click(button(m.ai_builder_replace_edit_action()));
    await waitFor(() => expect(posts).toBe(2));
    await waitFor(() => expect(screen.queryByText(m.ai_builder_replace_edit_title())).toBeNull());
    // Nothing was replaced: the review never opens, the driver's own create
    // error is what the user sees, and no review turn was sent.
    expect(screen.queryByRole("heading", { name: m.ai_builder_review_title() })).toBeNull();
    await waitFor(() => expect(service().error).not.toBeNull());
    expect(calls).toHaveLength(0);
    // The edit the user had is still there. It used to be gone: the driver
    // reset before the create, so a refusal left the no-session skeleton and
    // only a page reload brought the conversation back.
    expect(service().hasSession).toBe(true);
    expect(service().session?.session_id).toBe("e-ongoing");
    expect(service().messages.map((message) => message.content)).toContain(
      "Byt rubrik på rapporten"
    );
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

  it("treats a plan-only resumed edit session as ongoing from the session fact", async () => {
    let releaseCreate!: () => void;
    const held = new Promise<void>((resolve) => {
      releaseCreate = resolve;
    });
    // Empty conversation but a latest plan: the launch decision must read the
    // session fact, not the hydrated plan.
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
    const { fetch, reports } = makeFetch({ sessions: [turnSession("failed_before_provider")] });
    const { stream, calls } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-turn" });

    const title = await screen.findByText(m.ai_builder_turn_failed_before_provider_title());
    // A polite status, never an interrupting alert.
    const alert = title.closest("[data-slot='alert']")!;
    expect(alert.getAttribute("role")).toBe("status");
    expect(alert.getAttribute("aria-live")).toBe("polite");
    // A restored turn state without an error payload is still observed,
    // under its turn identity, with the class the alert showed.
    await waitFor(() => expect(reports).toHaveLength(1));
    expect(reports[0]).toMatchObject({
      code: "turn_failed_before_provider",
      request_id: TURN_ID,
      session_id: "s-turn",
      surface: "chat",
      presented_as: "failed_before_provider"
    });

    await fireEvent.click(button(m.ai_builder_turn_retry()));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      client_turn_id: TURN_ID,
      message: "Build a flow",
      acknowledge_duplicate_provider_spend: false
    });
    await waitFor(() => expect(reports).toHaveLength(2));
    expect(reports[1]).toMatchObject({
      client_event_id: reports[0]!.client_event_id,
      first_action: "retry_requested"
    });
  });

  it("requires explicit cost acknowledgement for an unknown provider outcome", async () => {
    const { fetch } = makeFetch({ sessions: [turnSession("provider_outcome_unknown")] });
    const { stream, calls } = makeStream();
    renderShell({ fetch, stream, resumeSessionId: "s-turn" });

    expect(
      await screen.findByText(
        new RegExp(escape(m.ai_builder_failure_cause_provider_outcome_unknown()))
      )
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: m.ai_builder_turn_retry() })).toBeNull();
    await fireEvent.click(button(m.ai_builder_turn_retry_with_cost_acknowledgement()));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({
      client_turn_id: TURN_ID,
      acknowledge_duplicate_provider_spend: true
    });
  });

  it("observes a failed reconciliation on the chat surface, once", async () => {
    // The refresh of a turn still processing fails: the alert shows that
    // failure, and the observation names the chat surface and the class shown.
    const [processing] = turnSession("processing");
    const { fetch, reports } = makeFetch({
      sessions: [processing!],
      failRead: { "s-turn": 2 }
    });
    renderShell({ fetch, stream: makeStream().stream, resumeSessionId: "s-turn" });
    expect(await screen.findByText(m.ai_builder_turn_active_title())).toBeTruthy();

    await fireEvent.click(button(m.refresh()));

    expect(await screen.findByText(m.ai_builder_turn_refresh_failed())).toBeTruthy();
    await waitFor(() => expect(reports).toHaveLength(1));
    expect(reports[0]).toMatchObject({
      session_id: "s-turn",
      surface: "chat",
      presented_as: "other"
    });
    // The first selection lands under the same identity.
    await fireEvent.click(button(m.ai_builder_failure_action_refresh()));
    await waitFor(() => expect(reports).toHaveLength(2));
    expect(reports[1]).toMatchObject({
      client_event_id: reports[0]!.client_event_id,
      first_action: "refresh_requested"
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

  it("keeps offering the fresh session when the first attempt is refused", async () => {
    const { fetch } = makeFetch({
      sessions: [questionSession()],
      created: makeSession({ session_id: "s-fresh" })
    });
    const baseFetch = fetch.getMockImplementation()!;
    let creates = 0;
    fetch.mockImplementation(async (path, init) => {
      if (path === SESSIONS_ROUTE && init?.method === "post") {
        creates += 1;
        if (creates === 1) throw new Error("create refused");
      }
      return baseFetch(path, init);
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

    await screen.findByText(m.ai_builder_unsupported_architecture_title());
    await fireEvent.click(button(m.ai_builder_start_fresh()));
    await waitFor(() => expect(creates).toBe(1));

    // The refusal replaced the typed error with its own, which used to take
    // the only way out with it: in create mode there is no header start over.
    await waitFor(() => expect(service().error?.code).not.toBe("unsupported_architecture"));
    expect(service().hasSession).toBe(true);
    await screen.findByRole("heading", { name: FORMAT_QUESTION.question });

    await fireEvent.click(button(m.ai_builder_start_fresh()));

    await waitFor(() => expect(creates).toBe(2));
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
