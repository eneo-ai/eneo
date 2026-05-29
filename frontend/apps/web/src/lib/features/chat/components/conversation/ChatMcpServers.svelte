<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.

    MCP server controls for the chat input toolbar: pick which of the partner's
    MCP servers are active for this conversation and whether tool calls run
    automatically or require per-call approval. State is owned by the parent
    (ConversationInput) so it can be sent with each ask request — this component
    only renders and mutates it.
-->
<script lang="ts">
  import { buttonVariants } from "$lib/components/ui/button/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { m } from "$lib/paraglide/messages";
  import { Plug, ShieldCheck } from "lucide-svelte";
  import type { SvelteSet } from "svelte/reactivity";

  type McpServer = {
    id: string;
    name: string;
    description?: string | null;
    icon_url?: string | null;
  };

  type Props = {
    servers: McpServer[];
    /** Server ids the user has switched off for this conversation (mutated in place). */
    disabledServerIds: SvelteSet<string>;
    /** When true, tool calls run without per-call approval. */
    autoAcceptTools: boolean;
  };

  let { servers, disabledServerIds, autoAcceptTools = $bindable() }: Props = $props();

  const total = $derived(servers.length);
  const disabledCount = $derived(
    servers.filter((server) => disabledServerIds.has(server.id)).length
  );
  const activeCount = $derived(total - disabledCount);

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
        {#if total > 1}
          <span class="flex items-center gap-0.5">
            <button
              type="button"
              class="hover:text-foreground rounded px-1 py-0.5 font-medium transition-colors disabled:pointer-events-none disabled:opacity-40"
              disabled={activeCount === total}
              onclick={() => setAll(true)}>{m.mcp_all_on()}</button
            >
            <span aria-hidden="true" class="text-border">·</span>
            <button
              type="button"
              class="hover:text-foreground rounded px-1 py-0.5 font-medium transition-colors disabled:pointer-events-none disabled:opacity-40"
              disabled={activeCount === 0}
              onclick={() => setAll(false)}>{m.mcp_all_off()}</button
            >
          </span>
        {/if}
      </div>
    </div>

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
  </Popover.Content>
</Popover.Root>
