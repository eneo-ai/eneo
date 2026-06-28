<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { Button } from "@eneo/ui";
  import { invalidate } from "$app/navigation";
  import { Plus } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { setSecurityContext } from "$lib/features/security-classifications/SecurityContext.js";
  import MCPServerDialog from "./MCPServerDialog.svelte";
  import MCPServersTable from "./MCPServersTable.svelte";
  import { writable } from "svelte/store";
  import { untrack } from "svelte";

  const { data } = $props();

  setSecurityContext(untrack(() => data.securityClassifications));

  let showAddDialog = writable(false);

  async function handleAddMCP(mcpData: Record<string, unknown>) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await data.eneo.mcpServers.create(mcpData as any);
    await Promise.all([invalidate("admin:layout"), invalidate("spaces:data")]);
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mcpServers = $derived((data.mcpSettings?.items || []) as any[]);
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
          <div
            class="border-default bg-secondary/30 flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-8 py-16"
          >
            <div
              class="bg-accent-dimmer mb-4 flex h-16 w-16 items-center justify-center rounded-2xl"
            >
              <Plus class="text-accent-default h-8 w-8" />
            </div>
            <h3 class="text-default mb-2 text-lg font-medium">{m.no_mcp_servers_available()}</h3>
            <p class="text-muted mb-6 max-w-sm text-center text-sm">
              {m.add_mcp_server_to_get_started()}
            </p>
            <Button variant="primary" size="sm" onclick={() => ($showAddDialog = true)}>
              <Plus class="mr-2 h-4 w-4" />
              {m.add_mcp_server()}
            </Button>
          </div>
        {/if}
      </Settings.Group>

      <Settings.Group title={m.what_are_mcp_servers()}>
        <div class="border-default bg-secondary/50 rounded-xl border p-6">
          <p class="text-secondary mb-4 text-sm leading-relaxed">
            {m.mcp_servers_description_paragraph()}
          </p>
          <div class="grid gap-3 sm:grid-cols-2">
            <div class="border-dimmer bg-primary/50 flex gap-3 rounded-lg border p-4">
              <div
                class="bg-amethyst-100 dark:bg-amethyst-900 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
              >
                <svg
                  class="text-amethyst-500 h-5 w-5"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  stroke-width="2"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"
                  />
                </svg>
              </div>
              <div>
                <h4 class="text-default text-sm font-medium">{m.mcp_auth_feature()}</h4>
                <p class="text-muted mt-0.5 text-xs">{m.mcp_auth_description()}</p>
              </div>
            </div>
            <div class="border-dimmer bg-primary/50 flex gap-3 rounded-lg border p-4">
              <div
                class="bg-pine-100 dark:bg-pine-900 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
              >
                <svg
                  class="text-pine-500 h-5 w-5"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  stroke-width="2"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
                  />
                </svg>
              </div>
              <div>
                <h4 class="text-default text-sm font-medium">{m.mcp_tool_discovery_feature()}</h4>
                <p class="text-muted mt-0.5 text-xs">{m.mcp_tool_discovery_description()}</p>
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
