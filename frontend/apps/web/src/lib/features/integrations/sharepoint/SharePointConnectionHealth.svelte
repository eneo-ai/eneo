<script lang="ts" module>
  export type HealthState = "ok" | "warning" | "error" | "unknown";

  /** The most severe of the checks, for a summary badge. */
  export function worstHealth(states: HealthState[]): HealthState {
    for (const level of ["error", "warning", "unknown"] as const) {
      if (states.includes(level)) return level;
    }
    return "ok";
  }
</script>

<script lang="ts">
  import Check from "@lucide/svelte/icons/check";
  import Circle from "@lucide/svelte/icons/circle";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import X from "@lucide/svelte/icons/x";
  import type { Eneo, components } from "@eneo/eneo-js";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { toast } from "$lib/components/toast";
  import { getErrorMessage, toastError } from "$lib/core/errors";
  import { formatDateTime } from "$lib/core/formatting/dateTime";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";
  import { classifyMicrosoftAuthError, getMicrosoftAuthGuidanceText } from "./microsoftAuthErrors";
  import { followServiceAccountSignIn } from "./serviceAccountAuth";

  type TenantSharePointAppPublic = components["schemas"]["TenantSharePointAppPublic"];
  type SharePointSubscription = components["schemas"]["SharePointSubscriptionPublic"];
  type TenantAppTestResult = components["schemas"]["TenantAppTestResult"];

  interface Props {
    eneo: Eneo;
    config: TenantSharePointAppPublic;
    subscriptionsOpen: boolean;
    onEdit: () => void;
    onToggleSubscriptions: () => void;
    /** Reload the app config; a test records its outcome as the credential health. */
    onConfigChanged: () => void | Promise<void>;
  }

  let { eneo, config, subscriptionsOpen, onEdit, onToggleSubscriptions, onConfigChanged }: Props =
    $props();

  // --- Sign-in ---

  let signInState = $derived<HealthState>(
    config.auth_status === "ok" ? "ok" : config.auth_status === "error" ? "error" : "unknown"
  );
  let guidance = $derived(classifyMicrosoftAuthError(config.last_auth_error));
  let isServiceAccount = $derived(config.auth_method === "service_account");

  const reauth = createAsyncState(async () => {
    try {
      followServiceAccountSignIn(
        await eneo.integrations.admin.sharepoint.restartServiceAccountAuth()
      );
    } catch (error) {
      toastError(error);
    }
  });

  // --- Change notifications ---

  let subscriptions = $state<SharePointSubscription[] | null>(null);

  const loadSubscriptions = createAsyncState(async () => {
    try {
      const response = await eneo.integrations.admin.sharepoint.listSubscriptions();
      subscriptions = Array.isArray(response) ? response : [];
    } catch {
      subscriptions = null;
    }
  });

  $effect(() => {
    loadSubscriptions();
  });

  let expired = $derived(subscriptions?.filter((s) => s.is_expired).length ?? 0);
  let failing = $derived(
    subscriptions?.filter((s) => !s.is_expired && (s.consecutive_renewal_failures ?? 0) > 0)
      .length ?? 0
  );
  let active = $derived((subscriptions?.length ?? 0) - expired - failing);
  let watchState = $derived<HealthState>(
    subscriptions === null || subscriptions.length === 0
      ? "unknown"
      : expired + failing > 0
        ? "warning"
        : "ok"
  );

  const renewExpired = createAsyncState(async () => {
    try {
      const result = await eneo.integrations.admin.sharepoint.renewExpiredSubscriptions();
      if ((result.failed ?? 0) > 0) {
        toast.error(
          m.sharepoint_subscriptions_renewed_partial({
            failed: result.failed ?? 0,
            errors: (result.errors ?? []).join(", ")
          })
        );
      } else {
        toast.success(m.sharepoint_subscriptions_renewed_success({ count: result.recreated ?? 0 }));
      }
    } catch (error) {
      toastError(error, m.sharepoint_subscriptions_renew_error());
    }
    await loadSubscriptions();
  });

  // --- Connection test ---

  let testResult = $state<TenantAppTestResult | null>(null);
  let testState = $derived<HealthState>(
    testResult === null ? "unknown" : testResult.success ? "ok" : "error"
  );

  const runTest = createAsyncState(async () => {
    testResult = null;
    try {
      testResult = await eneo.integrations.admin.sharepoint.testStoredConnection();
    } catch (error) {
      testResult = { success: false, error_message: getErrorMessage(error) };
    }
    await onConfigChanged();
  });

  let overall = $derived(worstHealth([signInState, watchState]));

  const stateStyles: Record<HealthState, string> = {
    ok: "bg-positive-dimmer text-positive-stronger",
    warning: "bg-warning-dimmer text-warning-stronger",
    error: "bg-negative-dimmer text-negative-stronger",
    unknown: "bg-secondary text-secondary"
  };

  function stateLabel(state: HealthState): string {
    switch (state) {
      case "ok":
        return m.sharepoint_health_state_ok();
      case "warning":
        return m.sharepoint_health_state_warning();
      case "error":
        return m.sharepoint_health_state_error();
      case "unknown":
        return m.sharepoint_health_state_unknown();
    }
  }

  function time(value: string | null | undefined): string {
    return value ? formatDateTime(value) : "";
  }
</script>

{#snippet stateIcon(state: HealthState)}
  <span
    class="flex size-7 shrink-0 items-center justify-center rounded-full {stateStyles[state]}"
    aria-hidden="true"
  >
    {#if state === "ok"}
      <Check class="size-3.5" />
    {:else if state === "error"}
      <X class="size-3.5" />
    {:else if state === "warning"}
      <TriangleAlert class="size-3.5" />
    {:else}
      <Circle class="size-3" />
    {/if}
  </span>
  <span class="sr-only">{stateLabel(state)}:</span>
{/snippet}

<section aria-labelledby="sharepoint-health-heading" class="border-default rounded-lg border">
  <div class="border-default flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
    <h3 id="sharepoint-health-heading" class="font-semibold">{m.sharepoint_health_heading()}</h3>
    <Badge variant="secondary" class="border-transparent {stateStyles[overall]}">
      {overall === "ok" ? m.sharepoint_health_overall_ok() : stateLabel(overall)}
    </Badge>
  </div>
  <ol class="flex flex-col">
    <li class="border-default flex flex-wrap items-start gap-3 border-b px-4 py-4">
      {@render stateIcon("ok")}
      <div class="flex min-w-0 flex-[1_1_18rem] flex-col gap-0.5">
        <p class="font-medium">{m.sharepoint_health_app_title()}</p>
        <p class="text-secondary text-sm break-words">
          {m.sharepoint_health_app_description({
            domain: config.tenant_domain,
            client: config.client_id.slice(-4)
          })}
        </p>
        {#if isServiceAccount && config.service_account_email}
          <p class="text-secondary text-sm">
            {m.sharepoint_health_service_account({ email: config.service_account_email })}
          </p>
        {/if}
      </div>
      <Button variant="outline" size="sm" onclick={onEdit}>{m.sharepoint_health_edit()}</Button>
    </li>

    <li
      class="border-default flex flex-wrap items-start gap-3 border-b px-4 py-4 {signInState ===
      'error'
        ? 'bg-negative-dimmer/30'
        : ''}"
    >
      {@render stateIcon(signInState)}
      <div class="flex min-w-0 flex-[1_1_18rem] flex-col gap-1">
        <p class="font-medium">{m.sharepoint_health_sign_in_title()}</p>
        {#if signInState === "error"}
          <p class="text-sm">
            {guidance
              ? getMicrosoftAuthGuidanceText(guidance)
              : m.sharepoint_health_sign_in_error({ time: time(config.last_auth_error_at) })}
          </p>
          <p class="text-secondary text-sm">{m.sharepoint_health_sign_in_impact()}</p>
          {#if config.last_auth_error}
            <details class="text-secondary text-xs">
              <summary class="cursor-pointer">{m.sharepoint_auth_error_details()}</summary>
              <p class="mt-1 font-mono break-words">{config.last_auth_error}</p>
            </details>
          {/if}
        {:else if signInState === "ok"}
          <p class="text-secondary text-sm">
            {m.sharepoint_auth_last_success({ time: time(config.last_auth_success_at) })}
          </p>
        {:else}
          <p class="text-secondary text-sm">{m.sharepoint_health_sign_in_unknown()}</p>
        {/if}
      </div>
      {#if signInState === "error"}
        {#if isServiceAccount}
          <Button size="sm" disabled={reauth.isLoading} onclick={reauth}>
            {reauth.isLoading ? m.redirecting() : m.sharepoint_reauth_with_microsoft()}
          </Button>
        {:else}
          <Button size="sm" onclick={onEdit}>{m.update_configuration()}</Button>
        {/if}
      {/if}
    </li>

    <li class="border-default flex flex-wrap items-start gap-3 border-b px-4 py-4">
      {@render stateIcon(watchState)}
      <div class="flex min-w-0 flex-[1_1_18rem] flex-col gap-0.5">
        <p class="font-medium">{m.sharepoint_health_watch_title()}</p>
        <p class="text-secondary text-sm">
          {#if subscriptions === null && loadSubscriptions.isLoading}
            {m.loading()}
          {:else if subscriptions === null}
            {m.sharepoint_subscriptions_load_error()}
          {:else if subscriptions.length === 0}
            {m.sharepoint_health_watch_none()}
          {:else if expired + failing === 0}
            {m.sharepoint_health_watch_ok({ count: active })}
          {:else}
            {m.sharepoint_health_watch_issues({
              active,
              total: subscriptions.length,
              expired,
              failing
            })}
          {/if}
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        {#if expired > 0}
          <Button
            variant="outline"
            size="sm"
            disabled={renewExpired.isLoading}
            aria-busy={renewExpired.isLoading}
            onclick={renewExpired}
          >
            {m.sharepoint_health_watch_renew()}
          </Button>
        {/if}
        <Button
          variant="ghost"
          size="sm"
          aria-expanded={subscriptionsOpen}
          onclick={onToggleSubscriptions}
        >
          {subscriptionsOpen ? m.sharepoint_health_watch_hide() : m.sharepoint_health_watch_show()}
        </Button>
      </div>
    </li>

    <li class="flex flex-wrap items-start gap-3 px-4 py-4">
      {@render stateIcon(testState)}
      <div class="flex min-w-0 flex-[1_1_18rem] flex-col gap-0.5" aria-live="polite">
        <p class="font-medium">{m.sharepoint_health_test_title()}</p>
        <p class="text-secondary text-sm break-words">
          {#if runTest.isLoading}
            {m.sharepoint_health_test_running()}
          {:else if testResult?.success}
            {m.sharepoint_health_test_ok()}
          {:else if testResult}
            {testResult.error_message ?? m.sharepoint_health_state_error()}
          {:else}
            {m.sharepoint_health_test_description()}
          {/if}
        </p>
      </div>
      <Button
        variant="outline"
        size="sm"
        disabled={runTest.isLoading}
        aria-busy={runTest.isLoading}
        onclick={runTest}
      >
        {#if runTest.isLoading}
          <IconLoadingSpinner size="sm" class="animate-spin" />
        {/if}
        {m.sharepoint_health_test_run()}
      </Button>
    </li>
  </ol>
</section>
