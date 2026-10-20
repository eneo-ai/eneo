import { eneoToolMetadata } from "@/features/chat/tool-presentation";

/** The loopback server the flow tools run on; the backend stamps the name on every call. */
export const FLOWS_SERVER_NAME = "flows";

/** Tools that change a flow (the panel refetches the definition when one finishes). */
export const FLOW_DEFINITION_TOOLS = new Set([
  "create_flow",
  "update_flow",
  "publish_flow",
  "delete_flow"
]);
/** Tools about a run (the panel shows the run when one finishes). */
export const FLOW_RUN_TOOLS = new Set(["run_flow", "get_run", "cancel_run", "review_run"]);

type ToolLike = {
  toolName: string;
  input?: unknown;
  providerMetadata?: unknown;
  callProviderMetadata?: unknown;
  resultProviderMetadata?: unknown;
};

/** The flow and run a tool call is about; either may be unknown. */
export type FlowRef = { flowId: string | null; runId: string | null };

/**
 * Whether a tool call ran on Eneo's own `flows` server. `is_internal` is the
 * backend's verdict on where the call was routed, so an external server an
 * admin named "flows" does not count.
 */
export function isFlowsCall(part: ToolLike): boolean {
  const eneo = eneoToolMetadata(part);
  return eneo.server_name === FLOWS_SERVER_NAME && eneo.is_internal === true;
}

const asId = (value: unknown): string | null =>
  typeof value === "string" && value.length > 0 ? value : null;

/**
 * The ids a finished call's `structured_content` names at its top level.
 * Every flows tool result carries `flow_id` and `run_id` (null when the tool
 * has none), so the panel binds without reading the rest.
 */
export function flowRefFromOutcome(structuredContent: unknown): FlowRef {
  if (!structuredContent || typeof structuredContent !== "object") {
    return { flowId: null, runId: null };
  }
  const content = structuredContent as Record<string, unknown>;
  return { flowId: asId(content.flow_id), runId: asId(content.run_id) };
}

/**
 * The ids a call names in its arguments (`update_flow`, `run_flow`,
 * `get_run`, …), known before the call has finished. A `run_id` alone names
 * a run whose flow the result tells.
 */
export function flowRefFromArguments(args: unknown): FlowRef {
  if (!args || typeof args !== "object" || Array.isArray(args)) {
    return { flowId: null, runId: null };
  }
  const input = args as Record<string, unknown>;
  return { flowId: asId(input.flow_id), runId: asId(input.run_id) };
}

export function hasFlowRef(ref: FlowRef): boolean {
  return ref.flowId !== null || ref.runId !== null;
}

/** The later reference fills in what the earlier one did not know. */
export function mergeFlowRefs(earlier: FlowRef, later: FlowRef): FlowRef {
  return { flowId: later.flowId ?? earlier.flowId, runId: later.runId ?? earlier.runId };
}
