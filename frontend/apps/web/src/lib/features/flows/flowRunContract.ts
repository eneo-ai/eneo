import type {
  FlowRunContract,
  FlowRunContractTemplateReadiness,
  FlowRunStepInputs
} from "@intric/intric-js";

type FileLike = { id: string };

type FlowRunIntentParams = {
  publishedFlowVersion: number;
  inputPayloadJson: Record<string, unknown>;
  stepInputs?: FlowRunStepInputs;
};

export function normalizeTemplateReadiness(
  templateReadiness:
    | FlowRunContract["template_readiness"]
    | FlowRunContractTemplateReadiness
    | null
    | undefined
): FlowRunContractTemplateReadiness[] {
  if (!templateReadiness) return [];
  return Array.isArray(templateReadiness) ? templateReadiness : [templateReadiness];
}

export function getBlockingTemplateReadinessItems(
  readinessItems: FlowRunContractTemplateReadiness[]
): FlowRunContractTemplateReadiness[] {
  return readinessItems.filter(
    (item) => item.status === "needs_action" || item.status === "unavailable"
  );
}

export function hasBlockingTemplateReadiness(
  readinessItems: FlowRunContractTemplateReadiness[]
): boolean {
  return getBlockingTemplateReadinessItems(readinessItems).length > 0;
}

export function buildStepInputsPayload(
  filesByStepId: Record<string, FileLike[]>
): FlowRunStepInputs | undefined {
  const payloadEntries = Object.entries(filesByStepId)
    .map(([stepId, files]) => [stepId, files.map((file) => file.id).filter(Boolean)] as const)
    .filter(([, fileIds]) => fileIds.length > 0)
    .map(([stepId, fileIds]) => [stepId, { file_ids: fileIds }] as const);

  if (payloadEntries.length === 0) {
    return undefined;
  }

  return Object.fromEntries(payloadEntries);
}

export function buildFlowRunIntent({
  publishedFlowVersion,
  inputPayloadJson,
  stepInputs
}: FlowRunIntentParams): {
  expected_flow_version: number;
  input_payload_json: Record<string, unknown>;
  step_inputs?: FlowRunStepInputs;
} {
  return {
    expected_flow_version: publishedFlowVersion,
    input_payload_json: inputPayloadJson,
    ...(stepInputs ? { step_inputs: stepInputs } : {})
  };
}
