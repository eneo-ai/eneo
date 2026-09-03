<!--
    Provider management for one capability: the active provider card, the
    saved providers list (activate / deactivate / tools) and the add dialog.
    Which capability is rendered comes entirely from the descriptor.
-->

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { Button } from "@eneo/ui";
  import { invalidate } from "$app/navigation";
  import { AlertTriangle, ChevronRight, ExternalLink, Plus, ShieldCheck } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { getEneo } from "$lib/core/Eneo";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  import type { CapabilityDescriptor } from "$lib/features/mcp/capabilities";
  import MCPServerDialog from "../mcp-servers/MCPServerDialog.svelte";
  import MCPServerPrimaryCell from "../mcp-servers/MCPServerPrimaryCell.svelte";
  import MCPServerActions from "../mcp-servers/MCPServerActions.svelte";
  import MCPToolsPanel from "../mcp-servers/MCPToolsPanel.svelte";
  import { writable } from "svelte/store";
  import type { components } from "@eneo/eneo-js";

  type MCPServerSettings = components["schemas"]["MCPServerSettingsPublic"];

  type Props = {
    capability: CapabilityDescriptor;
    /** Saved providers for this capability (any activation state). */
    providers: MCPServerSettings[];
  };

  const { capability, providers: savedProviders }: Props = $props();

  const eneo = getEneo();

  const showAddDialog = writable(false);

  const providers = $derived.by(() => {
    // Active provider first, then alphabetically.
    return [...savedProviders].sort((a, b) => {
      if (a.is_enabled !== b.is_enabled) return a.is_enabled ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
  });
  const activeProvider = $derived(providers.find((server) => server.is_enabled));

  // Track which provider has its tools panel expanded (one at a time).
  let expandedServerId = $state<string | null>(null);
  let switchError = $state("");
  let switchingId = $state<string | null>(null);

  async function handleAddProvider(mcpData: Record<string, unknown>) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await eneo.mcpServers.create(mcpData as any);
    await invalidate("admin:capabilities");
  }

  async function activateProvider(server: MCPServerSettings) {
    switchError = "";
    switchingId = server.mcp_server_id;
    try {
      await eneo.mcpServers.activate({ id: server.mcp_server_id });
      await invalidate("admin:capabilities");
    } catch (error) {
      switchError = getErrorMessage(error) || m.capability_activation_failed();
    } finally {
      switchingId = null;
    }
  }

  async function deactivateProvider(server: MCPServerSettings) {
    switchError = "";
    switchingId = server.mcp_server_id;
    try {
      await eneo.mcpServers.deactivate({ id: server.mcp_server_id });
      await invalidate("admin:capabilities");
    } catch (error) {
      switchError = getErrorMessage(error) || m.capability_deactivation_failed();
    } finally {
      switchingId = null;
    }
  }

  function toggleExpanded(serverId: string) {
    expandedServerId = expandedServerId === serverId ? null : serverId;
  }
</script>

<Settings.Page>
  <div class="flex justify-end pb-2">
    <Button variant="primary" size="sm" onclick={() => ($showAddDialog = true)}>
      <Plus class="mr-2 h-4 w-4" />
      {m.capability_add_provider()}
    </Button>
  </div>
  <Settings.Group title={m.capability_active_provider()}>
    {#if switchError}
      <div
        class="border-negative-default/30 bg-negative-dimmer text-negative-stronger mb-4 flex items-start gap-3 rounded-lg border px-4 py-3 text-sm"
        role="alert"
      >
        <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <p>{switchError}</p>
      </div>
    {/if}

    {#if activeProvider}
      <div class="border-positive-default/40 bg-positive-dimmer/20 rounded-xl border p-5">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div class="flex min-w-0 items-start gap-4">
            <span
              class="bg-positive-dimmer flex h-12 w-12 shrink-0 items-center justify-center rounded-xl"
            >
              <capability.icon class="text-positive-default h-6 w-6" aria-hidden="true" />
            </span>
            <div class="min-w-0">
              <MCPServerPrimaryCell mcpServer={activeProvider} />
              <div class="text-muted mt-2 flex flex-wrap items-center gap-3 text-xs">
                <span
                  class="bg-positive-dimmer text-positive-stronger inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-medium"
                >
                  {m.active()}
                </span>
                <span>{activeProvider.tools_count ?? 0} {m.tools()}</span>
                {#if activeProvider.security_classification}
                  <span class="inline-flex items-center gap-1">
                    <ShieldCheck class="h-3.5 w-3.5" aria-hidden="true" />
                    {activeProvider.security_classification.name}
                  </span>
                {/if}
              </div>
              {#if activeProvider.forward_identity}
                <p class="text-warning-default mt-2 flex items-center gap-1.5 text-xs">
                  <AlertTriangle class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  {m.capability_identity_forwarded_warning()}
                </p>
              {/if}
            </div>
          </div>
          {#if activeProvider.documentation_url}
            <!-- eslint-disable svelte/no-navigation-without-resolve -- external provider documentation URL -->
            <a
              href={activeProvider.documentation_url}
              target="_blank"
              rel="noreferrer"
              class="text-accent-default inline-flex items-center gap-1.5 text-sm underline"
            >
              <ExternalLink class="h-3.5 w-3.5" aria-hidden="true" />
              {m.documentation()}
            </a>
            <!-- eslint-enable svelte/no-navigation-without-resolve -->
          {/if}
        </div>
      </div>
    {:else}
      <div
        class="border-default bg-secondary/30 flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-8 py-12"
      >
        <div class="bg-accent-dimmer mb-4 flex h-14 w-14 items-center justify-center rounded-2xl">
          <capability.icon class="text-accent-default h-7 w-7" aria-hidden="true" />
        </div>
        <h3 class="text-default mb-2 text-lg font-medium">
          {m.capability_no_active_provider()}
        </h3>
        <p class="text-muted max-w-md text-center text-sm">
          {capability.noActiveProviderDescription()}
        </p>
      </div>
    {/if}
  </Settings.Group>

  <Settings.Group title={m.capability_saved_providers()}>
    <p class="text-muted pb-1 text-sm">{capability.providerManagedNote()}</p>
    <p class="text-muted pb-4 text-sm">{m.capability_atomic_switch_note()}</p>

    {#if providers.length > 0}
      <div class="flex flex-col gap-3">
        {#each providers as server (server.mcp_server_id)}
          {@const hasTools = (server.tools_count ?? 0) > 0}
          {@const expanded = expandedServerId === server.mcp_server_id}
          {@const switching = switchingId === server.mcp_server_id}
          <div class="border-default rounded-xl border {expanded ? 'bg-secondary/20' : ''}">
            <div class="flex items-start gap-3 p-4">
              <Button
                variant="simple"
                padding="icon"
                onclick={() => toggleExpanded(server.mcp_server_id)}
                disabled={!hasTools}
                class={hasTools ? "" : "opacity-30"}
                aria-expanded={expanded}
                aria-label="{m.tools()}: {server.name}"
              >
                <ChevronRight
                  class="h-4 w-4 transition-transform duration-200 {expanded ? 'rotate-90' : ''}"
                />
              </Button>

              <div class="min-w-0 flex-1">
                <MCPServerPrimaryCell mcpServer={server} />
                {#if server.forward_identity}
                  <p class="text-warning-default mt-1.5 flex items-center gap-1.5 text-xs">
                    <AlertTriangle class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                    {m.capability_identity_forwarded_warning()}
                  </p>
                {/if}
                {#if server.documentation_url}
                  <!-- eslint-disable svelte/no-navigation-without-resolve -- external provider documentation URL -->
                  <a
                    href={server.documentation_url}
                    target="_blank"
                    rel="noreferrer"
                    class="text-accent-default mt-1.5 inline-flex items-center gap-1.5 text-xs underline"
                  >
                    <ExternalLink class="h-3 w-3" aria-hidden="true" />
                    {m.documentation()}
                  </a>
                  <!-- eslint-enable svelte/no-navigation-without-resolve -->
                {/if}
              </div>

              <div class="flex shrink-0 items-center gap-2">
                <span
                  class="bg-secondary text-secondary inline-flex min-w-[2.5rem] items-center justify-center rounded-full px-2.5 py-1 text-xs font-medium tabular-nums {hasTools
                    ? ''
                    : 'opacity-50'}"
                  aria-label="{m.tools()}: {server.tools_count ?? 0}"
                >
                  {server.tools_count ?? 0}
                </span>
                {#if server.is_enabled}
                  <Button
                    variant="outlined"
                    size="sm"
                    onclick={() => deactivateProvider(server)}
                    disabled={switching}
                  >
                    {switching ? m.loading() : m.deactivate()}
                  </Button>
                {:else}
                  <Button
                    variant="primary"
                    size="sm"
                    onclick={() => activateProvider(server)}
                    disabled={switching || switchingId !== null}
                  >
                    {switching ? m.loading() : m.activate()}
                  </Button>
                {/if}
                <MCPServerActions mcpServer={server} purpose={capability.purpose} />
              </div>
            </div>

            {#if expanded}
              <div class="border-dimmer border-t">
                <MCPToolsPanel
                  mcpServerId={server.mcp_server_id}
                  serverName={server.name}
                  tools={server.tools || []}
                  eneoClient={eneo}
                />
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {:else}
      <div
        class="border-dimmer bg-secondary/20 flex min-h-[160px] flex-col items-center justify-center gap-3 rounded-lg border border-dashed py-10"
      >
        <p class="text-muted text-sm">{capability.noProviders()}</p>
        <Button variant="primary" size="sm" onclick={() => ($showAddDialog = true)}>
          <Plus class="mr-2 h-4 w-4" />
          {m.capability_add_provider()}
        </Button>
      </div>
    {/if}
  </Settings.Group>
</Settings.Page>

<MCPServerDialog
  openController={showAddDialog}
  purpose={capability.purpose}
  onSubmit={handleAddProvider}
/>
