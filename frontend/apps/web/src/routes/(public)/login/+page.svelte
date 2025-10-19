<script lang="ts">
  import { page } from "$app/state";
  import { enhance } from "$app/forms";
  import { Button, Input } from "@intric/ui";
  import { goto } from "$app/navigation";
  import { browser } from "$app/environment";
  import { onMount } from "svelte";
  import { LoadingScreen } from "$lib/components/layout";
  import EneoWordMark from "$lib/assets/EneoWordMark.svelte";
  import IntricWordMark from "$lib/assets/IntricWordMark.svelte";
  import TenantSelector from "$lib/components/TenantSelector.svelte";
  import { m } from "$lib/paraglide/messages";

  type TenantInfo = {
    slug: string;
    name: string;
    display_name: string;
  };

  const { data } = $props();

  const OIDC_ERROR_CODES = new Set([
    "authentication_failed",
    "unexpected_error",
    "no_state_received",
    "no_code_received",
    "oidc_callback_failed",
    "oidc_forbidden",
    "oidc_unauthorized"
  ]);

  // Reactive state that updates when URL changes
  let message = $state<string | null>(null);
  let oidcErrorCode = $state<string | null>(null);
  let oidcErrorDetailCode = $state<string | null>(null);
  let oidcCorrelationId = $state<string | null>(null);
  let oidcRawDetail = $state<string | null>(null);
  let activeTenantSlug = $state<string | null>(null);

  // Sync query params from URL reactively
  $effect(() => {
    const rawMessage = page.url.searchParams.get("message");
    const rawDetailCode = page.url.searchParams.get("detailCode");
    const rawCorrelation = page.url.searchParams.get("correlation");
    const rawRawDetail = page.url.searchParams.get("rawDetail");
    const rawTenant = page.url.searchParams.get("tenant");

    message = rawMessage && !OIDC_ERROR_CODES.has(rawMessage) ? rawMessage : null;
    oidcErrorCode = rawMessage && OIDC_ERROR_CODES.has(rawMessage) ? rawMessage : null;
    oidcErrorDetailCode = rawDetailCode;
    oidcCorrelationId = rawCorrelation;
    oidcRawDetail = rawRawDetail;

    if (rawTenant) {
      activeTenantSlug = rawTenant;
    }
  });

  const LAST_TENANT_KEY = "eneo-last-tenant-slug";
  const TENANT_SELECTOR_CACHE_KEY = "eneo:last-tenant";

  let loginFailed = $state(false);
  let isAwaitingLoginResponse = $state(false);
  let showTenantSelector = $state(false);
  let federationError = $state<string | null>(null);
  let preloadedTenants = $state<TenantInfo[]>([]);
  let isInitializing = $state(true);
  let showSlowLoadingWarning = $state(false);
  let loadingTimeoutId: number | null = null;

  let showUsernameAndPassword = $derived(page.url?.searchParams.get("showUsernameAndPassword"));
  let tenantFederationEnabled = $derived(Boolean(data.featureFlags?.tenantFederationEnabled));

  // Determine which loading message to display
  let loadingMessage = $derived.by(() => {
    // Check for OIDC error directly from URL (don't wait for $effect to set oidcErrorCode)
    const urlMessage = page.url.searchParams.get("message");
    const hasOidcErrorInUrl = urlMessage && OIDC_ERROR_CODES.has(urlMessage);

    if (hasOidcErrorInUrl && isInitializing) {
      return m.loading_error_details();
    }
    if (isAwaitingLoginResponse) {
      return m.redirecting_to_authentication();
    }
    if (isInitializing && tenantFederationEnabled) {
      return m.loading_organizations();
    }
    if ((data.zitadelLink || data.singleTenantOidcLink) && !hasQueryParams) {
      return m.redirecting_to_authentication();
    }
    return undefined;
  });

  // Check if user explicitly wants to see login form (e.g., after logout)
  const hasQueryParams = $derived(
    message !== null ||
      oidcErrorCode !== null ||
      showUsernameAndPassword !== null ||
      activeTenantSlug !== null
  );

  // Monitor loading state and show warning if taking too long
  $effect(() => {
    if (!browser) return;

    const isLoading = isInitializing || isAwaitingLoginResponse;

    if (isLoading) {
      // Start timeout to show slow loading warning after 10 seconds
      if (loadingTimeoutId === null) {
        loadingTimeoutId = window.setTimeout(() => {
          showSlowLoadingWarning = true;
        }, 10000);
      }
    } else {
      // Clear timeout and hide warning when loading completes
      if (loadingTimeoutId !== null) {
        clearTimeout(loadingTimeoutId);
        loadingTimeoutId = null;
      }
      showSlowLoadingWarning = false;
    }

    // Cleanup on unmount
    return () => {
      if (loadingTimeoutId !== null) {
        clearTimeout(loadingTimeoutId);
      }
    };
  });

  // Handle automatic redirects reactively
  $effect(() => {
    if (!browser) return;
    if (showTenantSelector) return;

    // We don't redirect on the server so we can render a loader/spinner during the redirection period
    if (data.zitadelLink && !hasQueryParams) {
      isInitializing = true; // Keep showing loader during redirect
      window.location.href = data.zitadelLink;
      return;
    }

    // Single-tenant OIDC: redirect to IdP immediately (unless user wants to see login form)
    if (data.singleTenantOidcLink && !hasQueryParams) {
      isInitializing = true; // Keep showing loader during redirect
      window.location.href = data.singleTenantOidcLink;
    }
  });

  // Check for tenant-based federation on mount
  onMount(async () => {
    if (!browser) return;

    if (activeTenantSlug) {
      sessionStorage.setItem(LAST_TENANT_KEY, activeTenantSlug);
    } else {
      const remembered = sessionStorage.getItem(LAST_TENANT_KEY);
      if (remembered) {
        activeTenantSlug = remembered;
      }
    }

    if (!tenantFederationEnabled) {
      isInitializing = false;
      return;
    }

    if (showUsernameAndPassword) {
      isInitializing = false;
      return;
    }

    const urlParams = new URLSearchParams(window.location.search);
    const tenant = urlParams.get("tenant") ?? activeTenantSlug;

    // Check URL params directly to avoid race condition with $effect
    const urlErrorMessage = urlParams.get("message");
    const hasOidcError = urlErrorMessage && OIDC_ERROR_CODES.has(urlErrorMessage);

    // CRITICAL: Do NOT attempt any login or load tenants if there's an OIDC error
    // This prevents infinite loops when login fails
    if (hasOidcError) {
      console.debug("[Login Page] OIDC error detected in URL, skipping auto-login");
      isInitializing = false;
      return;
    }

    if (tenant && /^[a-z0-9-]+$/.test(tenant)) {
      const success = await beginTenantLogin(tenant);
      if (success) {
        // Keep isInitializing=true to show loader until redirect completes
        return;
      }
    }

    if (!data.zitadelLink && !data.mobilityguardLink) {
      await loadTenantsAndMaybeShow();
    }

    // Done initializing
    isInitializing = false;
  });

  function rememberTenant(slug: string) {
    if (browser) {
      sessionStorage.setItem(LAST_TENANT_KEY, slug);
    }
    activeTenantSlug = slug;
  }

  function clearRememberedTenant() {
    if (browser) {
      sessionStorage.removeItem(LAST_TENANT_KEY);
    }
    activeTenantSlug = null;
  }

  async function clearOidcErrorFromUrl() {
    if (!browser) return;
    const params = new URLSearchParams(window.location.search);
    params.delete("message");
    params.delete("detailCode");
    params.delete("correlation");
    params.delete("rawDetail");
    const query = params.toString();
    await goto(`${window.location.pathname}${query ? `?${query}` : ""}`, { replaceState: true, noScroll: true });
  }

  async function beginTenantLogin(slug: string): Promise<boolean> {
    try {
      rememberTenant(slug);
      federationError = null;
      await clearOidcErrorFromUrl();
      showTenantSelector = false;
      isAwaitingLoginResponse = true;

      // Dynamic import to avoid SSR issues
      const { intric } = await import("$lib/api/client");

      const redirectUri = `${window.location.origin}/auth/callback`;
      const response = await intric.auth.initiateAuth({ tenant: slug, redirectUri });

      window.location.href = response.authorization_url;
      return true;
    } catch (err) {
      console.error("Failed to initiate federation auth:", err);
      federationError = m.failed_to_start_authentication();
      isAwaitingLoginResponse = false;
      return false;
    }
  }

  async function handleTenantSelect(slug: string) {
    await beginTenantLogin(slug);
  }

  async function loadTenantsAndMaybeShow({ forceShow = false }: { forceShow?: boolean } = {}) {
    try {
      const { intric } = await import("$lib/api/client");
      const response = await intric.auth.listTenants();
      const tenants = response.tenants ?? [];
      preloadedTenants = tenants;

      if (forceShow) {
        showTenantSelector = true;
      }

      if (tenants.length === 0) {
        showTenantSelector = false;
        return;
      }

      if (tenants.length === 1 && !forceShow) {
        await handleTenantSelect(tenants[0].slug);
        return;
      }

      showTenantSelector = true;
    } catch (err) {
      console.error("Failed to load tenants:", err);
      federationError = m.failed_to_load_organizations();
      showTenantSelector = false;
    }
  }

  async function retryTenantLogin() {
    if (!activeTenantSlug) {
      await loadTenantsAndMaybeShow({ forceShow: true });
      return;
    }

    await beginTenantLogin(activeTenantSlug);
  }

  async function chooseAnotherTenant() {
    clearRememberedTenant();
    federationError = null;
    isAwaitingLoginResponse = false;
    showTenantSelector = true;

    if (browser) {
      try {
        localStorage.removeItem(TENANT_SELECTOR_CACHE_KEY);
      } catch {
        // ignore storage errors (private browsing, etc.)
      }
      const params = new URLSearchParams(window.location.search);
      params.delete("message");
      params.delete("detailCode");
      params.delete("correlation");
      params.delete("rawDetail");
      params.delete("tenant");
      const query = params.toString();
      await goto(`${window.location.pathname}${query ? `?${query}` : ""}`, { replaceState: true, noScroll: true });
    }

    await loadTenantsAndMaybeShow({ forceShow: true });
  }

  async function handleRetryClick(event: MouseEvent) {
    event.preventDefault();
    await retryTenantLogin();
  }

  async function handleChooseAnotherClick(event: MouseEvent) {
    event.preventDefault();
    await chooseAnotherTenant();
  }

  function getOidcErrorMessage(): string {
    if (oidcErrorDetailCode === "access_denied") {
      return m.oidc_error_forbidden();
    }
    if (oidcErrorDetailCode === "unauthorized") {
      return m.oidc_error_unauthorized();
    }
    return m.oidc_error_generic();
  }

  // Copy to clipboard functionality for correlation ID
  let copied = $state(false);

  function copyToClipboard(text: string) {
    navigator.clipboard.writeText(text).then(() => {
      copied = true;
      setTimeout(() => { copied = false; }, 2000);
    });
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.login()}</title>
</svelte:head>

{#if isInitializing || isAwaitingLoginResponse || ((data.zitadelLink || data.singleTenantOidcLink) && !hasQueryParams)}
  <div class="relative flex h-[100vh] w-[100vw] items-center justify-center">
    <div class="flex flex-col items-center gap-6">
      <LoadingScreen message={loadingMessage} />
      {#if showSlowLoadingWarning}
        <div class="bg-warning-dimmer text-warning-default max-w-md rounded-lg p-4 shadow-lg" role="alert">
          <p class="mb-2">{m.connection_slow_warning()}</p>
          <Button
            variant="outlined"
            on:click={() => window.location.reload()}
            class="w-full justify-center">
            {m.retry()}
          </Button>
        </div>
      {/if}
    </div>
  </div>
{:else if showTenantSelector}
  <!-- Tenant Selector for Federation -->
  <div class="relative flex min-h-[100vh] w-[100vw] items-center justify-center py-8">
    <div class="w-full max-w-6xl">
      <h1 class="mb-8 flex justify-center">
        <IntricWordMark class="text-brand-intric h-16 w-24" />
        <span class="sr-only">{m.app_name()}</span>
      </h1>

      {#if federationError}
        <div class="mx-auto mb-6 max-w-md">
          <div class="bg-negative-dimmer text-negative-default flex flex-col gap-3 p-4 shadow-lg">
            <strong>{m.authentication_failed()}</strong>
            {federationError}
          </div>
        </div>
      {/if}

      <TenantSelector
        onTenantSelect={handleTenantSelect}
        baseUrl={window.location.origin}
        tenants={preloadedTenants}
      />
    </div>
  </div>
{:else}
  <div class="relative flex h-[100vh] w-[100vw] items-center justify-center">
    <div class="box w-[400px] justify-center">
      <h1 class="flex justify-center">
        <IntricWordMark class="text-brand-intric h-16 w-24" />
        <span class="sr-only">{m.app_name()}</span>
      </h1>

      {#if oidcErrorCode}
        <!-- Error Box Container with WCAG AA-compliant colors -->
        <div
          class="w-full max-w-md mx-auto bg-red-100 rounded-lg p-6 shadow-md mb-4"
          role="alert"
          aria-live="assertive">

          <!-- Error Title Section -->
          <div class="flex items-start gap-2">
            <!-- Error Icon -->
            <svg class="w-6 h-6 text-red-900 flex-shrink-0 mt-0.5"
                 fill="none"
                 viewBox="0 0 24 24"
                 stroke="currentColor"
                 aria-hidden="true">
              <path stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>

            <!-- Error Title -->
            <h1 class="text-lg font-semibold text-red-900 leading-tight">
              {m.failed_to_login()}
            </h1>
          </div>

          <!-- Error Message Section -->
          <div class="mt-4">
            <p class="text-red-900 leading-relaxed">
              {getOidcErrorMessage()}
            </p>
            {#if !oidcErrorDetailCode && oidcRawDetail}
              <p class="text-sm text-red-900 mt-2">{m.oidc_error_detail({ detail: oidcRawDetail })}</p>
            {/if}
          </div>

          <!-- Action Buttons Section -->
          <div class="mt-6 flex flex-col sm:flex-row gap-4 items-stretch">
            <!-- Primary Action: Retry Login -->
            {#if activeTenantSlug}
              <Button
                type="button"
                variant="primary"
                class="flex-1 justify-center"
                disabled={isAwaitingLoginResponse}
                on:click={handleRetryClick}>
                {#if isAwaitingLoginResponse}
                  {m.redirecting_to_authentication()}
                {:else}
                  {m.oidc_retry_login()}
                {/if}
              </Button>
            {/if}

            <!-- Secondary Action: Choose Another Organization -->
            <Button
              type="button"
              variant="outlined"
              on:click={handleChooseAnotherClick}
              class="flex-1 justify-center bg-white text-gray-900 border-gray-700 hover:bg-gray-50 hover:border-gray-800 hover:text-gray-900 shadow-sm">
              {m.oidc_choose_another_org()}
            </Button>
          </div>

          <!-- Correlation ID Section -->
          {#if oidcCorrelationId}
            <div class="mt-6 pt-4 border-t border-red-800">
              <div class="flex items-start gap-2">
                <div class="flex-1">
                  <p class="text-sm text-red-900 mb-1">
                    {m.oidc_correlation_hint()}
                  </p>
                  <code class="text-sm font-mono text-red-900 break-all select-all">
                    {oidcCorrelationId}
                  </code>
                </div>

                <!-- Copy to Clipboard Button -->
                <button
                  type="button"
                  class="p-2 rounded bg-red-50 text-red-800 hover:bg-red-100 hover:border hover:border-red-300 transition-colors flex-shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-900 focus-visible:ring-offset-2"
                  on:click={() => copyToClipboard(oidcCorrelationId)}
                  aria-label={copied ? m.copied_to_clipboard() : m.copy_correlation_id()}>
                  {#if copied}
                    <!-- Check Icon (copied state) -->
                    <svg class="w-5 h-5 text-green-800"
                         fill="none"
                         viewBox="0 0 24 24"
                         stroke="currentColor"
                         aria-hidden="true">
                      <path stroke-linecap="round"
                            stroke-linejoin="round"
                            stroke-width="2"
                            d="M5 13l4 4L19 7" />
                    </svg>
                  {:else}
                    <!-- Copy Icon (default state) -->
                    <svg class="w-5 h-5 text-red-900"
                         fill="none"
                         viewBox="0 0 24 24"
                         stroke="currentColor"
                         aria-hidden="true">
                      <path stroke-linecap="round"
                            stroke-linejoin="round"
                            stroke-width="2"
                            d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                  {/if}
                </button>
              </div>
            </div>
          {/if}
        </div>
      {/if}

      <div aria-live="polite">
        {#if message === "logout"}
          <div
            class="bg-positive-dimmer text-positive-default mb-2 flex flex-col gap-3 p-4 shadow-lg"
          >
            {m.logout_success()}
          </div>{/if}
        {#if message === "expired"}
          <div
            class="bg-warning-dimmer text-warning-default mb-2 flex flex-col gap-3 p-4 shadow-lg"
          >
            {m.session_expired_please_login_again()}
          </div>{/if}
        {#if message === "mobilityguard_login_error"}
          <div
            class="bg-negative-dimmer text-negative-default mb-2 flex flex-col gap-3 p-4 shadow-lg"
          >
            <strong>{m.authentication_failed()}</strong>
            {m.authentication_failed_details()}
            <ul class="mt-1 list-inside list-disc">
              <li>{m.invalid_credentials()}</li>
              <li>{m.account_restrictions()}</li>
              <li>{m.system_configuration_issues()}</li>
            </ul>
            {m.try_again_contact_admin()}
          </div>
        {:else if message === "mobilityguard_oauth_error"}
          <div
            class="bg-negative-dimmer text-negative-default mb-2 flex flex-col gap-3 p-4 shadow-lg"
          >
            <strong>{m.authentication_provider_error()}</strong>
            {m.authentication_service_error()}
          </div>
        {:else if message === "mobilityguard_access_denied"}
          <div
            class="bg-negative-dimmer text-negative-default mb-2 flex flex-col gap-3 p-4 shadow-lg"
          >
            <strong>{m.access_denied()}</strong>
            {m.access_denied_eneo()}
          </div>
        {:else if message === "mobilityguard_invalid_request"}
          <div
            class="bg-warning-dimmer text-warning-default mb-2 flex flex-col gap-3 p-4 shadow-lg"
          >
            <strong>{m.invalid_request()}</strong>
            {m.invalid_login_request()}
          </div>
        {:else if message === "no_code_received" || message === "no_state_received"}
          <div
            class="bg-warning-dimmer text-warning-default mb-2 flex flex-col gap-3 p-4 shadow-lg"
          >
            <strong>{m.login_process_interrupted()}</strong>
            {m.authentication_incomplete()}
          </div>
        {:else if message && message.includes("error")}
          <div
            class="bg-negative-dimmer text-negative-default mb-2 flex flex-col gap-3 p-4 shadow-lg"
          >
            <strong>{m.login_failed_general()}</strong>
            {m.authentication_error_occurred()}
          </div>
        {/if}
      </div>

      {#if !oidcErrorCode}
        <form
          method="POST"
          class="border-default bg-primary flex flex-col gap-3 p-4"
          action="?/login"
          use:enhance={() => {
            isAwaitingLoginResponse = true;

            return async ({ result }) => {
              if (result.type === "redirect") {
                goto(result.location);
              } else {
                isAwaitingLoginResponse = false;
                message = null;
                loginFailed = true;
              }
            };
          }}
        >
          <input type="text" hidden value={page.url.searchParams.get("next") ?? ""} name="next" />

          {#if loginFailed}
            <div class="label-negative bg-label-dimmer text-label-stronger rounded-lg p-4">
              {m.incorrect_credentials()}
            </div>
          {/if}

          {#if showUsernameAndPassword || (!data.mobilityguardLink && !data.singleTenantOidcLink)}
            <Input.Text
              label={m.email()}
              value=""
              name="email"
              autocomplete="username"
              type="email"
              required
              hiddenLabel={true}
              placeholder={m.email()}
            ></Input.Text>

            <Input.Text
              label={m.password()}
              value=""
              name="password"
              autocomplete="current-password"
              type="password"
              required
              hiddenLabel={true}
              placeholder={m.password()}
            ></Input.Text>

            <Button type="submit" disabled={isAwaitingLoginResponse} variant="primary">
              {#if isAwaitingLoginResponse}
                {m.logging_in()}
              {:else}
                {m.login()}
              {/if}
            </Button>
          {:else if data.singleTenantOidcLink}
            <Button variant="primary" href={data.singleTenantOidcLink}>{m.login()}</Button>
          {:else if data.mobilityguardLink}
            <Button variant="primary" href={data.mobilityguardLink}>{m.login()}</Button>
          {/if}
        </form>
      {/if}
    </div>
    <div class="absolute bottom-10 mt-12 flex justify-center">
      {#if showUsernameAndPassword && (data.mobilityguardLink || data.singleTenantOidcLink || oidcErrorCode)}
        <Button
          variant="outlined"
          class="bg-primary text-primary border-default hover:bg-hover-default"
          href="/login">
          {m.hide_login_fields()}
        </Button>
      {:else if data.mobilityguardLink || data.singleTenantOidcLink || oidcErrorCode}
        <Button
          variant="outlined"
          class="bg-primary text-primary border-default hover:bg-hover-default"
          href="/login?showUsernameAndPassword=true">
          {m.show_login_fields()}
        </Button>
      {/if}
    </div>
  </div>
{/if}

<style>
  form {
    box-shadow: 0px 8px 20px 4px rgba(0, 0, 0, 0.1);
    border: 0.5px solid rgba(54, 54, 54, 0.3);
  }
</style>
