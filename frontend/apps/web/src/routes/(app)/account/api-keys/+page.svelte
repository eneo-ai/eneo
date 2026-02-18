<script lang="ts">
  import { onMount } from "svelte";
  import { writable } from "svelte/store";
  import { Page, Settings } from "$lib/components/layout";
  import { getAppContext } from "$lib/core/AppContext.js";
  import { getIntric } from "$lib/core/Intric";
  import { Button, Dialog, Input } from "@intric/ui";
  import type { ApiKeyCreatedResponse, ApiKeyV2 } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";
  import ApiKeyTable from "./ApiKeyTable.svelte";
  import CreateApiKeyDialog from "./CreateApiKeyDialog.svelte";
  import ApiKeySecretDialog from "./ApiKeySecretDialog.svelte";
  import { Key, AlertCircle, RefreshCw, Search, X, ShieldAlert } from "lucide-svelte";
  import ExpiringKeysBanner from "$lib/features/api-keys/ExpiringKeysBanner.svelte";
  import NotificationPreferences from "$lib/features/api-keys/NotificationPreferences.svelte";
  import type { ExpiringKeyDisplayItem } from "$lib/features/api-keys/expirationUtils";
  import { getExpiringKeysStore } from "$lib/features/api-keys/expiringKeysStore";

  const {
    user,
    tenant,
    state: { userInfo }
  } = getAppContext();
  const intric = getIntric();
  const { forceRefresh: forceRefreshExpiringStore } = getExpiringKeysStore();

  let keys = $state<ApiKeyV2[]>([]);
  let loading = $state(true);
  let errorMessage = $state<string | null>(null);
  let searchQuery = $state("");
  const secretDialogOpen = writable(false);
  let latestSecret = $state<string | null>(null);
  let secretSource = $state<"created" | "rotated">("created");
  let expiringItems = $state<ExpiringKeyDisplayItem[]>([]);
  let followedKeyIds = $state<Set<string>>(new Set());
  let notificationsEnabled = $state(false);

  let notificationPrefsRef = $state<NotificationPreferences>();
  let nextCursor = $state<string | null>(null);
  let loadingMore = $state(false);

  // Legacy key revoke
  let legacySuffix = $state(user.legacy_api_key_suffix);
  const showRevokeDialog = writable(false);
  let revoking = $state(false);

  async function loadKeys() {
    loading = true;
    errorMessage = null;
    try {
      const response = await intric.apiKeys.list({ limit: 100 });
      keys = response.items ?? [];
      nextCursor = response.next_cursor ?? null;
    } catch (error: any) {
      console.error(error);
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
    } finally {
      loading = false;
    }
  }

  async function loadMoreKeys() {
    if (!nextCursor || loadingMore) return;
    loadingMore = true;
    try {
      const response = await intric.apiKeys.list({ limit: 100, cursor: nextCursor });
      keys = [...keys, ...(response.items ?? [])];
      nextCursor = response.next_cursor ?? null;
    } catch (error: any) {
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
    } finally {
      loadingMore = false;
    }
  }

  function handleSecret(response: ApiKeyCreatedResponse, source: "created" | "rotated") {
    if (source !== "rotated") return;
    latestSecret = response.secret;
    secretSource = source;
    secretDialogOpen.set(true);
    void loadKeys();
  }

  function handleCreated() {
    secretDialogOpen.set(false);
    latestSecret = null;
    void loadKeys();
  }

  async function handleFollowChanged() {
    await notificationPrefsRef?.refreshSubscriptions();
    await forceRefreshExpiringStore();
  }

  async function revokeLegacyKey() {
    revoking = true;
    try {
      await intric.users.revokeLegacyApiKey();
      legacySuffix = null;
      showRevokeDialog.set(false);
    } catch (error: any) {
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
    } finally {
      revoking = false;
    }
  }

  const filteredKeys = $derived.by(() => {
    if (!searchQuery.trim()) return keys;
    const query = searchQuery.toLowerCase();
    return keys.filter(
      (key) =>
        key.name.toLowerCase().includes(query) ||
        key.key_suffix?.toLowerCase().includes(query) ||
        key.description?.toLowerCase().includes(query)
    );
  });

  onMount(() => {
    void loadKeys();
  });
</script>

<svelte:head>
  <title>Eneo.ai – Account – {$userInfo.firstName}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.my_api_keys()} />
    <div class="flex items-center gap-3">
      <Button variant="ghost" on:click={loadKeys} class="gap-2">
        <RefreshCw class="h-4 w-4 {loading ? 'animate-spin' : ''}" />
        {m.api_keys_refresh()}
      </Button>
      <div class="hidden lg:block">
        <CreateApiKeyDialog onCreated={handleCreated} />
      </div>
    </div>
  </Page.Header>

  <Page.Main>
    <Settings.Page>
      <div class="space-y-5 py-4">
        <!-- Empty state (no keys and no legacy key) -->
        {#if keys.length === 0 && !legacySuffix && !loading}
          <div class="rounded-xl border-2 border-dashed border-default bg-subtle/30 p-12 text-center">
            <div class="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-accent-default/10">
              <Key class="h-8 w-8 text-accent-default" />
            </div>
            <h3 class="text-lg font-semibold text-default">{m.api_keys_your_keys()}</h3>
            <p class="mt-2 text-sm text-muted max-w-md mx-auto">{m.api_keys_description()}</p>
            <div class="mt-4">
              <CreateApiKeyDialog onCreated={handleCreated} />
            </div>
          </div>
        {/if}

        <!-- Error Message -->
        {#if errorMessage}
          <div
            role="alert"
            class="flex items-center gap-3 rounded-xl border border-negative/30 bg-negative/5 px-5 py-4"
          >
            <AlertCircle class="h-5 w-5 text-negative shrink-0" />
            <p class="text-sm text-negative">{errorMessage}</p>
          </div>
        {/if}

        <!-- Legacy key notice -->
        {#if legacySuffix && !loading}
          <div class="rounded-xl border border-caution/30 bg-caution/5 dark:bg-caution/10 p-5">
            <div class="flex items-start gap-4">
              <div class="flex h-10 w-10 items-center justify-center rounded-lg bg-caution/15 dark:bg-caution/20 shrink-0">
                <ShieldAlert class="h-5 w-5 text-caution" />
              </div>
              <div class="flex-1">
                <h3 class="font-semibold text-caution">{m.api_keys_legacy_detected()}</h3>
                <p class="mt-1 text-sm text-muted">
                  {m.api_keys_legacy_ending_in()} <code class="font-mono bg-caution/15 dark:bg-caution/20 px-1.5 py-0.5 rounded text-caution">****{legacySuffix}</code>.
                  {m.api_keys_legacy_recommend()}
                </p>
                <div class="mt-3 flex flex-wrap items-center gap-2">
                  <Button variant="ghost" class="text-negative hover:text-negative" on:click={() => showRevokeDialog.set(true)}>
                    {m.api_keys_legacy_revoke()}
                  </Button>
                  <CreateApiKeyDialog onCreated={handleCreated} />
                </div>
              </div>
            </div>
          </div>
        {/if}

        <!-- Notification preferences -->
        <NotificationPreferences
          bind:this={notificationPrefsRef}
          onExpiringItemsChanged={(items) => { expiringItems = items; }}
          onError={(msg) => { errorMessage = msg; }}
          onFollowedKeysChanged={(ids, hasSubs) => { followedKeyIds = ids; }}
          onNotificationsEnabledChanged={(enabled) => { notificationsEnabled = enabled; }}
        />

        <!-- Expiring keys banner -->
        {#if notificationsEnabled && expiringItems.length > 0}
          <ExpiringKeysBanner
            items={expiringItems}
            tenantId={tenant.id}
            userId={user.id}
          />
        {/if}

        <!-- Keys Table -->
        <div class="rounded-xl border border-default bg-primary shadow-sm overflow-hidden">
          <div class="px-6 py-3.5 border-b border-default bg-subtle/30">
            <div class="flex items-center justify-between gap-4">
              <h3 class="font-semibold text-default shrink-0">
                {filteredKeys.length === keys.length
                  ? (keys.length !== 1 ? m.api_keys_count_plural({ count: keys.length }) : m.api_keys_count({ count: keys.length }))
                  : m.api_keys_filtered({ filtered: filteredKeys.length, total: keys.length })}
              </h3>
              {#if keys.length > 3}
                <div class="relative flex-1 max-w-xs">
                  <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted pointer-events-none" />
                  <Input.Text
                    bind:value={searchQuery}
                    placeholder={m.api_keys_search_placeholder()}
                    class="!pl-9 !h-9 !bg-primary !border-default/60 focus:!border-accent-default !text-sm !rounded-lg"
                  />
                  {#if searchQuery}
                    <button
                      type="button"
                      onclick={() => (searchQuery = "")}
                      aria-label={m.api_keys_search_clear_button_aria_label()}
                      class="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded-md hover:bg-hover text-muted hover:text-default transition-colors"
                    >
                      <X class="h-3.5 w-3.5" />
                    </button>
                  {/if}
                </div>
              {/if}
              <div class="lg:hidden shrink-0">
                <CreateApiKeyDialog onCreated={handleCreated} />
              </div>
            </div>
          </div>

          <div class="p-4">
            <ApiKeyTable
              keys={filteredKeys}
              {loading}
              onChanged={loadKeys}
              onSecret={(r) => handleSecret(r, "rotated")}
              {followedKeyIds}
              onFollowChanged={handleFollowChanged}
            />
          </div>

          {#if nextCursor}
            <div class="flex justify-center border-t border-default px-6 py-3">
              <button
                type="button"
                onclick={loadMoreKeys}
                disabled={loadingMore}
                class="text-sm font-medium text-accent-default hover:text-accent-default/80
                       disabled:opacity-50 transition-colors"
              >
                {loadingMore ? m.api_keys_loading_more() : m.api_keys_load_more()}
              </button>
            </div>
          {/if}
        </div>
      </div>
    </Settings.Page>
  </Page.Main>
</Page.Root>

<Dialog.Root alert openController={showRevokeDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.api_keys_legacy_revoke_title()}</Dialog.Title>
    <Dialog.Description>
      {m.api_keys_legacy_revoke_description()}
    </Dialog.Description>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={revokeLegacyKey} disabled={revoking}>
        {revoking ? "..." : m.api_keys_legacy_revoke()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<ApiKeySecretDialog
  openController={secretDialogOpen}
  secret={latestSecret}
  source={secretSource}
/>
