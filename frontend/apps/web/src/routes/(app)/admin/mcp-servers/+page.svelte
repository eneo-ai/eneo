<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { Button } from "@intric/ui";
  import { invalidate } from "$app/navigation";
  import { Plus } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import MCPServerDialog from "./MCPServerDialog.svelte";
  import MCPServersTable from "./MCPServersTable.svelte";
  import { writable } from "svelte/store";

  const { data } = $props();

  let showAddDialog = writable(false);

  async function handleAddMCP(mcpData: any) {
    await data.intric.mcpServers.create(mcpData);
    await Promise.all([invalidate("admin:layout"), invalidate("spaces:data")]);
  }

  const mcpServers = $derived(data.mcpSettings?.items || []);
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.mcp_servers()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.mcp_servers()}></Page.Title>
    <div class="flex gap-2">
      <Button variant="primary" size="sm" onclick={() => ($showAddDialog = true)}>
        <Plus class="mr-2 h-4 w-4" />
        {m.add_mcp_server()}
      </Button>
    </div>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.available_mcp_servers()}>
        {#if mcpServers.length > 0}
          <MCPServersTable {mcpServers} />
        {:else}
          <div class="text-muted text-center py-8">
            <p>{m.no_mcp_servers_available()}</p>
            <p class="text-sm mt-2">{m.add_mcp_server_to_get_started()}</p>
          </div>
        {/if}
      </Settings.Group>

      <Settings.Group title={m.what_are_mcp_servers()}>
        <div class="text-muted text-sm space-y-2">
          <p>
            MCP (Model Context Protocol) servers provide additional tools and capabilities to AI
            assistants. Servers are connected via Streamable HTTP transport.
          </p>
          <ul class="list-disc list-inside space-y-1 ml-4">
            <li><strong>Authentication</strong> - Supports bearer tokens, API keys, and custom headers</li>
            <li><strong>Tool Discovery</strong> - Tools are automatically discovered when adding a server</li>
          </ul>
        </div>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>

<!-- Add MCP Dialog -->
<MCPServerDialog openController={showAddDialog} onSubmit={handleAddMCP} />
