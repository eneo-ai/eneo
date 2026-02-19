<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Input, Tooltip } from "@intric/ui";
  import { RefreshCw } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { invalidate } from "$app/navigation";

  type Props = {
    mcpServerId: string;
    serverName: string;
    tools: any[];
    intricClient: any;
  };

  const { mcpServerId, serverName, tools: initialTools, intricClient }: Props = $props();

  let tools = $state(initialTools);
  let syncing = $state(false);
  let bulkUpdating = $state(false);

  async function syncTools() {
    syncing = true;
    try {
      await intricClient.mcpServers.syncTools({ mcp_server_id: mcpServerId });
      const response = await intricClient.mcpServers.listTools({ mcp_server_id: mcpServerId });
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

  // Helper: update tool without invalidating (for bulk operations)
  async function updateToolEnabled(tool: any, enabled: boolean) {
    const updated = await intricClient.mcpServers.updateTenantToolEnabled({
      tool_id: tool.id,
      is_enabled: enabled
    });
    tools = tools.map((t) => (t.id === tool.id ? updated : t));
  }

  async function enableAllTools() {
    const targets = tools.filter((t) => !t.is_enabled_by_default);
    if (targets.length === 0) return;

    bulkUpdating = true;
    try {
      const results = await Promise.allSettled(
        targets.map((t) => updateToolEnabled(t, true))
      );
      const failures = results.filter((r) => r.status === "rejected");
      if (failures.length > 0) {
        console.error(`${failures.length} tools failed to enable`);
      }
    } finally {
      await invalidate("spaces:data");
      bulkUpdating = false;
    }
  }

  async function disableAllTools() {
    const targets = tools.filter((t) => t.is_enabled_by_default);
    if (targets.length === 0) return;

    bulkUpdating = true;
    try {
      const results = await Promise.allSettled(
        targets.map((t) => updateToolEnabled(t, false))
      );
      const failures = results.filter((r) => r.status === "rejected");
      if (failures.length > 0) {
        console.error(`${failures.length} tools failed to disable`);
      }
    } finally {
      await invalidate("spaces:data");
      bulkUpdating = false;
    }
  }
</script>

<div class="py-2">
  <!-- Header with sync button -->
  <div class="flex items-center justify-between px-4 py-3 ml-10 mr-4 mb-2 rounded-lg bg-primary/50 border border-dimmer">
    <div class="flex items-center gap-3">
      <div class="flex h-8 w-8 items-center justify-center rounded-md bg-accent-dimmer">
        <svg class="h-4 w-4 text-accent-default" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z" />
        </svg>
      </div>
      <div>
        <span class="text-sm font-medium text-default">{m.tools()}</span>
        <span class="ml-2 inline-flex items-center justify-center rounded-full bg-secondary px-2 py-0.5 text-xs font-medium tabular-nums text-muted">
          {tools.length}
        </span>
      </div>
    </div>
    <Button variant="secondary" size="sm" onclick={syncTools} disabled={syncing} class="gap-1.5">
      <RefreshCw class="h-3.5 w-3.5 {syncing ? 'animate-spin' : ''}" aria-hidden="true" />
      <span>{syncing ? m.syncing() : m.sync_tools()}</span>
    </Button>
  </div>

  <!-- Tools list -->
  <div class="ml-10 mr-4" role="list" aria-label="Tillgängliga verktyg">
    {#if tools.length === 0}
      <div class="flex flex-col items-center justify-center rounded-lg border border-dashed border-dimmer bg-primary/30 px-6 py-8 text-center">
        <svg class="mb-3 h-10 w-10 text-muted/40" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5m6 4.125l2.25 2.25m0 0l2.25 2.25M12 13.875l2.25-2.25M12 13.875l-2.25 2.25M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
        </svg>
        <p class="text-sm font-medium text-muted">{m.no_tools_found()}</p>
        <p class="mt-1 text-xs text-muted/70">{m.click_sync_to_discover_tools()}</p>
      </div>
    {:else}
      {@const enabledCount = tools.filter(t => t.is_enabled_by_default).length}
      <div class="rounded-lg border border-dimmer bg-primary/30 overflow-hidden border-l-[3px] border-l-accent-default/70">
        <!-- Bulk actions header -->
        <div class="flex items-center justify-between px-3 py-1.5 border-b border-dimmer/50 bg-secondary/30">
          <span class="text-[11px] font-medium uppercase tracking-wider text-muted">
            {enabledCount} / {tools.length} {m.enabled().toLowerCase()}
          </span>
          <div class="flex items-center gap-1">
            <button
              type="button"
              class="px-2 py-1 text-[10px] font-medium text-muted hover:text-default hover:bg-hover-dimmer rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-muted"
              onclick={enableAllTools}
              disabled={bulkUpdating}
            >
              Alla på
            </button>
            <span class="text-dimmer">|</span>
            <button
              type="button"
              class="px-2 py-1 text-[10px] font-medium text-muted hover:text-default hover:bg-hover-dimmer rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-muted"
              onclick={disableAllTools}
              disabled={bulkUpdating}
            >
              Alla av
            </button>
          </div>
        </div>
        <!-- Scrollable tools list -->
        <div class="max-h-[280px] overflow-y-auto">
          <div class="divide-y divide-dimmer">
            {#each tools as tool (tool.id)}
              <div
                class="flex items-center gap-3 px-3 py-2.5 transition-all hover:bg-hover-dimmer {tool.is_enabled_by_default ? '' : 'opacity-40 grayscale-[30%]'}"
                role="listitem"
              >
                <div class="flex-1 min-w-0">
                  <span class="text-xs font-medium text-default font-mono block truncate">{tool.name}</span>
                  {#if tool.description}
                    <Tooltip text={tool.description} placement="bottom">
                      <p class="text-xs text-muted leading-snug truncate cursor-help">{tool.description}</p>
                    </Tooltip>
                  {/if}
                </div>
                <Input.Switch
                  value={tool.is_enabled_by_default}
                  sideEffect={() => toggleToolEnabled(tool)}
                  aria-label="Aktivera {tool.name}"
                />
              </div>
            {/each}
          </div>
        </div>
      </div>
    {/if}
  </div>
</div>
