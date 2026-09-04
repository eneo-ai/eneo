<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Input } from "@eneo/ui";
  import { AlertTriangle, ChevronRight } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { getCapability, isCapabilityPurpose } from "$lib/features/mcp/capabilities";
  import MCPServerPrimaryCell from "./MCPServerPrimaryCell.svelte";
  import MCPServerEnabledSwitch from "./MCPServerEnabledSwitch.svelte";
  import MCPServerActions from "./MCPServerActions.svelte";
  import MCPToolsPanel from "./MCPToolsPanel.svelte";
  import { getEneo } from "$lib/core/Eneo";
  import type { components } from "@eneo/eneo-js";

  type MCPServerSettings = components["schemas"]["MCPServerSettingsPublic"];

  type Props = {
    mcpServers: MCPServerSettings[];
  };

  const { mcpServers }: Props = $props();

  const eneo = getEneo();

  // Track which server has tools expanded (only one at a time)
  let expandedServerId = $state<string | null>(null);

  // Filter state
  let filterValue = $state("");

  const filteredServers = $derived(
    mcpServers.filter((server) => {
      if (!filterValue) return true;
      const searchStr =
        `${server.name} ${server.description || ""} ${server.http_url} ${server.security_classification?.name || ""} ${getCapability(server.purpose)?.label() || ""} ${(server.user_groups ?? []).map((group) => group.name).join(" ")}`.toLowerCase();
      return searchStr.includes(filterValue.toLowerCase());
    })
  );

  // Activating a capability provider can be refused (unreachable, no usable
  // tools); the switch reports that here so it shows above the table.
  let switchError = $state("");

  // The switch column means "activated as provider" for capability rows and
  // "enabled for the tenant" for general servers; label it for what is shown.
  const switchColumnLabel = $derived(
    filteredServers.length > 0 &&
      filteredServers.every((server) => isCapabilityPurpose(server.purpose))
      ? m.active()
      : m.enabled()
  );

  function toggleExpanded(serverId: string) {
    expandedServerId = expandedServerId === serverId ? null : serverId;
  }

  function isExpanded(serverId: string): boolean {
    return expandedServerId === serverId;
  }
</script>

<div class="flex w-full flex-col">
  <!-- Filter bar -->
  <div class="flex items-center justify-between gap-4 pt-2 pb-4">
    <Input.Text
      bind:value={filterValue}
      label={m.filter()}
      class="max-w-md flex-grow"
      placeholder="{m.filter()} {m.mcp_servers()}..."
      hiddenLabel={true}
      inputClass="!px-4 !rounded-lg !bg-secondary/50"
    />
  </div>

  {#if switchError}
    <div
      class="border-negative-default/30 bg-negative-dimmer text-negative-stronger mb-4 flex items-start gap-3 rounded-lg border px-4 py-3 text-sm"
      role="alert"
    >
      <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <p>{switchError}</p>
    </div>
  {/if}

  <!-- Server cards -->
  <div class="w-full">
    <table class="w-full table-fixed border-separate border-spacing-0">
      <thead class="bg-frosted-glass-primary sticky top-0 z-30">
        <tr>
          <th
            class="border-default text-muted h-12 w-10 border-b px-2 text-left text-xs font-medium tracking-wider uppercase"
          ></th>
          <th
            class="border-default text-muted h-12 border-b px-4 text-left text-xs font-medium tracking-wider uppercase"
            >{m.name()}</th
          >
          <th
            class="border-default text-muted h-12 w-24 border-b px-4 text-center text-xs font-medium tracking-wider uppercase"
            >{m.tools()}</th
          >
          <th
            class="border-default text-muted h-12 w-28 border-b px-4 text-center text-xs font-medium tracking-wider uppercase"
            >{switchColumnLabel}</th
          >
          <th
            class="border-default text-muted h-12 w-16 border-b px-4 text-left text-xs font-medium tracking-wider uppercase"
          ></th>
        </tr>
      </thead>
      <tbody>
        {#each filteredServers as server (server.mcp_server_id)}
          {@const hasTools = (server.tools_count ?? 0) > 0}
          {@const expanded = isExpanded(server.mcp_server_id)}
          {@const capability = getCapability(server.purpose)}
          <!-- Server row -->
          <tr
            class="group relative transition-colors duration-150 {expanded
              ? 'bg-secondary/30'
              : 'hover:bg-hover-dimmer'}"
          >
            <td class="border-dimmer border-b px-2 py-3 align-top">
              <Button
                variant="simple"
                padding="icon"
                onclick={() => toggleExpanded(server.mcp_server_id)}
                disabled={!hasTools}
                class={hasTools ? "" : "opacity-30"}
              >
                <ChevronRight
                  class="h-4 w-4 transition-transform duration-200 {expanded ? 'rotate-90' : ''}"
                />
              </Button>
            </td>
            <td class="border-dimmer overflow-hidden border-b px-4 py-3">
              <MCPServerPrimaryCell mcpServer={server} />
              {#if capability && server.forward_identity}
                <p class="text-warning-default mt-1.5 flex items-center gap-1.5 text-xs">
                  <AlertTriangle class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  {m.capability_identity_forwarded_warning()}
                </p>
              {/if}
            </td>
            <td class="border-dimmer border-b px-4 py-3 text-center align-middle">
              <span
                class="bg-secondary text-secondary inline-flex min-w-[2.5rem] items-center justify-center rounded-full px-2.5 py-1 text-xs font-medium tabular-nums {hasTools
                  ? ''
                  : 'opacity-50'}"
              >
                {server.tools_count ?? 0}
              </span>
            </td>
            <td class="border-dimmer border-b px-4 py-3 align-middle">
              <div class="flex justify-center">
                <MCPServerEnabledSwitch
                  mcpServer={server}
                  onAttempt={() => (switchError = "")}
                  onError={(message) => (switchError = message)}
                />
              </div>
            </td>
            <td class="border-dimmer border-b px-4 py-3 align-middle">
              <div
                class="flex items-center justify-end opacity-0 transition-opacity duration-150 group-hover:opacity-100 {expanded
                  ? '!opacity-100'
                  : ''}"
              >
                <MCPServerActions mcpServer={server} />
              </div>
            </td>
          </tr>

          <!-- Expanded tools panel row -->
          {#if expanded}
            <tr>
              <td colspan="5" class="border-default bg-secondary/20 border-b p-0">
                <MCPToolsPanel
                  mcpServerId={server.mcp_server_id}
                  serverName={server.name}
                  tools={server.tools || []}
                  eneoClient={eneo}
                />
              </td>
            </tr>
          {/if}
        {/each}
      </tbody>
    </table>

    {#if filteredServers.length === 0}
      <div
        class="border-dimmer bg-secondary/20 pointer-events-none flex min-h-[200px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed py-12"
      >
        <svg
          class="text-muted/50 h-10 w-10"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          stroke-width="1.5"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
          />
        </svg>
        <div class="text-muted text-center">
          {#if filterValue}
            <p class="font-medium">{m.no_results_found()}</p>
            <p class="text-muted/70 mt-1 text-xs">{m.mcp_try_different_search()}</p>
          {:else}
            <p>{m.no_mcp_servers_available()}</p>
          {/if}
        </div>
      </div>
    {/if}
  </div>
</div>
