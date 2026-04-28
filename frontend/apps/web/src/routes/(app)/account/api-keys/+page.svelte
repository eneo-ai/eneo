<script lang="ts">
  import { onMount } from "svelte";
  import { Page, Settings } from "$lib/components/layout";
  import { getAppContext } from "$lib/core/AppContext.js";
  import { getIntric } from "$lib/core/Intric";
  import type { ApiKeyCreatedResponse, ApiKeyV2, SpaceSparse } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  import ApiKeyTable from "./ApiKeyTable.svelte";
  import CreateApiKeyDialog from "$lib/features/api-keys/CreateApiKeyDialog.svelte";
  import ApiKeySecretDialog from "$lib/features/api-keys/ApiKeySecretDialog.svelte";
  import { Key, AlertCircle, RefreshCw, Search, X, ShieldAlert } from "lucide-svelte";
  import ExpiringKeysBanner from "$lib/features/api-keys/ExpiringKeysBanner.svelte";
  import NotificationPreferences from "$lib/features/api-keys/NotificationPreferences.svelte";
  import ApiKeyStateFilter from "$lib/features/api-keys/ApiKeyStateFilter.svelte";
  import type { ApiKeyStateFilterValue } from "$lib/features/api-keys/apiKeyTableUtils";
  import type { ExpiringKeyDisplayItem } from "$lib/features/api-keys/expirationUtils";
  import { getExpiringKeysStore } from "$lib/features/api-keys/expiringKeysStore";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";

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
  let stateFilter = $state<ApiKeyStateFilterValue>("active");
  let secretDialogOpen = $state(false);
  let latestSecret = $state<string | null>(null);
  let secretSource = $state<"created" | "rotated">("created");
  let expiringItems = $state<ExpiringKeyDisplayItem[]>([]);
  let followedKeyIds = $state<Set<string>>(new Set());
  let notificationsEnabled = $state(false);

  let notificationPrefsRef = $state<NotificationPreferences>();
  let nextCursor = $state<string | null>(null);
  let loadingMore = $state(false);

  // Scope name resolution
  type ResourceOption = { id: string; name: string };
  let scopeResources = $state<ResourceOption[]>([]);

  const scopeNamesById = $derived.by(() => {
    const mapping: Record<string, string> = {};
    for (const resource of scopeResources) {
      mapping[resource.id] = resource.name;
    }
    return mapping;
  });

  // Legacy key revoke
  let legacySuffix = $state(user.legacy_api_key_suffix);
  let showRevokeDialog = $state(false);
  let revoking = $state(false);

  async function loadKeys() {
    loading = true;
    errorMessage = null;
    try {
      const response = await intric.apiKeys.list({
        limit: 100,
        state: stateFilter || null
      });
      keys = response.items ?? [];
      nextCursor = response.next_cursor ?? null;
    } catch (error: unknown) {
      console.error(error);
      errorMessage = getErrorMessage(error);
    } finally {
      loading = false;
    }
  }

  async function loadMoreKeys() {
    if (!nextCursor || loadingMore) return;
    loadingMore = true;
    try {
      const response = await intric.apiKeys.list({
        limit: 100,
        cursor: nextCursor,
        state: stateFilter || null
      });
      keys = [...keys, ...(response.items ?? [])];
      nextCursor = response.next_cursor ?? null;
    } catch (error: unknown) {
      errorMessage = getErrorMessage(error);
    } finally {
      loadingMore = false;
    }
  }

  function handleSecret(response: ApiKeyCreatedResponse, source: "created" | "rotated") {
    if (source !== "rotated") return;
    latestSecret = response.secret;
    secretSource = source;
    secretDialogOpen = true;
    void loadKeys();
  }

  function handleCreated() {
    secretDialogOpen = false;
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
      showRevokeDialog = false;
    } catch (error: unknown) {
      errorMessage = getErrorMessage(error);
    } finally {
      revoking = false;
    }
  }

  async function loadScopeResources() {
    try {
      let listedSpaces: SpaceSparse[] = [];
      try {
        listedSpaces = await intric.spaces.list({
          include_personal: true,
          include_applications: true
        });
      } catch {
        listedSpaces = await intric.spaces.list();
      }

      const resources: ResourceOption[] = listedSpaces.map((s) => ({ id: s.id, name: s.name }));

      const applicationsBySpace = await Promise.all(
        listedSpaces.map(async (space) => {
          try {
            const applications = await intric.spaces.listApplications({ id: space.id });
            return { space, applications };
          } catch {
            return { space, applications: space.applications ?? null };
          }
        })
      );

      for (const { applications } of applicationsBySpace) {
        for (const assistant of applications?.assistants?.items ?? []) {
          resources.push({ id: assistant.id, name: assistant.name });
        }
        for (const app of applications?.apps?.items ?? []) {
          resources.push({ id: app.id, name: app.name });
        }
      }

      scopeResources = resources;
    } catch (error) {
      console.error("Failed to load scope resources:", error);
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
    void loadScopeResources();
  });
</script>

<svelte:head>
  <title>Eneo.ai – Account – {$userInfo.firstName}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.my_api_keys()} />
    <div class="flex items-center gap-3">
      <Button variant="ghost" onclick={loadKeys}>
        <RefreshCw class={loading ? "animate-spin" : ""} />
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
          <div
            class="border-default bg-subtle/30 rounded-xl border-2 border-dashed p-12 text-center"
          >
            <div
              class="bg-accent-default/10 mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl"
            >
              <Key class="text-accent-default h-8 w-8" />
            </div>
            <h3 class="text-default text-lg font-semibold">{m.api_keys_your_keys()}</h3>
            <p class="text-muted mx-auto mt-2 max-w-md text-sm">{m.api_keys_description()}</p>
            <div class="mt-4">
              <CreateApiKeyDialog onCreated={handleCreated} />
            </div>
          </div>
        {/if}

        <!-- Error Message -->
        {#if errorMessage}
          <Alert.Root variant="destructive">
            <AlertCircle />
            <Alert.Description>{errorMessage}</Alert.Description>
          </Alert.Root>
        {/if}

        <!-- Legacy key notice -->
        {#if legacySuffix && !loading}
          <Alert.Root class="border-caution/30 bg-caution/5 dark:bg-caution/10">
            <ShieldAlert class="text-caution" />
            <Alert.Title class="text-caution">{m.api_keys_legacy_detected()}</Alert.Title>
            <Alert.Description>
              {m.api_keys_legacy_ending_in()}
              <code
                class="bg-caution/15 dark:bg-caution/20 text-caution rounded px-1.5 py-0.5 font-mono"
                >****{legacySuffix}</code
              >.
              {m.api_keys_legacy_recommend()}
              <div class="mt-3 flex flex-wrap items-center gap-2">
                <Button variant="destructive" size="sm" onclick={() => (showRevokeDialog = true)}>
                  {m.api_keys_legacy_revoke()}
                </Button>
                <CreateApiKeyDialog onCreated={handleCreated} />
              </div>
            </Alert.Description>
          </Alert.Root>
        {/if}

        <!-- Notification preferences -->
        <NotificationPreferences
          bind:this={notificationPrefsRef}
          onExpiringItemsChanged={(items) => {
            expiringItems = items;
          }}
          onError={(msg) => {
            errorMessage = msg;
          }}
          onFollowedKeysChanged={(ids, _hasSubs) => {
            followedKeyIds = ids;
          }}
          onNotificationsEnabledChanged={(enabled) => {
            notificationsEnabled = enabled;
          }}
        />

        <!-- Expiring keys banner -->
        {#if notificationsEnabled && expiringItems.length > 0}
          <ExpiringKeysBanner items={expiringItems} tenantId={tenant.id} userId={user.id} />
        {/if}

        <!-- Keys Table -->
        <div class="border-default bg-primary overflow-hidden rounded-xl border shadow-sm">
          <div class="border-default bg-subtle/30 border-b px-6 py-3.5">
            <div class="flex items-center justify-between gap-4">
              <h3 class="text-default shrink-0 font-semibold">
                {filteredKeys.length === keys.length
                  ? keys.length !== 1
                    ? m.api_keys_count_plural({ count: keys.length })
                    : m.api_keys_count({ count: keys.length })
                  : m.api_keys_filtered({ filtered: filteredKeys.length, total: keys.length })}
              </h3>
              {#if keys.length > 3}
                <div class="relative max-w-xs flex-1">
                  <Search
                    class="text-muted pointer-events-none absolute top-1/2 left-3 z-10 h-4 w-4 -translate-y-1/2"
                    aria-hidden="true"
                  />
                  <Input
                    bind:value={searchQuery}
                    placeholder={m.api_keys_search_placeholder()}
                    aria-label={m.api_keys_search_placeholder()}
                    class="h-9 pr-9 pl-9 text-sm"
                  />
                  {#if searchQuery}
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      onclick={() => (searchQuery = "")}
                      aria-label={m.api_keys_search_clear_button_aria_label()}
                      class="absolute top-1/2 right-1.5 -translate-y-1/2"
                    >
                      <X />
                    </Button>
                  {/if}
                </div>
              {/if}
              <div class="shrink-0 lg:hidden">
                <CreateApiKeyDialog onCreated={handleCreated} />
              </div>
            </div>
            <ApiKeyStateFilter
              bind:value={stateFilter}
              onChange={() => void loadKeys()}
              class="mt-3"
            />
          </div>

          <div class="p-4">
            <ApiKeyTable
              keys={filteredKeys}
              {loading}
              onChanged={loadKeys}
              onSecret={(r) => handleSecret(r, "rotated")}
              {followedKeyIds}
              onFollowChanged={handleFollowChanged}
              scopeNames={scopeNamesById}
            />
          </div>

          {#if nextCursor}
            <div class="border-default flex justify-center border-t px-6 py-3">
              <Button
                variant="link"
                onclick={loadMoreKeys}
                disabled={loadingMore}
                class="text-accent-default"
              >
                {loadingMore ? m.api_keys_loading_more() : m.api_keys_load_more()}
              </Button>
            </div>
          {/if}
        </div>
      </div>
    </Settings.Page>
  </Page.Main>
</Page.Root>

<AlertDialog.Root bind:open={showRevokeDialog}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.api_keys_legacy_revoke_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.api_keys_legacy_revoke_description()}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" onclick={revokeLegacyKey} disabled={revoking}>
        {revoking ? "..." : m.api_keys_legacy_revoke()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<ApiKeySecretDialog bind:open={secretDialogOpen} secret={latestSecret} source={secretSource} />
