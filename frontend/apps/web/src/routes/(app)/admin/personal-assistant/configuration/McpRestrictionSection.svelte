<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { m } from "$lib/paraglide/messages";
  import { Info, Plug } from "lucide-svelte";
  import PolicySection from "./PolicySection.svelte";

  type McpServer = { id: string; name: string; is_available?: boolean };
  type ReadableSet<T> = {
    has(value: T): boolean;
    size: number;
  };

  type Props = {
    mcpEnabled: boolean;
    allMcpServers: McpServer[];
    mcpSelections: ReadableSet<string>;
    mcpSummary: string;
    badgeVariant: (enabled: boolean, valid: boolean) => "default" | "outline" | "destructive";
    toggleMcp: (serverId: string, selected: boolean) => void;
  };

  let {
    mcpEnabled = $bindable(),
    allMcpServers,
    mcpSelections,
    mcpSummary,
    badgeVariant,
    toggleMcp
  }: Props = $props();
</script>

<PolicySection
  id="mcp"
  title={m.governance_mcp_heading()}
  description={m.governance_mcp_section_desc()}
  summary={mcpSummary}
  summaryVariant={badgeVariant(mcpEnabled, true)}
>
  {#snippet icon()}
    <Plug class="h-5 w-5" />
  {/snippet}

  <div class="flex items-center justify-between gap-3">
    <Label for="mcp-enabled" class="text-sm font-medium">
      {m.governance_mcp_toggle_label()}
    </Label>
    <Switch id="mcp-enabled" bind:checked={mcpEnabled} aria-describedby="mcp-help" />
  </div>

  {#if mcpEnabled}
    {#if allMcpServers.length === 0}
      <p id="mcp-help" class="text-secondary flex items-center gap-2 text-sm">
        <Info class="h-4 w-4 shrink-0" aria-hidden="true" />
        {m.governance_mcp_none_enabled()}
      </p>
    {:else}
      <p id="mcp-help" class="text-secondary text-sm">
        {m.governance_mcp_help_enabled()}
      </p>
      <fieldset class="border-default rounded-lg border p-4">
        <legend class="sr-only">{m.governance_mcp_legend()}</legend>
        <div class="space-y-2.5">
          {#each allMcpServers as server (server.id)}
            <label
              class="hover:bg-hover-default -mx-2 flex items-center gap-3 rounded-md px-2 py-1.5"
            >
              <Checkbox
                checked={mcpSelections.has(server.id)}
                onCheckedChange={(v) => toggleMcp(server.id, !!v)}
              />
              <span class="text-sm">{server.name}</span>
            </label>
          {/each}
        </div>
      </fieldset>
    {/if}
  {:else}
    <p id="mcp-help" class="text-secondary text-sm">
      {m.governance_mcp_help_disabled()}
    </p>
  {/if}
</PolicySection>
