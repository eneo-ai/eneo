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

  const { data } = $props();

  let loginFailed = $state(false);
  let isAwaitingLoginResponse = $state(false);
  let showTenantSelector = $state(false);
  let federationError = $state<string | null>(null);

  let message = $derived(page.url.searchParams.get("message") ?? null);
  let showUsernameAndPassword = $derived(page.url?.searchParams.get("showUsernameAndPassword"));

  // We don't redirect on the server so we can render a loader/spinner during the redirection period
  if (data.zitadelLink && browser) {
    window.location.href = data.zitadelLink;
  }

  // Check for tenant-based federation on mount
  onMount(async () => {
    if (!browser) return;

    const urlParams = new URLSearchParams(window.location.search);
    const tenant = urlParams.get("tenant");

    // If tenant parameter exists, initiate federated auth
    if (tenant && /^[a-z0-9-]+$/.test(tenant)) {
      try {
        // Dynamic import to avoid SSR issues
        const { intric } = await import("$lib/api/client");

        const redirectUri = `${window.location.origin}/auth/callback`;
        const response = await intric.auth.initiateAuth({ tenant, redirectUri });

        // Redirect to IdP
        window.location.href = response.authorization_url;
      } catch (err) {
        console.error("Failed to initiate federation auth:", err);
        federationError = m.failed_to_start_authentication();
        showTenantSelector = false;
      }
    } else if (!data.zitadelLink && !data.mobilityguardLink) {
      // No existing auth methods - show tenant selector
      showTenantSelector = true;
    }
  });

  async function handleTenantSelect(slug: string) {
    try {
      federationError = null;

      // Dynamic import to avoid SSR issues
      const { intric } = await import("$lib/api/client");

      const redirectUri = `${window.location.origin}/auth/callback`;
      const response = await intric.auth.initiateAuth({ tenant: slug, redirectUri });

      // Redirect to IdP
      window.location.href = response.authorization_url;
    } catch (err) {
      console.error("Failed to initiate federation auth:", err);
      federationError = m.failed_to_start_authentication();
    }
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.login()}</title>
</svelte:head>

{#if data.zitadelLink}
  <LoadingScreen />
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

      <TenantSelector onTenantSelect={handleTenantSelect} baseUrl={window.location.origin} />
    </div>
  </div>
{:else}
  <div class="relative flex h-[100vh] w-[100vw] items-center justify-center">
    <div class="box w-[400px] justify-center">
      <h1 class="flex justify-center">
        <IntricWordMark class="text-brand-intric h-16 w-24" />
        <span class="sr-only">{m.app_name()}</span>
      </h1>

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

        {#if showUsernameAndPassword || !data.mobilityguardLink}
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
        {:else}
          <Button variant="primary" href={data.mobilityguardLink}>{m.login()}</Button>
        {/if}
      </form>
    </div>
    <div class="absolute bottom-10 mt-12 flex justify-center">
      {#if showUsernameAndPassword && data.mobilityguardLink}
        <Button variant="outlined" class="text-secondary" href="/login?"
          >{m.hide_login_fields()}</Button
        >
      {:else if data.mobilityguardLink}
        <Button
          variant="outlined"
          class="text-secondary"
          href="/login?showUsernameAndPassword=true"
        >
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
