<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { enhance } from "$app/forms";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { m } from "$lib/paraglide/messages";

  const MESSAGE_TYPE = "intric/integration-callback";
  const SERVICE_ACCOUNT_STORAGE_KEY = "sharepoint_service_account_oauth";

  // Flow types
  type FlowType = "popup" | "service_account" | "unknown";
  type Status = "processing" | "popup_complete" | "service_success" | "error";

  let status = $state<Status>("processing");
  let errorMessage = $state<string | null>(null);
  let serviceAccountEmail = $state<string | null>(null);
  let flowType = $state<FlowType>("unknown");

  // Service account stored data interface
  interface ServiceAccountStoredData {
    state: string;
    client_id: string;
    client_secret: string;
    tenant_domain: string;
  }

  function extractParams() {
    const url = new URL(window.location.href);
    return {
      code: url.searchParams.get("code"),
      state: url.searchParams.get("state"),
      error: url.searchParams.get("error"),
      errorDescription: url.searchParams.get("error_description"),
      rawParams: url.search
    };
  }

  function detectFlowType(): FlowType {
    // Check for popup flow first
    if (window.opener) {
      return "popup";
    }

    // Check for service account flow
    const storedData = sessionStorage.getItem(SERVICE_ACCOUNT_STORAGE_KEY);
    if (storedData) {
      return "service_account";
    }

    return "unknown";
  }

  function handlePopupFlow(code: string | null, state: string | null, rawParams: string): void {
    const opener = window.opener;
    if (opener) {
      opener.postMessage(
        { type: MESSAGE_TYPE, code, state, params: rawParams },
        "*"
      );
      status = "popup_complete";
      window.close();
    }
  }

  async function handleServiceAccountFlow(code: string | null, state: string | null): Promise<void> {
    // Validate required params
    if (!code || !state) {
      status = "error";
      errorMessage = "Missing authorization code or state parameter";
      return;
    }

    // Get and validate stored data
    const storedDataStr = sessionStorage.getItem(SERVICE_ACCOUNT_STORAGE_KEY);
    if (!storedDataStr) {
      status = "error";
      errorMessage = "OAuth session expired. Please try again.";
      return;
    }

    let storedData: ServiceAccountStoredData;
    try {
      storedData = JSON.parse(storedDataStr);
    } catch {
      status = "error";
      errorMessage = "Invalid OAuth session data";
      return;
    }

    // Verify state matches (CSRF protection)
    if (storedData.state !== state) {
      status = "error";
      errorMessage = "OAuth state mismatch. This may be a security issue.";
      return;
    }

    // Clear stored data immediately after validation
    sessionStorage.removeItem(SERVICE_ACCOUNT_STORAGE_KEY);

    // Complete OAuth flow via server action
    // (This page is outside (app) layout, so Intric context is not available)
    // Store data for form submission
    serviceAccountFormData = {
      auth_code: code,
      state: state,
      client_id: storedData.client_id,
      client_secret: storedData.client_secret,
      tenant_domain: storedData.tenant_domain,
    };

    // Trigger form submission programmatically
    await submitServiceAccountForm();
  }

  // Form data for service account flow
  let serviceAccountFormData = $state<{
    auth_code: string;
    state: string;
    client_id: string;
    client_secret: string;
    tenant_domain: string;
  } | null>(null);

  let formElement: HTMLFormElement | undefined = $state();

  async function submitServiceAccountForm() {
    // Wait for next tick to ensure form is rendered with data
    await new Promise((resolve) => setTimeout(resolve, 0));
    formElement?.requestSubmit();
  }

  onMount(async () => {
    const params = extractParams();

    // Check for OAuth errors from provider first
    if (params.error) {
      status = "error";
      errorMessage = params.errorDescription || params.error;
      return;
    }

    // Detect and handle flow type
    flowType = detectFlowType();

    switch (flowType) {
      case "popup":
        handlePopupFlow(params.code, params.state, params.rawParams);
        break;

      case "service_account":
        await handleServiceAccountFlow(params.code, params.state);
        break;

      case "unknown":
        status = "error";
        errorMessage = "Unable to determine authentication flow. Please try again from the application.";
        break;
    }
  });
</script>

<svelte:head>
  <title>
    {status === "processing"
      ? "Processing..."
      : status === "service_success"
        ? "Success"
        : status === "error"
          ? "Error"
          : "Integration Authentication"}
  </title>
</svelte:head>

<main class="callback">
  {#if status === "processing"}
    <!-- Processing state -->
    {#if flowType === "service_account"}
      <IconLoadingSpinner class="h-12 w-12 animate-spin text-blue-500" />
      <h1 class="text-xl font-semibold text-primary">
        {m.completing_authentication()}
      </h1>
      <p class="text-secondary">
        {m.please_wait()}
      </p>
    {:else}
      <h1>Finishing sign-in…</h1>
      <p>You can close this window.</p>
    {/if}

  {:else if status === "popup_complete"}
    <!-- Popup complete state (fallback if window doesn't close) -->
    <h1>Finishing sign-in…</h1>
    <p>You can close this window.</p>

  {:else if status === "service_success"}
    <!-- Service account success -->
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

  {:else if status === "error"}
    <!-- Error state -->
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

  <!-- Hidden form for service account OAuth completion -->
  {#if serviceAccountFormData}
    <form
      bind:this={formElement}
      method="POST"
      action="?/completeServiceAccountAuth"
      class="hidden"
      use:enhance={() => {
        return async ({ result }) => {
          if (result.type === "success" && result.data?.success) {
            status = "service_success";
            serviceAccountEmail = result.data.service_account_email || null;
            setTimeout(() => {
              goto("/admin/integrations?sharepoint_configured=true");
            }, 2000);
          } else if (result.type === "failure") {
            status = "error";
            errorMessage = result.data?.error || "Failed to complete authentication";
          } else {
            status = "error";
            errorMessage = "Unexpected error during authentication";
          }
        };
      }}
    >
      <input type="hidden" name="auth_code" value={serviceAccountFormData.auth_code} />
      <input type="hidden" name="state" value={serviceAccountFormData.state} />
      <input type="hidden" name="client_id" value={serviceAccountFormData.client_id} />
      <input type="hidden" name="client_secret" value={serviceAccountFormData.client_secret} />
      <input type="hidden" name="tenant_domain" value={serviceAccountFormData.tenant_domain} />
    </form>
  {/if}
</main>

<style>
  /* Basic styling that works both in popup (minimal CSS) and full page */
  .callback {
    margin: 0;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 1rem;
    padding: 2rem;
    text-align: center;
    background: var(--color-primary-bg, #fff);
    color: var(--color-primary-text, #111);
  }
</style>
