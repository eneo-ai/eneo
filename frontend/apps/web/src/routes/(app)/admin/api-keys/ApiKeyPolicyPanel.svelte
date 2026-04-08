<script lang="ts">
  import { onMount } from "svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import type { ApiKeyPolicy } from "@intric/intric-js";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  import {
    Calendar,
    Clock,
    Gauge,
    Layers,
    Link,
    AlertCircle,
    Check,
    RotateCcw
  } from "lucide-svelte";
  import { fly } from "svelte/transition";

  const intric = getIntric();

  let loading = $state(false);
  let saving = $state(false);
  let errorMessage = $state<string | null>(null);
  let successMessage = $state<string | null>(null);

  let originalPolicy = $state<ApiKeyPolicy>({});

  let maxDelegationDepth = $state<number | null>(null);
  let maxExpirationDays = $state<number | null>(null);
  let autoExpireUnusedDays = $state<number | null>(null);
  let maxRateLimitOverride = $state<number | null>(null);
  let requireExpiration = $state(false);
  let revocationCascadeEnabled = $state(false);

  function syncFromPolicy(policy: ApiKeyPolicy) {
    maxDelegationDepth = policy.max_delegation_depth ?? null;
    maxExpirationDays = policy.max_expiration_days ?? null;
    autoExpireUnusedDays = policy.auto_expire_unused_days ?? null;
    maxRateLimitOverride = policy.max_rate_limit_override ?? null;
    requireExpiration = policy.require_expiration ?? false;
    revocationCascadeEnabled = policy.revocation_cascade_enabled ?? false;
  }

  function snapshot() {
    return {
      max_delegation_depth: maxDelegationDepth,
      max_expiration_days: maxExpirationDays,
      auto_expire_unused_days: autoExpireUnusedDays,
      max_rate_limit_override: maxRateLimitOverride,
      require_expiration: requireExpiration,
      revocation_cascade_enabled: revocationCascadeEnabled
    };
  }

  function originalSnapshot() {
    return {
      max_delegation_depth: originalPolicy.max_delegation_depth ?? null,
      max_expiration_days: originalPolicy.max_expiration_days ?? null,
      auto_expire_unused_days: originalPolicy.auto_expire_unused_days ?? null,
      max_rate_limit_override: originalPolicy.max_rate_limit_override ?? null,
      require_expiration: originalPolicy.require_expiration ?? false,
      revocation_cascade_enabled: originalPolicy.revocation_cascade_enabled ?? false
    };
  }

  const hasChanges = $derived(JSON.stringify(snapshot()) !== JSON.stringify(originalSnapshot()));

  async function loadPolicy() {
    loading = true;
    errorMessage = null;
    try {
      const policy = await intric.apiKeys.admin.getPolicy();
      originalPolicy = policy;
      syncFromPolicy(policy);
    } catch (error) {
      console.error(error);
      errorMessage = getErrorMessage(error);
    } finally {
      loading = false;
    }
  }

  async function savePolicy() {
    errorMessage = null;
    successMessage = null;
    const current = snapshot();
    const original = originalSnapshot();

    const updates: Partial<ApiKeyPolicy> = {};
    if (current.max_delegation_depth !== original.max_delegation_depth) {
      updates.max_delegation_depth = current.max_delegation_depth;
    }
    if (current.max_expiration_days !== original.max_expiration_days) {
      updates.max_expiration_days = current.max_expiration_days;
    }
    if (current.auto_expire_unused_days !== original.auto_expire_unused_days) {
      updates.auto_expire_unused_days = current.auto_expire_unused_days;
    }
    if (current.max_rate_limit_override !== original.max_rate_limit_override) {
      updates.max_rate_limit_override = current.max_rate_limit_override;
    }
    if (current.require_expiration !== original.require_expiration) {
      updates.require_expiration = current.require_expiration;
    }
    if (current.revocation_cascade_enabled !== original.revocation_cascade_enabled) {
      updates.revocation_cascade_enabled = current.revocation_cascade_enabled;
    }

    saving = true;
    try {
      const policy = await intric.apiKeys.admin.updatePolicy(updates);
      originalPolicy = policy;
      syncFromPolicy(policy);
      successMessage = m.api_keys_admin_policy_updated();
      setTimeout(() => (successMessage = null), 3000);
    } catch (error) {
      console.error(error);
      errorMessage = getErrorMessage(error);
    } finally {
      saving = false;
    }
  }

  function resetPolicy() {
    syncFromPolicy(originalPolicy);
    errorMessage = null;
    successMessage = null;
  }

  onMount(() => {
    void loadPolicy();
  });

  // Policy items configuration
  const policyItems = $derived([
    {
      id: "requireExpiration",
      title: m.api_keys_admin_policy_require_expiration(),
      description: m.api_keys_admin_policy_require_expiration_desc(),
      icon: Calendar,
      type: "toggle" as const
    },
    {
      id: "maxExpirationDays",
      title: m.api_keys_admin_policy_max_expiration(),
      description: m.api_keys_admin_policy_max_expiration_desc(),
      icon: Clock,
      type: "number" as const,
      placeholder: m.api_keys_admin_policy_placeholder_no_limit(),
      suffix: m.api_keys_admin_policy_suffix_days()
    },
    {
      id: "autoExpireUnusedDays",
      title: m.api_keys_admin_policy_auto_expire(),
      description: m.api_keys_admin_policy_auto_expire_desc(),
      icon: Clock,
      type: "number" as const,
      placeholder: m.api_keys_admin_policy_placeholder_disabled(),
      suffix: m.api_keys_admin_policy_suffix_days()
    },
    {
      id: "maxRateLimitOverride",
      title: m.api_keys_admin_policy_max_rate_limit(),
      description: m.api_keys_admin_policy_max_rate_limit_desc(),
      icon: Gauge,
      type: "number" as const,
      placeholder: m.api_keys_admin_policy_placeholder_no_limit(),
      suffix: m.api_keys_admin_policy_suffix_req_hr()
    },
    {
      id: "maxDelegationDepth",
      title: m.api_keys_admin_policy_max_delegation(),
      description: m.api_keys_admin_policy_max_delegation_desc(),
      icon: Layers,
      type: "number" as const,
      placeholder: m.api_keys_admin_policy_placeholder_no_limit(),
      suffix: m.api_keys_admin_policy_suffix_levels()
    },
    {
      id: "revocationCascadeEnabled",
      title: m.api_keys_admin_policy_revocation_cascade(),
      description: m.api_keys_admin_policy_revocation_cascade_desc(),
      icon: Link,
      type: "toggle" as const
    }
  ]);
</script>

<div class="space-y-4">
  <!-- Messages -->
  {#if errorMessage}
    <div transition:fly={{ y: -8, duration: 150 }}>
      <Alert.Root variant="destructive">
        <AlertCircle />
        <Alert.Description>{errorMessage}</Alert.Description>
      </Alert.Root>
    </div>
  {/if}

  {#if successMessage}
    <div
      class="border-positive-default/40 bg-positive-default/10 flex items-center gap-3 rounded-lg border px-4 py-3"
      transition:fly={{ y: -8, duration: 150 }}
    >
      <Check class="text-positive-stronger h-4 w-4 flex-shrink-0" />
      <p class="text-positive-stronger text-sm">{successMessage}</p>
    </div>
  {/if}

  {#if loading}
    <div class="space-y-4">
      {#each Array(6) as _, i (i)}
        <div class="border-default bg-subtle/50 rounded-lg border p-4">
          <div class="flex items-center gap-4">
            <Skeleton class="h-10 w-10 rounded-lg" />
            <div class="flex-1 space-y-2">
              <Skeleton class="h-4 w-32" />
              <Skeleton class="h-3 w-48" />
            </div>
            <Skeleton class="h-6 w-12" />
          </div>
        </div>
      {/each}
    </div>
  {:else}
    <!-- Policy Items -->
    <div class="space-y-3">
      {#each policyItems as item (item.id)}
        {@const PolicyIcon = item.icon}
        <div
          class="border-default bg-subtle/30 hover:bg-subtle/50 rounded-lg border p-4 transition-colors"
        >
          <div class="flex items-center justify-between gap-4">
            <div class="flex items-center gap-4">
              <div
                class="bg-primary border-default flex h-10 w-10 items-center justify-center rounded-lg border"
              >
                <PolicyIcon class="text-muted h-5 w-5" />
              </div>
              <div>
                <h4 class="text-default text-sm font-semibold">{item.title}</h4>
                <p class="text-muted mt-0.5 max-w-md text-xs">{item.description}</p>
              </div>
            </div>

            <div class="flex-shrink-0">
              {#if item.type === "toggle"}
                {#if item.id === "requireExpiration"}
                  <Switch
                    checked={requireExpiration}
                    onCheckedChange={(next) => (requireExpiration = next)}
                    aria-label={item.title}
                  />
                {:else if item.id === "revocationCascadeEnabled"}
                  <Switch
                    checked={revocationCascadeEnabled}
                    onCheckedChange={(next) => (revocationCascadeEnabled = next)}
                    aria-label={item.title}
                  />
                {/if}
              {:else if item.type === "number"}
                <div class="flex items-center gap-2">
                  {#if item.id === "maxExpirationDays"}
                    <Field.Field>
                      <Field.Label class="sr-only" for={`policy-${item.id}`}>
                        {item.title}
                      </Field.Label>
                      <Input
                        id={`policy-${item.id}`}
                        type="number"
                        min="1"
                        bind:value={maxExpirationDays}
                        placeholder={item.placeholder}
                        class="h-9 w-24 text-right text-sm"
                      />
                    </Field.Field>
                  {:else if item.id === "autoExpireUnusedDays"}
                    <Field.Field>
                      <Field.Label class="sr-only" for={`policy-${item.id}`}>
                        {item.title}
                      </Field.Label>
                      <Input
                        id={`policy-${item.id}`}
                        type="number"
                        min="1"
                        bind:value={autoExpireUnusedDays}
                        placeholder={item.placeholder}
                        class="h-9 w-24 text-right text-sm"
                      />
                    </Field.Field>
                  {:else if item.id === "maxRateLimitOverride"}
                    <Field.Field>
                      <Field.Label class="sr-only" for={`policy-${item.id}`}>
                        {item.title}
                      </Field.Label>
                      <Input
                        id={`policy-${item.id}`}
                        type="number"
                        min="1"
                        bind:value={maxRateLimitOverride}
                        placeholder={item.placeholder}
                        class="h-9 w-24 text-right text-sm"
                      />
                    </Field.Field>
                  {:else if item.id === "maxDelegationDepth"}
                    <Field.Field>
                      <Field.Label class="sr-only" for={`policy-${item.id}`}>
                        {item.title}
                      </Field.Label>
                      <Input
                        id={`policy-${item.id}`}
                        type="number"
                        min="1"
                        bind:value={maxDelegationDepth}
                        placeholder={item.placeholder}
                        class="h-9 w-24 text-right text-sm"
                      />
                    </Field.Field>
                  {/if}
                  {#if item.suffix}
                    <span class="text-muted text-xs whitespace-nowrap">{item.suffix}</span>
                  {/if}
                </div>
              {/if}
            </div>
          </div>
        </div>
      {/each}
    </div>

    <!-- Save bar -->
    {#if hasChanges}
      <div
        class="border-accent-default/30 bg-accent-default/5 sticky bottom-0 mt-4 rounded-lg border p-4 backdrop-blur-sm"
        transition:fly={{ y: 20, duration: 200 }}
      >
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <div class="bg-accent-default/15 rounded-md p-2">
              <Check class="text-accent-default h-4 w-4" />
            </div>
            <div>
              <p class="text-default text-sm font-semibold">{m.api_keys_admin_unsaved_changes()}</p>
              <p class="text-muted text-xs">{m.api_keys_admin_changes_apply()}</p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <Button variant="ghost" onclick={resetPolicy} disabled={saving}>
              <RotateCcw class="h-4 w-4" />
              {m.api_keys_admin_discard()}
            </Button>
            <Button onclick={savePolicy} disabled={saving}>
              {#if saving}
                <div
                  class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
                ></div>
                {m.api_keys_admin_saving()}
              {:else}
                <Check class="h-4 w-4" />
                {m.api_keys_admin_save_changes()}
              {/if}
            </Button>
          </div>
        </div>
      </div>
    {/if}
  {/if}
</div>
