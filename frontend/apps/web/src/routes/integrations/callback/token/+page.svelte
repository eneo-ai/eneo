<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { enhance } from "$app/forms";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { buttonVariants } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils.js";

  import { SHAREPOINT_SERVICE_ACCOUNT_OAUTH_KEY as SERVICE_ACCOUNT_STORAGE_KEY } from "$lib/features/integrations/sharepoint/serviceAccountAuth";

  const MESSAGE_TYPE = "eneo/integration-callback";

  // Flow types
  type FlowType = "popup" | "service_account" | "unknown";
  type Status = "processing" | "popup_complete" | "service_success" | "error";

  let status = $state<Status>("processing");
  let errorMessage = $state<string | null>(null);
  let serviceAccountEmail = $state<string | null>(null);
  let flowType = $state<FlowType>("unknown");

  function getActionErrorMessage(errorKey?: string, errorDetail?: string): string {
    switch (errorKey) {
      case "integration_callback_missing_required_fields":
        return m.integration_callback_missing_required_fields();
      case "integration_callback_backend_url_not_configured":
        return m.integration_callback_backend_url_not_configured();
      case "integration_callback_not_authenticated":
        return m.integration_callback_not_authenticated();
      case "integration_callback_failed_to_complete_authentication":
        return errorDetail
          ? `${m.integration_callback_failed_to_complete_authentication()}: ${errorDetail}`
          : m.integration_callback_failed_to_complete_authentication();
      default:
        return m.integration_callback_failed_to_complete_authentication();
    }
  }

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
      // The integration page only accepts callbacks from its own origin. Keep
      // OAuth credentials inside that origin even when a foreign site opened us.
      opener.postMessage(
        { type: MESSAGE_TYPE, code, state, params: rawParams },
        window.location.origin
      );
      status = "popup_complete";
      window.close();
    }
  }

  async function handleServiceAccountFlow(
    code: string | null,
    state: string | null
  ): Promise<void> {
    // Validate required params
    if (!code || !state) {
      status = "error";
      errorMessage = m.integration_callback_missing_authorization_code_or_state();
      return;
    }

    // Get and validate stored data
    const storedDataStr = sessionStorage.getItem(SERVICE_ACCOUNT_STORAGE_KEY);
    if (!storedDataStr) {
      status = "error";
      errorMessage = m.integration_callback_oauth_session_expired();
      return;
    }

    let storedData: ServiceAccountStoredData;
    try {
      storedData = JSON.parse(storedDataStr);
    } catch {
      status = "error";
      errorMessage = m.integration_callback_invalid_oauth_session_data();
      return;
    }

    // Verify state matches (CSRF protection)
    if (storedData.state !== state) {
      status = "error";
      errorMessage = m.integration_callback_oauth_state_mismatch();
      return;
    }

    // Clear stored data immediately after validation
    sessionStorage.removeItem(SERVICE_ACCOUNT_STORAGE_KEY);

    // Complete OAuth flow via server action
    // (This page is outside (app) layout, so Eneo context is not available)
    // Store data for form submission
    serviceAccountFormData = {
      auth_code: code,
      state: state
    };

    // Trigger form submission programmatically
    await submitServiceAccountForm();
  }

  // Form data for service account flow
  let serviceAccountFormData = $state<{
    auth_code: string;
    state: string;
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
        errorMessage = m.integration_callback_unable_to_determine_flow();
        break;
    }
  });
</script>

<svelte:head>
  <title>
    {status === "processing"
      ? m.processing()
      : status === "service_success"
        ? m.success()
        : status === "error"
          ? m.error()
          : m.integration_authentication()}
  </title>
</svelte:head>

<main
  class="bg-primary text-primary flex min-h-screen flex-col items-center justify-center gap-4 p-8 text-center"
>
  {#if status === "processing"}
    <!-- Processing state -->
    {#if flowType === "service_account"}
      <IconLoadingSpinner class="text-accent-default h-12 w-12 animate-spin" />
      <h1 class="text-primary text-xl font-semibold">
        {m.completing_authentication()}
      </h1>
      <p class="text-secondary">
        {m.please_wait()}
      </p>
    {:else}
      <h1>{m.integration_callback_finishing_sign_in()}</h1>
      <p>{m.integration_callback_close_window()}</p>
    {/if}
  {:else if status === "popup_complete"}
    <!-- Popup complete state (fallback if window doesn't close) -->
    <h1>{m.integration_callback_finishing_sign_in()}</h1>
    <p>{m.integration_callback_close_window()}</p>
  {:else if status === "service_success"}
    <!-- Service account success -->
    <div class="bg-positive-dimmer rounded-full p-4">
      <svg
        class="text-positive-default h-12 w-12"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
      </svg>
    </div>
    <h1 class="text-positive-stronger text-xl font-semibold">
      {m.service_account_configured()}
    </h1>
    {#if serviceAccountEmail}
      <p class="text-secondary">
        {m.connected_as()}: <span class="font-medium">{serviceAccountEmail}</span>
      </p>
    {/if}
    <p class="text-secondary text-sm">
      {m.redirecting_back()}
    </p>
  {:else if status === "error"}
    <!-- Error state -->
    <div class="bg-negative-dimmer rounded-full p-4">
      <svg
        class="text-negative-default h-12 w-12"
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
    <h1 class="text-negative-stronger text-xl font-semibold">
      {m.authentication_failed()}
    </h1>
    {#if errorMessage}
      <p class="text-secondary max-w-md text-center">{errorMessage}</p>
    {/if}
    <!-- eslint-disable svelte/no-navigation-without-resolve -- static literal route, public callback layout -->
    <a href="/admin/integrations" class={cn(buttonVariants(), "mt-4")}>
      {m.back_to_integrations()}
    </a>
    <!-- eslint-enable svelte/no-navigation-without-resolve -->
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
            serviceAccountEmail = (result.data.service_account_email as string) || null;
            setTimeout(() => {
              // eslint-disable-next-line svelte/no-navigation-without-resolve -- static literal route with query string
              goto("/admin/integrations?sharepoint_configured=true");
            }, 2000);
          } else if (result.type === "failure") {
            status = "error";
            const data = (result as { data?: Record<string, string> }).data || {};
            errorMessage = data.error
              ? data.error
              : getActionErrorMessage(data.error_key, data.error_detail);
          } else {
            status = "error";
            errorMessage = m.integration_callback_unexpected_error();
          }
        };
      }}
    >
      <input type="hidden" name="auth_code" value={serviceAccountFormData.auth_code} />
      <input type="hidden" name="state" value={serviceAccountFormData.state} />
    </form>
  {/if}
</main>
