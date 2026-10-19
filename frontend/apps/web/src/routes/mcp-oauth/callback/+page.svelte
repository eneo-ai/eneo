<!--
  Copyright (c) 2026 Sundsvalls Kommun

  Licensed under the MIT License.

  Where a vendor's authorization server sends the browser back after the user
  authorized Eneo. Opened in the popup the chat or account page launched, it
  hands the code to that opener and closes; opened full-page (the connect
  route for API integrators), it carries the code on to that route, which is
  signed in and finishes the authorization.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { m } from "$lib/paraglide/messages";

  const MESSAGE_TYPE = "eneo/mcp-oauth-callback";
  const FULL_PAGE_STORAGE_KEY = "eneo.mcp-oauth.full-page";

  let status = $state<"processing" | "closing" | "error">("processing");
  let errorMessage = $state<string | null>(null);

  onMount(() => {
    const params = new URL(window.location.href).searchParams;
    const payload = {
      type: MESSAGE_TYPE,
      code: params.get("code"),
      state: params.get("state"),
      iss: params.get("iss"),
      error: params.get("error"),
      error_description: params.get("error_description")
    };

    if (window.opener) {
      // Same-origin only: the code must never leave this deployment. The
      // opener owns this window: it navigates it on to the next server when
      // several are connected in turn, and closes it when it is done.
      window.opener.postMessage(payload, window.location.origin);
      status = "closing";
      return;
    }

    let pending: { server: string; state: string } | null = null;
    try {
      const raw = sessionStorage.getItem(FULL_PAGE_STORAGE_KEY);
      pending = raw ? JSON.parse(raw) : null;
      sessionStorage.removeItem(FULL_PAGE_STORAGE_KEY);
    } catch {
      pending = null;
    }
    if (pending && pending.state === payload.state) {
      const next = new URL("/mcp-oauth/connect", window.location.origin);
      next.searchParams.set("server", pending.server);
      for (const key of ["code", "state", "iss", "error", "error_description"] as const) {
        const value = payload[key];
        if (value) next.searchParams.set(key, value);
      }
      window.location.replace(next.toString());
      return;
    }

    status = "error";
    errorMessage = payload.error_description || payload.error || m.mcp_oauth_callback_no_opener();
  });
</script>

<svelte:head>
  <title>{m.mcp_oauth_connect_page_title()}</title>
</svelte:head>

<main class="flex min-h-screen flex-col items-center justify-center gap-4 p-8 text-center">
  {#if status === "error"}
    <h1 class="text-primary text-xl font-semibold">{m.mcp_oauth_connect_failed()}</h1>
    {#if errorMessage}
      <p class="text-secondary max-w-prose text-sm">{errorMessage}</p>
    {/if}
  {:else}
    <IconLoadingSpinner class="h-10 w-10 animate-spin" />
    <p class="text-secondary text-sm">{m.mcp_oauth_callback_closing()}</p>
  {/if}
</main>
