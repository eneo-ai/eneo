<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { onMount } from "svelte";
  import { getIntric } from "$lib/core/Intric";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Input } from "@intric/ui";
  import { Plug } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";

  interface MCPServer {
    id: string;
    name: string;
    description?: string;
    is_org_enabled: boolean;
  }

  /** Array of MCP server objects with id field that are selected */
  export let selectedMCPServers: Array<{ id: string }> = [];

  const intric = getIntric();
  const {
    state: { currentSpace }
  } = getSpacesManager();

  let availableMCPs: MCPServer[] = [];
  let loading = true;

  // Load available MCPs that are enabled for the tenant
  async function loadAvailableMCPs() {
    loading = true;
    try {
      const settings = await intric.mcpServers.listSettings();
      // Filter to only show enabled MCPs
      availableMCPs = settings.items.filter((mcp: MCPServer) => mcp.is_org_enabled);
    } catch (error) {
      console.error("Failed to load MCP servers:", error);
      availableMCPs = [];
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    loadAvailableMCPs();
  });

  function toggleMCP(mcpId: string) {
    const isSelected = selectedMCPServers.some((mcp) => mcp.id === mcpId);
    if (isSelected) {
      selectedMCPServers = selectedMCPServers.filter((mcp) => mcp.id !== mcpId);
    } else {
      selectedMCPServers = [...selectedMCPServers, { id: mcpId }];
    }
  }
</script>

<div class="space-y-3">
  {#if loading}
    <div class="text-muted text-sm">{m.loading()}...</div>
  {:else if availableMCPs.length === 0}
    <div class="text-muted text-sm">
      <p>{m.no_mcp_servers_available()}</p>
      <p class="mt-1">{m.enable_mcp_servers_in_admin()}</p>
    </div>
  {:else}
    {#each availableMCPs as mcp}
      <div class="border-default flex items-start gap-3 rounded-lg border p-3">
        <Input.Checkbox
          checked={selectedMCPServers.some((selected) => selected.id === mcp.id)}
          onCheckedChange={() => toggleMCP(mcp.id)}
        />
        <div class="flex-1">
          <div class="flex items-center gap-2">
            <Plug class="text-muted h-4 w-4" />
            <span class="text-default font-medium">{mcp.name}</span>
          </div>
          {#if mcp.description}
            <p class="text-muted text-sm mt-1">{mcp.description}</p>
          {/if}
        </div>
      </div>
    {/each}
  {/if}
</div>
