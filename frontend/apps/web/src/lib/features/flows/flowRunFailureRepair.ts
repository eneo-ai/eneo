import { FLOW_API_ERROR_CODE } from "$lib/features/flows/flowRuntimeErrorMapping";

/** A failed step the AI Builder is asked to repair: the run and the step,
 *  nothing more. The server decides which attempt, whether the model's
 *  rejected output was kept, and whether the flow is still the one that ran. */
export interface FlowRunFailureRepairTarget {
  runId: string;
  stepOrder: number;
}

/** Error codes a repair MAY apply to: the ones a typed step raises when the
 *  model's answer did not meet its output contract. The same codes are also
 *  raised for input the step received, so the card only offers the action;
 *  the Builder's launch asks the server and shows its answer. */
const FAILURE_REPAIR_CANDIDATE_CODES: ReadonlySet<string> = new Set([
  FLOW_API_ERROR_CODE.TYPED_IO_OUTPUT_PARSE_FAILED,
  FLOW_API_ERROR_CODE.TYPED_IO_CONTRACT_VIOLATION,
  FLOW_API_ERROR_CODE.TYPED_IO_VALIDATION_FAILED,
  // A truncated answer is never kept; the server explains it from the
  // attempt's finish reason and token counts instead.
  FLOW_API_ERROR_CODE.LLM_OUTPUT_TRUNCATED
]);

export function isFailureRepairCandidate(errorCode: string | null | undefined): boolean {
  return errorCode != null && FAILURE_REPAIR_CANDIDATE_CODES.has(errorCode);
}
