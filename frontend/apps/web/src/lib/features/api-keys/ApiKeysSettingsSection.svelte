<script lang="ts">
  import { onMount } from "svelte";
  import type { ApiKeyCreatedResponse, ApiKeyScopeType, ApiKeyV2 } from "@intric/intric-js";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import {
    Key,
    ChevronDown,
    AlertCircle,
    ExternalLink,
    RefreshCw,
    Bell,
    BellOff
  } from "lucide-svelte";
  import { slide } from "svelte/transition";
  import ApiKeyTable from "../../../routes/(app)/account/api-keys/ApiKeyTable.svelte";
  import CreateApiKeyDialog from "$lib/features/api-keys/CreateApiKeyDialog.svelte";
  import ApiKeySecretDialog from "$lib/features/api-keys/ApiKeySecretDialog.svelte";
  import ExpiringKeysBanner from "./ExpiringKeysBanner.svelte";
  import { getExpiringKeys, toDisplayItems } from "./expirationUtils";
  import { getAppContext } from "$lib/core/AppContext";
  import {
    extractFollowedKeyIds,
    followScopeNotifications,
    hasScopeSubscription,
    listNotificationSubscriptions,
    unfollowScopeNotifications
  } from "./notificationPreferences";
  import { getExpiringKeysStore } from "./expiringKeysStore";

  const intric = getIntric();
  const { user, tenant } = getAppContext();
  const { forceRefresh: forceRefreshExpiringStore } = getExpiringKeysStore();

  let {
    scopeType,
    scopeId,
    scopeName
  }: {
    scopeType: ApiKeyScopeType;
    scopeId: string;
    scopeName: string;
  } = $props();

  let keys = $state<ApiKeyV2[]>([]);
  let loading = $state(false);
  let errorMessage = $state<string | null>(null);
  let expanded = $state(false);

  // Secret dialog state
  let secretDialogOpen = $state(false);
  let latestSecret = $state<string | null>(null);
  let secretSource = $state<"created" | "rotated">("created");
  let isScopeFollowed = $state(false);
  let scopeFollowLoading = $state(false);
  let followedKeyIds = $state<Set<string>>(new Set());

  // Computed stats
  const activeCount = $derived(keys.filter((k) => k.state === "active").length);
  const suspendedCount = $derived(keys.filter((k) => k.state === "suspended").length);
  const expiringDisplayItems = $derived(toDisplayItems(getExpiringKeys(keys)));
  const effectiveFollowedKeyIds = $derived(
    isScopeFollowed
      ? new Set([...followedKeyIds, ...keys.filter((k) => k.state !== "revoked").map((k) => k.id)])
      : followedKeyIds
  );
  const canFollowScope = $derived(
    scopeType === "assistant" || scopeType === "app" || scopeType === "space"
  );

  async function loadKeys() {
    loading = true;
    errorMessage = null;
    try {
      const response = await intric.apiKeys.list({
        scope_type: scopeType,
        scope_id: scopeId,
        limit: 20
      });
      keys = response.items ?? [];
    } catch (error) {
      console.error(error);
      const err = error as { getReadableMessage?: () => string };
      errorMessage = err?.getReadableMessage?.() ?? m.api_keys_load_error();
    } finally {
      loading = false;
    }
  }

  async function loadScopeFollowState() {
    if (!canFollowScope) return;
    try {
      const subscriptions = await listNotificationSubscriptions(intric);
      followedKeyIds = extractFollowedKeyIds(subscriptions);
      isScopeFollowed = hasScopeSubscription(subscriptions, scopeType, scopeId);
    } catch (error) {
      console.error(error);
    }
  }

  async function toggleScopeFollow() {
    if (!canFollowScope) return;
    scopeFollowLoading = true;
    try {
      if (isScopeFollowed) {
        await unfollowScopeNotifications(intric, scopeType, scopeId);
      } else {
        await followScopeNotifications(intric, scopeType, scopeId);
      }
      await loadScopeFollowState();
      await forceRefreshExpiringStore();
    } catch (error) {
      console.error(error);
    } finally {
      scopeFollowLoading = false;
    }
  }

  function handleSecret(response: ApiKeyCreatedResponse) {
    latestSecret = response.secret;
    secretSource = "rotated";
    secretDialogOpen = true;
    void loadKeys();
  }

  function handleCreated() {
    secretDialogOpen = false;
    latestSecret = null;
    void loadKeys();
  }

  function getEmptyMessage(): string {
    switch (scopeType) {
      case "assistant":
        return m.api_keys_empty_assistant();
      case "space":
        return m.api_keys_empty_space();
      case "app":
        return m.api_keys_empty_app();
      default:
        return m.api_keys_empty_assistant();
    }
  }

  onMount(() => {
    void loadKeys();
    void loadScopeFollowState();
  });
</script>

<div class="w-full">
  {#if errorMessage}
    <!-- Error state -->
    <div
      class="border-negative-default/20 bg-negative-dimmer flex items-center gap-3 rounded-lg border px-5 py-4"
    >
      <AlertCircle class="text-negative-default h-4 w-4 flex-shrink-0" />
      <p class="text-negative-default flex-1 text-sm">{errorMessage}</p>
      <Button variant="ghost" size="sm" onclick={loadKeys}>
        <RefreshCw />
        {m.retry()}
      </Button>
    </div>
  {:else if loading && keys.length === 0}
    <!-- Loading state -->
    <div class="flex items-center gap-3 py-4">
      <div
        class="border-accent-default h-4 w-4 animate-spin rounded-full border-2 border-t-transparent"
      ></div>
      <span class="text-muted text-sm">{m.loading()}...</span>
    </div>
  {:else if keys.length === 0}
    <!-- Empty state -->
    <div class="border-default flex items-start gap-4 rounded-lg border px-5 py-5">
      <Key class="text-muted mt-0.5 h-5 w-5 flex-shrink-0" />
      <div class="flex flex-col gap-3">
        <p class="text-secondary text-sm leading-relaxed">{getEmptyMessage()}</p>
        <div>
          <CreateApiKeyDialog
            onCreated={handleCreated}
            lockedScopeType={scopeType}
            lockedScopeId={scopeId}
            lockedScopeName={scopeName}
            triggerVariant="outlined"
          />
        </div>
      </div>
    </div>
  {:else}
    <!-- Collapsible key list -->
    <div class="border-default overflow-hidden rounded-lg border">
      <!-- Summary header -->
      <div class="flex w-full items-center gap-2 px-5 py-4">
        <button
          type="button"
          onclick={() => (expanded = !expanded)}
          class="hover:text-default flex min-w-0 flex-1 items-center justify-between text-left transition-colors"
          aria-expanded={expanded}
        >
          <div class="flex items-center gap-3">
            <Key class="text-muted h-4 w-4" />
            <span class="text-default text-sm font-medium">
              {keys.length}
              {m.api_keys()}
            </span>
            <span class="text-muted text-xs">
              {m.api_keys_summary({ active: activeCount, suspended: suspendedCount })}
            </span>
          </div>
          <ChevronDown
            class="text-muted h-4 w-4 transition-transform duration-200 {expanded
              ? 'rotate-180'
              : ''}"
          />
        </button>
        {#if canFollowScope}
          <button
            type="button"
            onclick={() => void toggleScopeFollow()}
            class="border-default text-muted hover:text-default inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs"
            disabled={scopeFollowLoading}
          >
            {#if isScopeFollowed}
              <BellOff class="h-3.5 w-3.5" />
              {m.api_keys_notifications_unfollow_scope_action()}
            {:else}
              <Bell class="h-3.5 w-3.5" />
              {m.api_keys_notifications_follow_scope_action()}
            {/if}
          </button>
        {/if}
      </div>

      <!-- Expanded content -->
      {#if expanded}
        <div transition:slide={{ duration: 200 }}>
          {#if expiringDisplayItems.length > 0}
            <div class="border-default border-t px-5 pt-4">
              <ExpiringKeysBanner
                items={expiringDisplayItems}
                tenantId={tenant.id}
                userId={user.id}
                compact
                qualifier={m.api_keys_expiring_in_view()}
              />
            </div>
          {/if}
          <div class="border-default border-t px-5 py-5">
            <ApiKeyTable
              {keys}
              {loading}
              onChanged={loadKeys}
              onSecret={handleSecret}
              followedKeyIds={effectiveFollowedKeyIds}
              scopeFollowed={isScopeFollowed}
              onFollowChanged={async () => {
                await loadScopeFollowState();
                await forceRefreshExpiringStore();
              }}
              scopeNames={{ [scopeId]: scopeName }}
              currentUserId={user.id}
            />
          </div>
        </div>
      {/if}

      <!-- Footer actions -->
      <div class="border-dimmer flex items-center justify-between border-t px-5 py-3">
        <CreateApiKeyDialog
          onCreated={handleCreated}
          lockedScopeType={scopeType}
          lockedScopeId={scopeId}
          lockedScopeName={scopeName}
          triggerVariant="outlined"
        />
        <!-- eslint-disable svelte/no-navigation-without-resolve -- linked from settings module -->
        <a
          href="/account/api-keys"
          class="text-secondary hover:text-default flex items-center gap-1.5 text-xs transition-colors"
        >
          {m.api_keys_manage_all()}
          <ExternalLink class="h-3 w-3" />
        </a>
        <!-- eslint-enable svelte/no-navigation-without-resolve -->
      </div>
    </div>
  {/if}
</div>

<ApiKeySecretDialog bind:open={secretDialogOpen} secret={latestSecret} source={secretSource} />
