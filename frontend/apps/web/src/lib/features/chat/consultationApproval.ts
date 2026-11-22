/**
 * The tool calls a specialist's pending approval decides.
 *
 * The backend lists them in `awaiting_tool_call_ids`. A specialist's internal
 * steps (knowledge, files, Skills) run in the same round without approval and
 * must not become approval cards: a decision for one of them is dropped by the
 * backend, and the "approve all" count would be wrong. History recorded
 * before that field existed falls back to the external pending steps.
 */
export type ConsultationApprovalLike = {
  status: string;
  approval_id?: string | null;
  awaiting_tool_call_ids?: string[] | null;
  tool_calls?: Array<{
    step_id?: string | null;
    server_name: string;
    tool_name: string;
    tool_call_id?: string | null;
    arguments?: Record<string, unknown> | null;
    approved?: boolean | null;
    result_status?: string | null;
    is_internal?: boolean | null;
  }> | null;
};

export type AwaitingToolCall = {
  server_name: string;
  tool_name: string;
  arguments?: Record<string, unknown>;
  tool_call_id?: string;
};

type ApprovalStep = NonNullable<ConsultationApprovalLike["tool_calls"]>[number];

export function awaitingConsultationSteps<T extends ApprovalStep>(
  consultation: Omit<ConsultationApprovalLike, "tool_calls"> & { tool_calls?: T[] | null }
): T[] {
  if (consultation.status !== "awaiting_approval" || !consultation.approval_id) return [];
  const listed = new Set(consultation.awaiting_tool_call_ids);
  const current = new Map<string, T>();
  for (const step of consultation.tool_calls ?? []) {
    const id = step.tool_call_id;
    if (!id || step.is_internal || step.approved != null) continue;
    if (listed.size && !listed.has(id)) continue;
    if (
      step.result_status == null ||
      ["pending", "awaiting_approval"].includes(step.result_status)
    ) {
      current.set(id, step);
    }
  }
  return [...current.values()];
}

export function awaitingToolCalls(consultation: ConsultationApprovalLike): AwaitingToolCall[] {
  return awaitingConsultationSteps(consultation).map((step) => ({
    server_name: step.server_name,
    tool_name: step.tool_name,
    arguments: step.arguments ?? undefined,
    tool_call_id: step.tool_call_id ?? undefined
  }));
}

/** Whether `step` is one of the calls the consultation's pending approval decides. */
export function isAwaitingApproval(
  consultation: ConsultationApprovalLike,
  step: { tool_call_id?: string | null; step_id?: string | null }
): boolean {
  if (!step.tool_call_id) return false;
  return awaitingConsultationSteps(consultation).some((call) =>
    step.step_id ? call.step_id === step.step_id : call.tool_call_id === step.tool_call_id
  );
}
