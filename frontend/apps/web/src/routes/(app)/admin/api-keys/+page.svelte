<script lang="ts">
  import { onMount } from "svelte";
  import { writable } from "svelte/store";
  import { Page, Settings } from "$lib/components/layout";
  import { Button, Input, Select, Label } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import type { ApiKeyCreatedResponse, ApiKeyV2, SpaceSparse, UserSparse } from "@intric/intric-js";
  import AdminApiKeyTable from "./AdminApiKeyTable.svelte";
  import ApiKeyPolicyPanel from "./ApiKeyPolicyPanel.svelte";
  import SuperKeyStatusPanel from "./SuperKeyStatusPanel.svelte";
  import ScopeResourceSelector from "../../account/api-keys/ScopeResourceSelector.svelte";
  import ApiKeySecretDialog from "../../account/api-keys/ApiKeySecretDialog.svelte";
  import {
    Search,
    Filter,
    X,
    Check,
    Key,
    AlertCircle,
    ChevronDown,
    RefreshCw,
    Building2,
    Shield,
    Lock,
    Globe
  } from "lucide-svelte";
  import { fly, slide } from "svelte/transition";

  const intric = getIntric();

  type AdminApiKey = ApiKeyV2 & {
    owner_user?: { id: string; email?: string | null; username?: string | null } | null;
    created_by_user?: { id: string; email?: string | null; username?: string | null } | null;
    search_match_reasons?: string[] | null;
  };

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
  let stateFilter = $state("");
  let keyType = $state("");
  let scopeId = $state("");
  let createdByUserId = $state("");
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
  const secretDialogOpen = writable(false);
  let latestSecret = $state<string | null>(null);
  let secretSource = $state<"created" | "rotated">("created");
  let trackingConfigLoading = $state(false);
  let trackingConfigLoaded = $state(false);
  let apiKeyUsedTrackingEnabled = $state(false);
  let apiKeyAuthFailedTrackingEnabled = $state(true);

  // Quick filter chips
  const quickFilters = $derived([
    {
      label: m.api_keys_admin_quick_active(),
      filter: { state: "active" },
      color: "green" as const
    },
    {
      label: m.api_keys_admin_quick_suspended(),
      filter: { state: "suspended" },
      color: "yellow" as const
    },
    {
      label: m.api_keys_admin_quick_expired(),
      filter: { state: "expired" },
      color: "gray" as const
    },
    {
      label: m.api_keys_admin_quick_revoked(),
      filter: { state: "revoked" },
      color: "red" as const
    },
    { label: m.api_keys_admin_quick_secret(), filter: { keyType: "sk_" }, color: "blue" as const },
    { label: m.api_keys_admin_quick_public(), filter: { keyType: "pk_" }, color: "orange" as const }
  ]);

  const scopeOptions = $derived([
    { value: "", label: m.api_keys_admin_scope_all() },
    { value: "tenant", label: m.api_keys_admin_scope_tenant() },
    { value: "space", label: m.api_keys_admin_scope_space() },
    { value: "assistant", label: m.api_keys_admin_scope_assistant() },
    { value: "app", label: m.api_keys_admin_scope_app() }
  ]);

  const stateOptions = $derived([
    { value: "", label: m.api_keys_admin_state_all() },
    { value: "active", label: m.api_keys_admin_state_active() },
    { value: "suspended", label: m.api_keys_admin_state_suspended() },
    { value: "revoked", label: m.api_keys_admin_state_revoked() },
    { value: "expired", label: m.api_keys_admin_state_expired() }
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
    let count = [scopeType, stateFilter, keyType, scopeId.trim()].filter(Boolean).length;
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
    if (scopeId.trim()) params.scope_id = scopeId.trim();
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

      if (
        reset &&
        searchScope === "entity" &&
        isLikelyFullApiKeySecret(searchQuery)
      ) {
        try {
          const lookupResponse = await intric.apiKeys.admin.lookup({
            secret: searchQuery.trim()
          });
          keys = lookupResponse?.api_key ? [lookupResponse.api_key as AdminApiKey] : [];
          nextCursor = null;
          totalCount = keys.length;
          errorMessage = null;
          return;
        } catch (lookupError) {
          if (lookupError?.status === 404) {
            // Graceful fallback: if exact secret lookup misses (typo/old secret), still
            // search by key suffix so admins can locate candidate keys quickly.
            forcedSearchFallback = getSecretSuffixFallback(searchQuery);
          }
          if (lookupError?.status !== 404) throw lookupError;
        }
      }

      const params = buildParams(reset ? null : nextCursor);
      if (forcedSearchFallback) {
        params.search = forcedSearchFallback;
      }
      const response = await intric.apiKeys.admin.list(params);
      const items = (response.items ?? []) as AdminApiKey[];
      keys = reset ? items : [...keys, ...items];
      nextCursor = response.next_cursor ?? null;
      totalCount = response.total_count ?? null;
    } catch (error) {
      console.error(error);
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
    } finally {
      loading = false;
      loadingMore = false;
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
      } catch (error) {
        console.error(error);
      }

      if (listedSpaces.length === 0) {
        listedSpaces = await intric.spaces.list();
      }

      spaces = listedSpaces;

      const applicationsBySpace = await Promise.all(
        spaces.map(async (space) => {
          try {
            const applications = await intric.spaces.listApplications({ id: space.id });
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
          const assistants = await intric.assistants.list();
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
    const responseByEmail = await intric.users.list({
      includeDetails: true,
      search_email: query,
      page: 1,
      page_size: 10
    });
    const emailItems = responseByEmail?.items ?? [];
    if (emailItems.length > 0) {
      return emailItems;
    }

    const responseByName = await intric.users.list({
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

  function handleClickOutside(event: MouseEvent) {
    const target = event.target as HTMLElement;
    if (
      showSearchScopeDropdown &&
      !target.closest(".api-keys-search-scope-container") &&
      !target.closest(".scope-dropdown-container")
    ) {
      showSearchScopeDropdown = false;
    }
    if (
      showUserDropdown &&
      !target.closest(".api-keys-user-search-container") &&
      !target.closest(".user-dropdown-container")
    ) {
      showUserDropdown = false;
    }
  }

  function resetFilters() {
    scopeType = "";
    stateFilter = "";
    keyType = "";
    scopeId = "";
    limit = "100";
    userRelation = "owner";
    searchQuery = "";
    searchScope = "entity";
    showSearchScopeDropdown = false;
    clearUserFilter();
    void loadKeys({ reset: true });
  }

  function applyQuickFilter(filter: { state?: string; keyType?: string }) {
    if (filter.state) {
      stateFilter = stateFilter === filter.state ? "" : filter.state;
    }
    if (filter.keyType) {
      keyType = keyType === filter.keyType ? "" : filter.keyType;
    }
    void loadKeys({ reset: true });
  }

  function isQuickFilterActive(filter: { state?: string; keyType?: string }): boolean {
    if (filter.state) return stateFilter === filter.state;
    if (filter.keyType) return keyType === filter.keyType;
    return false;
  }

  function handleSecret(response: ApiKeyCreatedResponse, source: "created" | "rotated" = "created") {
    latestSecret = response.secret;
    secretSource = source;
    secretDialogOpen.set(true);
    void loadKeys({ reset: true });
  }

  async function loadApiKeyTrackingConfig() {
    trackingConfigLoading = true;
    try {
      const config = await intric.audit.getActionConfig();
      const actions = config?.actions ?? [];
      apiKeyUsedTrackingEnabled = actions.find((item) => item.action === "api_key_used")?.enabled ?? false;
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

  async function updateTrackingAction(action: "api_key_used" | "api_key_auth_failed", enabled: boolean) {
    const previousUsed = apiKeyUsedTrackingEnabled;
    const previousFailed = apiKeyAuthFailedTrackingEnabled;
    if (action === "api_key_used") apiKeyUsedTrackingEnabled = enabled;
    if (action === "api_key_auth_failed") apiKeyAuthFailedTrackingEnabled = enabled;

    try {
      await intric.audit.updateActionConfig({
        updates: [{ action, enabled }]
      });
    } catch (error) {
      console.error(error);
      apiKeyUsedTrackingEnabled = previousUsed;
      apiKeyAuthFailedTrackingEnabled = previousFailed;
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
    }
  }

  onMount(() => {
    void Promise.all([loadScopeResources(), loadKeys({ reset: true }), loadApiKeyTrackingConfig()]);
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
    <Page.Title title={m.api_keys()}>
      <div slot="actions" class="flex items-center gap-3">
        <Button variant="ghost" on:click={() => loadKeys({ reset: true })} class="gap-2">
          <RefreshCw class="h-4 w-4 {loading ? 'animate-spin' : ''}" />
          {m.api_keys_refresh()}
        </Button>
      </div>
    </Page.Title>
  </Page.Header>

  <Page.Main>
    <div class="space-y-6 py-4 pr-4">
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
            <div class="api-keys-user-search-container scope-dropdown-container user-dropdown-container relative flex-1 min-w-[280px]">
              <div class="absolute top-1/2 left-2 z-10 flex -translate-y-1/2 items-center">
                <button
                  type="button"
                  onclick={() => (showSearchScopeDropdown = !showSearchScopeDropdown)}
                  aria-haspopup="listbox"
                  aria-expanded={showSearchScopeDropdown}
                  class="text-muted bg-subtle/80 border-default/40 hover:bg-hover hover:text-default hover:border-default/60 flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-xs font-semibold transition-all duration-150 focus-visible:ring-2 focus-visible:ring-accent-default focus-visible:ring-offset-1 focus-visible:outline-none"
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
                      class="w-full px-3 py-2 text-left text-sm transition-colors {searchScope === 'entity'
                        ? 'bg-accent-default/5 text-accent-default font-medium'
                        : 'text-default hover:bg-subtle'}"
                    >
                      <span class="flex items-center justify-between gap-2">
                        {m.audit_search_scope_entity()}
                        {#if searchScope === "entity"}
                          <Check class="h-4 w-4 text-accent-default" />
                        {/if}
                      </span>
                    </button>
                    <button
                      role="option"
                      aria-selected={searchScope === "user"}
                      type="button"
                      onclick={() => handleSearchScopeChange("user")}
                      class="w-full px-3 py-2 text-left text-sm transition-colors {searchScope === 'user'
                        ? 'bg-accent-default/5 text-accent-default font-medium'
                        : 'text-default hover:bg-subtle'}"
                    >
                      <span class="flex items-center justify-between gap-2">
                        {m.audit_search_scope_user()}
                        {#if searchScope === "user"}
                          <Check class="h-4 w-4 text-accent-default" />
                        {/if}
                      </span>
                    </button>
                  </div>
                {/if}

                <div class="bg-default/40 ml-2 h-6 w-px"></div>
              </div>

              <input
                type="text"
                bind:value={searchQuery}
                oninput={(event) => handleScopedSearch((event.currentTarget as HTMLInputElement).value)}
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
                  class="text-muted hover:text-default hover:bg-hover absolute top-1/2 right-2 -translate-y-1/2 rounded-md p-1.5 transition-all duration-150 focus-visible:ring-2 focus-visible:ring-accent-default focus-visible:outline-none"
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
                  {#each userSearchResults as user, index}
                    <button
                      role="option"
                      aria-selected={false}
                      type="button"
                      onclick={() => selectUser(user)}
                      class="focus:bg-accent-default/5 hover:bg-accent-default/5 w-full px-4 py-3 text-left transition-colors focus:outline-none {index > 0
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
                  <span class="text-muted text-xs font-medium">{m.api_keys_admin_user_relation_label()}</span>
                  <div class="inline-flex items-center gap-1 rounded-lg border border-default bg-primary p-1">
                    <button
                      type="button"
                      onclick={() => (userRelation = "owner")}
                      class="rounded-md px-2 py-1 text-xs font-medium transition-colors {userRelation === 'owner'
                        ? 'bg-accent-default/10 text-accent-default'
                        : 'text-muted hover:text-default'}"
                    >
                      {m.api_keys_admin_user_relation_owner()}
                    </button>
                    <button
                      type="button"
                      onclick={() => (userRelation = "creator")}
                      class="rounded-md px-2 py-1 text-xs font-medium transition-colors {userRelation === 'creator'
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
              {#each quickFilters as qf}
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
                  {:else if qf.filter.keyType === "pk_"}
                    <Globe class="h-3 w-3" />
                  {:else}
                    <span
                      class="h-2 w-2 rounded-full
                             {qf.color === 'green' ? 'bg-green-500' : ''}
                             {qf.color === 'yellow' ? 'bg-yellow-500' : ''}
                             {qf.color === 'gray' ? 'bg-gray-500' : ''}
                             {qf.color === 'red' ? 'bg-red-500' : ''}
                             {qf.color === 'blue' ? 'bg-blue-500' : ''}
                             {qf.color === 'orange' ? 'bg-orange-500' : ''}"
                    ></span>
                  {/if}
                  {qf.label}
                  {#if isActive}
                    <X class="h-3 w-3" />
                  {/if}
                </button>
              {/each}
            </div>

            <!-- Advanced Filters -->
            <div class="grid gap-4 md:grid-cols-3">
              <Select.Simple bind:value={scopeType} options={scopeOptions} resourceName="scope">
                {m.api_keys_admin_label_scope_type()}
              </Select.Simple>
              <Select.Simple bind:value={stateFilter} options={stateOptions} resourceName="state">
                {m.api_keys_admin_label_state()}
              </Select.Simple>
              <Select.Simple bind:value={keyType} options={keyTypeOptions} resourceName="key type">
                {m.api_keys_admin_label_key_type()}
              </Select.Simple>
            </div>

            <div class="grid gap-4 md:grid-cols-3">
              {#if scopeSelectorType}
                <ScopeResourceSelector
                  scopeType={scopeSelectorType}
                  bind:value={scopeId}
                  {spaces}
                  assistants={assistantOptions}
                  apps={appOptions}
                />
              {:else}
                <div></div>
              {/if}
              <Input.Text
                bind:value={createdByUserId}
                label={userRelation === "owner"
                  ? m.api_keys_admin_label_owner_user_id()
                  : m.api_keys_admin_label_created_by()}
                placeholder={m.api_keys_enter_uuid()}
              />
              <Select.Simple
                bind:value={limit}
                options={resultLimitOptions}
                resourceName="results limit"
              >
                {m.api_keys_admin_label_results_limit()}
              </Select.Simple>
            </div>

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
                <Button variant="ghost" on:click={resetFilters} class="text-sm">
                  <X class="mr-1.5 h-4 w-4" />
                  {m.api_keys_admin_clear_all()}
                </Button>
                <Button variant="primary" on:click={applyFilters} class="text-sm">
                  <Filter class="mr-1.5 h-4 w-4" />
                  {m.api_keys_admin_apply_filters()}
                </Button>
              </div>
            </div>
          </div>
        {/if}
      </div>

      <!-- Error Message -->
      {#if errorMessage}
        <div
          class="flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-5 py-4 dark:border-red-900 dark:bg-red-950/50"
          transition:fly={{ y: -8, duration: 150 }}
        >
          <AlertCircle class="h-5 w-5 flex-shrink-0 text-red-600 dark:text-red-400" />
          <p class="text-sm text-red-700 dark:text-red-300">{errorMessage}</p>
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
              <Button variant="outlined" on:click={() => loadKeys({ reset: false })} class="gap-2">
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

      <!-- API Key Tracking Section -->
      <div class="border-default bg-primary overflow-hidden rounded-xl border shadow-sm">
        <div class="border-default bg-subtle/30 border-b px-6 py-4">
          <div class="flex items-center gap-3">
            <div
              class="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-100 dark:bg-blue-900/30"
            >
              <Search class="h-5 w-5 text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <h3 class="text-default font-semibold">{m.api_keys_admin_tracking_title()}</h3>
              <p class="text-muted text-xs">{m.api_keys_admin_tracking_description()}</p>
            </div>
          </div>
        </div>
        <div class="space-y-4 p-6">
          <Settings.Row
            title={m.api_keys_admin_tracking_used_title()}
            description={m.api_keys_admin_tracking_used_description()}
          >
            <Input.Switch
              bind:value={apiKeyUsedTrackingEnabled}
              sideEffect={({ next }) => updateTrackingAction("api_key_used", next)}
              disabled={trackingConfigLoading || !trackingConfigLoaded}
            />
          </Settings.Row>
          <Settings.Row
            title={m.api_keys_admin_tracking_failed_title()}
            description={m.api_keys_admin_tracking_failed_description()}
          >
            <Input.Switch
              bind:value={apiKeyAuthFailedTrackingEnabled}
              sideEffect={({ next }) => updateTrackingAction("api_key_auth_failed", next)}
              disabled={trackingConfigLoading || !trackingConfigLoaded}
            />
          </Settings.Row>
          <a
            href="/admin/audit-logs?tab=config"
            class="text-accent-default hover:text-accent-default/80 inline-flex items-center gap-1.5 text-xs font-medium"
          >
            {m.api_keys_admin_tracking_open_audit_config()}
          </a>
        </div>
      </div>

      <!-- Policy Section -->
      <div class="border-default bg-primary overflow-hidden rounded-xl border shadow-sm">
        <div class="border-default bg-subtle/30 border-b px-6 py-4">
          <div class="flex items-center gap-3">
            <div
              class="flex h-10 w-10 items-center justify-center rounded-xl bg-purple-100 dark:bg-purple-900/30"
            >
              <Shield class="h-5 w-5 text-purple-600 dark:text-purple-400" />
            </div>
            <div>
              <h3 class="text-default font-semibold">{m.api_keys_admin_tenant_policy()}</h3>
              <p class="text-muted text-xs">{m.api_keys_admin_policy_description()}</p>
            </div>
          </div>
        </div>
        <div class="p-6">
          <ApiKeyPolicyPanel />
        </div>
      </div>

      <!-- Super Key Status Section -->
      <div class="border-default bg-primary overflow-hidden rounded-xl border shadow-sm">
        <div class="border-default bg-subtle/30 border-b px-6 py-4">
          <div class="flex items-center gap-3">
            <div
              class="flex h-10 w-10 items-center justify-center rounded-xl bg-orange-100 dark:bg-orange-900/30"
            >
              <Building2 class="h-5 w-5 text-orange-600 dark:text-orange-400" />
            </div>
            <div>
              <h3 class="text-default font-semibold">{m.api_keys_admin_super_key_status()}</h3>
              <p class="text-muted text-xs">{m.api_keys_admin_super_key_description()}</p>
            </div>
          </div>
        </div>
        <div class="p-6">
          <SuperKeyStatusPanel />
        </div>
      </div>
    </div>
  </Page.Main>
</Page.Root>

<svelte:window onclick={handleClickOutside} />

<ApiKeySecretDialog
  openController={secretDialogOpen}
  secret={latestSecret}
  source={secretSource}
/>
