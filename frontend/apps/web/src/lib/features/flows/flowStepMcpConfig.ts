import type { FlowStep } from "@eneo/eneo-js";

type MCPToolLike = {
  id?: string;
  name?: string;
  is_enabled?: boolean;
};

type MCPServerLike = {
  id?: string;
  security_classification?: { security_level?: number; name?: string } | null;
  tools?: MCPToolLike[] | null;
};

type AssistantMcpLike = {
  mcp_servers?: MCPServerLike[] | null;
  groups?: Array<{
    embedding_model?: { security_classification?: { security_level?: number } | null };
  }>;
  websites?: Array<{
    embedding_model?: { security_classification?: { security_level?: number } | null };
  }>;
  integration_knowledge_list?: Array<{
    embedding_model?: { security_classification?: { security_level?: number } | null };
  }>;
};

export type FlowStepMcpSummary = {
  enabledToolCount: number;
  // A server assignment alone is not enough; the runtime needs at least one enabled tool.
  hasActiveMcp: boolean;
};

export type FlowStepMcpCompatibility = {
  isCompatible: boolean;
  requiredLevel: number | null;
};

type FlowStepMcpCompatibilityInput = {
  step: FlowStep;
  steps: FlowStep[];
  assistantsById: Map<string, AssistantMcpLike | null | undefined> | Map<string, unknown>;
  availableServers: Array<{
    id: string;
    security_classification?: { security_level?: number } | null;
  }>;
  spaceSecurityClassification?: { security_level?: number } | null;
};

export function createEmptyFlowStepMcpSummary(): FlowStepMcpSummary {
  return {
    enabledToolCount: 0,
    hasActiveMcp: false
  };
}

export function shouldShowStepMcpSection(
  outputMode: FlowStep["output_mode"] | null | undefined
): boolean {
  return outputMode !== "transcribe_only" && outputMode !== "template_fill";
}

export function summarizeAssistantMcp(
  assistant: { mcp_servers?: unknown } | null | undefined
): FlowStepMcpSummary {
  const servers = Array.isArray(assistant?.mcp_servers)
    ? (assistant.mcp_servers as MCPServerLike[])
    : [];
  const enabledToolCount = servers.reduce((count, server) => {
    const tools = Array.isArray(server.tools) ? server.tools : [];
    return count + tools.filter((tool) => tool?.is_enabled === true).length;
  }, 0);

  return {
    ...createEmptyFlowStepMcpSummary(),
    enabledToolCount,
    hasActiveMcp: enabledToolCount > 0
  };
}

function classificationLevel(
  classification: { security_level?: number } | null | undefined
): number | null {
  return typeof classification?.security_level === "number" ? classification.security_level : null;
}

function maxLevel(...levels: Array<number | null>): number | null {
  const presentLevels = levels.filter((level): level is number => typeof level === "number");
  return presentLevels.length > 0 ? Math.max(...presentLevels) : null;
}

function assistantKnowledgeLevel(assistant: AssistantMcpLike | null | undefined): number | null {
  const sources = [
    ...(assistant?.groups ?? []),
    ...(assistant?.websites ?? []),
    ...(assistant?.integration_knowledge_list ?? [])
  ];
  const levels = sources
    .map((item) => classificationLevel(item.embedding_model?.security_classification))
    .filter((level): level is number => level !== null);
  return levels.length > 0 ? Math.max(...levels) : null;
}

function assistantMcpLevel(assistant: AssistantMcpLike | null | undefined): number | null {
  const levels = (assistant?.mcp_servers ?? [])
    .map((server) => classificationLevel(server.security_classification))
    .filter((level): level is number => level !== null);
  return levels.length > 0 ? Math.max(...levels) : null;
}

function inputFloorLevel(args: {
  stepOrder: number;
  inputSource: FlowStep["input_source"];
  priorOutputLevelsByOrder: Map<number, number | null>;
  baselineLevel: number | null;
}): number | null {
  const { stepOrder, inputSource, priorOutputLevelsByOrder, baselineLevel } = args;
  if (inputSource === "previous_step") {
    return maxLevel(baselineLevel, priorOutputLevelsByOrder.get(stepOrder - 1) ?? null);
  }
  if (inputSource === "all_previous_steps") {
    const priorLevels = [...priorOutputLevelsByOrder.entries()]
      .filter(([order, level]) => order < stepOrder && level !== null)
      .map(([, level]) => level as number);
    return maxLevel(baselineLevel, priorLevels.length > 0 ? Math.max(...priorLevels) : null);
  }
  return baselineLevel;
}

export function buildFlowStepMcpCompatibilityMap(
  input: FlowStepMcpCompatibilityInput
): Record<string, FlowStepMcpCompatibility> {
  const { step, steps, assistantsById, availableServers, spaceSecurityClassification } = input;
  const baselineLevel = classificationLevel(spaceSecurityClassification);
  const priorOutputLevelsByOrder = new Map<number, number | null>();

  for (const currentStep of [...steps].sort((left, right) => left.step_order - right.step_order)) {
    if (currentStep.step_order >= step.step_order) {
      break;
    }

    const assistantId = currentStep.assistant_id ?? "";
    const assistant = assistantsById.get(assistantId) as AssistantMcpLike | null | undefined;
    const currentInputFloor = inputFloorLevel({
      stepOrder: currentStep.step_order,
      inputSource: currentStep.input_source,
      priorOutputLevelsByOrder,
      baselineLevel
    });
    const effectiveOutputLevel = maxLevel(
      currentInputFloor,
      assistantKnowledgeLevel(assistant),
      assistantMcpLevel(assistant),
      currentStep.output_classification_override ?? null
    );
    priorOutputLevelsByOrder.set(currentStep.step_order, effectiveOutputLevel);
  }

  const requiredLevel = inputFloorLevel({
    stepOrder: step.step_order,
    inputSource: step.input_source,
    priorOutputLevelsByOrder,
    baselineLevel
  });

  return Object.fromEntries(
    availableServers.map((server) => {
      const serverLevel = classificationLevel(server.security_classification);
      const isCompatible =
        requiredLevel === null || (serverLevel !== null && serverLevel >= requiredLevel);
      return [
        server.id,
        {
          isCompatible,
          requiredLevel
        }
      ];
    })
  );
}

export function hasLoadedFlowStepMcpClassificationInputs(args: {
  step: FlowStep | null | undefined;
  steps: FlowStep[];
  assistantsById: Map<string, AssistantMcpLike | null | undefined> | Map<string, unknown>;
}): boolean {
  const { step, steps, assistantsById } = args;
  if (!step) return false;
  const requiredAssistantIds = steps
    .filter((candidate) => candidate.step_order <= step.step_order)
    .map((candidate) => candidate.assistant_id)
    .filter(
      (assistantId): assistantId is string =>
        typeof assistantId === "string" && assistantId.length > 0
    );

  return requiredAssistantIds.every((assistantId) => assistantsById.has(assistantId));
}
