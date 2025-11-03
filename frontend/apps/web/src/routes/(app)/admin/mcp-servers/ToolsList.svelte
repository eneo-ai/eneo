<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Input } from "@intric/ui";
  import { RefreshCw, ChevronDown, ChevronRight } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { invalidate } from "$app/navigation";

  type Props = {
    mcpServerId: string;
    intricClient: any;
  };

  const { mcpServerId, intricClient }: Props = $props();

  let tools = $state<any[]>([]);
  let loading = $state(false);
  let syncing = $state(false);
  let expanded = $state(false);
  let expandedGroups = $state<Set<string>>(new Set());

  // Detect group from tool name
  function detectToolGroup(toolName: string): string | null {
    // Try double underscore first (most common convention)
    if (toolName.includes("__")) {
      const parts = toolName.split("__", 2);
      if (parts.length === 2 && parts[0]) {
        return parts[0];
      }
    }

    // Try single underscore (but only if there's more than 2 parts)
    if (toolName.includes("_")) {
      const parts = toolName.split("_");
      if (parts.length >= 2 && parts[0].length > 2) {
        // Only consider it a group if prefix is substantial
        // This avoids false positives like "get_data" -> "get"
        return parts[0];
      }
    }

    return null;
  }

  // Group tools by detecting group from tool names
  let groupedTools = $derived.by(() => {
    const groups: Record<string, any[]> = {};
    const ungrouped: any[] = [];

    for (const tool of tools) {
      const group = detectToolGroup(tool.name);
      if (group) {
        if (!groups[group]) {
          groups[group] = [];
        }
        groups[group].push(tool);
      } else {
        ungrouped.push(tool);
      }
    }

    return { groups, ungrouped };
  });

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
      console.error('Failed to load tools:', error);
    } finally {
      loading = false;
    }
  }

  async function syncTools() {
    syncing = true;
    try {
      const response = await intricClient.mcpServers.syncTools({ mcp_server_id: mcpServerId });
      tools = response.items || [];
    } catch (error) {
      console.error('Failed to sync tools:', error);
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

      // Update local state
      tools = tools.map(t => t.id === tool.id ? updated : t);

      // Invalidate only space data, not the entire layout
      // This triggers a refetch of space data to reflect tenant-level tool changes
      await invalidate('spaces:data');
    } catch (error) {
      console.error('Failed to update tool:', error);
    }
  }

  function toggleGroup(groupName: string) {
    const newExpanded = new Set(expandedGroups);
    if (newExpanded.has(groupName)) {
      newExpanded.delete(groupName);
    } else {
      newExpanded.add(groupName);
    }
    expandedGroups = newExpanded;
  }
</script>

<div class="mt-4">
  <div class="flex items-center justify-between">
    <button
      onclick={() => expanded = !expanded}
      class="flex items-center gap-2 text-sm font-medium text-default hover:text-muted transition-colors"
    >
      {#if expanded}
        <ChevronDown class="h-4 w-4" />
      {:else}
        <ChevronRight class="h-4 w-4" />
      {/if}
      <span>Tools ({tools.length})</span>
    </button>

    <Button
      variant="ghost"
      size="sm"
      onclick={syncTools}
      disabled={syncing || loading}
    >
      <RefreshCw class="h-4 w-4 {syncing ? 'animate-spin' : ''}" />
      {syncing ? 'Syncing...' : 'Sync Tools'}
    </Button>
  </div>

  {#if expanded}
    <div class="mt-3 space-y-3">
      {#if loading}
        <p class="text-sm text-muted">Loading tools...</p>
      {:else if tools.length === 0}
        <p class="text-sm text-muted">No tools available. Click "Sync Tools" to discover tools from this server.</p>
      {:else}
        {@const { groups, ungrouped } = groupedTools}

        <!-- Grouped tools -->
        {#each Object.entries(groups) as [groupName, groupTools]}
          <div class="border-default rounded-md border overflow-hidden">
            <button
              onclick={() => toggleGroup(groupName)}
              class="w-full flex items-center justify-between bg-muted px-3 py-2 hover:bg-accent transition-colors"
            >
              <div class="flex items-center gap-2">
                {#if expandedGroups.has(groupName)}
                  <ChevronDown class="h-3.5 w-3.5" />
                {:else}
                  <ChevronRight class="h-3.5 w-3.5" />
                {/if}
                <span class="text-sm font-medium text-default capitalize">{groupName}</span>
                <span class="text-xs text-muted">({groupTools.length})</span>
              </div>
            </button>

            {#if expandedGroups.has(groupName)}
              <div class="divide-y divide-default">
                {#each groupTools as tool}
                  <div class="bg-secondary p-3">
                    <div class="flex items-start justify-between">
                      <div class="flex-1">
                        <h4 class="text-sm font-medium text-default">{tool.name}</h4>
                        {#if tool.description}
                          <p class="text-xs text-muted mt-1">{tool.description}</p>
                        {/if}
                      </div>
                      <div class="ml-4">
                        <Input.Switch
                          value={tool.is_enabled_by_default}
                          sideEffect={() => toggleToolEnabled(tool)}
                        />
                      </div>
                    </div>
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        {/each}

        <!-- Ungrouped tools -->
        {#if ungrouped.length > 0}
          <div class="space-y-2">
            {#if Object.keys(groups).length > 0}
              <h4 class="text-xs font-medium text-muted uppercase tracking-wide">Other Tools</h4>
            {/if}
            {#each ungrouped as tool}
              <div class="border-default bg-secondary rounded-md border p-3">
                <div class="flex items-start justify-between">
                  <div class="flex-1">
                    <h4 class="text-sm font-medium text-default">{tool.name}</h4>
                    {#if tool.description}
                      <p class="text-xs text-muted mt-1">{tool.description}</p>
                    {/if}
                  </div>
                  <div class="ml-4">
                    <Input.Switch
                      value={tool.is_enabled_by_default}
                      sideEffect={() => toggleToolEnabled(tool)}
                    />
                  </div>
                </div>
              </div>
            {/each}
          </div>
        {/if}
      {/if}
    </div>
  {/if}
</div>
