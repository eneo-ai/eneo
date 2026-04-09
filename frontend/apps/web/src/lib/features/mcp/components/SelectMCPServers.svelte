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
  import { SvelteSet } from "svelte/reactivity";

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
    [key: string]: unknown;
  }

  type Props = {
    /** Array of MCP server objects that are selected. Uses index signature for schema compatibility. */
    selectedMCPServers: { [key: string]: unknown }[];
    /** Optional: MCP tool settings to track tool-level overrides */
    selectedMCPTools?: Array<{ tool_id: string; is_enabled: boolean }>;
    /** Optional: Currently selected completion model to check tool calling support */
    selectedModel?: { supports_tool_calling?: boolean } | null;
  };

  let {
    selectedMCPServers = $bindable([]),
    selectedMCPTools = $bindable([]),
    selectedModel = null
  }: Props = $props();

  /** Type-safe view of selectedMCPServers */
  let servers = $derived(selectedMCPServers as unknown as MCPServer[]);

  let modelSupportsTools = $derived(selectedModel?.supports_tool_calling !== false);

  const {
    state: { currentSpace }
  } = getSpacesManager();

  let availableServers = $state<MCPServer[]>([]);
  let loading = $state(true);

  // Track expanded servers
  const expandedServers = new SvelteSet<string>();

  function toggleExpanded(serverId: string) {
    if (expandedServers.has(serverId)) {
      expandedServers.delete(serverId);
    } else {
      expandedServers.add(serverId);
    }
  }

  function getServerTools(server: MCPServer): MCPTool[] {
    return server.tools ?? [];
  }

  // Load available MCP servers from space
  async function loadAvailableServers() {
    loading = true;
    try {
      // Get servers enabled for this space, and filter to only show enabled tools
      const spaceServers = ($currentSpace.mcp_servers || []) as unknown as MCPServer[];
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

    for (const selectedServer of servers) {
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
    return servers.some((s) => s.id === serverId);
  }

  // Get the selected server object (if it exists with tools)
  function getSelectedServer(serverId: string): MCPServer | undefined {
    return servers.find((s) => s.id === serverId);
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
      selectedMCPServers = servers.filter((s) => s.id !== server.id);
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
      selectedMCPServers = [...servers, newServer];

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
    const selectedServerIndex = servers.findIndex((s) => s.id === server.id);
    if (selectedServerIndex !== -1 && servers[selectedServerIndex].tools) {
      const toolIndex = servers[selectedServerIndex].tools!.findIndex(
        (t: MCPTool) => t.id === tool.id
      );
      if (toolIndex !== -1) {
        servers[selectedServerIndex].tools![toolIndex].is_enabled = !currentEnabled;
        selectedMCPServers = [...servers];
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
    <div
      class="border-dimmer bg-secondary/30 flex items-center gap-3 rounded-lg border border-dashed px-4 py-6"
    >
      <svg
        class="text-muted h-5 w-5 animate-spin"
        fill="none"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
        ></circle>
        <path
          class="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        ></path>
      </svg>
      <span class="text-muted text-sm">{m.loading()}...</span>
    </div>
  {:else if availableServers.length === 0}
    <div
      class="border-dimmer bg-secondary/30 flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-8 text-center"
    >
      <div class="bg-secondary flex h-12 w-12 items-center justify-center rounded-xl">
        <svg
          class="text-muted h-6 w-6"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          stroke-width="1.5"
          aria-hidden="true"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z"
          />
        </svg>
      </div>
      <div>
        <p class="text-default text-sm font-medium">{m.no_mcp_servers_available()}</p>
        <p class="text-muted mt-1 text-xs">{m.enable_mcp_in_space_settings()}</p>
      </div>
    </div>
  {:else}
    <div class="divide-dimmer border-default divide-y overflow-hidden rounded-xl border">
      {#each availableServers as server (server.id)}
        {@const isSelected = isServerSelected(server.id)}
        {@const hasTools = isSelected && server.tools && server.tools.length > 0}
        {@const isExpanded = expandedServers.has(server.id)}
        {@const toolCount = server.tools?.length ?? 0}
        {@const enabledToolCount =
          server.tools?.filter((t) => isToolEnabled(server, t.id)).length ?? 0}
        <div class="transition-colors {isSelected ? 'bg-accent-dimmer/20' : ''}">
          <!-- Server Row -->
          <div class="flex items-center">
            <!-- Expand Button -->
            <button
              type="button"
              class="text-muted hover:text-default disabled:hover:text-muted flex h-full w-10 shrink-0 items-center justify-center p-2.5 transition-colors disabled:opacity-20"
              disabled={!hasTools}
              onclick={() => toggleExpanded(server.id)}
              aria-label={isExpanded ? "Dölj verktyg" : "Visa verktyg"}
              aria-expanded={isExpanded}
            >
              <ChevronRight
                class="h-4 w-4 transition-transform duration-200 {isExpanded ? 'rotate-90' : ''}"
              />
            </button>

            <!-- Server Toggle -->
            <div class="flex-1 py-2.5 pr-4">
              <Input.Switch value={isSelected} sideEffect={() => toggleServer(server)}>
                <div class="flex flex-col gap-0.5">
                  <div class="flex items-center gap-2">
                    <span class="text-default font-medium">{server.name}</span>
                    {#if hasTools}
                      <span
                        class="bg-secondary text-muted inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium tabular-nums"
                      >
                        <span class="text-positive-default">{enabledToolCount}</span>
                        <span class="text-dimmer">/</span>
                        <span>{toolCount}</span>
                      </span>
                    {/if}
                  </div>
                  {#if server.description}
                    <p class="text-muted line-clamp-1 text-xs leading-snug">{server.description}</p>
                  {/if}
                </div>
              </Input.Switch>
            </div>
          </div>

          <!-- Tools List (only show if expanded) -->
          {#if hasTools && isExpanded}
            <div
              class="border-dimmer bg-secondary/20 border-l-accent-default/70 mr-3 mb-2 ml-10 rounded-lg border-t border-l-[3px]"
              role="group"
              aria-label="Verktyg för {server.name}"
            >
              <!-- Tools header with bulk actions -->
              <div class="border-dimmer/50 flex items-center justify-between border-b px-3 py-1.5">
                <span class="text-muted text-[11px] font-medium tracking-wider uppercase"
                  >{m.tools()} ({toolCount})</span
                >
                <div class="flex items-center gap-1">
                  <button
                    type="button"
                    class="text-muted hover:text-default hover:bg-hover-dimmer rounded px-2 py-1 text-[10px] font-medium transition-colors"
                    onclick={() => {
                      server.tools?.forEach((tool) => {
                        if (!isToolEnabled(server, tool.id)) toggleTool(server, tool);
                      });
                    }}
                  >
                    Alla på
                  </button>
                  <span class="text-dimmer">|</span>
                  <button
                    type="button"
                    class="text-muted hover:text-default hover:bg-hover-dimmer rounded px-2 py-1 text-[10px] font-medium transition-colors"
                    onclick={() => {
                      server.tools?.forEach((tool) => {
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
                <div class="divide-dimmer divide-y">
                  {#each getServerTools(server) as tool (tool.id)}
                    {@const toolEnabled = isToolEnabled(server, tool.id)}
                    <div
                      class="hover:bg-hover-dimmer flex items-center gap-3 px-3 py-2.5 transition-all {toolEnabled
                        ? ''
                        : 'opacity-40 grayscale-[30%]'}"
                    >
                      <div class="min-w-0 flex-1">
                        <span class="text-default block truncate font-mono text-xs font-medium"
                          >{tool.name}</span
                        >
                        {#if tool.description}
                          <Tooltip text={tool.description} placement="bottom">
                            <p class="text-muted cursor-help truncate text-xs leading-snug">
                              {tool.description}
                            </p>
                          </Tooltip>
                        {/if}
                      </div>
                      <Input.Switch
                        value={toolEnabled}
                        sideEffect={() => toggleTool(server, tool)}
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
