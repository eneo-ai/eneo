<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.

    MCP server controls for the chat input toolbar: pick which of the partner's
    MCP servers are active for this conversation and whether tool calls run
    automatically or require per-call approval. State is owned by the parent
    (ConversationInput) so it can be sent with each ask request — this component
    only renders and mutates it. Eneo's own internal (loopback) servers are
    listed too, but they are always active and cannot be toggled. The tenant's
    web-search provider is a real MCP server under the hood but is presented as
    a togglable capability row, not a server.
-->
<script lang="ts">
  import { buttonVariants } from "$lib/components/ui/button/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { m } from "$lib/paraglide/messages";
  import { serverDisplayName } from "$lib/features/chat/internalToolLabels";
  import { BookOpen, Globe, Paperclip, Plug, ShieldCheck } from "lucide-svelte";
  import type { SvelteSet } from "svelte/reactivity";

  type McpServer = {
    id: string;
    name: string;
    description?: string | null;
    icon_url?: string | null;
  };

  type InternalMcpServer = {
    /** Internal server name as the backend attaches it (e.g. "knowledge"). */
    name: string;
  };

  type Props = {
    /** General-purpose external MCP servers. */
    servers: McpServer[];
    /** The tenant's web-search provider(s): rendered as a capability, not a server. */
    webSearchServers?: McpServer[];
    /** Eneo's built-in loopback servers active for this partner (not togglable). */
    internalServers?: InternalMcpServer[];
    /** Server ids the user has switched off for this conversation (mutated in place). */
    disabledServerIds: SvelteSet<string>;
    /** When true, tool calls run without per-call approval. */
    autoAcceptTools: boolean;
  };

  let {
    servers,
    webSearchServers = [],
    internalServers = [],
    disabledServerIds,
    autoAcceptTools = $bindable()
  }: Props = $props();

  const INTERNAL_SERVER_ICONS: Record<string, typeof Plug> = {
    knowledge: BookOpen,
    files: Paperclip
  };

  // Built-ins are always active; web-search and external servers toggle via
  // disabledServerIds.
  const total = $derived(servers.length + webSearchServers.length + internalServers.length);
  const disabledCount = $derived(
    [...servers, ...webSearchServers].filter((server) => disabledServerIds.has(server.id)).length
  );
  const activeCount = $derived(total - disabledCount);
  // All-on/all-off only sweeps the general external servers, so its disabled
  // states must not count the web-search toggle.
  const generalDisabledCount = $derived(
    servers.filter((server) => disabledServerIds.has(server.id)).length
  );

  function setServer(id: string, on: boolean) {
    if (on) disabledServerIds.delete(id);
    else disabledServerIds.add(id);
  }

  function setAll(on: boolean) {
    for (const server of servers) setServer(server.id, on);
  }
</script>

<Popover.Root>
  <Popover.Trigger
    class={buttonVariants({ variant: activeCount > 0 ? "secondary" : "ghost", size: "sm" }) +
      " h-9 gap-1.5 rounded-lg"}
    title={m.mcp_servers()}
    aria-label={m.mcp_servers_status_aria({ active: activeCount, total })}
  >
    <Plug class="size-4" aria-hidden="true" />
    <span class="hidden sm:inline">{m.mcp_servers()}</span>
    <Badge
      variant={activeCount > 0 ? "default" : "outline"}
      class="ml-0.5 px-1.5 tabular-nums"
      aria-hidden="true">{activeCount}</Badge
    >
  </Popover.Trigger>

  <Popover.Content side="top" align="start" class="w-80 gap-0 p-0">
    <div class="border-b px-3 py-2.5">
      <Popover.Title class="text-sm">{m.mcp_servers()}</Popover.Title>
      <div class="text-muted-foreground mt-0.5 flex items-center justify-between gap-2 text-xs">
        <span>{m.mcp_servers_active_count({ active: activeCount, total })}</span>
        {#if servers.length > 1}
          <span class="flex items-center gap-0.5">
            <button
              type="button"
              class="hover:text-foreground rounded px-1 py-0.5 font-medium transition-colors disabled:pointer-events-none disabled:opacity-40"
              disabled={generalDisabledCount === 0}
              onclick={() => setAll(true)}>{m.mcp_all_on()}</button
            >
            <span aria-hidden="true" class="text-border">·</span>
            <button
              type="button"
              class="hover:text-foreground rounded px-1 py-0.5 font-medium transition-colors disabled:pointer-events-none disabled:opacity-40"
              disabled={generalDisabledCount === servers.length}
              onclick={() => setAll(false)}>{m.mcp_all_off()}</button
            >
          </span>
        {/if}
      </div>
    </div>

    {#if internalServers.length > 0}
      <div
        class="flex items-center gap-2 border-b px-3 py-2"
        role="group"
        aria-label={m.mcp_internal_server_hint()}
      >
        <div class="flex min-w-0 flex-1 flex-wrap items-center gap-1">
          {#each internalServers as server (server.name)}
            {@const Icon = INTERNAL_SERVER_ICONS[server.name] ?? Plug}
            <span
              class="bg-muted text-foreground flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
              title={m.mcp_internal_server_hint()}
            >
              <Icon class="text-muted-foreground size-3.5" aria-hidden="true" />
              {serverDisplayName(server.name)}
            </span>
          {/each}
        </div>
        <span class="text-muted-foreground shrink-0 text-xs"
          >{m.mcp_internal_tools_always_active()}</span
        >
      </div>
    {/if}

    {#if webSearchServers.length > 0}
      <div class="border-b p-1" role="group" aria-label={m.web_search()}>
        {#each webSearchServers as server (server.id)}
          {@const on = !disabledServerIds.has(server.id)}
          <!-- Capability framing: Globe + "Web search", deliberately without
               server avatar styling or provider identity. Which provider
               serves the search is an admin concern. -->
          <label
            class="hover:bg-muted flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-2 transition-colors"
          >
            <Globe
              class="text-muted-foreground size-5 shrink-0 {on ? '' : 'opacity-50'}"
              aria-hidden="true"
            />
            <span class="min-w-0 flex-1 {on ? '' : 'opacity-60'}">
              <span class="text-foreground block truncate text-sm font-medium"
                >{m.web_search()}</span
              >
            </span>
            <Switch
              checked={on}
              onCheckedChange={(value) => setServer(server.id, value)}
              aria-label={m.web_search()}
            />
          </label>
        {/each}
      </div>
    {/if}

    {#if servers.length > 0}
      <div
        class="flex max-h-64 flex-col overflow-y-auto p-1"
        role="group"
        aria-label={m.mcp_servers()}
      >
        {#each servers as server (server.id)}
          {@const on = !disabledServerIds.has(server.id)}
          {@const descId = server.description ? `mcp-desc-${server.id}` : undefined}
          <label
            class="hover:bg-muted flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-2 transition-colors"
          >
            <span
              class="bg-muted text-muted-foreground flex size-7 shrink-0 items-center justify-center overflow-hidden rounded-md text-xs font-semibold {on
                ? ''
                : 'opacity-50'}"
              aria-hidden="true"
            >
              {#if server.icon_url}
                <img src={server.icon_url} alt="" class="size-full object-cover" />
              {:else}
                {server.name.charAt(0).toUpperCase()}
              {/if}
            </span>
            <span class="min-w-0 flex-1 {on ? '' : 'opacity-60'}">
              <span class="text-foreground block truncate text-sm font-medium">{server.name}</span>
              {#if server.description}
                <span
                  id={descId}
                  class="text-muted-foreground block truncate text-xs"
                  title={server.description}>{server.description}</span
                >
              {/if}
            </span>
            <Switch
              checked={on}
              onCheckedChange={(value) => setServer(server.id, value)}
              aria-label={server.name}
              aria-describedby={descId}
            />
          </label>
        {/each}
      </div>
    {/if}

    {#if servers.length > 0 || webSearchServers.length > 0}
      <Separator />

      <div class="p-1">
        <label
          class="hover:bg-muted flex cursor-pointer items-start gap-2.5 rounded-md px-2 py-2 transition-colors"
        >
          <ShieldCheck class="text-muted-foreground mt-0.5 size-5 shrink-0" aria-hidden="true" />
          <span class="min-w-0 flex-1">
            <span class="text-foreground block text-sm font-medium"
              >{m.mcp_run_tools_automatically()}</span
            >
            <span id="mcp-auto-accept-desc" class="text-muted-foreground block text-xs">
              {autoAcceptTools ? m.auto_accept_tools_on() : m.auto_accept_tools_off()}
            </span>
          </span>
          <Switch
            bind:checked={autoAcceptTools}
            aria-label={m.mcp_run_tools_automatically()}
            aria-describedby="mcp-auto-accept-desc"
          />
        </label>
      </div>
    {/if}
  </Popover.Content>
</Popover.Root>
