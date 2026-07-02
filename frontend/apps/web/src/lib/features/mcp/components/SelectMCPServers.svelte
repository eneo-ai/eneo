<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { createEventDispatcher, untrack } from "svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Input, Tooltip } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import { ChevronRight } from "lucide-svelte";
  import { SvelteSet } from "svelte/reactivity";
  import {
    sanitizeMcpSelection,
    type MCPSelectionServer,
    type MCPSelectionTool,
    type MCPToolSelection
  } from "$lib/features/mcp/mcpSelection";

  interface MCPTool extends MCPSelectionTool {
    id: string;
    name: string;
    description?: string;
    is_enabled: boolean;
  }

  interface MCPServer extends MCPSelectionServer {
    id: string;
    name: string;
    description?: string;
    tags?: string[];
    tools?: MCPTool[];
  }

  type ServerCompatibility = {
    isCompatible: boolean;
    requiredLevel?: number | null;
    reason?: string;
  };

  type MCPSelectionChangeDetail = {
    selectedMCPServers: MCPSelectionServer[];
    selectedMCPTools: MCPToolSelection[];
  };

  type Props = {
    selectedMCPServers: MCPSelectionServer[] | undefined;
    selectedMCPTools?: MCPToolSelection[];
    selectedModel?: { supports_tool_calling?: boolean } | null;
    serverCompatibilityById?: Record<string, ServerCompatibility>;
    /** Optional policy-filtered server list for personal assistant governance */
    allowedMCPServers?: { [key: string]: unknown }[] | undefined;
  };

  let {
    selectedMCPServers = $bindable([]),
    selectedMCPTools = $bindable([]),
    selectedModel = null,
    serverCompatibilityById = {},
    allowedMCPServers = undefined
  }: Props = $props();

  let servers = $derived((selectedMCPServers ?? []) as unknown as MCPServer[]);

  let modelSupportsTools = $derived(selectedModel?.supports_tool_calling !== false);
  const dispatch = createEventDispatcher<{ change: MCPSelectionChangeDetail }>();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  // Servers offered for selection: the space's enabled servers (with only their
  // space-enabled tools), narrowed to the policy-allowed set for personal
  // assistants. Pure derivation — never write it from an effect (a self-read +
  // self-write effect re-schedules itself forever and freezes the page).
  let availableServers = $derived.by(() => {
    const spaceServers = (allowedMCPServers ??
      $currentSpace.mcp_servers ??
      []) as unknown as MCPServer[];
    return spaceServers.map((server) => ({
      ...server,
      tools: server.tools?.filter((tool) => tool.is_enabled) || []
    }));
  });

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

  // When the allowed set changes (governance policy, or a server removed from
  // the space), drop any selected server/tool that is no longer available.
  // Keyed only on `availableServers`; the selection reads + writes are
  // untracked so this never re-triggers on user toggles (which would churn the
  // whole list) or loops on its own writes.
  $effect(() => {
    const availableServerIds = new Set(availableServers.map((server) => server.id));
    const availableToolIds = new Set(
      availableServers.flatMap((server) => server.tools?.map((tool) => tool.id) ?? [])
    );
    untrack(() => {
      const filteredSelectedServers = servers.filter((server) => availableServerIds.has(server.id));
      if (filteredSelectedServers.length !== servers.length) {
        selectedMCPServers = filteredSelectedServers;
      }

      const filteredSelectedTools = selectedMCPTools.filter((tool) =>
        availableToolIds.has(tool.tool_id)
      );
      if (filteredSelectedTools.length !== selectedMCPTools.length) {
        selectedMCPTools = filteredSelectedTools;
      }
    });
  });

  function withAllSelectedToolOverrides(
    selectedServers: MCPSelectionServer[],
    currentTools: MCPToolSelection[]
  ): MCPToolSelection[] {
    const toolsById = new Map(currentTools.map((tool) => [tool.tool_id, tool.is_enabled]));

    for (const selectedServer of selectedServers) {
      for (const tool of selectedServer.tools ?? []) {
        if (typeof tool.id !== "string" || toolsById.has(tool.id)) continue;
        toolsById.set(tool.id, tool.is_enabled === true);
      }
    }

    return [...toolsById.entries()].map(([tool_id, is_enabled]) => ({ tool_id, is_enabled }));
  }

  function commitSelection(nextServers: MCPSelectionServer[], nextTools: MCPToolSelection[]): void {
    const sanitized = sanitizeMcpSelection({
      selectedServers: nextServers,
      selectedTools: nextTools,
      availableServers
    });

    selectedMCPServers = sanitized.selectedServers;
    selectedMCPTools = sanitized.selectedTools;
    dispatch("change", {
      selectedMCPServers: sanitized.selectedServers,
      selectedMCPTools: sanitized.selectedTools
    });
  }

  // Check if a server is selected
  function isServerSelected(serverId: string): boolean {
    return servers.some((s) => s.id === serverId);
  }

  function getSelectedServer(serverId: string): MCPServer | undefined {
    return servers.find((s) => s.id === serverId);
  }

  function isToolEnabled(server: MCPServer, toolId: string): boolean {
    const toolOverride = selectedMCPTools.find((t) => t.tool_id === toolId);
    if (toolOverride !== undefined) {
      return toolOverride.is_enabled;
    }

    const selectedServer = getSelectedServer(server.id);
    if (selectedServer && selectedServer.tools) {
      const tool = selectedServer.tools.find((t) => t.id === toolId);
      if (tool) return tool.is_enabled;
    }

    const tool = server.tools?.find((t) => t.id === toolId);
    return tool?.is_enabled ?? false;
  }

  function isServerCompatible(serverId: string): boolean {
    return serverCompatibilityById[serverId]?.isCompatible !== false;
  }

  function toggleServer(server: MCPServer) {
    if (isServerSelected(server.id)) {
      const serverToolIds = new Set((server.tools ?? []).map((tool) => tool.id));
      commitSelection(
        servers.filter((s) => s.id !== server.id),
        selectedMCPTools.filter((tool) => !serverToolIds.has(tool.tool_id))
      );
      return;
    }

    if (!isServerCompatible(server.id)) return;

    const nextServer = {
      ...server,
      tools: (server.tools ?? []).map((tool) => ({ ...tool, is_enabled: true }))
    };
    const nextServerToolIds = new Set(nextServer.tools.map((tool) => tool.id));
    const nextTools = [
      ...selectedMCPTools.filter((tool) => !nextServerToolIds.has(tool.tool_id)),
      ...nextServer.tools.map((tool) => ({
        tool_id: tool.id,
        is_enabled: true
      }))
    ];

    commitSelection([...servers, nextServer], nextTools);
  }

  function toggleTool(server: MCPServer, tool: MCPTool) {
    const currentEnabled = isToolEnabled(server, tool.id);
    const nextServers = servers.map((selectedServer) => {
      if (selectedServer.id !== server.id) return selectedServer;
      return {
        ...selectedServer,
        tools: (selectedServer.tools ?? []).map((selectedTool) =>
          selectedTool.id === tool.id
            ? { ...selectedTool, is_enabled: !currentEnabled }
            : selectedTool
        )
      };
    });

    const nextTools = withAllSelectedToolOverrides(nextServers, selectedMCPTools).map(
      (selectedTool) =>
        selectedTool.tool_id === tool.id
          ? { ...selectedTool, is_enabled: !currentEnabled }
          : selectedTool
    );

    commitSelection(nextServers, nextTools);
  }

  function toggleAllTools(server: MCPServer, enabled: boolean) {
    const serverTools = server.tools ?? [];
    if (!serverTools.some((tool) => isToolEnabled(server, tool.id) !== enabled)) return;

    const serverToolIds = new Set(serverTools.map((tool) => tool.id));
    const nextServers = servers.map((selectedServer) => {
      if (selectedServer.id !== server.id) return selectedServer;
      return {
        ...selectedServer,
        tools: (selectedServer.tools ?? []).map((selectedTool) =>
          serverToolIds.has(selectedTool.id)
            ? { ...selectedTool, is_enabled: enabled }
            : selectedTool
        )
      };
    });
    const nextToolsById = new Map(
      withAllSelectedToolOverrides(nextServers, selectedMCPTools).map((tool) => [
        tool.tool_id,
        tool.is_enabled
      ])
    );

    for (const tool of serverTools) {
      nextToolsById.set(tool.id, enabled);
    }

    commitSelection(
      nextServers,
      [...nextToolsById.entries()].map(([tool_id, is_enabled]) => ({ tool_id, is_enabled }))
    );
  }
</script>

<div class="space-y-1" role="group" aria-label={m.mcp_servers()}>
  {#if !modelSupportsTools}
    <p
      class="label-warning border-label-default bg-label-dimmer text-label-stronger mb-2 rounded-md border px-2 py-1 text-sm"
    >
      <span class="font-bold">{m.warning()}:&nbsp;</span>{m.model_does_not_support_tools()}
    </p>
  {/if}
  {#if availableServers.length === 0}
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
        {@const isCompatible = isServerCompatible(server.id)}
        {@const enabledToolCount =
          server.tools?.filter((t) => isToolEnabled(server, t.id)).length ?? 0}
        <div class="transition-colors {isSelected ? 'bg-accent-dimmer/20' : ''}">
          <div class="flex items-center">
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

            <div class="flex-1 py-2.5 pr-4">
              <Input.Switch
                value={isSelected}
                disabled={!isSelected && !isCompatible}
                sideEffect={() => toggleServer(server)}
              >
                <div class="flex flex-col gap-0.5">
                  <div class="flex items-center gap-2">
                    <span class="text-default font-medium">{server.name}</span>
                    {#if !isCompatible}
                      <Tooltip
                        text={m.flow_step_mcp_server_does_not_meet_security_classification()}
                        placement="bottom"
                      >
                        <span
                          class="label-warning border-label-default bg-label-dimmer text-label-stronger inline-flex rounded border px-1.5 py-0.5 text-[10px] font-medium"
                        >
                          {m.security_classification()}
                        </span>
                      </Tooltip>
                    {/if}
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

          {#if hasTools && isExpanded}
            <div
              class="border-dimmer bg-secondary/20 border-l-accent-default/70 mr-3 mb-2 ml-10 rounded-lg border-t border-l-[3px]"
              role="group"
              aria-label={m.mcp_tools_for_server_aria({ name: server.name })}
            >
              <div class="border-dimmer/50 flex items-center justify-between border-b px-3 py-1.5">
                <span class="text-muted text-[11px] font-medium tracking-wider uppercase"
                  >{m.tools()} ({toolCount})</span
                >
                <div class="flex items-center gap-1">
                  <button
                    type="button"
                    class="text-muted hover:text-default hover:bg-hover-dimmer rounded px-2 py-1 text-[10px] font-medium transition-colors"
                    onclick={() => toggleAllTools(server, true)}
                  >
                    {m.mcp_all_on()}
                  </button>
                  <span class="text-dimmer">|</span>
                  <button
                    type="button"
                    class="text-muted hover:text-default hover:bg-hover-dimmer rounded px-2 py-1 text-[10px] font-medium transition-colors"
                    onclick={() => toggleAllTools(server, false)}
                  >
                    {m.mcp_all_off()}
                  </button>
                </div>
              </div>

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
                      <Input.Switch value={toolEnabled} sideEffect={() => toggleTool(server, tool)}>
                        <span class="sr-only">{tool.name}</span>
                      </Input.Switch>
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
