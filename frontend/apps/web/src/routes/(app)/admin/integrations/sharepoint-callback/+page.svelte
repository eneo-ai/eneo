<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();

  let status = $state<"processing" | "success" | "error">("processing");
  let errorMessage = $state<string | null>(null);
  let serviceAccountEmail = $state<string | null>(null);

  onMount(async () => {
    const url = new URL(window.location.href);
    const code = url.searchParams.get("code");
    const state = url.searchParams.get("state");
    const error = url.searchParams.get("error");
    const errorDescription = url.searchParams.get("error_description");

    // Check for OAuth errors
    if (error) {
      status = "error";
      errorMessage = errorDescription || error;
      return;
    }

    if (!code || !state) {
      status = "error";
      errorMessage = "Missing authorization code or state parameter";
      return;
    }

    // Get stored credentials from sessionStorage
    const storedDataStr = sessionStorage.getItem("sharepoint_service_account_oauth");
    if (!storedDataStr) {
      status = "error";
      errorMessage = "OAuth session expired. Please try again.";
      return;
    }

    let storedData: {
      state: string;
      client_id: string;
      client_secret: string;
      tenant_domain: string;
    };

    try {
      storedData = JSON.parse(storedDataStr);
    } catch {
      status = "error";
      errorMessage = "Invalid OAuth session data";
      return;
    }

    // Verify state matches
    if (storedData.state !== state) {
      status = "error";
      errorMessage = "OAuth state mismatch. This may be a security issue.";
      return;
    }

    // Clear stored data
    sessionStorage.removeItem("sharepoint_service_account_oauth");

    try {
      // Complete OAuth flow
      const result = await intric.client.fetch(
        "/api/v1/admin/sharepoint/service-account/auth/callback",
        {
          method: "post",
          params: {},
          requestBody: {
            "application/json": {
              auth_code: code,
              state: state,
              client_id: storedData.client_id,
              client_secret: storedData.client_secret,
              tenant_domain: storedData.tenant_domain,
            },
          },
        }
      );

      status = "success";
      serviceAccountEmail = (result as { service_account_email?: string }).service_account_email || null;

      // Redirect back to admin integrations page after a short delay
      setTimeout(() => {
        goto("/admin/integrations?sharepoint_configured=true");
      }, 2000);
    } catch (error) {
      status = "error";
      errorMessage =
        error instanceof Error ? error.message : "Failed to complete authentication";
    }
  });
</script>

<svelte:head>
  <title>
    {status === "processing"
      ? "Processing..."
      : status === "success"
        ? "Success"
        : "Error"}
  </title>
</svelte:head>

<main class="flex min-h-screen w-full flex-col items-center justify-center gap-4 p-8 text-center">
  {#if status === "processing"}
    <IconLoadingSpinner class="h-12 w-12 animate-spin text-blue-500" />
    <h1 class="text-xl font-semibold text-primary">
      {m.completing_authentication()}
    </h1>
    <p class="text-secondary">
      {m.please_wait()}
    </p>
  {:else if status === "success"}
    <div class="rounded-full bg-green-100 p-4">
      <svg
        class="h-12 w-12 text-green-600"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="2"
          d="M5 13l4 4L19 7"
        />
      </svg>
    </div>
    <h1 class="text-xl font-semibold text-green-700">
      {m.service_account_configured()}
    </h1>
    {#if serviceAccountEmail}
      <p class="text-secondary">
        {m.connected_as()}: <span class="font-medium">{serviceAccountEmail}</span>
      </p>
    {/if}
    <p class="text-sm text-secondary">
      {m.redirecting_back()}
    </p>
  {:else}
    <div class="rounded-full bg-red-100 p-4">
      <svg
        class="h-12 w-12 text-red-600"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="2"
          d="M6 18L18 6M6 6l12 12"
        />
      </svg>
    </div>
    <h1 class="text-xl font-semibold text-red-700">
      {m.authentication_failed()}
    </h1>
    {#if errorMessage}
      <p class="max-w-md text-center text-secondary">{errorMessage}</p>
    {/if}
    <a
      href="/admin/integrations"
      class="mt-4 rounded-lg bg-blue-600 px-6 py-2 text-white hover:bg-blue-700"
    >
      {m.back_to_integrations()}
    </a>
  {/if}
</main>
