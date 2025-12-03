<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { onMount } from "svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Input } from "@intric/ui";
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
  };

  let { selectedMCPServers = $bindable([]), selectedMCPTools = $bindable([]) }: Props = $props();

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

<div class="space-y-2">
  {#if loading}
    <div class="text-muted text-sm">{m.loading()}...</div>
  {:else if availableServers.length === 0}
    <div class="text-muted text-sm">
      <p>{m.no_mcp_servers_available()}</p>
      <p class="mt-1">{m.enable_mcp_in_space_settings()}</p>
    </div>
  {:else}
    {#each availableServers as server (server.id)}
      {@const hasTools = isServerSelected(server.id) && server.tools && server.tools.length > 0}
      {@const isExpanded = expandedServers.has(server.id)}
      <div class="border-default border-b last:border-b-0">
        <!-- Server Row -->
        <div class="flex items-center hover:bg-hover-dimmer">
          <!-- Expand Button -->
          <button
            type="button"
            class="flex h-full w-10 shrink-0 items-center justify-center p-2 disabled:opacity-30"
            disabled={!hasTools}
            onclick={() => toggleExpanded(server.id)}
          >
            <ChevronRight
              class="h-4 w-4 transition-transform {isExpanded ? 'rotate-90' : ''}"
            />
          </button>

          <!-- Server Toggle -->
          <div class="flex-1 py-3 pr-4">
            <Input.Switch
              value={isServerSelected(server.id)}
              sideEffect={() => toggleServer(server)}
            >
              <div class="flex flex-col gap-1">
                <div class="flex items-center gap-2">
                  <span class="font-medium">{server.name}</span>
                  {#if hasTools}
                    <span class="text-xs text-muted">({server.tools?.length} {m.tools()})</span>
                  {/if}
                </div>
                {#if server.description}
                  <div class="text-sm text-muted">{server.description}</div>
                {/if}
                {#if server.tags && server.tags.length > 0}
                  <div class="text-xs text-muted flex gap-2">
                    {#each server.tags as tag}
                      <span
                        class="inline-flex items-center rounded-full border border-gray-300 dark:border-gray-600 px-2 py-0.5 text-xs font-medium text-gray-700 dark:text-gray-300"
                        >{tag}</span
                      >
                    {/each}
                  </div>
                {/if}
              </div>
            </Input.Switch>
          </div>
        </div>

        <!-- Tools List (only show if expanded) -->
        {#if hasTools && isExpanded}
          <div class="pl-10 pr-4 pb-2">
            <div class="text-xs font-medium text-muted mb-2">{m.tools()}</div>
            {#each server.tools as tool (tool.id)}
              <div class="py-2 border-b border-dimmer last:border-b-0 hover:bg-hover-dimmer">
                <Input.Switch
                  value={isToolEnabled(server, tool.id)}
                  sideEffect={() => toggleTool(server, tool)}
                >
                  <div class="flex flex-col">
                    <div class="text-sm font-medium">{tool.name}</div>
                    {#if tool.description}
                      <div class="text-xs text-muted line-clamp-2">{tool.description}</div>
                    {/if}
                  </div>
                </Input.Switch>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    {/each}
  {/if}
</div>
