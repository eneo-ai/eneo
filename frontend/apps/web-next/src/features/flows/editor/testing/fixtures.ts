/**
 * Test-only: flows, steps and step assistants as the flow API returns them,
 * and a stand-in for the typed API client that answers by path.
 */
import type { StepKind, StepKindOption, StepKindPlace, StepKindRefusal } from "../step-kinds";
import type { FlowAssistant, FlowPublic, FlowStep } from "../step-types";

export function makeStep(overrides: Partial<FlowStep> = {}): FlowStep {
  return {
    id: "step-1",
    assistant_id: "assistant-1",
    step_order: 1,
    user_description: "Sammanfatta",
    input_source: "flow_input",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "text",
    input_bindings: null,
    input_config: null,
    output_config: null,
    input_contract: null,
    output_contract: null,
    output_classification_override: null,
    review_policy: null,
    timeout_seconds: null,
    ...overrides
  };
}

export function makeFlow(overrides: Partial<FlowPublic> = {}): FlowPublic {
  return {
    id: "flow-1",
    tenant_id: "tenant-1",
    space_id: "space-1",
    space_name: "Upphandling",
    name: "Ärendeflöde",
    description: null,
    published_version: null,
    step_count: 1,
    draft_revision: 4,
    metadata_json: null,
    run_history_retention: { state: "off" } as FlowPublic["run_history_retention"],
    permissions: {
      can_edit: true,
      can_publish: true,
      can_delete: true,
      can_run: true,
      can_view_runs: true
    },
    steps: [makeStep()],
    ...overrides
  };
}

export function makeAssistant(overrides: Partial<FlowAssistant> = {}): FlowAssistant {
  return {
    id: "assistant-1",
    name: "Sammanfatta",
    space_id: "space-1",
    prompt: {
      id: "prompt-1",
      text: "Sammanfatta ärendet.",
      description: null,
      user: { id: "user-1", email: "anna.lind@example.se", username: "Anna Lind" }
    } as FlowAssistant["prompt"],
    completion_model: { id: "model-1", name: "snabb-modell" } as FlowAssistant["completion_model"],
    completion_model_kwargs: {},
    logging_enabled: false,
    attachments: [],
    allowed_attachments: { accepted_file_types: [], limit: { max_files: 0, max_size: 0 } },
    groups: [],
    websites: [],
    integration_knowledge_list: [],
    user: { id: "user-1", email: "anna.lind@example.se", username: "Anna Lind" },
    tools: { assistants: [] },
    type: "assistant",
    insight_enabled: false,
    ...overrides
  } as FlowAssistant;
}

/** A kind as the core's step-kinds answer gives it: allowed unless refused, an AI step's configuration. */
export function makeKindOption(
  kind: StepKind,
  {
    configuration,
    ...overrides
  }: Omit<Partial<StepKindOption>, "configuration"> & {
    configuration?: Partial<StepKindOption["configuration"]>;
  } = {}
): StepKindOption {
  const refusals = overrides.refusals ?? [];
  return {
    kind,
    allowed: refusals.length === 0,
    configuration: {
      input_source: "previous_step",
      input_type: "text",
      input_contract: null,
      output_mode: "pass_through",
      output_type: "text",
      output_contract: null,
      input_bindings: null,
      input_config: null,
      output_config: null,
      review_policy: null,
      ...configuration
    },
    step_edits: [],
    turns_on_transcription: false,
    ...overrides,
    refusals
  };
}

export function makeKindRefusal(overrides: Partial<StepKindRefusal> = {}): StepKindRefusal {
  return {
    code: "typed_io_incompatible_type_chain",
    issue_code: "typed_io_incompatible_type_chain",
    step_order: 2,
    step_id: null,
    message: "Refused.",
    ...overrides
  };
}

/** An insertion place of the core's answer with `options` (every other kind allowed). */
export function makeKindPlace(position: number, options: StepKindOption[] = []): StepKindPlace {
  const kinds: StepKind[] = [
    "ai",
    "structured",
    "compose",
    "document",
    "template",
    "transcribe",
    "speakers",
    "review",
    "fetch_http",
    "tool",
    "send_http"
  ];
  return {
    position,
    step_id: null,
    options: kinds.map(
      (kind) => options.find((option) => option.kind === kind) ?? makeKindOption(kind)
    )
  };
}

type Answer = { status?: number; body: unknown };
type Handler = (init: {
  params?: { path?: Record<string, string>; query?: Record<string, string> };
  body?: unknown;
}) => Answer;

/**
 * A browserApi stand-in: `routes["PATCH /api/v1/flows/{id}/editor/"]` answers
 * that request. Unrouted requests answer 404, so a test sees what it missed.
 */
export function apiStub(routes: Record<string, Handler>) {
  const calls: { method: string; path: string; init: Parameters<Handler>[0] }[] = [];
  const respond =
    (method: string) =>
    (path: string, init: Parameters<Handler>[0] = {}) => {
      calls.push({ method, path, init });
      const handler = routes[`${method} ${path}`];
      const answer = handler
        ? handler(init)
        : { status: 404, body: { message: "Not routed", code: "not_found" } };
      const status = answer.status ?? 200;
      const response = new Response(JSON.stringify(answer.body), {
        status,
        headers: { "content-type": "application/json" }
      });
      return Promise.resolve(
        status < 400 ? { data: answer.body, response } : { error: answer.body, response }
      );
    };
  return {
    calls,
    client: {
      GET: respond("GET"),
      POST: respond("POST"),
      PATCH: respond("PATCH"),
      PUT: respond("PUT"),
      DELETE: respond("DELETE")
    }
  };
}
