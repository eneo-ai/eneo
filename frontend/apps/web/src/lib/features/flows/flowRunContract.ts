import type {
  FlowRunContract,
  FlowRunContractTemplateReadiness,
  FlowRunStepInputs
} from "@intric/intric-js";

type FileLike = { id: string };

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
