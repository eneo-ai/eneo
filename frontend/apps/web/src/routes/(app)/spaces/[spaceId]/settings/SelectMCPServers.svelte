<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Input } from "@intric/ui";
  import { derived } from "svelte/store";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { ChevronRight } from "lucide-svelte";

  type Props = {
    selectableServers: any[];
  };

  const { selectableServers }: Props = $props();

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

  const {
    state: { currentSpace },
    updateSpace
  } = getSpacesManager();

  const currentlySelectedServers = derived(
    currentSpace,
    ($currentSpace) => $currentSpace.mcp_servers?.map((server) => server.id) ?? []
  );

  // Get tools for a specific server from current space
  function getServerTools(serverId: string) {
    const server = $currentSpace.mcp_servers?.find((s) => s.id === serverId);
    return server?.tools ?? [];
  }

  let loading = $state(new Set<string>());

  async function toggleServer(server: any) {
    const newLoading = new Set(loading);
    newLoading.add(server.id);
    loading = newLoading;

    try {
      if ($currentlySelectedServers.includes(server.id)) {
        const newServers = $currentlySelectedServers
          .filter((id) => id !== server.id)
          .map((id) => ({ id }));
        await updateSpace({ mcp_servers: newServers });
      } else {
        const newServers = [...$currentlySelectedServers, server.id].map((id) => ({ id }));
        await updateSpace({ mcp_servers: newServers });
      }
    } catch (e) {
      console.error("Failed to toggle server:", e);
    }

    const updatedLoading = new Set(loading);
    updatedLoading.delete(server.id);
    loading = updatedLoading;
  }

  async function toggleTool(tool: any) {
    try {
      // Get current tool settings from space
      const currentTools =
        $currentSpace.mcp_servers?.flatMap(
          (server) => server.tools?.map((t) => ({ tool_id: t.id, is_enabled: t.is_enabled })) ?? []
        ) ?? [];

      // Toggle this tool
      const toolExists = currentTools.find((t) => t.tool_id === tool.id);
      const newTools = toolExists
        ? currentTools.map((t) =>
            t.tool_id === tool.id ? { tool_id: t.tool_id, is_enabled: !t.is_enabled } : t
          )
        : [...currentTools, { tool_id: tool.id, is_enabled: !tool.is_enabled }];

      await updateSpace({ mcp_tools: newTools });
    } catch (e) {
      console.error("Failed to toggle tool:", e);
    }
  }
</script>

<Settings.Row title="MCP Servers" description="Select which MCP servers are available in this space">
  <svelte:fragment slot="description">
    {#if ($currentSpace.mcp_servers?.length ?? 0) === 0}
      <p
        class="label-warning border-label-default bg-label-dimmer text-label-stronger mt-2.5 rounded-md border px-2 py-1 text-sm"
      >
        <span class="font-bold">{m.hint()}:&nbsp;</span>Enable at least one MCP server to make
        tools available to assistants.
      </p>
    {/if}
  </svelte:fragment>

  {#each selectableServers as server (server.id)}
    {@const serverTools = getServerTools(server.id)}
    {@const hasTools = $currentlySelectedServers.includes(server.id) && serverTools.length > 0}
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
        <div class="flex-1 py-4 pr-4">
          <Input.Switch
            value={$currentlySelectedServers.includes(server.id)}
            sideEffect={() => toggleServer(server)}
          >
            <div class="flex flex-col gap-1">
              <div class="flex items-center gap-2">
                <span class="font-medium">{server.name}</span>
                {#if hasTools}
                  <span class="text-xs text-muted">({serverTools.length} {m.tools()})</span>
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
          {#each serverTools as tool (tool.id)}
            <div class="py-2 border-b border-dimmer last:border-b-0 hover:bg-hover-dimmer">
              <Input.Switch value={tool.is_enabled} sideEffect={() => toggleTool(tool)}>
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
</Settings.Row>
