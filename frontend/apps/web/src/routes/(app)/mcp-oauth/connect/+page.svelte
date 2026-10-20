<!--
  Copyright (c) 2026 Sundsvalls Kommun

  Licensed under the MIT License.

  The full-page connect route: where an API integrator sends a user whose
  tool call answered with the authorization-required remedy. It runs the
  vendor's authorization full-page instead of in a popup and ends with a
  "done, go back" message.
-->
<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  import { m } from "$lib/paraglide/messages";
  import { onMount, untrack } from "svelte";
  import type { PageProps } from "./$types";

  const FULL_PAGE_STORAGE_KEY = "eneo.mcp-oauth.full-page";

  const { data }: PageProps = $props();
  const eneo = getEneo();

  // The load result seeds the page; the page then owns the state as the
  // authorization proceeds, so the initial read is deliberately one-off.
  let connection = $state(untrack(() => data.connection));
  let phase = $state<"idle" | "starting" | "completing" | "done" | "error">(
    untrack(() => (data.code ? "completing" : data.oauthError ? "error" : "idle"))
  );
  let errorMessage = $state<string | null>(untrack(() => data.oauthError ?? null));

  const serverName = $derived(connection?.server_name ?? "");

  async function start() {
    phase = "starting";
    errorMessage = null;
    try {
      if (!data.serverId) return;
      const { url, state } = await eneo.mcpOauth.authorizeUrl({ id: data.serverId });
      sessionStorage.setItem(
        FULL_PAGE_STORAGE_KEY,
        JSON.stringify({ server: data.serverId, state })
      );
      window.location.assign(url);
    } catch (e) {
      phase = "error";
      errorMessage = getErrorMessage(e);
    }
  }

  onMount(async () => {
    if (!data.serverId || !data.code || !data.state) return;
    try {
      connection = await eneo.mcpOauth.completeCallback({
        id: data.serverId,
        code: data.code,
        state: data.state,
        iss: data.iss
      });
      phase = "done";
    } catch (e) {
      phase = "error";
      errorMessage = getErrorMessage(e);
    }
  });
</script>

<svelte:head>
  <title>Eneo.ai – {m.mcp_oauth_connect_page_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.mcp_oauth_connect_page_title()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <div class="mx-auto flex max-w-prose flex-col gap-4 p-6">
      {#if !connection}
        <p class="text-secondary">{m.mcp_oauth_connect_page_unknown_server()}</p>
      {:else if phase === "done" || (phase === "idle" && connection.status === "connected")}
        <p class="text-default">{m.mcp_oauth_connect_page_done()}</p>
      {:else}
        <p class="text-default">{m.mcp_oauth_connect_page_intro({ server: serverName })}</p>
        {#if errorMessage}
          <p class="text-negative-default text-sm">{errorMessage}</p>
        {/if}
        <div>
          <Button onclick={start} disabled={phase === "starting" || phase === "completing"}>
            {m.mcp_oauth_connect_server({ server: serverName })}
          </Button>
        </div>
      {/if}
    </div>
  </Page.Main>
</Page.Root>
