<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Input } from "@intric/ui";
  import { RefreshCw } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { invalidate } from "$app/navigation";

  type Props = {
    mcpServerId: string;
    serverName: string;
    intricClient: any;
    onClose: () => void;
  };

  const { mcpServerId, serverName, intricClient, onClose }: Props = $props();

  let tools = $state<any[]>([]);
  let loading = $state(true);
  let syncing = $state(false);

  // Load tools on mount
  $effect(() => {
    loadTools();
  });

  async function loadTools() {
    loading = true;
    try {
      const response = await intricClient.mcpServers.listTools({ mcp_server_id: mcpServerId });
      tools = response.items || [];
    } catch (error) {
      console.error("Failed to load tools:", error);
    } finally {
      loading = false;
    }
  }

  async function syncTools() {
    syncing = true;
    try {
      const response = await intricClient.mcpServers.syncTools({ mcp_server_id: mcpServerId });
      tools = response.items || [];
      await invalidate("spaces:data");
    } catch (error) {
      console.error("Failed to sync tools:", error);
    } finally {
      syncing = false;
    }
  }

  async function toggleToolEnabled(tool: any) {
    try {
      const updated = await intricClient.mcpServers.updateTenantToolEnabled({
        tool_id: tool.id,
        is_enabled: !tool.is_enabled_by_default
      });

      tools = tools.map((t) => (t.id === tool.id ? updated : t));
      await invalidate("spaces:data");
    } catch (error) {
      console.error("Failed to update tool:", error);
    }
  }
</script>

<div>
  <!-- Header with sync button -->
  <div class="flex items-center justify-between py-2 pl-14 pr-4">
    <span class="text-xs font-medium text-muted">
      {m.tools()} ({tools.length})
    </span>
    <Button variant="ghost" size="sm" onclick={syncTools} disabled={syncing || loading}>
      <RefreshCw class="mr-1.5 h-3 w-3 {syncing ? 'animate-spin' : ''}" />
      <span class="text-xs">{syncing ? m.syncing() : m.sync_tools()}</span>
    </Button>
  </div>

  <!-- Tools list -->
  <div>
    {#if loading}
      <div class="text-muted pl-14 pr-4 py-4 text-sm">{m.loading()}</div>
    {:else if tools.length === 0}
      <div class="text-muted pl-14 pr-4 py-4 text-sm">
        <p>{m.no_tools_found()}</p>
        <p class="mt-1 text-xs">{m.click_sync_to_discover_tools()}</p>
      </div>
    {:else}
      {#each tools as tool (tool.id)}
        <div class="flex items-start gap-4 py-2 pl-14 pr-4 hover:bg-hover-dimmer border-b border-dimmer last:border-b-0">
          <div class="flex-1 min-w-0 overflow-hidden">
            <div class="text-sm">{tool.name}</div>
            {#if tool.description}
              <div class="text-xs text-muted line-clamp-2">{tool.description}</div>
            {/if}
          </div>
          <div class="shrink-0">
            <Input.Switch
              value={tool.is_enabled_by_default}
              sideEffect={() => toggleToolEnabled(tool)}
            />
          </div>
        </div>
      {/each}
    {/if}
  </div>
</div>
