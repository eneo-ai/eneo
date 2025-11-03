<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Input, Tooltip } from "@intric/ui";
  import { derived } from "svelte/store";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";

  export let selectableServers: any[];

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

  let loading = new Set<string>();
  async function toggleServer(server: any) {
    loading.add(server.id);
    loading = loading;

    try {
      if ($currentlySelectedServers.includes(server.id)) {
        const newServers = $currentlySelectedServers
          .filter((id) => id !== server.id)
          .map((id) => {
            return { id };
          });
        await updateSpace({ mcp_servers: newServers });
      } else {
        const newServers = [...$currentlySelectedServers, server.id].map((id) => {
          return { id };
        });
        await updateSpace({ mcp_servers: newServers });
      }
    } catch (e) {
      alert(e);
    }
    loading.delete(server.id);
    loading = loading;
  }

  async function toggleTool(tool: any) {
    try {
      // Get current tool settings from space
      const currentTools = $currentSpace.mcp_servers?.flatMap(server =>
        server.tools?.map(t => ({ tool_id: t.id, is_enabled: t.is_enabled })) ?? []
      ) ?? [];

      // Toggle this tool
      const toolExists = currentTools.find(t => t.tool_id === tool.id);
      const newTools = toolExists
        ? currentTools.map(t => t.tool_id === tool.id ? { tool_id: t.tool_id, is_enabled: !t.is_enabled } : t)
        : [...currentTools, { tool_id: tool.id, is_enabled: !tool.is_enabled }];

      await updateSpace({ mcp_tools: newTools });
    } catch (e) {
      alert(e);
    }
  }
</script>

<Settings.Row title="MCP Servers" description="Select which MCP servers are available in this space">
  <svelte:fragment slot="description">
    {#if ($currentSpace.mcp_servers?.length ?? 0) === 0}
      <p
        class="label-warning border-label-default bg-label-dimmer text-label-stronger mt-2.5 rounded-md border px-2 py-1 text-sm"
      >
        <span class="font-bold">{m.hint()}:&nbsp;</span>Enable at least one MCP server to make tools available to assistants.
      </p>
    {/if}
  </svelte:fragment>

  {#each selectableServers as server (server.id)}
    <div class="border-default border-b">
      <!-- Server Toggle -->
      <div class="hover:bg-hover-dimmer cursor-pointer py-4 pr-4 pl-2">
        <Input.Switch
          value={$currentlySelectedServers.includes(server.id)}
          sideEffect={() => toggleServer(server)}
        >
          <div class="flex flex-col gap-1">
            <div class="font-medium">{server.name}</div>
            {#if server.description}
              <div class="text-sm text-muted">{server.description}</div>
            {/if}
            <div class="text-xs text-muted flex gap-2">
              <span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                {server.transport_type}
              </span>
              {#if server.tags && server.tags.length > 0}
                {#each server.tags as tag}
                  <span class="inline-flex items-center rounded-full border border-gray-300 dark:border-gray-600 px-2 py-0.5 text-xs font-medium text-gray-700 dark:text-gray-300">{tag}</span>
                {/each}
              {/if}
            </div>
          </div>
        </Input.Switch>
      </div>

      <!-- Tools List (only show if server is enabled for space) -->
      {#if $currentlySelectedServers.includes(server.id) && getServerTools(server.id).length > 0}
        <div class="bg-hover-dimmer/30 px-8 py-2">
          <div class="text-xs font-medium text-muted mb-2">Tools</div>
          {#each getServerTools(server.id) as tool (tool.id)}
            <div class="py-2">
              <Input.Switch
                value={tool.is_enabled}
                sideEffect={() => toggleTool(tool)}
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
</Settings.Row>
