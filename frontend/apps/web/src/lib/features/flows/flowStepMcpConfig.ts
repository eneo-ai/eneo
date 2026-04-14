import type { FlowStep } from "@intric/intric-js";

type MCPToolLike = {
  is_enabled?: boolean;
};

type MCPServerLike = {
  tools?: MCPToolLike[] | null;
};

type AssistantMcpLike = {
  mcp_servers?: MCPServerLike[] | null;
};

export type FlowStepMcpSummary = {
  serverCount: number;
  enabledToolCount: number;
  hasConfiguredMcp: boolean;
};

export function createEmptyFlowStepMcpSummary(): FlowStepMcpSummary {
  return {
    serverCount: 0,
    enabledToolCount: 0,
    hasConfiguredMcp: false
  };
}

export function shouldShowStepMcpSection(
  outputMode: FlowStep["output_mode"] | null | undefined
): boolean {
  return outputMode !== "transcribe_only" && outputMode !== "template_fill";
}

export function summarizeAssistantMcp(
  assistant: AssistantMcpLike | null | undefined
): FlowStepMcpSummary {
  const servers = Array.isArray(assistant?.mcp_servers) ? assistant.mcp_servers : [];
  const enabledToolCount = servers.reduce((count, server) => {
    const tools = Array.isArray(server.tools) ? server.tools : [];
    return count + tools.filter((tool) => tool?.is_enabled === true).length;
  }, 0);

  return {
    ...createEmptyFlowStepMcpSummary(),
    serverCount: servers.length,
    enabledToolCount,
    hasConfiguredMcp: servers.length > 0
  };
}
