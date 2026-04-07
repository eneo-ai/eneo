<script lang="ts">
  import { onMount } from "svelte";
  import { Button, Input } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import type { ApiKeyPolicy } from "@intric/intric-js";
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

  let maxDelegationDepth = $state("");
  let maxExpirationDays = $state("");
  let autoExpireUnusedDays = $state("");
  let maxRateLimitOverride = $state("");
  let requireExpiration = $state(false);
  let revocationCascadeEnabled = $state(false);

  function toNumber(value: string) {
    if (!value.trim()) return null;
    const parsed = Number(value);
    return Number.isNaN(parsed) ? null : parsed;
  }

  function syncFromPolicy(policy: ApiKeyPolicy) {
    maxDelegationDepth = policy.max_delegation_depth?.toString() ?? "";
    maxExpirationDays = policy.max_expiration_days?.toString() ?? "";
    autoExpireUnusedDays = policy.auto_expire_unused_days?.toString() ?? "";
    maxRateLimitOverride = policy.max_rate_limit_override?.toString() ?? "";
    requireExpiration = policy.require_expiration ?? false;
    revocationCascadeEnabled = policy.revocation_cascade_enabled ?? false;
  }

  function snapshot() {
    return {
      max_delegation_depth: toNumber(maxDelegationDepth),
      max_expiration_days: toNumber(maxExpirationDays),
      auto_expire_unused_days: toNumber(autoExpireUnusedDays),
      max_rate_limit_override: toNumber(maxRateLimitOverride),
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
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
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
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
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
    <div
      class="flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 dark:border-red-900 dark:bg-red-950/50"
      transition:fly={{ y: -8, duration: 150 }}
    >
      <AlertCircle class="h-4 w-4 flex-shrink-0 text-red-600 dark:text-red-400" />
      <p class="text-sm text-red-700 dark:text-red-300">{errorMessage}</p>
    </div>
  {/if}

  {#if successMessage}
    <div
      class="flex items-center gap-3 rounded-lg border border-green-200 bg-green-50 px-4 py-3 dark:border-green-900 dark:bg-green-950/50"
      transition:fly={{ y: -8, duration: 150 }}
    >
      <Check class="h-4 w-4 flex-shrink-0 text-green-600 dark:text-green-400" />
      <p class="text-sm text-green-700 dark:text-green-300">{successMessage}</p>
    </div>
  {/if}

  {#if loading}
    <div class="animate-pulse space-y-4">
      {#each Array(6) as _}
        <div class="border-default bg-subtle/50 rounded-lg border p-4">
          <div class="flex items-center gap-4">
            <div class="bg-subtle h-10 w-10 rounded-lg"></div>
            <div class="flex-1 space-y-2">
              <div class="bg-subtle h-4 w-32 rounded"></div>
              <div class="bg-subtle h-3 w-48 rounded"></div>
            </div>
            <div class="bg-subtle h-6 w-12 rounded"></div>
          </div>
        </div>
      {/each}
    </div>
  {:else}
    <!-- Policy Items -->
    <div class="space-y-3">
      {#each policyItems as item}
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
                  <Input.Switch bind:value={requireExpiration} />
                {:else if item.id === "revocationCascadeEnabled"}
                  <Input.Switch bind:value={revocationCascadeEnabled} />
                {/if}
              {:else if item.type === "number"}
                <div class="flex items-center gap-2">
                  {#if item.id === "maxExpirationDays"}
                    <Input.Text
                      bind:value={maxExpirationDays}
                      placeholder={item.placeholder}
                      type="number"
                      min="1"
                      class="!h-9 !w-24 text-right text-sm"
                    />
                  {:else if item.id === "autoExpireUnusedDays"}
                    <Input.Text
                      bind:value={autoExpireUnusedDays}
                      placeholder={item.placeholder}
                      type="number"
                      min="1"
                      class="!h-9 !w-24 text-right text-sm"
                    />
                  {:else if item.id === "maxRateLimitOverride"}
                    <Input.Text
                      bind:value={maxRateLimitOverride}
                      placeholder={item.placeholder}
                      type="number"
                      min="1"
                      class="!h-9 !w-24 text-right text-sm"
                    />
                  {:else if item.id === "maxDelegationDepth"}
                    <Input.Text
                      bind:value={maxDelegationDepth}
                      placeholder={item.placeholder}
                      type="number"
                      min="1"
                      class="!h-9 !w-24 text-right text-sm"
                    />
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
            <Button variant="ghost" on:click={resetPolicy} disabled={saving} class="gap-2">
              <RotateCcw class="h-4 w-4" />
              {m.api_keys_admin_discard()}
            </Button>
            <Button variant="primary" on:click={savePolicy} disabled={saving} class="gap-2">
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
