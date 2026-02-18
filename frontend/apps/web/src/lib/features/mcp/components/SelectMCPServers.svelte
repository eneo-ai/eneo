<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { onMount } from "svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Input, Tooltip } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { ChevronRight } from "lucide-svelte";

  interface MCPTool {
    id: string;
    name: string;
    description?: string;
    is_enabled: boolean;
  }

  interface MCPServer {
    id: string;
    name: string;
    description?: string;
    tags?: string[];
    tools?: MCPTool[];
  }

  type Props = {
    /** Array of MCP server objects that are selected. */
    selectedMCPServers: Array<any>;
    /** Optional: MCP tool settings to track tool-level overrides */
    selectedMCPTools?: Array<{ tool_id: string; is_enabled: boolean }>;
    /** Optional: Currently selected completion model to check tool calling support */
    selectedModel?: { supports_tool_calling?: boolean } | null;
  };

  let { selectedMCPServers = $bindable([]), selectedMCPTools = $bindable([]), selectedModel = null }: Props = $props();

  let modelSupportsTools = $derived(selectedModel?.supports_tool_calling !== false);

  const {
    state: { currentSpace }
  } = getSpacesManager();

  let availableServers = $state<MCPServer[]>([]);
  let loading = $state(true);

  // Track expanded servers
  let expandedServers = $state(new Set<string>());

  function toggleExpanded(serverId: string) {
    const newExpanded = new Set(expandedServers);
    if (newExpanded.has(serverId)) {
      newExpanded.delete(serverId);
    } else {
      newExpanded.add(serverId);
    }
    expandedServers = newExpanded;
  }

  // Load available MCP servers from space
  async function loadAvailableServers() {
    loading = true;
    try {
      // Get servers enabled for this space, and filter to only show enabled tools
      const spaceServers = $currentSpace.mcp_servers || [];
      availableServers = spaceServers.map((server) => ({
        ...server,
        // Only include tools that are enabled at the space level
        tools: server.tools?.filter((tool) => tool.is_enabled) || []
      }));
    } catch (error) {
      console.error("Failed to load MCP servers:", error);
      availableServers = [];
    } finally {
      loading = false;
    }
  }

  // Ensure all tools from ALL selected servers are tracked in selectedMCPTools
  // This is called when user toggles any tool to ensure complete state is sent to backend
  function ensureAllSelectedServersToolsTracked() {
    let newOverrides: Array<{ tool_id: string; is_enabled: boolean }> = [];

    for (const selectedServer of selectedMCPServers) {
      if (!selectedServer.tools) continue;

      // Check if any tool from this server is already tracked
      const serverToolIds = new Set(selectedServer.tools.map((t: MCPTool) => t.id));
      const hasAnyTracked = selectedMCPTools.some((t) => serverToolIds.has(t.tool_id));

      // If not tracking any tools from this server yet, add ALL of them
      if (!hasAnyTracked) {
        const serverOverrides = selectedServer.tools.map((tool: MCPTool) => ({
          tool_id: tool.id,
          is_enabled: tool.is_enabled
        }));
        newOverrides = [...newOverrides, ...serverOverrides];
      }
    }

    if (newOverrides.length > 0) {
      selectedMCPTools = [...selectedMCPTools, ...newOverrides];
    }
  }

  onMount(() => {
    loadAvailableServers();
  });

  // Check if a server is selected
  function isServerSelected(serverId: string): boolean {
    return selectedMCPServers.some((s) => s.id === serverId);
  }

  // Get the selected server object (if it exists with tools)
  function getSelectedServer(serverId: string): MCPServer | undefined {
    return selectedMCPServers.find((s) => s.id === serverId);
  }

  // Check if a tool is enabled
  function isToolEnabled(server: MCPServer, toolId: string): boolean {
    // First check if there's a tool override in selectedMCPTools
    const toolOverride = selectedMCPTools.find((t) => t.tool_id === toolId);
    if (toolOverride !== undefined) {
      return toolOverride.is_enabled;
    }

    // Otherwise, check the selected server's tools
    const selectedServer = getSelectedServer(server.id);
    if (selectedServer && selectedServer.tools) {
      const tool = selectedServer.tools.find((t) => t.id === toolId);
      if (tool) return tool.is_enabled;
    }

    // Fall back to the available server's tool default
    // Note: Tools are OFF by default for assistants unless explicitly enabled
    const tool = server.tools?.find((t) => t.id === toolId);
    return tool?.is_enabled ?? false;
  }

  function toggleServer(server: MCPServer) {
    if (isServerSelected(server.id)) {
      // Remove server and its tool overrides
      selectedMCPServers = selectedMCPServers.filter((s) => s.id !== server.id);
      if (server.tools) {
        selectedMCPTools = selectedMCPTools.filter(
          (t) => !server.tools?.some((tool) => tool.id === t.tool_id)
        );
      }
    } else {
      // Add server with all tools enabled for convenience
      const newServer = {
        ...server,
        tools: server.tools?.map((tool) => ({ ...tool, is_enabled: true })) || []
      };
      selectedMCPServers = [...selectedMCPServers, newServer];

      // Also add tool overrides so they're sent to backend
      if (server.tools && server.tools.length > 0) {
        const toolOverrides = server.tools.map((tool) => ({
          tool_id: tool.id,
          is_enabled: true
        }));
        selectedMCPTools = [...selectedMCPTools, ...toolOverrides];
      }
    }
  }

  function toggleTool(server: MCPServer, tool: MCPTool) {
    // First ensure ALL tools from ALL selected servers are tracked (so they're all sent to backend)
    ensureAllSelectedServersToolsTracked();

    const currentEnabled = isToolEnabled(server, tool.id);

    // Update the tool override (it should exist now after ensureAllSelectedServersToolsTracked)
    const existingIndex = selectedMCPTools.findIndex((t) => t.tool_id === tool.id);
    if (existingIndex !== -1) {
      selectedMCPTools[existingIndex].is_enabled = !currentEnabled;
      selectedMCPTools = [...selectedMCPTools];
    } else {
      selectedMCPTools = [...selectedMCPTools, { tool_id: tool.id, is_enabled: !currentEnabled }];
    }

    // Also update the tool in the selected server object
    const selectedServerIndex = selectedMCPServers.findIndex((s) => s.id === server.id);
    if (selectedServerIndex !== -1 && selectedMCPServers[selectedServerIndex].tools) {
      const toolIndex = selectedMCPServers[selectedServerIndex].tools.findIndex(
        (t: MCPTool) => t.id === tool.id
      );
      if (toolIndex !== -1) {
        selectedMCPServers[selectedServerIndex].tools[toolIndex].is_enabled = !currentEnabled;
        selectedMCPServers = [...selectedMCPServers];
      }
    }
  }
</script>

<div class="space-y-1" role="group" aria-label="MCP-servrar">
  {#if !modelSupportsTools}
    <p
      class="label-warning border-label-default bg-label-dimmer text-label-stronger mb-2 rounded-md border px-2 py-1 text-sm"
    >
      <span class="font-bold">{m.warning()}:&nbsp;</span>{m.model_does_not_support_tools()}
    </p>
  {/if}
  {#if loading}
    <div class="flex items-center gap-3 rounded-lg border border-dashed border-dimmer bg-secondary/30 px-4 py-6">
      <svg class="h-5 w-5 animate-spin text-muted" fill="none" viewBox="0 0 24 24" aria-hidden="true">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
      </svg>
      <span class="text-sm text-muted">{m.loading()}...</span>
    </div>
  {:else if availableServers.length === 0}
    <div class="flex flex-col items-center gap-3 rounded-lg border border-dashed border-dimmer bg-secondary/30 px-6 py-8 text-center">
      <div class="flex h-12 w-12 items-center justify-center rounded-xl bg-secondary">
        <svg class="h-6 w-6 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" />
        </svg>
      </div>
      <div>
        <p class="text-sm font-medium text-default">{m.no_mcp_servers_available()}</p>
        <p class="mt-1 text-xs text-muted">{m.enable_mcp_in_space_settings()}</p>
      </div>
    </div>
  {:else}
    <div class="divide-y divide-dimmer rounded-xl border border-default overflow-hidden">
      {#each availableServers as server (server.id)}
        {@const isSelected = isServerSelected(server.id)}
        {@const hasTools = isSelected && server.tools && server.tools.length > 0}
        {@const isExpanded = expandedServers.has(server.id)}
        {@const toolCount = server.tools?.length ?? 0}
        {@const enabledToolCount = server.tools?.filter(t => isToolEnabled(server, t.id)).length ?? 0}
        <div class="transition-colors {isSelected ? 'bg-accent-dimmer/20' : ''}">
          <!-- Server Row -->
          <div class="flex items-center">
            <!-- Expand Button -->
            <button
              type="button"
              class="flex h-full w-10 shrink-0 items-center justify-center p-2.5 text-muted transition-colors hover:text-default disabled:opacity-20 disabled:hover:text-muted"
              disabled={!hasTools}
              onclick={() => toggleExpanded(server.id)}
              aria-label={isExpanded ? 'Dölj verktyg' : 'Visa verktyg'}
              aria-expanded={isExpanded}
            >
              <ChevronRight
                class="h-4 w-4 transition-transform duration-200 {isExpanded ? 'rotate-90' : ''}"
              />
            </button>

            <!-- Server Toggle -->
            <div class="flex-1 py-2.5 pr-4">
              <Input.Switch
                value={isSelected}
                sideEffect={() => toggleServer(server)}
              >
                <div class="flex flex-col gap-0.5">
                  <div class="flex items-center gap-2">
                    <span class="font-medium text-default">{server.name}</span>
                    {#if hasTools}
                      <span class="inline-flex items-center gap-1 rounded bg-secondary px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-muted">
                        <span class="text-positive-default">{enabledToolCount}</span>
                        <span class="text-dimmer">/</span>
                        <span>{toolCount}</span>
                      </span>
                    {/if}
                  </div>
                  {#if server.description}
                    <p class="text-xs text-muted leading-snug line-clamp-1">{server.description}</p>
                  {/if}
                </div>
              </Input.Switch>
            </div>
          </div>

          <!-- Tools List (only show if expanded) -->
          {#if hasTools && isExpanded}
            <div class="border-t border-dimmer bg-secondary/20 ml-10 mr-3 mb-2 rounded-lg border-l-[3px] border-l-accent-default/70" role="group" aria-label="Verktyg för {server.name}">
              <!-- Tools header with bulk actions -->
              <div class="flex items-center justify-between px-3 py-1.5 border-b border-dimmer/50">
                <span class="text-[11px] font-medium uppercase tracking-wider text-muted">{m.tools()} ({toolCount})</span>
                <div class="flex items-center gap-1">
                  <button
                    type="button"
                    class="px-2 py-1 text-[10px] font-medium text-muted hover:text-default hover:bg-hover-dimmer rounded transition-colors"
                    onclick={() => {
                      server.tools?.forEach(tool => {
                        if (!isToolEnabled(server, tool.id)) toggleTool(server, tool);
                      });
                    }}
                  >
                    Alla på
                  </button>
                  <span class="text-dimmer">|</span>
                  <button
                    type="button"
                    class="px-2 py-1 text-[10px] font-medium text-muted hover:text-default hover:bg-hover-dimmer rounded transition-colors"
                    onclick={() => {
                      server.tools?.forEach(tool => {
                        if (isToolEnabled(server, tool.id)) toggleTool(server, tool);
                      });
                    }}
                  >
                    Alla av
                  </button>
                </div>
              </div>

              <!-- Scrollable tools list -->
              <div class="max-h-[240px] overflow-y-auto">
                <div class="divide-y divide-dimmer">
                  {#each server.tools as tool (tool.id)}
                    {@const toolEnabled = isToolEnabled(server, tool.id)}
                    <div class="flex items-center gap-3 px-3 py-2.5 transition-all hover:bg-hover-dimmer {toolEnabled ? '' : 'opacity-40 grayscale-[30%]'}">
                      <div class="flex-1 min-w-0">
                        <span class="text-xs font-medium font-mono text-default block truncate">{tool.name}</span>
                        {#if tool.description}
                          <Tooltip text={tool.description} placement="bottom">
                            <p class="text-xs text-muted leading-snug truncate cursor-help">{tool.description}</p>
                          </Tooltip>
                        {/if}
                      </div>
                      <Input.Switch
                        value={toolEnabled}
                        sideEffect={() => toggleTool(server, tool)}
                        aria-label="Aktivera {tool.name}"
                      />
                    </div>
                  {/each}
                </div>
              </div>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>
