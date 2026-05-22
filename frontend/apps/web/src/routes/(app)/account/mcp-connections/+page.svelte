<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->
<script lang="ts">
  import { resolve } from "$app/paths";
  import { Page, Settings } from "$lib/components/layout";
  import type { MCPConnection } from "./+page.server.js";

  type Props = { data: { connections: MCPConnection[]; errorMessage: string | null } };
  const { data }: Props = $props();

  const statusLabel: Record<MCPConnection["status"], string> = {
    connected: "Ansluten",
    expired: "Sessionen har upphört",
    not_authenticated: "Ej autentiserad",
    idp_mismatch: "IdP matchar inte",
    not_applicable: "Ej tillämpligt"
  };

  const statusDescription: Record<MCPConnection["status"], string> = {
    connected:
      "En giltig token finns cachad. Verktyg från servern är tillgängliga utan ytterligare steg.",
    expired:
      "Den cachade token har upphört. Nästa anrop förnyar den automatiskt om din SSO-session fortfarande är aktiv.",
    not_authenticated:
      "Du har inte loggat in via den IdP som servern kräver. Logga ut och logga in igen via SSO för att aktivera servern.",
    idp_mismatch:
      "Din inloggnings-IdP matchar inte den IdP som servern accepterar. Servern kan inte nås innan en administratör uppdaterar konfigurationen.",
    not_applicable: "Servern använder en statisk Bearer-token och beror inte på din inloggning."
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
  <title>Eneo.ai – Mina MCP-anslutningar</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title="Mina MCP-anslutningar" />
  </Page.Header>

  <Page.Main>
    <Settings.Page>
      <div class="space-y-4 py-4">
        <p class="text-muted text-sm">
          Översikt över de MCP-servrar som din administratör har aktiverat och om din SSO-session
          räcker för att nå dem.
        </p>

        {#if data.errorMessage}
          <div
            class="border-negative-default/30 bg-negative-dimmer text-negative-stronger rounded-lg border px-4 py-3 text-sm"
            role="alert"
          >
            Kunde inte hämta anslutningsstatus: {data.errorMessage}
          </div>
        {/if}

        {#if data.connections.length === 0 && !data.errorMessage}
          <div
            class="border-default bg-secondary/30 rounded-lg border px-4 py-6 text-center text-sm"
          >
            Det finns inga MCP-servrar aktiverade för din organisation.
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
                {statusLabel[connection.status]}
              </span>
            </header>

            <p class="text-muted text-sm">{statusDescription[connection.status]}</p>

            <dl class="text-muted grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
              <div>
                <dt class="font-medium">OAuth-omfattning</dt>
                <dd class="font-mono">{connection.auth_scope}</dd>
              </div>
              {#if connection.expected_idp_issuer}
                <div>
                  <dt class="font-medium">Förväntad IdP</dt>
                  <dd class="font-mono break-all">{connection.expected_idp_issuer}</dd>
                </div>
              {/if}
              <div>
                <dt class="font-medium">Token upphör</dt>
                <dd class="font-mono">{formatExpiry(connection.expires_at)}</dd>
              </div>
            </dl>

            {#if connection.status === "not_authenticated" || connection.status === "expired"}
              <div>
                <a
                  href={resolve("/logout?message=reauth_for_mcp")}
                  class="text-accent-default text-sm font-medium underline"
                >
                  Logga in på nytt via SSO
                </a>
              </div>
            {/if}
          </article>
        {/each}
      </div>
    </Settings.Page>
  </Page.Main>
</Page.Root>
