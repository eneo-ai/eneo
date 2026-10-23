<script lang="ts">
  import { page } from "$app/state";
  import { deserialize, enhance } from "$app/forms";
  import { goto } from "$app/navigation";
  import { browser } from "$app/environment";
  import { onMount, tick } from "svelte";
  import { prefersReducedMotion } from "svelte/motion";
  import { fade } from "svelte/transition";
  import { SvelteURLSearchParams } from "svelte/reactivity";
  import { ArrowLeft } from "@lucide/svelte";
  import { Button } from "$lib/components/ui/button";
  import * as Field from "$lib/components/ui/field";
  import { Input } from "$lib/components/ui/input";
  import { LoadingScreen } from "$lib/components/layout";
  import AuthAlert from "$lib/features/auth/components/AuthAlert.svelte";
  import AuthPageShell from "$lib/features/auth/components/AuthPageShell.svelte";
  import CorrelationReference from "$lib/features/auth/components/CorrelationReference.svelte";
  import LoginStatusAlert from "$lib/features/auth/components/LoginStatusAlert.svelte";
  import PasswordInput from "$lib/features/auth/components/PasswordInput.svelte";
  import TenantSelector from "$lib/features/auth/components/TenantSelector.svelte";
  import type { EneoLoginFailureReason } from "$lib/features/auth/eneo.server";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

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
    "oidc_unauthorized",
    "oidc_invalid_request",
    "oidc_attempt_rejected",
    "oidc_oauth_error",
    "oidc_access_denied",
    "oidc_unauthorized_client",
    "oidc_server_error",
    "oidc_temporarily_unavailable"
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

    if (rawTenant && tenantFederationEnabled) {
      activeTenantSlug = rawTenant;
    }
  });

  const LAST_TENANT_KEY = "eneo-last-tenant-slug";
  const TENANT_SELECTOR_CACHE_KEY = "eneo:last-tenant";

  let loginFailed = $state(false);
  // Survives the loading-view swap so a typo in the password doesn't cost the email too.
  let email = $state("");
  let upLoginCorrelationId = $state<string | null>(null);
  let loginAttemptsRemaining = $state<number | null>(null);
  let loginRetryAfterSeconds = $state<number | null>(null);
  let loginFailureReason = $state<EneoLoginFailureReason>("credentials");
  const loginRetryAfterMinutes = $derived(
    loginRetryAfterSeconds === null ? null : Math.max(1, Math.ceil(loginRetryAfterSeconds / 60))
  );
  let loginErrorAlert = $state<HTMLDivElement | null>(null);
  let isAwaitingLoginResponse = $state(false);
  let showTenantSelector = $state(false);
  let federationError = $state<string | null>(null);
  let preloadedTenants = $state<TenantInfo[]>([]);
  let isInitializing = $state(true);
  let showSlowLoadingWarning = $state(false);
  let loadingTimeoutId: number | null = null;
  let isSubmittingUPLogin = $state(false);

  let showUsernameAndPassword = $derived(page.url?.searchParams.get("showUsernameAndPassword"));
  let tenantFederationEnabled = $derived(
    Boolean(data.featureFlags?.federationStatus?.has_multi_tenant_federation)
  );
  const fadeDuration = $derived(prefersReducedMotion.current ? 0 : 200);

  // Check if user explicitly wants to see login form (e.g., after logout)
  const hasQueryParams = $derived(
    message !== null ||
      oidcErrorCode !== null ||
      showUsernameAndPassword !== null ||
      page.url.searchParams.get("tenant") !== null ||
      activeTenantSlug !== null
  );

  const hasExternalLogin = $derived(
    Boolean(data.mobilityguardLink || data.hasSingleTenantOidc || oidcErrorCode)
  );
  const showCredentialsForm = $derived(
    Boolean(showUsernameAndPassword) ||
      federationError !== null ||
      (!data.mobilityguardLink && !data.hasSingleTenantOidc)
  );

  // Determine which loading message to display
  let loadingMessage = $derived.by(() => {
    // Check for OIDC error directly from URL (don't wait for $effect to set oidcErrorCode)
    const urlMessage = page.url.searchParams.get("message");
    const hasOidcErrorInUrl = urlMessage && OIDC_ERROR_CODES.has(urlMessage);

    if (isSubmittingUPLogin) {
      return m.logging_in();
    }
    if (hasOidcErrorInUrl && isInitializing) {
      return m.loading_error_details();
    }
    // Hide loading message during tenant login flow (activeTenantSlug means we're in tenant flow)
    if (isAwaitingLoginResponse && !activeTenantSlug) {
      return m.redirecting_to_authentication();
    }
    if (isInitializing && tenantFederationEnabled && !activeTenantSlug) {
      return m.loading_organizations();
    }
    if ((data.zitadelLink || data.hasSingleTenantOidc) && !hasQueryParams) {
      return m.redirecting_to_authentication();
    }
    return undefined;
  });

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

  // Handle automatic redirects reactively. Named so tests can run the effect
  // itself instead of relying on declaration order.
  function redirectToExternalLogin() {
    if (!browser) return;
    if (showTenantSelector) return;
    if (isAwaitingLoginResponse || federationError) return;

    // We don't redirect on the server so we can render a loader/spinner during the redirection period
    if (data.zitadelLink && !hasQueryParams) {
      isInitializing = true; // Keep showing loader during redirect
      window.location.href = data.zitadelLink;
      return;
    }

    // Single-tenant OIDC: redirect to IdP immediately (unless user wants to see login form)
    if (data.hasSingleTenantOidc && !hasQueryParams) {
      void beginOidcLogin();
    }
  }
  $effect(redirectToExternalLogin);

  // Check for tenant-based federation on mount
  onMount(async () => {
    if (!browser) return;
    if (!tenantFederationEnabled) {
      isInitializing = false;
      return;
    }

    if (activeTenantSlug) {
      sessionStorage.setItem(LAST_TENANT_KEY, activeTenantSlug);
    } else {
      const remembered = sessionStorage.getItem(LAST_TENANT_KEY);
      if (remembered) {
        activeTenantSlug = remembered;
      }
    }

    const urlParams = new URLSearchParams(window.location.search);
    const explicitTenantParam = urlParams.get("tenant");

    // EARLY EXIT: Only skip initialization when we're already on the username/password form
    // without an explicit tenant slug in the URL (prevents flashing when user opted out of SSO)
    if (activeTenantSlug && !showTenantSelector && !explicitTenantParam) {
      isInitializing = false;
      return;
    }

    if (showUsernameAndPassword) {
      isInitializing = false;
      return;
    }

    const tenant = explicitTenantParam ?? activeTenantSlug;

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
      const success = await beginOidcLogin(tenant);
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

  async function replaceQueryParams(remove: string[]) {
    const params = new SvelteURLSearchParams(window.location.search);
    for (const key of remove) {
      params.delete(key);
    }
    const query = params.toString();
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic URL built from window.location
    await goto(`${window.location.pathname}${query ? `?${query}` : ""}`, {
      replaceState: true,
      noScroll: true
    });
  }

  async function clearOidcErrorFromUrl() {
    if (!browser) return;
    await replaceQueryParams(["message", "detailCode", "correlation", "rawDetail"]);
  }

  async function beginOidcLogin(slug?: string): Promise<boolean> {
    if (isAwaitingLoginResponse) return false;
    isAwaitingLoginResponse = true;
    const tenantSlug = tenantFederationEnabled ? slug : undefined;
    try {
      if (tenantSlug) rememberTenant(tenantSlug);
      federationError = null;
      await clearOidcErrorFromUrl();
      showTenantSelector = false;
      const form = new FormData();
      const next = page.url.searchParams.get("next");
      if (next !== null) form.set("next", next);
      if (tenantSlug) form.set("tenant", tenantSlug);
      const response = await fetch("?/oidc", {
        method: "POST",
        headers: { Accept: "application/json", "x-sveltekit-action": "true" },
        body: form
      });
      const result = deserialize(await response.text());
      if (result.type !== "redirect") throw new Error("OIDC initiation failed");

      // Allow natural browser history navigation - back button returns to tenant selector
      window.location.href = result.location;
      return true;
    } catch (err) {
      console.error("Failed to initiate OIDC authentication:", err);
      federationError = m.failed_to_start_authentication();
      isAwaitingLoginResponse = false;
      isInitializing = false;
      showTenantSelector = preloadedTenants.length > 0;
      return false;
    }
  }

  async function handleTenantSelect(slug: string) {
    await beginOidcLogin(slug);
  }

  async function loadTenantsAndMaybeShow({ forceShow = false }: { forceShow?: boolean } = {}) {
    try {
      const { eneo } = await import("$lib/api/client");
      const response = await eneo.auth.listTenants();
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
    if (!activeTenantSlug && !data.hasSingleTenantOidc) {
      await loadTenantsAndMaybeShow({ forceShow: true });
      return;
    }

    await beginOidcLogin(tenantFederationEnabled ? (activeTenantSlug ?? undefined) : undefined);
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
      await replaceQueryParams(["message", "detailCode", "correlation", "rawDetail", "tenant"]);
    }

    await loadTenantsAndMaybeShow({ forceShow: true });
  }

  function getOidcErrorMessage(): string {
    if (oidcErrorCode === "oidc_attempt_rejected") {
      return m.oidc_error_attempt_rejected();
    }
    if (oidcErrorDetailCode === "access_denied") {
      return m.oidc_error_forbidden();
    }
    if (oidcErrorDetailCode === "unauthorized") {
      return m.oidc_error_unauthorized();
    }
    return m.oidc_error_generic();
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.login()}</title>
</svelte:head>

{#if isInitializing || isAwaitingLoginResponse || isSubmittingUPLogin}
  <!-- Overlays the page so the outgoing loader doesn't push the incoming view down mid-fade. -->
  <div class="absolute inset-0" transition:fade={{ duration: fadeDuration }}>
    <LoadingScreen message={loadingMessage} />

    {#if showSlowLoadingWarning}
      <div class="absolute inset-x-0 bottom-8 flex flex-col items-center gap-3 px-4">
        <AuthAlert tone="warning" class="max-w-md">
          <p>{m.connection_slow_warning()}</p>
        </AuthAlert>
        <Button variant="outline" onclick={() => window.location.reload()}>
          {m.retry()}
        </Button>
      </div>
    {/if}
  </div>
{:else if showTenantSelector}
  <div transition:fade={{ duration: fadeDuration }}>
    <AuthPageShell title={m.select_your_organization()} size="md">
      {#if federationError}
        <AuthAlert tone="error" title={m.authentication_failed()}>
          <p>{federationError}</p>
        </AuthAlert>
      {/if}

      <TenantSelector onTenantSelect={handleTenantSelect} tenants={preloadedTenants} />
    </AuthPageShell>
  </div>
{:else}
  <div transition:fade={{ duration: fadeDuration }}>
    <AuthPageShell
      title={m.login()}
      description={oidcErrorCode ? undefined : m.login_description()}
    >
      {#if tenantFederationEnabled && activeTenantSlug}
        <Button variant="link" class="h-auto self-start p-0" onclick={chooseAnotherTenant}>
          <ArrowLeft aria-hidden="true" />
          {m.oidc_choose_another_org()}
        </Button>
      {/if}

      {#if oidcErrorCode}
        <AuthAlert tone="error" title={m.failed_to_login()}>
          <p>{getOidcErrorMessage()}</p>
          {#if !oidcErrorDetailCode && oidcRawDetail}
            <p class="text-xs">{m.oidc_error_detail({ detail: oidcRawDetail })}</p>
          {/if}
          {#if oidcCorrelationId}
            <CorrelationReference correlationId={oidcCorrelationId} />
          {/if}
        </AuthAlert>

        <div class="flex flex-col gap-2">
          {#if activeTenantSlug || data.hasSingleTenantOidc}
            <Button
              type="button"
              size="lg"
              class="w-full"
              disabled={isAwaitingLoginResponse}
              onclick={retryTenantLogin}
            >
              {#if isAwaitingLoginResponse}
                {m.redirecting_to_authentication()}
              {:else}
                {m.oidc_retry_login()}
              {/if}
            </Button>
          {/if}
          {#if tenantFederationEnabled}
            <Button
              type="button"
              variant="outline"
              size="lg"
              class="w-full"
              onclick={chooseAnotherTenant}
            >
              {m.oidc_choose_another_org()}
            </Button>
          {/if}
        </div>
      {:else}
        <LoginStatusAlert {message} />

        {#if federationError}
          <AuthAlert tone="error" title={m.failed_to_login()}>
            <p>{federationError}</p>
          </AuthAlert>
          {#if data.hasSingleTenantOidc}
            <Button type="button" size="lg" class="w-full" onclick={() => beginOidcLogin()}>
              {m.oidc_retry_login()}
            </Button>
          {/if}
        {/if}

        <form
          method="POST"
          class="flex flex-col gap-4"
          action="?/login"
          use:enhance={() => {
            isSubmittingUPLogin = true;
            loginFailed = false;
            upLoginCorrelationId = null;
            loginAttemptsRemaining = null;
            loginRetryAfterSeconds = null;
            loginFailureReason = "credentials";

            return async ({ result }) => {
              if (result.type === "redirect") {
                // eslint-disable-next-line svelte/no-navigation-without-resolve -- redirect location from server form action
                await goto(result.location);
                return;
              }

              isSubmittingUPLogin = false;
              message = null;
              loginFailed = true;
              // Capture correlation ID from form action result
              if (result.type === "failure" && result.data) {
                upLoginCorrelationId = (result.data.correlationId as string) || null;
                loginAttemptsRemaining = (result.data.attemptsRemaining as number | null) ?? null;
                loginRetryAfterSeconds = (result.data.retryAfterSeconds as number | null) ?? null;
                loginFailureReason =
                  (result.data.reason as EneoLoginFailureReason | undefined) ?? "credentials";
              }
              await tick();
              loginErrorAlert?.focus();
            };
          }}
        >
          <input type="hidden" name="next" value={page.url.searchParams.get("next") ?? ""} />

          {#if loginFailed}
            <AuthAlert tone="error" id="login-error" tabindex={-1} bind:ref={loginErrorAlert}>
              {#if loginFailureReason === "unavailable"}
                <p>{m.login_unavailable()}</p>
              {:else if loginAttemptsRemaining === 0 && loginRetryAfterMinutes !== null}
                <p>{m.login_too_many_attempts({ minutes: loginRetryAfterMinutes })}</p>
              {:else}
                <p>{m.incorrect_credentials()}</p>
                {#if loginAttemptsRemaining !== null}
                  <p>{m.login_attempts_remaining({ count: loginAttemptsRemaining })}</p>
                {/if}
              {/if}
              {#if upLoginCorrelationId}
                <CorrelationReference correlationId={upLoginCorrelationId} />
              {/if}
            </AuthAlert>
          {/if}

          {#if showCredentialsForm}
            <Field.Group class="gap-4">
              <Field.Field>
                <Field.Label for="login-email">{m.email()}</Field.Label>
                <Input
                  id="login-email"
                  name="email"
                  bind:value={email}
                  type="email"
                  autocomplete="username"
                  required
                  class="h-10"
                  aria-describedby={loginFailed ? "login-error" : undefined}
                />
              </Field.Field>

              <Field.Field>
                <Field.Label for="login-password">{m.password()}</Field.Label>
                <PasswordInput
                  id="login-password"
                  name="password"
                  autocomplete="current-password"
                  required
                  class="h-10"
                  aria-describedby={loginFailed ? "login-error" : undefined}
                />
              </Field.Field>
            </Field.Group>

            <Button type="submit" size="lg" class="w-full" disabled={isSubmittingUPLogin}>
              {#if isSubmittingUPLogin}
                {m.logging_in()}
              {:else}
                {m.login()}
              {/if}
            </Button>
          {:else if data.hasSingleTenantOidc}
            <Button type="button" size="lg" class="w-full" onclick={() => beginOidcLogin()}
              >{m.login()}</Button
            >
          {:else if data.mobilityguardLink}
            <Button size="lg" class="w-full" href={data.mobilityguardLink}>{m.login()}</Button>
          {/if}
        </form>
      {/if}

      {#snippet footer()}
        {#if hasExternalLogin}
          {#if showUsernameAndPassword}
            <Button variant="link" href={localizeHref("/login")}>{m.hide_login_fields()}</Button>
          {:else}
            <Button variant="link" href={localizeHref("/login?showUsernameAndPassword=true")}>
              {m.show_login_fields()}
            </Button>
          {/if}
        {/if}
      {/snippet}
    </AuthPageShell>
  </div>
{/if}
