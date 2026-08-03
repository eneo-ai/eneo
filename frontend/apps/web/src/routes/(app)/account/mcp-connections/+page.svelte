<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->
<script lang="ts">
  import { resolve } from "$app/paths";
  import { Page, Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type { MCPConnection } from "./+page.server.js";

  type Props = { data: { connections: MCPConnection[]; errorMessage: string | null } };
  const { data }: Props = $props();

  const statusLabel: Record<MCPConnection["status"], () => string> = {
    connected: m.mcp_connection_status_connected,
    expired: m.mcp_connection_status_expired,
    not_authenticated: m.mcp_connection_status_not_authenticated,
    idp_mismatch: m.mcp_connection_status_idp_mismatch,
    not_applicable: m.mcp_connection_status_not_applicable
  };

  const statusDescription: Record<MCPConnection["status"], () => string> = {
    connected: m.mcp_connection_status_connected_description,
    expired: m.mcp_connection_status_expired_description,
    not_authenticated: m.mcp_connection_status_not_authenticated_description,
    idp_mismatch: m.mcp_connection_status_idp_mismatch_description,
    not_applicable: m.mcp_connection_status_not_applicable_description
  };

  const statusBadgeClass: Record<MCPConnection["status"], string> = {
    connected: "bg-positive-dimmer text-positive-stronger",
    expired: "bg-caution/15 text-caution",
    not_authenticated: "bg-warning-dimmer text-warning-stronger",
    idp_mismatch: "bg-negative-dimmer text-negative-stronger",
    not_applicable: "bg-secondary text-muted"
  };

  function formatExpiry(iso: string | null): string {
    if (!iso) return "—";
    try {
      const date = new Date(iso);
      return date.toLocaleString("sv-SE");
    } catch {
      return iso;
    }
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.mcp_connections_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.mcp_connections_title()} />
  </Page.Header>

  <Page.Main>
    <Settings.Page>
      <div class="space-y-4 py-4">
        <p class="text-muted text-sm">
          {m.mcp_connections_intro()}
        </p>

        {#if data.errorMessage}
          <div
            class="border-negative-default/30 bg-negative-dimmer text-negative-stronger rounded-lg border px-4 py-3 text-sm"
            role="alert"
          >
            {m.mcp_connections_error_prefix()}
            {data.errorMessage}
          </div>
        {/if}

        {#if data.connections.length === 0 && !data.errorMessage}
          <div
            class="border-default bg-secondary/30 rounded-lg border px-4 py-6 text-center text-sm"
          >
            {m.mcp_connections_empty()}
          </div>
        {/if}

        {#each data.connections as connection (connection.mcp_server_id)}
          <article
            class="border-default bg-primary flex flex-col gap-3 rounded-xl border p-4 shadow-sm"
          >
            <header class="flex flex-wrap items-baseline justify-between gap-2">
              <h2 class="text-default text-base font-semibold">{connection.name}</h2>
              <span
                class="rounded-full px-2.5 py-1 text-xs font-medium {statusBadgeClass[
                  connection.status
                ]}"
              >
                {statusLabel[connection.status]()}
              </span>
            </header>

            <p class="text-muted text-sm">{statusDescription[connection.status]()}</p>

            <dl class="text-muted grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
              <div>
                <dt class="font-medium">{m.mcp_connections_scope_label()}</dt>
                <dd class="font-mono">{connection.auth_scope}</dd>
              </div>
              {#if connection.expected_idp_issuer}
                <div>
                  <dt class="font-medium">{m.mcp_connections_idp_label()}</dt>
                  <dd class="font-mono break-all">{connection.expected_idp_issuer}</dd>
                </div>
              {/if}
              <div>
                <dt class="font-medium">{m.mcp_connections_expiry_label()}</dt>
                <dd class="font-mono">{formatExpiry(connection.expires_at)}</dd>
              </div>
            </dl>

            {#if connection.status === "not_authenticated" || connection.status === "expired"}
              <div>
                <a
                  href={resolve("/logout?message=reauth_for_mcp")}
                  class="text-accent-default text-sm font-medium underline"
                >
                  {m.mcp_connections_relogin()}
                </a>
              </div>
            {/if}
          </article>
        {/each}
      </div>
    </Settings.Page>
  </Page.Main>
</Page.Root>
