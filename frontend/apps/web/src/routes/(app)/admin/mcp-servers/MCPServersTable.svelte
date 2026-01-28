<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Input } from "@intric/ui";
  import { ChevronRight } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import MCPServerPrimaryCell from "./MCPServerPrimaryCell.svelte";
  import MCPServerEnabledSwitch from "./MCPServerEnabledSwitch.svelte";
  import MCPServerActions from "./MCPServerActions.svelte";
  import MCPToolsPanel from "./MCPToolsPanel.svelte";
  import { getIntric } from "$lib/core/Intric";

  type Props = {
    mcpServers: any[];
  };

  const { mcpServers }: Props = $props();

  const intric = getIntric();

  // Track which server has tools expanded (only one at a time)
  let expandedServerId = $state<string | null>(null);

  // Filter state
  let filterValue = $state("");

  const filteredServers = $derived(
    mcpServers.filter((server) => {
      if (!filterValue) return true;
      const searchStr = `${server.name} ${server.description || ""} ${server.http_url}`.toLowerCase();
      return searchStr.includes(filterValue.toLowerCase());
    })
  );

  function toggleExpanded(serverId: string) {
    expandedServerId = expandedServerId === serverId ? null : serverId;
  }

  function isExpanded(serverId: string): boolean {
    return expandedServerId === serverId;
  }
</script>

<div class="flex w-full flex-col">
  <!-- Filter bar -->
  <div class="flex items-center justify-between gap-4 pb-1 pr-3 pt-3.5">
    <Input.Text
      bind:value={filterValue}
      label={m.filter()}
      class="flex-grow"
      placeholder="{m.filter()} {m.mcp_servers()}"
      hiddenLabel={true}
      inputClass="!px-4"
    />
  </div>

  <!-- Table header -->
  <div class="w-full">
    <table class="w-full border-separate border-spacing-0 table-fixed">
      <thead class="bg-frosted-glass-primary sticky top-0 z-30">
        <tr>
          <th class="h-14 border-b border-default px-2 text-left font-medium w-10"></th>
          <th class="h-14 border-b border-default px-2 text-left font-medium">{m.name()}</th>
          <th class="h-14 border-b border-default px-2 text-left font-medium w-24">{m.tools()}</th>
          <th class="h-14 border-b border-default px-2 text-left font-medium w-24">{m.enabled()}</th>
          <th class="h-14 border-b border-default px-2 text-left font-medium w-16"></th>
        </tr>
      </thead>
      <tbody>
        {#each filteredServers as server (server.mcp_server_id)}
          <!-- Server row -->
          <tr class="hover:bg-hover-dimmer relative h-16">
            <td class="border-b border-dimmer px-2">
              <Button
                variant="ghost"
                padding="icon"
                onclick={() => toggleExpanded(server.mcp_server_id)}
                disabled={server.tools_count === 0}
              >
                <ChevronRight
                  class="h-4 w-4 transition-transform duration-200 {isExpanded(server.mcp_server_id)
                    ? 'rotate-90'
                    : ''}"
                />
              </Button>
            </td>
            <td class="border-b border-dimmer px-4 overflow-hidden">
              <MCPServerPrimaryCell mcpServer={server} />
            </td>
            <td class="border-b border-dimmer px-4">
              <span class="text-sm text-muted">{server.tools_count ?? 0}</span>
            </td>
            <td class="border-b border-dimmer px-4">
              <MCPServerEnabledSwitch mcpServer={server} />
            </td>
            <td class="border-b border-dimmer px-4">
              <div class="flex items-center justify-end">
                <MCPServerActions mcpServer={server} />
              </div>
            </td>
          </tr>

          <!-- Expanded tools panel row -->
          {#if isExpanded(server.mcp_server_id)}
            <tr>
              <td colspan="5" class="p-0">
                <MCPToolsPanel
                  mcpServerId={server.mcp_server_id}
                  serverName={server.name}
                  tools={server.tools || []}
                  intricClient={intric}
                />
              </td>
            </tr>
          {/if}
        {/each}
      </tbody>
    </table>

    {#if filteredServers.length === 0}
      <div class="pointer-events-none flex min-h-[200px] items-center justify-center">
        <div class="text-center text-muted">
          {#if filterValue}
            <p>{m.no_results_found()}</p>
          {:else}
            <p>{m.no_mcp_servers_available()}</p>
          {/if}
        </div>
      </div>
    {/if}
  </div>
</div>
