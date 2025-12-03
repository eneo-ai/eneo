<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { onMount } from "svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

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
    const tool = server.tools?.find((t) => t.id === toolId);
    return tool?.is_enabled ?? true;
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
      // Add server with its tools (using space's enabled state)
      const newServer = { ...server };
      selectedMCPServers = [...selectedMCPServers, newServer];
    }
  }

  function toggleTool(server: MCPServer, tool: MCPTool) {
    const currentEnabled = isToolEnabled(server, tool.id);

    // Update or add tool override
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
      <p class="mt-1">Enable MCP servers in space settings first.</p>
    </div>
  {:else}
    {#each availableServers as server (server.id)}
      <div class="border-default border-b last:border-b-0">
        <!-- Server Toggle -->
        <div class="hover:bg-hover-dimmer cursor-pointer py-3 pr-4 pl-2">
          <Input.Switch
            value={isServerSelected(server.id)}
            sideEffect={() => toggleServer(server)}
          >
            <div class="flex flex-col gap-1">
              <div class="font-medium">{server.name}</div>
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

        <!-- Tools List (only show if server is enabled and has tools) -->
        {#if isServerSelected(server.id) && server.tools && server.tools.length > 0}
          <div class="bg-hover-dimmer/30 px-8 py-2">
            <div class="text-xs font-medium text-muted mb-2">Tools</div>
            {#each server.tools as tool (tool.id)}
              <div class="py-2">
                <Input.Switch
                  value={isToolEnabled(server, tool.id)}
                  sideEffect={() => toggleTool(server, tool)}
                >
                  <div class="flex flex-col">
                    <div class="text-sm font-medium">{tool.name}</div>
                    {#if tool.description}
                      <div class="text-xs text-muted">{tool.description}</div>
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
