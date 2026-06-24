<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Label } from "$lib/components/ui/label/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { m } from "$lib/paraglide/messages";
  import { AlertCircle, ChevronRight, Info, Plug } from "lucide-svelte";
  import { SvelteSet } from "svelte/reactivity";
  import PolicySection from "./PolicySection.svelte";

  type McpTool = { id: string; name: string; description?: string | null };
  type McpServer = {
    id: string;
    name: string;
    description?: string | null;
    tools: McpTool[];
  };
  type ReadableMap<K, V> = {
    has(key: K): boolean;
    get(key: K): V | undefined;
    size: number;
  };
  type ReadableSet<T> = {
    has(value: T): boolean;
    size: number;
  };

  type Props = {
    mcpEnabled: boolean;
    allMcpServers: McpServer[];
    mcpSelections: ReadableMap<string, { isDefaultEnabled: boolean }>;
    disabledMcpToolIds: ReadableSet<string>;
    mcpSummary: string;
    mcpValid: boolean;
    badgeVariant: (enabled: boolean, valid: boolean) => "default" | "outline" | "destructive";
    toggleMcp: (serverId: string, selected: boolean) => void;
    toggleMcpDefault: (serverId: string, defaultEnabled: boolean) => void;
    toggleMcpTool: (toolId: string, enabled: boolean) => void;
  };

  let {
    mcpEnabled = $bindable(),
    allMcpServers,
    mcpSelections,
    disabledMcpToolIds,
    mcpSummary,
    mcpValid,
    badgeVariant,
    toggleMcp,
    toggleMcpDefault,
    toggleMcpTool
  }: Props = $props();

  const expandedServers = new SvelteSet<string>();

  function toggleExpanded(serverId: string) {
    if (expandedServers.has(serverId)) expandedServers.delete(serverId);
    else expandedServers.add(serverId);
  }

  function enabledToolCount(server: McpServer): number {
    return server.tools.filter((tool) => !disabledMcpToolIds.has(tool.id)).length;
  }
</script>

<PolicySection
  id="mcp"
  title={m.governance_mcp_heading()}
  description={m.governance_mcp_section_desc()}
  summary={mcpSummary}
  summaryVariant={badgeVariant(mcpEnabled, mcpValid)}
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
      <fieldset class="border-default divide-default divide-y overflow-hidden rounded-lg border">
        <legend class="sr-only">{m.governance_mcp_legend()}</legend>
        {#each allMcpServers as server (server.id)}
          {@const isSelected = mcpSelections.has(server.id)}
          {@const isDefaultEnabled = mcpSelections.get(server.id)?.isDefaultEnabled ?? true}
          {@const hasTools = server.tools.length > 0}
          {@const isExpanded = isSelected && expandedServers.has(server.id)}
          {@const enabledCount = enabledToolCount(server)}
          <div class={isSelected ? "bg-secondary/30" : ""}>
            <div class="flex items-center gap-3 py-2.5 pr-4 pl-1">
              <button
                type="button"
                class="text-tertiary hover:text-primary disabled:hover:text-tertiary flex h-8 w-8 shrink-0 items-center justify-center rounded-md disabled:opacity-20"
                disabled={!isSelected || !hasTools}
                onclick={() => toggleExpanded(server.id)}
                aria-label={isExpanded
                  ? m.governance_mcp_hide_tools()
                  : m.governance_mcp_show_tools()}
                aria-expanded={isExpanded}
              >
                <ChevronRight
                  class="h-4 w-4 transition-transform duration-200 {isExpanded ? 'rotate-90' : ''}"
                />
              </button>
              <Switch
                checked={isSelected}
                onCheckedChange={(v) => toggleMcp(server.id, v)}
                aria-label={m.governance_mcp_allow_aria({ name: server.name })}
              />
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span class="text-sm font-medium {isSelected ? '' : 'text-secondary'}">
                    {server.name}
                  </span>
                  {#if isSelected && hasTools}
                    <span
                      class="bg-secondary text-secondary inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium tabular-nums"
                    >
                      {enabledCount}<span class="text-tertiary">/</span>{server.tools.length}
                    </span>
                  {/if}
                </div>
                {#if server.description}
                  <p class="text-tertiary line-clamp-1 text-xs">{server.description}</p>
                {/if}
              </div>
              {#if isSelected}
                <label class="flex shrink-0 items-center gap-2">
                  <span class="text-secondary text-xs">{m.governance_mcp_default_label()}</span>
                  <Switch
                    checked={isDefaultEnabled}
                    onCheckedChange={(v) => toggleMcpDefault(server.id, v)}
                    aria-label={m.governance_mcp_default_aria({ name: server.name })}
                  />
                </label>
              {/if}
            </div>

            {#if isExpanded}
              <div
                class="border-default bg-secondary/40 mr-3 mb-2.5 ml-9 rounded-lg border"
                role="group"
                aria-label={m.mcp_tools_for_server_aria({ name: server.name })}
              >
                <div
                  class="border-default flex items-center justify-between gap-3 border-b px-3 py-1.5"
                >
                  <span class="text-tertiary text-[11px] font-medium tracking-wider uppercase">
                    {m.tools()} ({server.tools.length})
                  </span>
                  <div class="flex items-center gap-1">
                    <button
                      type="button"
                      class="text-secondary hover:text-primary hover:bg-hover-default rounded px-2 py-1 text-[10px] font-medium disabled:pointer-events-none disabled:opacity-40"
                      disabled={enabledCount === server.tools.length}
                      onclick={() => {
                        for (const tool of server.tools) toggleMcpTool(tool.id, true);
                      }}
                    >
                      {m.mcp_all_on()}
                    </button>
                    <span class="text-tertiary" aria-hidden="true">|</span>
                    <button
                      type="button"
                      class="text-secondary hover:text-primary hover:bg-hover-default rounded px-2 py-1 text-[10px] font-medium disabled:pointer-events-none disabled:opacity-40"
                      disabled={enabledCount === 0}
                      onclick={() => {
                        for (const tool of server.tools) toggleMcpTool(tool.id, false);
                      }}
                    >
                      {m.mcp_all_off()}
                    </button>
                  </div>
                </div>
                <div class="divide-default max-h-[240px] divide-y overflow-y-auto">
                  {#each server.tools as tool (tool.id)}
                    {@const toolEnabled = !disabledMcpToolIds.has(tool.id)}
                    <label
                      class="hover:bg-hover-default flex items-center gap-3 px-3 py-2 {toolEnabled
                        ? ''
                        : 'opacity-50'}"
                    >
                      <span class="min-w-0 flex-1">
                        <span class="block truncate font-mono text-xs font-medium">{tool.name}</span
                        >
                        {#if tool.description}
                          <span
                            class="text-tertiary block truncate text-xs"
                            title={tool.description}
                          >
                            {tool.description}
                          </span>
                        {/if}
                      </span>
                      <Switch
                        checked={toolEnabled}
                        onCheckedChange={(v) => toggleMcpTool(tool.id, v)}
                        aria-label={tool.name}
                      />
                    </label>
                  {/each}
                </div>
                <p class="text-tertiary border-default border-t px-3 py-1.5 text-xs">
                  {m.governance_mcp_tools_disabled_note()}
                </p>
              </div>
            {/if}
          </div>
        {/each}
      </fieldset>
      {#if !mcpValid}
        <p class="text-destructive flex items-center gap-2 text-sm" role="alert">
          <AlertCircle class="h-4 w-4 shrink-0" aria-hidden="true" />
          {m.governance_mcp_error_none()}
        </p>
      {/if}
    {/if}
  {:else}
    <p id="mcp-help" class="text-secondary text-sm">
      {m.governance_mcp_help_disabled()}
    </p>
  {/if}
</PolicySection>
