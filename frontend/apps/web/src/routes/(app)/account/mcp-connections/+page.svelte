<!--
  Copyright (c) 2026 Sundsvalls Kommun

  Licensed under the MIT License.

  "Mina kopplingar": every OAuth MCP server of the tenant and where the user
  stands with it. A per-user server is connected and disconnected here; a
  shared one only shows whether an administrator has connected it.
-->
<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import {
    useMcpOAuthConnect,
    type McpOAuthConnection
  } from "$lib/features/mcp/McpOAuthConnectService.svelte";
  import type { PageProps } from "./$types";
  import { SvelteSet } from "svelte/reactivity";
  import { untrack } from "svelte";

  const { data }: PageProps = $props();
  const eneo = getEneo();
  const connect = useMcpOAuthConnect();

  // Seeded from the load; the page owns the list as connections change.
  let connections = $state<McpOAuthConnection[]>(untrack(() => data.connections));
  const disconnecting = new SvelteSet<string>();

  connect.subscribe((serverId, result) => {
    if (!result.success) {
      if (result.error.message !== "popup_closed") toastError(result.error);
      return;
    }
    connections = connections.map((c) => (c.mcp_server_id === serverId ? result.connection : c));
    toast.success(m.connected());
  });

  async function disconnect(connection: McpOAuthConnection) {
    disconnecting.add(connection.mcp_server_id);
    try {
      await eneo.mcpOauth.disconnect({ id: connection.mcp_server_id });
      connections = connections.map((c) =>
        c.mcp_server_id === connection.mcp_server_id
          ? { ...c, status: "not_connected", scopes: [], connected_at: null, strategy: null }
          : c
      );
    } catch (e) {
      toastError(e);
    } finally {
      disconnecting.delete(connection.mcp_server_id);
    }
  }

  function statusLabel(connection: McpOAuthConnection): string {
    switch (connection.status) {
      case "connected":
        return m.connected();
      case "needs_authorization":
        return m.mcp_oauth_needs_authorization();
      default:
        return m.mcp_oauth_not_connected();
    }
  }

  function statusVariant(connection: McpOAuthConnection): "default" | "outline" | "destructive" {
    if (connection.status === "connected") return "default";
    if (connection.status === "needs_authorization") return "destructive";
    return "outline";
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.account()} – {m.mcp_my_connections()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.mcp_my_connections()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.mcp_my_connections()}>
        <Settings.Row
          title={m.mcp_servers()}
          fullWidth
          description={m.mcp_my_connections_description()}
        >
          {#if connections.length === 0}
            <p class="text-secondary text-sm">{m.mcp_my_connections_empty()}</p>
          {:else}
            <ul class="divide-dimmer border-dimmer divide-y rounded-lg border">
              {#each connections as connection (connection.mcp_server_id)}
                <li class="flex flex-wrap items-center gap-3 px-4 py-3">
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2">
                      <span class="text-default truncate font-medium">{connection.server_name}</span
                      >
                      <Badge variant={statusVariant(connection)}>{statusLabel(connection)}</Badge>
                    </div>
                    {#if connection.auth_scope === "shared"}
                      <p class="text-muted text-xs">{m.mcp_oauth_scope_shared_hint()}</p>
                    {:else if (connection.scopes ?? []).length > 0}
                      <p class="text-muted text-xs">
                        {m.mcp_oauth_scopes_label()}: {(connection.scopes ?? []).join(", ")}
                      </p>
                    {/if}
                  </div>
                  {#if connection.auth_scope === "per_user"}
                    {#if connection.status === "connected"}
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={disconnecting.has(connection.mcp_server_id)}
                        onclick={() => disconnect(connection)}>{m.disconnect()}</Button
                      >
                    {:else}
                      <Button
                        size="sm"
                        disabled={connect.isConnecting(connection.mcp_server_id)}
                        onclick={() => connect.connect(connection.mcp_server_id)}
                        >{m.connect()}</Button
                      >
                    {/if}
                  {/if}
                </li>
              {/each}
            </ul>
          {/if}
        </Settings.Row>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>
