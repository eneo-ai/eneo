<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { Button } from "@eneo/ui";
  import { invalidate } from "$app/navigation";
  import { KeyRound, Plus, Sparkles, Wrench } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { setSecurityContext } from "$lib/features/security-classifications/SecurityContext.js";
  import { CAPABILITIES } from "$lib/features/mcp/capabilities";
  import MCPServerDialog from "./MCPServerDialog.svelte";
  import MCPServersTable from "./MCPServersTable.svelte";
  import { writable } from "svelte/store";
  import { untrack } from "svelte";

  const { data } = $props();

  setSecurityContext(untrack(() => data.securityClassifications));

  let showAddDialog = writable(false);
  // The dialog opens on this purpose: "general" from the page header, a
  // capability from its card so the admin never has to find "Used for".
  let presetPurpose = $state("general");

  function openAddDialog(purpose = "general") {
    presetPurpose = purpose;
    $showAddDialog = true;
  }

  async function handleAddMCP(mcpData: Record<string, unknown>) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await data.eneo.mcpServers.create(mcpData as any);
    await Promise.all([invalidate("admin:layout"), invalidate("spaces:data")]);
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mcpServers = $derived((data.mcpSettings?.items || []) as any[]);

  const explainerCards = [
    {
      icon: Sparkles,
      title: m.mcp_capability_feature,
      description: m.mcp_capability_feature_description,
      wide: true
    },
    { icon: KeyRound, title: m.mcp_auth_feature, description: m.mcp_auth_description, wide: false },
    {
      icon: Wrench,
      title: m.mcp_tool_discovery_feature,
      description: m.mcp_tool_discovery_description,
      wide: false
    }
  ];
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.mcp_servers()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.mcp_servers()}></Page.Title>
    <div class="flex gap-2">
      <Button variant="primary" size="sm" onclick={() => openAddDialog()}>
        <Plus class="mr-2 h-4 w-4" />
        {m.add_mcp_server()}
      </Button>
    </div>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.available_mcp_servers()}>
        <!-- Which provider is live for each capability, at a glance. -->
        <section
          aria-labelledby="capability-overview-title"
          class="border-dimmer bg-secondary/20 mb-4 rounded-xl border p-4"
        >
          <div class="mb-4 flex max-w-[72ch] flex-col gap-1">
            <h3 id="capability-overview-title" class="text-default text-sm font-semibold">
              {m.capability_overview_title()}
            </h3>
            <p class="text-secondary text-sm leading-5">{m.capability_overview_lead()}</p>
          </div>
          <div class="grid gap-4 sm:grid-cols-2">
            {#each CAPABILITIES as capability (capability.purpose)}
              {@const labelInSentence = capability.label().toLocaleLowerCase()}
              {@const activeProviders = mcpServers.filter(
                (server) => server.purpose === capability.purpose && server.is_enabled
              )}
              {@const active = activeProviders.find((server) => server.audience !== "groups")}
              {@const groupProviders = activeProviders.filter(
                (server) => server.audience === "groups"
              )}
              {@const groupNames = groupProviders.map((server) => server.name).join(", ")}
              <div class="flex items-start gap-3">
                <span
                  class="bg-accent-dimmer flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
                >
                  <capability.icon class="text-accent-default h-4 w-4" aria-hidden="true" />
                </span>
                <div class="min-w-0 flex-1">
                  <p class="text-default text-sm font-medium">{capability.label()}</p>
                  {#if active}
                    <p class="text-secondary flex items-center gap-1.5 text-sm">
                      <span
                        class="bg-positive-dimmer text-positive-stronger inline-flex shrink-0 rounded-md px-1.5 py-0.5 text-xs font-medium"
                      >
                        {m.capability_default_provider()}
                      </span>
                      <span aria-hidden="true">·</span>
                      <span class="truncate">{active.name}</span>
                    </p>
                  {:else}
                    <p class="text-secondary text-sm">
                      {m.capability_no_active_provider({ capability: labelInSentence })}
                    </p>
                    <Button
                      variant="primary-outlined"
                      size="sm"
                      class="mt-2 text-sm"
                      onclick={() => openAddDialog(capability.purpose)}
                    >
                      {m.capability_configure({ capability: labelInSentence })}
                    </Button>
                  {/if}
                  {#if groupProviders.length > 0}
                    <p class="text-secondary truncate text-sm">
                      {m.capability_group_providers({
                        count: groupProviders.length,
                        names: groupNames
                      })}
                    </p>
                  {/if}
                </div>
              </div>
            {/each}
          </div>
        </section>
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
            <Button variant="primary" size="sm" onclick={() => openAddDialog()}>
              <Plus class="mr-2 h-4 w-4" />
              {m.add_mcp_server()}
            </Button>
          </div>
        {/if}
      </Settings.Group>

      <Settings.Group title={m.what_are_mcp_servers()}>
        <div class="border-default bg-secondary/50 rounded-xl border p-6">
          <p class="text-secondary mb-4 max-w-[72ch] text-sm leading-relaxed">
            {m.mcp_servers_description_paragraph()}
          </p>
          <div class="grid gap-3 sm:grid-cols-2">
            {#each explainerCards as card (card.title)}
              <div
                class="border-dimmer bg-primary/50 flex gap-3 rounded-lg border p-4 {card.wide
                  ? 'sm:col-span-2'
                  : ''}"
              >
                <div
                  class="bg-accent-dimmer flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
                >
                  <card.icon class="text-accent-default h-5 w-5" aria-hidden="true" />
                </div>
                <div>
                  <h3 class="text-default text-sm font-medium">{card.title()}</h3>
                  <p class="text-secondary mt-0.5 max-w-[72ch] text-sm leading-5">
                    {card.description()}
                  </p>
                </div>
              </div>
            {/each}
          </div>
        </div>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>

<!-- Add MCP Dialog -->
<MCPServerDialog
  openController={showAddDialog}
  onSubmit={handleAddMCP}
  initialPurpose={presetPurpose}
/>
