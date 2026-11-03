import { useAppContext, type AppContextValue } from "@/components/providers/app-context";
import type { Capability } from "@/features/capabilities/capabilities";
import type { Schema } from "@/lib/api/models";
import { useConversationSettings } from "./conversation-settings";

/** The capabilities the user may use, as this conversation's settings choose them. */
function permittedCapabilities(
  resolution: Schema<"ConversationSettingsResolution"> | null,
  can: AppContextValue["can"]
) {
  return (resolution?.capabilities ?? []).filter((capability) => can(capability.purpose));
}

/** The capabilities the user may use that this conversation has switched off. */
export function disabledCapabilitiesOf(
  resolution: Schema<"ConversationSettingsResolution"> | null,
  can: AppContextValue["can"]
) {
  return new Set(
    permittedCapabilities(resolution, can)
      .filter(({ selected }) => !selected)
      .map(({ purpose }) => purpose)
  );
}

export function useToolChoices() {
  const { can } = useAppContext();
  const { resolution, update } = useConversationSettings();
  const settings = resolution?.settings;
  const modelSupportsTools = resolution?.supports_tool_calling ?? false;
  const allCapabilities = permittedCapabilities(resolution, can);
  const capabilities = allCapabilities.map((capability) => ({
    ...capability,
    reason: capability.reason ?? null
  }));
  const mcpServers = (resolution?.mcp_servers ?? []).map((server) => ({
    ...server,
    description: server.description ?? null,
    icon_url: server.icon_url ?? null
  }));
  const disabledCapabilities = disabledCapabilitiesOf(resolution, can);
  const disabledMcpServerIds = new Set(
    mcpServers.filter(({ selected }) => !selected).map(({ id }) => id)
  );

  function setTools(mcpDisabled: Set<string>, capabilityDisabled: Set<Capability>) {
    // Only what the user changed is sent, and the provider merges it into the
    // latest maps: a tool never touched stays out of them and keeps following
    // the administrator's default, dormant choices for removed tools stay, and
    // a change queued behind another save cannot undo it.
    const mcp_server_states: Record<string, boolean> = {};
    const capability_states: Record<string, boolean> = {};
    for (const server of mcpServers) {
      const selected = !mcpDisabled.has(server.id);
      if (selected !== server.selected) mcp_server_states[server.id] = selected;
    }
    for (const capability of allCapabilities) {
      const selected = !capabilityDisabled.has(capability.purpose);
      if (selected !== capability.selected) capability_states[capability.purpose] = selected;
    }
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
