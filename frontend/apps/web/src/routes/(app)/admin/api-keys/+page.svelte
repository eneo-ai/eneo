<script lang="ts">
  import { onMount } from "svelte";
  import { resolve } from "$app/paths";
  import { Page, Settings } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { EneoError } from "@eneo/eneo-js";
  import type { ApiKeyCreatedResponse, SpaceSparse, UserSparse } from "@eneo/eneo-js";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  import type { AdminApiKey } from "$lib/features/api-keys/apiKeyTableUtils";
  import AdminApiKeyTable from "./AdminApiKeyTable.svelte";
  import ApiKeyPolicyPanel from "./ApiKeyPolicyPanel.svelte";
  import SuperKeyStatusPanel from "./SuperKeyStatusPanel.svelte";
  import ScopeResourceSelector from "$lib/features/api-keys/ScopeResourceSelector.svelte";
  import ApiKeySecretDialog from "$lib/features/api-keys/ApiKeySecretDialog.svelte";
  import ApiKeyStateFilter from "$lib/features/api-keys/ApiKeyStateFilter.svelte";
  import type { ApiKeyStateFilterValue } from "$lib/features/api-keys/apiKeyTableUtils";
  import {
    Filter,
    X,
    Check,
    Key,
    AlertCircle,
    ChevronDown,
    RefreshCw,
    Lock,
    Globe
  } from "lucide-svelte";
  import { fly, slide } from "svelte/transition";
  import {
    getAdminNotificationPolicy,
    updateAdminNotificationPolicy,
    type ApiKeyNotificationPolicy
  } from "$lib/features/api-keys/notificationPreferences";

  const eneo = getEneo();

  let keys = $state<AdminApiKey[]>([]);
  let loading = $state(false);
  let loadingMore = $state(false);
  let errorMessage = $state<string | null>(null);
  let nextCursor = $state<string | null>(null);
  let totalCount = $state<number | null>(null);
  type ResourceOption = { id: string; name: string; spaceName?: string };
  let spaces = $state<SpaceSparse[]>([]);
  let assistantOptions = $state<ResourceOption[]>([]);
  let appOptions = $state<ResourceOption[]>([]);

  // Filter states
  let scopeType = $state("");
  let stateFilter = $state<ApiKeyStateFilterValue>("active");
  let keyType = $state("");
  let scopeId = $state<string | null>(null);
  let createdByUserId = $state("");
  let expiresWithinDays = $state("");
  let userRelation = $state<"owner" | "creator">("owner");
  let limit = $state("100");
  let searchQuery = $state("");
  let searchScope = $state<"entity" | "user">("entity");
  let selectedUser = $state<UserSparse | null>(null);
  let userSearchResults = $state<UserSparse[]>([]);
  let isSearchingUsers = $state(false);
  let showUserDropdown = $state(false);
  let userSearchCompleted = $state(false);
  let showSearchScopeDropdown = $state(false);
  let userSearchTimer: ReturnType<typeof setTimeout>;

  // UI states
  let showFilters = $state(true);
  let secretDialogOpen = $state(false);
  let latestSecret = $state<string | null>(null);
  let secretSource = $state<"created" | "rotated">("created");
  let trackingConfigLoading = $state(false);
  let trackingConfigLoaded = $state(false);
  let apiKeyUsedTrackingEnabled = $state(false);
  let apiKeyAuthFailedTrackingEnabled = $state(true);
  let expiryNotificationsEnabled = $state(true);
  let tenantSettingsLoading = $state(false);
  let notificationPolicyLoading = $state(false);
  let notificationPolicySaving = $state(false);
  let notificationPolicy = $state<ApiKeyNotificationPolicy>({
    enabled: true,
    default_days_before_expiry: [30],
    max_days_before_expiry: 365,
    allow_auto_follow_published_assistants: false,
    allow_auto_follow_published_apps: false
  });
  let notificationPolicyDaysInput = $state("30");
  let notificationPolicyMaxDaysInput = $state("365");

  // Quick filter chips — state lives in <ApiKeyStateFilter>; key class stays here
  const quickFilters = $derived([
    { label: m.api_keys_admin_quick_secret(), filter: { keyType: "sk_" } },
    { label: m.api_keys_admin_quick_public(), filter: { keyType: "pk_" } }
  ]);

  const scopeOptions = $derived([
    { value: "", label: m.api_keys_admin_scope_all() },
    { value: "tenant", label: m.api_keys_admin_scope_tenant() },
    { value: "space", label: m.api_keys_admin_scope_space() },
    { value: "assistant", label: m.api_keys_admin_scope_assistant() },
    { value: "app", label: m.api_keys_admin_scope_app() }
  ]);

  const keyTypeOptions = $derived([
    { value: "", label: m.api_keys_admin_key_type_all() },
    { value: "pk_", label: m.api_keys_admin_key_type_public() },
    { value: "sk_", label: m.api_keys_admin_key_type_secret() }
  ]);

  const resultLimitOptions = $derived([
    { value: "25", label: "25" },
    { value: "50", label: "50" },
    { value: "100", label: "100" },
    { value: "250", label: "250" }
  ]);

  const scopeSelectorType = $derived.by(() => {
    if (scopeType === "space" || scopeType === "assistant" || scopeType === "app") {
      return scopeType;
    }
    return null;
  });

  const scopeNamesById = $derived.by(() => {
    const mapping: Record<string, string> = {};
    for (const space of spaces) {
      mapping[space.id] = space.name;
    }
    for (const assistant of assistantOptions) {
      mapping[assistant.id] = assistant.name;
    }
    for (const app of appOptions) {
      mapping[app.id] = app.name;
    }
    return mapping;
  });

  // Active filter count
  const activeFilterCount = $derived.by(() => {
    let count = [scopeType, stateFilter, keyType, scopeId?.trim()].filter(Boolean).length;
    if (expiresWithinDays.trim()) {
      count += 1;
    }
    if (searchScope === "entity" && searchQuery.trim()) {
      count += 1;
    }
    if (searchScope === "user" && createdByUserId.trim()) {
      count += 1;
    }
    return count;
  });

  function parseLimit() {
    const parsed = Number(limit);
    return Number.isNaN(parsed) || parsed <= 0 ? undefined : parsed;
  }

  function buildParams(cursor?: string | null) {
    const params: Record<string, unknown> = {};
    const parsedLimit = parseLimit();
    if (parsedLimit) params.limit = parsedLimit;
    if (cursor) params.cursor = cursor;
    if (scopeType) params.scope_type = scopeType;
    if (stateFilter) params.state = stateFilter;
    if (keyType) params.key_type = keyType;
    if (scopeId?.trim()) params.scope_id = scopeId.trim();
    if (expiresWithinDays.trim()) {
      const parsed = Number(expiresWithinDays.trim());
      if (Number.isFinite(parsed) && parsed > 0) {
        params.expires_within_days = Math.floor(parsed);
      }
    }
    if (createdByUserId.trim()) {
      if (userRelation === "owner") {
        params.owner_user_id = createdByUserId.trim();
      } else {
        params.created_by_user_id = createdByUserId.trim();
      }
      params.user_relation = userRelation;
    }
    if (searchScope === "entity" && searchQuery.trim()) {
      params.search = searchQuery.trim();
    }
    return params;
  }

  function isLikelyFullApiKeySecret(value: string): boolean {
    const normalized = value.trim();
    if (!normalized) return false;
    if (!/^((sk_)|(pk_)|(inp_)|(ina_))[a-z0-9]+$/i.test(normalized)) return false;
    return normalized.length >= 40;
  }

  function getSecretSuffixFallback(value: string): string | null {
    const normalized = value.trim();
    if (!isLikelyFullApiKeySecret(normalized)) return null;
    const rawSecret = normalized.includes("_") ? normalized.split("_", 2)[1] : normalized;
    if (!rawSecret || rawSecret.length < 4) return null;
    // Prefer an 8-char suffix match first since persisted key_suffix uses this granularity.
    return rawSecret.slice(-8);
  }

  async function loadKeys({ reset }: { reset: boolean }) {
    if (reset) {
      loading = true;
      errorMessage = null;
    } else {
      loadingMore = true;
    }

    try {
      let forcedSearchFallback: string | null = null;

      if (reset && searchScope === "entity" && isLikelyFullApiKeySecret(searchQuery)) {
        try {
          const lookupResponse = await eneo.apiKeys.admin.lookup({
            secret: searchQuery.trim()
          });
          keys = lookupResponse?.api_key ? [lookupResponse.api_key as AdminApiKey] : [];
          nextCursor = null;
          totalCount = keys.length;
          errorMessage = null;
          return;
        } catch (lookupError) {
          const isNotFound = lookupError instanceof EneoError && lookupError.status === 404;
          if (isNotFound) {
            // Graceful fallback: if exact secret lookup misses (typo/old secret), still
            // search by key suffix so admins can locate candidate keys quickly.
            forcedSearchFallback = getSecretSuffixFallback(searchQuery);
          } else {
            throw lookupError;
          }
        }
      }

      const params = buildParams(reset ? null : nextCursor);
      if (forcedSearchFallback) {
        params.search = forcedSearchFallback;
      }
      const response = await eneo.apiKeys.admin.list(params);
      const items = (response.items ?? []) as AdminApiKey[];
      keys = reset ? items : [...keys, ...items];
      nextCursor = response.next_cursor ?? null;
      totalCount = response.total_count ?? null;
    } catch (error) {
      console.error(error);
      errorMessage = getErrorMessage(error);
    } finally {
      loading = false;
      loadingMore = false;
    }
  }

  async function loadScopeResources() {
    try {
      let listedSpaces: SpaceSparse[] = [];
      try {
        listedSpaces = await eneo.spaces.list({
          include_personal: true,
          include_applications: true
        });
      } catch (error) {
        console.error(error);
      }

      if (listedSpaces.length === 0) {
        listedSpaces = await eneo.spaces.list();
      }

      spaces = listedSpaces;

      const applicationsBySpace = await Promise.all(
        spaces.map(async (space) => {
          try {
            const applications = await eneo.spaces.listApplications({ id: space.id });
            return { space, applications };
          } catch {
            return { space, applications: space.applications ?? null };
          }
        })
      );

      assistantOptions = applicationsBySpace.flatMap(({ space, applications }) =>
        (applications?.assistants?.items ?? []).map((assistant) => ({
          id: assistant.id,
          name: assistant.name,
          spaceName: space.name
        }))
      );

      appOptions = applicationsBySpace.flatMap(({ space, applications }) =>
        (applications?.apps?.items ?? []).map((app) => ({
          id: app.id,
          name: app.name,
          spaceName: space.name
        }))
      );

      if (assistantOptions.length === 0) {
        try {
          const assistants = await eneo.assistants.list();
          assistantOptions = assistants.map((assistant) => ({
            id: assistant.id,
            name: assistant.name
          }));
        } catch (error) {
          console.error(error);
        }
      }
    } catch (error) {
      console.error(error);
    }
  }

  function applyFilters() {
    void loadKeys({ reset: true });
  }

  function clearUserFilter() {
    selectedUser = null;
    createdByUserId = "";
    userSearchResults = [];
    showUserDropdown = false;
    userSearchCompleted = false;
    isSearchingUsers = false;
  }

  async function searchUsers(query: string): Promise<UserSparse[]> {
    const responseByEmail = await eneo.users.list({
      includeDetails: true,
      search_email: query,
      page: 1,
      page_size: 10
    });
    const emailItems = responseByEmail?.items ?? [];
    if (emailItems.length > 0) {
      return emailItems;
    }

    const responseByName = await eneo.users.list({
      includeDetails: true,
      search_name: query,
      page: 1,
      page_size: 10
    });
    return responseByName?.items ?? [];
  }

  function selectUser(user: UserSparse) {
    selectedUser = user;
    createdByUserId = user.id;
    searchQuery = user.email ?? user.username ?? "";
    userSearchResults = [];
    showUserDropdown = false;
    userSearchCompleted = false;
  }

  function handleSearchScopeChange(nextScope: "entity" | "user") {
    searchScope = nextScope;
    showSearchScopeDropdown = false;
    clearUserFilter();
    if (nextScope === "user") {
      searchQuery = "";
    }
  }

  function clearSearch() {
    searchQuery = "";
    if (searchScope === "user") {
      clearUserFilter();
    }
  }

  function handleScopedSearch(query: string) {
    searchQuery = query;
    if (searchScope !== "user") {
      return;
    }

    userSearchCompleted = false;

    if (selectedUser && query !== (selectedUser.email ?? selectedUser.username ?? "")) {
      selectedUser = null;
      createdByUserId = "";
    }

    if (query.trim().length < 3) {
      userSearchResults = [];
      showUserDropdown = false;
      isSearchingUsers = false;
      return;
    }

    clearTimeout(userSearchTimer);
    userSearchTimer = setTimeout(async () => {
      const expectedQuery = query.trim().toLowerCase();
      isSearchingUsers = true;
      try {
        const results = await searchUsers(query.trim());
        if (searchQuery.trim().toLowerCase() !== expectedQuery || searchScope !== "user") {
          return;
        }
        userSearchResults = results;
        showUserDropdown = results.length > 0;
        userSearchCompleted = true;
      } catch (error) {
        console.error(error);
        if (searchQuery.trim().toLowerCase() === expectedQuery) {
          userSearchResults = [];
          showUserDropdown = false;
          userSearchCompleted = true;
        }
      } finally {
        if (searchQuery.trim().toLowerCase() === expectedQuery) {
          isSearchingUsers = false;
        }
      }
    }, 300);
  }

  let searchScopeContainerRef: HTMLDivElement | undefined = $state();
  let userSearchContainerRef: HTMLDivElement | undefined = $state();

  function handleClickOutside(event: MouseEvent) {
    const target = event.target as HTMLElement;
    if (
      showSearchScopeDropdown &&
      searchScopeContainerRef &&
      !searchScopeContainerRef.contains(target)
    ) {
      showSearchScopeDropdown = false;
    }
    if (showUserDropdown && userSearchContainerRef && !userSearchContainerRef.contains(target)) {
      showUserDropdown = false;
    }
  }

  function resetFilters() {
    scopeType = "";
    stateFilter = "active";
    keyType = "";
    scopeId = null;
    expiresWithinDays = "";
    limit = "100";
    userRelation = "owner";
    searchQuery = "";
    searchScope = "entity";
    showSearchScopeDropdown = false;
    clearUserFilter();
    void loadKeys({ reset: true });
  }

  function applyQuickFilter(filter: { keyType: string }) {
    keyType = keyType === filter.keyType ? "" : filter.keyType;
    void loadKeys({ reset: true });
  }

  function isQuickFilterActive(filter: { keyType: string }): boolean {
    return keyType === filter.keyType;
  }

  function handleSecret(
    response: ApiKeyCreatedResponse,
    source: "created" | "rotated" = "created"
  ) {
    latestSecret = response.secret;
    secretSource = source;
    secretDialogOpen = true;
    void loadKeys({ reset: true });
  }

  async function loadApiKeyTrackingConfig() {
    trackingConfigLoading = true;
    try {
      const config = await eneo.audit.getActionConfig();
      const actions = config?.actions ?? [];
      apiKeyUsedTrackingEnabled =
        actions.find((item) => item.action === "api_key_used")?.enabled ?? false;
      apiKeyAuthFailedTrackingEnabled =
        actions.find((item) => item.action === "api_key_auth_failed")?.enabled ?? true;
      trackingConfigLoaded = true;
    } catch (error) {
      console.error(error);
      trackingConfigLoaded = false;
    } finally {
      trackingConfigLoading = false;
    }
  }

  async function updateTrackingAction(
    action: "api_key_used" | "api_key_auth_failed",
    enabled: boolean
  ) {
    const previousUsed = apiKeyUsedTrackingEnabled;
    const previousFailed = apiKeyAuthFailedTrackingEnabled;
    if (action === "api_key_used") apiKeyUsedTrackingEnabled = enabled;
    if (action === "api_key_auth_failed") apiKeyAuthFailedTrackingEnabled = enabled;

    try {
      await eneo.audit.updateActionConfig({
        updates: [{ action, enabled }]
      });
    } catch (error) {
      console.error(error);
      apiKeyUsedTrackingEnabled = previousUsed;
      apiKeyAuthFailedTrackingEnabled = previousFailed;
      errorMessage = getErrorMessage(error);
    }
  }

  async function loadAdminSettings() {
    tenantSettingsLoading = true;
    try {
      const settings = await eneo.settings.get();
      expiryNotificationsEnabled = settings.api_key_expiry_notifications ?? true;
    } catch (error) {
      console.error(error);
    } finally {
      tenantSettingsLoading = false;
    }
  }

  function parsePositiveInt(value: string): number | null {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) return null;
    return Math.floor(parsed);
  }

  function pickPolicyDefaultDay(raw: number[] | undefined): number {
    if (!raw || raw.length === 0) return 30;
    const max = Math.max(...raw);
    return Number.isFinite(max) && max > 0 ? Math.floor(max) : 30;
  }

  async function loadNotificationPolicy() {
    notificationPolicyLoading = true;
    try {
      const policy = await getAdminNotificationPolicy(eneo);
      notificationPolicy = policy;
      notificationPolicyDaysInput = String(pickPolicyDefaultDay(policy.default_days_before_expiry));
      notificationPolicyMaxDaysInput = policy.max_days_before_expiry
        ? String(policy.max_days_before_expiry)
        : "";
    } catch (error) {
      console.error(error);
    } finally {
      notificationPolicyLoading = false;
    }
  }

  async function toggleExpiryNotifications({ current, next }: { current: boolean; next: boolean }) {
    expiryNotificationsEnabled = next;
    try {
      const updated = await eneo.settings.updateApiKeyExpiryNotifications(next);
      expiryNotificationsEnabled = updated.api_key_expiry_notifications ?? true;
    } catch (error) {
      console.error(error);
      expiryNotificationsEnabled = current;
      errorMessage = getErrorMessage(error);
    }
  }

  async function saveNotificationPolicy() {
    const defaultDay = parsePositiveInt(notificationPolicyDaysInput);
    if (defaultDay === null) {
      errorMessage = m.api_keys_notifications_policy_days_validation();
      return;
    }
    const maxDays = parsePositiveInt(notificationPolicyMaxDaysInput);

    notificationPolicySaving = true;
    try {
      const updated = await updateAdminNotificationPolicy(eneo, {
        enabled: notificationPolicy.enabled,
        default_days_before_expiry: [defaultDay],
        max_days_before_expiry: maxDays,
        allow_auto_follow_published_assistants:
          notificationPolicy.allow_auto_follow_published_assistants,
        allow_auto_follow_published_apps: notificationPolicy.allow_auto_follow_published_apps
      });
      notificationPolicy = updated;
      notificationPolicyDaysInput = String(
        pickPolicyDefaultDay(updated.default_days_before_expiry)
      );
      notificationPolicyMaxDaysInput = updated.max_days_before_expiry
        ? String(updated.max_days_before_expiry)
        : "";
    } catch (error) {
      console.error(error);
      errorMessage = getErrorMessage(error);
    } finally {
      notificationPolicySaving = false;
    }
  }

  onMount(() => {
    void Promise.all([
      loadScopeResources(),
      loadKeys({ reset: true }),
      loadApiKeyTrackingConfig(),
      loadAdminSettings(),
      loadNotificationPolicy()
    ]);
    return () => {
      clearTimeout(userSearchTimer);
    };
  });
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.api_keys()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.api_keys()}></Page.Title>
    <div class="flex items-center gap-3">
      <Button variant="ghost" onclick={() => loadKeys({ reset: true })}>
        <RefreshCw class="h-4 w-4 {loading ? 'animate-spin' : ''}" />
        {m.api_keys_refresh()}
      </Button>
    </div>
  </Page.Header>

  <Page.Main>
    <Settings.Page>
      <div class="space-y-6">
        <!-- Filter Section -->
        <div class="border-default bg-primary overflow-hidden rounded-xl border shadow-sm">
          <!-- Filter Header -->
          <button
            type="button"
            onclick={() => (showFilters = !showFilters)}
            aria-expanded={showFilters}
            aria-controls="admin-api-key-filters-panel"
            class="bg-subtle/50 hover:bg-subtle flex w-full items-center justify-between px-6 py-4 transition-colors"
          >
            <div class="flex items-center gap-3">
              <div
                class="bg-primary border-default flex h-9 w-9 items-center justify-center rounded-lg border"
              >
                <Filter class="text-muted h-4 w-4" />
              </div>
              <div class="text-left">
                <h3 class="text-default text-sm font-semibold">
                  {m.api_keys_admin_filters_search()}
                </h3>
                <p class="text-muted text-xs">
                  {activeFilterCount > 0
                    ? activeFilterCount > 1
                      ? m.api_keys_admin_filters_active_plural({ count: activeFilterCount })
                      : m.api_keys_admin_filters_active({ count: activeFilterCount })
                    : m.api_keys_admin_filters_description()}
                </p>
              </div>
              {#if activeFilterCount > 0}
                <span
                  class="bg-accent-default text-on-fill inline-flex h-5 w-5 items-center justify-center rounded-full text-xs font-bold"
                >
                  {activeFilterCount}
                </span>
              {/if}
            </div>
            <ChevronDown
              class="text-muted h-5 w-5 transition-transform duration-200 {showFilters
                ? 'rotate-180'
                : ''}"
            />
          </button>

          <!-- Filter Content -->
          {#if showFilters}
            <div
              id="admin-api-key-filters-panel"
              transition:slide={{ duration: 200 }}
              class="border-default space-y-5 border-t px-6 py-5"
            >
              <!-- Search -->
              <div bind:this={userSearchContainerRef} class="relative min-w-[280px] flex-1">
                <div class="absolute top-1/2 left-2 z-10 flex -translate-y-1/2 items-center">
                  <div bind:this={searchScopeContainerRef} class="relative">
                    <button
                      type="button"
                      onclick={() => (showSearchScopeDropdown = !showSearchScopeDropdown)}
                      aria-haspopup="listbox"
                      aria-expanded={showSearchScopeDropdown}
                      class="text-muted bg-subtle/80 border-default/40 hover:bg-hover hover:text-default hover:border-default/60 focus-visible:ring-accent-default flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-xs font-semibold transition-all duration-150 focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:outline-none"
                    >
                      {searchScope === "entity"
                        ? m.audit_search_scope_entity()
                        : m.audit_search_scope_user()}
                      <ChevronDown
                        class="h-3 w-3 transition-transform duration-150 {showSearchScopeDropdown
                          ? 'rotate-180'
                          : ''}"
                      />
                    </button>

                    {#if showSearchScopeDropdown}
                      <div
                        role="listbox"
                        class="bg-primary border-default absolute top-full left-0 z-30 mt-1.5 min-w-[140px] overflow-hidden rounded-lg border py-1 shadow-lg"
                        transition:slide={{ duration: 150 }}
                      >
                        <button
                          role="option"
                          aria-selected={searchScope === "entity"}
                          type="button"
                          onclick={() => handleSearchScopeChange("entity")}
                          class="w-full px-3 py-2 text-left text-sm transition-colors {searchScope ===
                          'entity'
                            ? 'bg-accent-default/5 text-accent-default font-medium'
                            : 'text-default hover:bg-subtle'}"
                        >
                          <span class="flex items-center justify-between gap-2">
                            {m.audit_search_scope_entity()}
                            {#if searchScope === "entity"}
                              <Check class="text-accent-default h-4 w-4" />
                            {/if}
                          </span>
                        </button>
                        <button
                          role="option"
                          aria-selected={searchScope === "user"}
                          type="button"
                          onclick={() => handleSearchScopeChange("user")}
                          class="w-full px-3 py-2 text-left text-sm transition-colors {searchScope ===
                          'user'
                            ? 'bg-accent-default/5 text-accent-default font-medium'
                            : 'text-default hover:bg-subtle'}"
                        >
                          <span class="flex items-center justify-between gap-2">
                            {m.audit_search_scope_user()}
                            {#if searchScope === "user"}
                              <Check class="text-accent-default h-4 w-4" />
                            {/if}
                          </span>
                        </button>
                      </div>
                    {/if}
                  </div>

                  <div class="bg-default/40 ml-2 h-6 w-px"></div>
                </div>

                <input
                  type="text"
                  bind:value={searchQuery}
                  oninput={(event) =>
                    handleScopedSearch((event.currentTarget as HTMLInputElement).value)}
                  onfocus={() =>
                    searchScope === "user" &&
                    searchQuery.length >= 3 &&
                    userSearchResults.length > 0 &&
                    (showUserDropdown = true)}
                  placeholder={searchScope === "entity"
                    ? m.api_keys_admin_search_placeholder()
                    : m.audit_search_placeholder_user()}
                  aria-label={searchScope === "entity"
                    ? m.api_keys_admin_search_placeholder()
                    : m.audit_search_placeholder_user()}
                  autocomplete="off"
                  class="text-default border-default bg-primary placeholder:text-muted focus:border-accent-default focus:ring-accent-default/30 h-11 w-full rounded-lg border py-2 pr-10 pl-32 text-sm transition-all duration-150 focus:ring-2 focus:outline-none"
                />

                {#if isSearchingUsers && searchScope === "user"}
                  <div class="absolute top-1/2 right-8 -translate-y-1/2">
                    <div
                      class="border-accent-default h-4 w-4 animate-spin rounded-full border-2 border-t-transparent"
                    ></div>
                  </div>
                {/if}

                {#if searchQuery.length > 0}
                  <button
                    type="button"
                    onclick={clearSearch}
                    class="text-muted hover:text-default hover:bg-hover focus-visible:ring-accent-default absolute top-1/2 right-2 -translate-y-1/2 rounded-md p-1.5 transition-all duration-150 focus-visible:ring-2 focus-visible:outline-none"
                    aria-label={m.audit_search_clear()}
                  >
                    <X class="h-4 w-4" />
                  </button>
                {/if}

                {#if searchScope === "user" && showUserDropdown && userSearchResults.length > 0}
                  <div
                    role="listbox"
                    class="bg-primary border-default absolute top-full right-0 left-0 z-20 mt-2 max-h-64 overflow-y-auto rounded-lg border shadow-xl"
                    transition:slide={{ duration: 150 }}
                  >
                    {#each userSearchResults as user, index (user.id)}
                      <button
                        role="option"
                        aria-selected={false}
                        type="button"
                        onclick={() => selectUser(user)}
                        class="focus:bg-accent-default/5 hover:bg-accent-default/5 w-full px-4 py-3 text-left transition-colors focus:outline-none {index >
                        0
                          ? 'border-default/50 border-t'
                          : ''}"
                      >
                        <div class="flex items-center gap-3">
                          <div
                            class="text-accent-default bg-accent-default/10 flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold"
                          >
                            {(user.email ?? user.username ?? "U").charAt(0).toUpperCase()}
                          </div>
                          <div class="min-w-0">
                            <div class="text-default truncate text-sm font-medium">
                              {user.username ?? user.email}
                            </div>
                            <div class="text-muted truncate text-xs">{user.email}</div>
                          </div>
                        </div>
                      </button>
                    {/each}
                  </div>
                {/if}

                {#if searchScope === "user" && searchQuery.trim().length >= 3 && userSearchCompleted && userSearchResults.length === 0 && !isSearchingUsers}
                  <div
                    class="bg-primary border-default absolute top-full right-0 left-0 z-20 mt-2 rounded-lg border p-4 shadow-lg"
                    transition:slide={{ duration: 150 }}
                  >
                    <div class="flex flex-col items-center gap-2 py-2 text-center">
                      <div class="bg-muted/20 rounded-full p-2">
                        <X class="text-muted h-5 w-5" />
                      </div>
                      <p class="text-muted text-sm">{m.no_users_found()}</p>
                    </div>
                  </div>
                {/if}
              </div>

              {#if searchScope === "user"}
                <div class="space-y-1">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="text-muted text-xs font-medium"
                      >{m.api_keys_admin_user_relation_label()}</span
                    >
                    <div
                      class="border-default bg-primary inline-flex items-center gap-1 rounded-lg border p-1"
                    >
                      <button
                        type="button"
                        onclick={() => (userRelation = "owner")}
                        class="rounded-md px-2 py-1 text-xs font-medium transition-colors {userRelation ===
                        'owner'
                          ? 'bg-accent-default/10 text-accent-default'
                          : 'text-muted hover:text-default'}"
                      >
                        {m.api_keys_admin_user_relation_owner()}
                      </button>
                      <button
                        type="button"
                        onclick={() => (userRelation = "creator")}
                        class="rounded-md px-2 py-1 text-xs font-medium transition-colors {userRelation ===
                        'creator'
                          ? 'bg-accent-default/10 text-accent-default'
                          : 'text-muted hover:text-default'}"
                      >
                        {m.api_keys_admin_user_relation_creator()}
                      </button>
                    </div>
                  </div>
                  <p class="text-muted text-xs">
                    {userRelation === "owner"
                      ? m.api_keys_admin_user_relation_help_owner()
                      : m.api_keys_admin_user_relation_help_creator()}
                  </p>
                </div>
              {/if}

              {#if searchScope === "user" && selectedUser}
                <div class="flex flex-wrap items-center gap-2">
                  <span
                    class="text-accent-default bg-accent-default/10 inline-flex items-center gap-2 rounded-md px-2.5 py-1 text-xs font-medium"
                  >
                    <span>{selectedUser.email ?? selectedUser.username ?? selectedUser.id}</span>
                    <button
                      type="button"
                      onclick={clearUserFilter}
                      class="hover:bg-accent-default/20 rounded p-0.5"
                    >
                      <X class="h-3 w-3" />
                    </button>
                  </span>
                </div>
              {/if}

              <!-- Quick Filters -->
              <div class="flex flex-wrap gap-2">
                {#each quickFilters as qf (qf.label)}
                  {@const isActive = isQuickFilterActive(qf.filter)}
                  <button
                    type="button"
                    onclick={() => applyQuickFilter(qf.filter)}
                    class="inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-all
                         {isActive
                      ? 'border-accent-default bg-accent-default/10 text-accent-default ring-accent-default/20 ring-2'
                      : 'border-default bg-primary text-muted hover:border-dimmer hover:text-default'}"
                  >
                    {#if qf.filter.keyType === "sk_"}
                      <Lock class="h-3 w-3" />
                    {:else}
                      <Globe class="h-3 w-3" />
                    {/if}
                    {qf.label}
                    {#if isActive}
                      <X class="h-3 w-3" />
                    {/if}
                  </button>
                {/each}
              </div>

              <!--
                Advanced Filters: a single 2-column stack where each row pairs fields that
                belong together. Reading top-to-bottom signals "what kind of key am I looking
                for?" — scope first, then state/type, then ownership/time. Results limit lives
                in its own row at the bottom because it's a query setting, not a filter.
              -->
              <div class="grid gap-4 md:grid-cols-2">
                <!-- Row 1: scope type + its target -->
                <Field.Field>
                  <Field.Label for="filter-scope-type">
                    {m.api_keys_admin_label_scope_type()}
                  </Field.Label>
                  <Select.Root type="single" bind:value={scopeType}>
                    <Select.Trigger id="filter-scope-type">
                      {scopeOptions.find((o) => o.value === scopeType)?.label ??
                        m.api_keys_admin_scope_all()}
                    </Select.Trigger>
                    <Select.Content>
                      {#each scopeOptions as opt (opt.value)}
                        <Select.Item value={opt.value} label={opt.label}>{opt.label}</Select.Item>
                      {/each}
                    </Select.Content>
                  </Select.Root>
                </Field.Field>
                <ScopeResourceSelector
                  scopeType={scopeSelectorType}
                  bind:value={scopeId}
                  {spaces}
                  assistants={assistantOptions}
                  apps={appOptions}
                  id="filter-scope-target"
                />

                <!-- Row 2: lifecycle state + key class -->
                <Field.Field class="md:col-span-2">
                  <Field.Label>{m.api_keys_admin_label_state()}</Field.Label>
                  <ApiKeyStateFilter bind:value={stateFilter} />
                </Field.Field>
                <Field.Field>
                  <Field.Label for="filter-key-type">
                    {m.api_keys_admin_label_key_type()}
                  </Field.Label>
                  <Select.Root type="single" bind:value={keyType}>
                    <Select.Trigger id="filter-key-type">
                      {keyTypeOptions.find((o) => o.value === keyType)?.label ??
                        m.api_keys_admin_key_type_all()}
                    </Select.Trigger>
                    <Select.Content>
                      {#each keyTypeOptions as opt (opt.value)}
                        <Select.Item value={opt.value} label={opt.label}>{opt.label}</Select.Item>
                      {/each}
                    </Select.Content>
                  </Select.Root>
                </Field.Field>

                <!-- Row 3: ownership + time window -->
                <Field.Field>
                  <Field.Label for="filter-created-by">
                    {userRelation === "owner"
                      ? m.api_keys_admin_label_owner_user_id()
                      : m.api_keys_admin_label_created_by()}
                  </Field.Label>
                  <Input
                    id="filter-created-by"
                    bind:value={createdByUserId}
                    placeholder={m.api_keys_enter_uuid()}
                  />
                </Field.Field>
                <Field.Field>
                  <Field.Label for="filter-expires-within">
                    {m.api_keys_admin_expires_within_label()}
                  </Field.Label>
                  <Input
                    id="filter-expires-within"
                    bind:value={expiresWithinDays}
                    placeholder="14"
                  />
                </Field.Field>
              </div>

              <!--
                Query setting (not a filter): kept on its own row with a constrained width
                to make the categorical difference obvious. The visual gap above is the
                same `space-y-5` from the parent, so it reads as "another section".
              -->
              <Field.Field class="md:max-w-[calc(50%-0.5rem)]">
                <Field.Label for="filter-results-limit">
                  {m.api_keys_admin_label_results_limit()}
                </Field.Label>
                <Select.Root type="single" bind:value={limit}>
                  <Select.Trigger id="filter-results-limit">
                    {resultLimitOptions.find((o) => o.value === limit)?.label ?? limit}
                  </Select.Trigger>
                  <Select.Content>
                    {#each resultLimitOptions as opt (opt.value)}
                      <Select.Item value={opt.value} label={opt.label}>{opt.label}</Select.Item>
                    {/each}
                  </Select.Content>
                </Select.Root>
              </Field.Field>

              <!-- Filter Actions -->
              <div class="border-default flex items-center justify-between border-t pt-2">
                <p class="text-muted text-xs">
                  {totalCount !== null
                    ? m.api_keys_admin_keys_count({
                        filtered: keys.length,
                        total: totalCount
                      })
                    : ""}
                </p>
                <div class="flex items-center gap-2">
                  <Button variant="ghost" onclick={resetFilters} class="text-sm">
                    <X class="h-4 w-4" />
                    {m.api_keys_admin_clear_all()}
                  </Button>
                  <Button onclick={applyFilters} class="text-sm">
                    <Filter class="h-4 w-4" />
                    {m.api_keys_admin_apply_filters()}
                  </Button>
                </div>
              </div>
            </div>
          {/if}
        </div>

        <!-- Error Message -->
        {#if errorMessage}
          <div transition:fly={{ y: -8, duration: 150 }}>
            <Alert.Root variant="destructive">
              <AlertCircle />
              <Alert.Description>{errorMessage}</Alert.Description>
            </Alert.Root>
          </div>
        {/if}

        <!-- Keys Table Section -->
        <div class="border-default bg-primary overflow-hidden rounded-xl border shadow-sm">
          <div class="border-default bg-subtle/30 border-b px-6 py-4">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-3">
                <div
                  class="bg-accent-default/10 flex h-10 w-10 items-center justify-center rounded-xl"
                >
                  <Key class="text-accent-default h-5 w-5" />
                </div>
                <div>
                  <h3 class="text-default font-semibold">{m.api_keys()}</h3>
                  <p class="text-muted text-xs">
                    {totalCount !== null
                      ? m.api_keys_admin_showing_keys({
                          filtered: keys.length,
                          total: totalCount
                        })
                      : loading
                        ? m.api_keys_admin_loading_keys()
                        : m.api_keys_admin_keys_count_simple({ count: keys.length })}
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div class="p-4">
            <AdminApiKeyTable
              {keys}
              {loading}
              scopeNames={scopeNamesById}
              onChanged={() => loadKeys({ reset: true })}
              onSecret={(r) => handleSecret(r, "rotated")}
            />

            {#if nextCursor}
              <div class="mt-4 flex justify-center">
                <Button variant="outline" onclick={() => loadKeys({ reset: false })}>
                  {#if loadingMore}
                    <div
                      class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
                    ></div>
                    {m.api_keys_loading()}
                  {:else}
                    {m.api_keys_admin_load_more()}
                  {/if}
                </Button>
              </div>
            {/if}
          </div>
        </div>

        <!-- API key settings and feature flags -->
        <Settings.Group title={m.api_keys_admin_runtime_settings_title()}>
          <Settings.Row
            title={m.api_keys_notifications_feature_flag_title()}
            description={m.api_keys_notifications_feature_flag_description()}
          >
            <Switch
              checked={expiryNotificationsEnabled}
              onCheckedChange={(next) => {
                const current = expiryNotificationsEnabled;
                expiryNotificationsEnabled = next;
                void toggleExpiryNotifications({ current, next });
              }}
              disabled={tenantSettingsLoading}
              aria-label={m.api_keys_notifications_feature_flag_title()}
            />
          </Settings.Row>
        </Settings.Group>

        <!-- Notification policy -->
        <Settings.Group title={m.api_keys_notifications_policy_title()}>
          <Settings.Row
            title={m.api_keys_notifications_policy_enabled_title()}
            description={m.api_keys_notifications_policy_enabled_description()}
          >
            <Switch
              checked={notificationPolicy.enabled}
              onCheckedChange={(next) => (notificationPolicy.enabled = next)}
              disabled={notificationPolicyLoading || notificationPolicySaving}
              aria-label={m.api_keys_notifications_policy_enabled_title()}
            />
          </Settings.Row>
          <Settings.Row
            title={m.api_keys_notifications_policy_default_days_label()}
            description={m.api_keys_notifications_policy_default_days_description()}
          >
            <Field.Field>
              <Field.Label for="notification-policy-default-days" class="sr-only">
                {m.api_keys_notifications_policy_default_days_label()}
              </Field.Label>
              <Input
                id="notification-policy-default-days"
                bind:value={notificationPolicyDaysInput}
                placeholder="30"
                disabled={notificationPolicyLoading || notificationPolicySaving}
              />
            </Field.Field>
          </Settings.Row>
          <Settings.Row
            title={m.api_keys_notifications_policy_max_days_label()}
            description={m.api_keys_notifications_policy_max_days_description()}
          >
            <Field.Field>
              <Field.Label for="notification-policy-max-days" class="sr-only">
                {m.api_keys_notifications_policy_max_days_label()}
              </Field.Label>
              <Input
                id="notification-policy-max-days"
                bind:value={notificationPolicyMaxDaysInput}
                placeholder="365"
                disabled={notificationPolicyLoading || notificationPolicySaving}
              />
            </Field.Field>
          </Settings.Row>
          <Settings.Row
            title={m.api_keys_notifications_policy_autofollow_assistants_title()}
            description={m.api_keys_notifications_policy_autofollow_assistants_description()}
          >
            <Switch
              checked={notificationPolicy.allow_auto_follow_published_assistants}
              onCheckedChange={(next) =>
                (notificationPolicy.allow_auto_follow_published_assistants = next)}
              disabled={notificationPolicyLoading || notificationPolicySaving}
              aria-label={m.api_keys_notifications_policy_autofollow_assistants_title()}
            />
          </Settings.Row>
          <Settings.Row
            title={m.api_keys_notifications_policy_autofollow_apps_title()}
            description={m.api_keys_notifications_policy_autofollow_apps_description()}
          >
            <Switch
              checked={notificationPolicy.allow_auto_follow_published_apps}
              onCheckedChange={(next) =>
                (notificationPolicy.allow_auto_follow_published_apps = next)}
              disabled={notificationPolicyLoading || notificationPolicySaving}
              aria-label={m.api_keys_notifications_policy_autofollow_apps_title()}
            />
          </Settings.Row>
          <div class="flex justify-end px-4">
            <Button
              onclick={saveNotificationPolicy}
              disabled={notificationPolicyLoading || notificationPolicySaving}
            >
              {m.save()}
            </Button>
          </div>
        </Settings.Group>

        <!-- API Key Tracking Section -->
        <Settings.Group title={m.api_keys_admin_tracking_title()}>
          <Settings.Row
            title={m.api_keys_admin_tracking_used_title()}
            description={m.api_keys_admin_tracking_used_description()}
          >
            <Switch
              checked={apiKeyUsedTrackingEnabled}
              onCheckedChange={(next) => {
                apiKeyUsedTrackingEnabled = next;
                void updateTrackingAction("api_key_used", next);
              }}
              disabled={trackingConfigLoading || !trackingConfigLoaded}
              aria-label={m.api_keys_admin_tracking_used_title()}
            />
          </Settings.Row>
          <Settings.Row
            title={m.api_keys_admin_tracking_failed_title()}
            description={m.api_keys_admin_tracking_failed_description()}
          >
            <Switch
              checked={apiKeyAuthFailedTrackingEnabled}
              onCheckedChange={(next) => {
                apiKeyAuthFailedTrackingEnabled = next;
                void updateTrackingAction("api_key_auth_failed", next);
              }}
              disabled={trackingConfigLoading || !trackingConfigLoaded}
              aria-label={m.api_keys_admin_tracking_failed_title()}
            />
          </Settings.Row>
          <div class="px-4">
            <a
              href={resolve("/admin/audit-logs?tab=config")}
              class="text-accent-default hover:text-accent-default/80 inline-flex items-center gap-1.5 text-sm font-medium"
            >
              {m.api_keys_admin_tracking_open_audit_config()}
            </a>
          </div>
        </Settings.Group>

        <!-- Policy Section -->
        <Settings.Group title={m.api_keys_admin_tenant_policy()}>
          <div class="flex flex-col gap-2 px-4 lg:pr-6 lg:pl-2">
            <p class="text-secondary text-sm whitespace-pre-wrap">
              {m.api_keys_admin_policy_description()}
            </p>
            <ApiKeyPolicyPanel />
          </div>
        </Settings.Group>

        <!-- Super Key Status Section -->
        <Settings.Group title={m.api_keys_admin_super_key_status()}>
          <div class="flex flex-col gap-2 px-4 lg:pr-6 lg:pl-2">
            <p class="text-secondary text-sm whitespace-pre-wrap">
              {m.api_keys_admin_super_key_description()}
            </p>
            <SuperKeyStatusPanel />
          </div>
        </Settings.Group>
      </div>
    </Settings.Page>
  </Page.Main>
</Page.Root>

<svelte:window
  onclick={(e) => {
    if (showSearchScopeDropdown || showUserDropdown) handleClickOutside(e);
  }}
/>

<ApiKeySecretDialog bind:open={secretDialogOpen} secret={latestSecret} source={secretSource} />
