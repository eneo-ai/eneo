"use client";

import { useAppContext } from "@/components/providers/app-context";
import type { Capability } from "@/features/capabilities/capabilities";
import { useConversationSettings } from "./conversation-settings";

export function useToolChoices() {
  const { featureFlags, can } = useAppContext();
  const { resolution, update } = useConversationSettings();
  const settings = resolution?.settings;
  const modelSupportsTools = resolution?.supports_tool_calling ?? false;
  const allCapabilities = (resolution?.capabilities ?? []).filter((capability) =>
    can(capability.purpose)
  );
  const capabilities = allCapabilities
    .filter((capability) => capability.purpose !== "web_search" || featureFlags.showWebSearch)
    .map((capability) => ({ ...capability, reason: capability.reason ?? null }));
  const mcpServers = (resolution?.mcp_servers ?? []).map((server) => ({
    ...server,
    description: server.description ?? null,
    icon_url: server.icon_url ?? null
  }));
  const disabledCapabilities = new Set(
    allCapabilities.filter(({ selected }) => !selected).map(({ purpose }) => purpose)
  );
  const disabledMcpServerIds = new Set(
    mcpServers.filter(({ selected }) => !selected).map(({ id }) => id)
  );

  function setTools(mcpDisabled: Set<string>, capabilityDisabled: Set<Capability>) {
    // Keep dormant choices for removed/disabled tools, so re-enabling restores the user's choice.
    const mcp_server_states = { ...settings?.mcp_server_states };
    const capability_states = { ...settings?.capability_states };
    for (const server of mcpServers) mcp_server_states[server.id] = !mcpDisabled.has(server.id);
    for (const { purpose } of allCapabilities)
      capability_states[purpose] = !capabilityDisabled.has(purpose);
    void update({ mcp_server_states, capability_states });
  }
  return {
    modelSupportsTools,
    capabilities,
    disabledCapabilities,
    mcpServers,
    disabledMcpServerIds,
    setDisabledCapabilities: (next: Set<Capability>) => setTools(disabledMcpServerIds, next),
    setDisabledMcpServerIds: (next: Set<string>) => setTools(next, disabledCapabilities),
    setTools,
    toggleCapability: (purpose: Capability) => {
      const next = new Set(disabledCapabilities);
      if (next.has(purpose)) next.delete(purpose);
      else next.add(purpose);
      setTools(disabledMcpServerIds, next);
    },
    autoAcceptTools: settings?.require_tool_approval === false,
    setAutoAcceptTools: (enabled: boolean) => {
      void update({ require_tool_approval: !enabled });
    }
  };
}
