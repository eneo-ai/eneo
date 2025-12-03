<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { Button, Input, Tooltip } from "@intric/ui";
  import { invalidate } from "$app/navigation";
  import { Plus } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import AddMCPDialog from "./AddMCPDialog.svelte";
  import ToolsList from "./ToolsList.svelte";
  import { writable } from "svelte/store";

  const { data } = $props();

  let showAddDialog = writable(false);

  async function toggleMCPEnabled(mcpServer: any) {
    const isCurrentlyEnabled = mcpServer.is_org_enabled;

    try {
      if (isCurrentlyEnabled) {
        // Disable MCP
        await data.intric.mcpServers.disable({ mcp_server_id: mcpServer.mcp_server_id });
      } else {
        // Enable MCP
        await data.intric.mcpServers.enable({
          mcp_server_id: mcpServer.mcp_server_id,
          env_vars: {}
        });
      }

      // Refresh both admin layout and space data
      await Promise.all([
        invalidate('admin:layout'),
        invalidate('spaces:data')
      ]);
    } catch (error) {
      console.error('Failed to toggle MCP:', error);
    }
  }

  async function handleAddMCP(mcpData: any) {
    // Create MCP server - errors are thrown and handled by the dialog
    await data.intric.mcpServers.create(mcpData);
    // Refresh both admin layout and space data
    await Promise.all([
      invalidate('admin:layout'),
      invalidate('spaces:data')
    ]);
  }

  function getAuthTypeColor(type: string) {
    switch (type) {
      case 'none': return 'bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200';
      case 'bearer': return 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200';
      case 'api_key': return 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200';
      case 'custom_headers': return 'bg-pink-100 text-pink-800 dark:bg-pink-900 dark:text-pink-200';
      default: return 'bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200';
    }
  }

  function formatAuthType(type: string) {
    if (type === 'none') return 'None';
    if (type === 'bearer') return 'Bearer Token';
    if (type === 'api_key') return 'API Key';
    if (type === 'custom_headers') return 'Custom Headers';
    return type;
  }
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
        <div class="space-y-4">
          {#if data.mcpSettings && data.mcpSettings.items && data.mcpSettings.items.length > 0}
            {#each data.mcpSettings.items as mcpServer}
              <div class="border-default rounded-lg border p-4">
                <div class="flex items-center justify-between">
                  <div class="flex-1">
                    <div class="flex items-center gap-3">
                      <h3 class="text-default text-lg font-semibold">{mcpServer.name}</h3>
                      <span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium {getAuthTypeColor(mcpServer.http_auth_type)}">
                        {formatAuthType(mcpServer.http_auth_type)}
                      </span>
                      {#if mcpServer.is_org_enabled}
                        <span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">
                          {m.enabled()}
                        </span>
                      {/if}
                    </div>
                    {#if mcpServer.description}
                      <p class="text-muted text-sm mt-1">{mcpServer.description}</p>
                    {/if}
                    <div class="mt-2 flex flex-wrap gap-2">
                      <span class="text-xs text-muted">
                        <strong>{m.url()}:</strong> {mcpServer.http_url}
                      </span>
                    </div>
                    {#if mcpServer.tags && mcpServer.tags.length > 0}
                      <div class="mt-2 flex flex-wrap gap-1">
                        {#each mcpServer.tags as tag}
                          <span class="inline-flex items-center rounded-full border border-gray-300 dark:border-gray-600 px-2.5 py-0.5 text-xs font-medium text-gray-700 dark:text-gray-300">{tag}</span>
                        {/each}
                      </div>
                    {/if}
                  </div>
                  <div class="flex items-center gap-4">
                    {#if mcpServer.documentation_url}
                      <a
                        href={mcpServer.documentation_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        class="text-sm text-blue-600 hover:underline dark:text-blue-400"
                      >
                        {m.docs()}
                      </a>
                    {/if}
                    <Tooltip text={mcpServer.is_org_enabled ? m.click_to_disable() : m.click_to_enable()}>
                      <Input.Switch
                        sideEffect={() => toggleMCPEnabled(mcpServer)}
                        value={mcpServer.is_org_enabled}
                      ></Input.Switch>
                    </Tooltip>
                  </div>
                </div>

                <!-- Tools list for this server -->
                <ToolsList mcpServerId={mcpServer.mcp_server_id} intricClient={data.intric} />
              </div>
            {/each}
          {:else}
            <div class="text-muted text-center py-8">
              <p>{m.no_mcp_servers_available()}</p>
              <p class="text-sm mt-2">{m.add_mcp_server_to_get_started()}</p>
            </div>
          {/if}
        </div>
      </Settings.Group>

      <Settings.Group title={m.what_are_mcp_servers()}>
        <div class="text-muted text-sm space-y-2">
          <p>
            MCP (Model Context Protocol) servers provide additional tools and capabilities to AI assistants.
            Servers are connected via Streamable HTTP transport.
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

<AddMCPDialog openController={showAddDialog} onSubmit={handleAddMCP} />
