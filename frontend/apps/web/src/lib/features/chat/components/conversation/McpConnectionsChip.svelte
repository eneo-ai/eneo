<!--
  Copyright (c) 2026 Sundsvalls Kommun

  Licensed under the MIT License.

  Above the composer: the OAuth servers of this assistant the user has not
  authorized Eneo for, or whose connection has run out. Lazy by default: the
  chat works without connecting, a call to one of these servers simply
  answers with a connect action. The chip lets the user connect ahead of
  time, one server or all of them in a single popup window, and can be
  dismissed for this assistant until another server needs connecting.
-->
<script lang="ts">
  import { browser } from "$app/environment";
  import { Button } from "$lib/components/ui/button/index.js";
  import { toastError } from "$lib/core/errors";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import {
    getMcpOAuthConnect,
    type McpOAuthConnection
  } from "$lib/features/mcp/McpOAuthConnectService.svelte";
  import { ChevronRight, Plug, X } from "@lucide/svelte";
  import { onDestroy } from "svelte";

  let { assistantId }: { assistantId: string } = $props();

  const eneo = getEneo();
  const connect = getMcpOAuthConnect();

  let connections = $state<McpOAuthConnection[]>([]);
  let expanded = $state(false);
  let dismissed = $state(false);

  const dismissKey = $derived(`eneo.mcp-oauth.chip-dismissed.${assistantId}`);

  // Only servers the user can connect themselves: a shared server's state
  // is an administrator's business and stays out of the chip.
  const pending = $derived(
    connections.filter((c) => c.auth_scope === "per_user" && c.status !== "connected")
  );

  // The list is verified by the backend: a connection that ran out while the
  // user was away is reported as such here, not first by a failing call.
  async function load(id: string) {
    const before = new Set(pending.map((c) => c.mcp_server_id));
    const reloading = connections.length > 0;
    try {
      connections = await eneo.mcpOauth.assistantConnections({ assistantId: id });
    } catch {
      connections = [];
    }
    try {
      dismissed = browser ? sessionStorage.getItem(dismissKey) === "1" : false;
    } catch {
      dismissed = false;
    }
    // A dismissal covered the servers pending then; another one is news.
    if (reloading && pending.some((c) => !before.has(c.mcp_server_id))) undismiss();
  }

  $effect(() => {
    void load(assistantId);
  });

  // Sessions run out while the user is away: ask again when they come back.
  $effect(() => {
    if (!browser) return;
    const onVisible = () => {
      if (document.visibilityState === "visible") void load(assistantId);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  });

  function undismiss() {
    dismissed = false;
    try {
      sessionStorage.removeItem(dismissKey);
    } catch {
      /* storage unavailable */
    }
  }

  // The service outlives the chip's props: subscribe once, for the chip's life.
  const unsubscribe = connect?.subscribe((serverId, result) => {
    if (result.success) {
      connections = connections.map((c) => (c.mcp_server_id === serverId ? result.connection : c));
      // A connection that broke reappears: the dismissal was for this round.
      undismiss();
    } else if (result.error.message !== "popup_closed") {
      toastError(result.error);
    }
  });
  // A step that needs authorization for a server listed here as connected
  // means that connection broke after the list was fetched: fetch it again,
  // and bring the chip back for this round.
  const unsubscribeBroken = connect?.onAuthorizationRequired(async (serverId) => {
    const believed = connections.find((c) => c.mcp_server_id === serverId);
    if (!believed || believed.status !== "connected") return;
    await load(assistantId);
    const now = connections.find((c) => c.mcp_server_id === serverId);
    if (now && now.status !== "connected") undismiss();
  });
  onDestroy(() => {
    unsubscribe?.();
    unsubscribeBroken?.();
  });

  function dismiss() {
    dismissed = true;
    try {
      sessionStorage.setItem(dismissKey, "1");
    } catch {
      /* storage unavailable */
    }
  }
</script>

{#if connect && pending.length > 0 && !dismissed}
  <div
    class="bg-accent-dimmer border-accent-default mx-1.5 mt-1.5 rounded-lg border-l-[3px] px-3 py-2 text-sm"
    role="status"
  >
    <div class="flex items-center gap-2">
      <Plug class="text-accent-stronger size-4 shrink-0" aria-hidden="true" />
      {#if pending.length === 1}
        <span class="text-accent-stronger min-w-0 flex-1 truncate font-medium">
          {pending[0].status === "needs_authorization"
            ? m.mcp_oauth_chip_title_expired_one({ server: pending[0].server_name })
            : m.mcp_oauth_chip_title_one({ server: pending[0].server_name })}
        </span>
      {:else}
        <button
          type="button"
          class="text-accent-stronger flex min-w-0 flex-1 items-center gap-1 text-left font-medium"
          onclick={() => (expanded = !expanded)}
          aria-expanded={expanded}
        >
          <span class="truncate">
            {m.mcp_oauth_chip_title_many({ count: pending.length })}
          </span>
          <ChevronRight
            class="size-3.5 shrink-0 transition-transform {expanded ? 'rotate-90' : ''}"
            aria-hidden="true"
          />
        </button>
      {/if}
      {#if pending.length === 1}
        <Button
          size="sm"
          class="h-7 text-xs"
          disabled={connect.isConnecting(pending[0].mcp_server_id)}
          onclick={() => connect.connect(pending[0].mcp_server_id)}
        >
          {m.connect()}
        </Button>
      {:else}
        <Button
          size="sm"
          class="h-7 text-xs"
          disabled={pending.some((c) => connect.isConnecting(c.mcp_server_id))}
          onclick={() => connect.connectAll(pending.map((c) => c.mcp_server_id))}
        >
          {m.mcp_oauth_connect_all()}
        </Button>
      {/if}
      <button
        type="button"
        class="text-secondary hover:bg-background hover:text-default rounded p-0.5 transition-colors"
        aria-label={m.mcp_oauth_chip_dismiss()}
        onclick={dismiss}
      >
        <X class="size-4" aria-hidden="true" />
      </button>
    </div>
    {#if expanded && pending.length > 1}
      <ul class="mt-2 flex flex-col gap-1 pl-6">
        {#each pending as connection (connection.mcp_server_id)}
          <li class="flex items-center justify-between gap-2">
            <span class="text-default truncate">{connection.server_name}</span>
            <Button
              variant="outline"
              size="sm"
              class="h-6 text-xs"
              disabled={connect.isConnecting(connection.mcp_server_id)}
              onclick={() => connect.connect(connection.mcp_server_id)}
            >
              {m.connect()}
            </Button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}
