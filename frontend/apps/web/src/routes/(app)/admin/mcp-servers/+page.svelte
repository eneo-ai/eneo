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
          <!-- Empty state with visual appeal -->
          <div class="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-default bg-secondary/30 px-8 py-16">
            <div class="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-accent-dimmer">
              <Plus class="h-8 w-8 text-accent-default" />
            </div>
            <h3 class="mb-2 text-lg font-medium text-default">{m.no_mcp_servers_available()}</h3>
            <p class="mb-6 max-w-sm text-center text-sm text-muted">{m.add_mcp_server_to_get_started()}</p>
            <Button variant="primary" size="sm" onclick={() => ($showAddDialog = true)}>
              <Plus class="mr-2 h-4 w-4" />
              {m.add_mcp_server()}
            </Button>
          </div>
        {/if}
      </Settings.Group>

      <Settings.Group title={m.what_are_mcp_servers()}>
        <div class="rounded-xl border border-default bg-secondary/50 p-6">
          <p class="mb-4 text-sm leading-relaxed text-secondary">
            {m.mcp_servers_description_paragraph()}
          </p>
          <div class="grid gap-3 sm:grid-cols-2">
            <div class="flex gap-3 rounded-lg border border-dimmer bg-primary/50 p-4">
              <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-amethyst-100 dark:bg-amethyst-900">
                <svg class="h-5 w-5 text-amethyst-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                </svg>
              </div>
              <div>
                <h4 class="text-sm font-medium text-default">{m.mcp_auth_feature()}</h4>
                <p class="mt-0.5 text-xs text-muted">{m.mcp_auth_description()}</p>
              </div>
            </div>
            <div class="flex gap-3 rounded-lg border border-dimmer bg-primary/50 p-4">
              <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-pine-100 dark:bg-pine-900">
                <svg class="h-5 w-5 text-pine-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
              </div>
              <div>
                <h4 class="text-sm font-medium text-default">{m.mcp_tool_discovery_feature()}</h4>
                <p class="mt-0.5 text-xs text-muted">{m.mcp_tool_discovery_description()}</p>
              </div>
            </div>
          </div>
        </div>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>

<!-- Add MCP Dialog -->
<MCPServerDialog openController={showAddDialog} onSubmit={handleAddMCP} />
