<script lang="ts">
  import { onMount } from "svelte";
  import { Page, Settings } from "$lib/components/layout";
  import { Button, CodeBlock, Dialog, Input, Select, Label } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import type { ApiKeyCreatedResponse, ApiKeyV2, SpaceSparse } from "@intric/intric-js";
  import AdminApiKeyTable from "./AdminApiKeyTable.svelte";
  import ApiKeyPolicyPanel from "./ApiKeyPolicyPanel.svelte";
  import SuperKeyStatusPanel from "./SuperKeyStatusPanel.svelte";
  import ScopeResourceSelector from "../../account/api-keys/ScopeResourceSelector.svelte";
  import {
    Search,
    Filter,
    X,
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

  let keys = $state<ApiKeyV2[]>([]);
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
  let limit = $state("100");
  let searchQuery = $state("");

  // UI states
  let showFilters = $state(true);
  let secretDialogOpen = $state<Dialog.OpenState>(undefined);
  let latestSecret = $state<string | null>(null);

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
  const activeFilterCount = $derived(
    [scopeType, stateFilter, keyType, scopeId.trim(), createdByUserId.trim()].filter(Boolean).length
  );

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
    if (createdByUserId.trim()) params.created_by_user_id = createdByUserId.trim();
    return params;
  }

  async function loadKeys({ reset }: { reset: boolean }) {
    if (reset) {
      loading = true;
      errorMessage = null;
    } else {
      loadingMore = true;
    }

    try {
      const response = await intric.apiKeys.admin.list(buildParams(reset ? null : nextCursor));
      const items = response.items ?? [];
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

  function resetFilters() {
    scopeType = "";
    stateFilter = "";
    keyType = "";
    scopeId = "";
    createdByUserId = "";
    limit = "100";
    searchQuery = "";
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

  function handleSecret(response: ApiKeyCreatedResponse) {
    latestSecret = response.secret;
    secretDialogOpen = true;
    void loadKeys({ reset: true });
  }

  // Filter keys by search query (client-side)
  const filteredKeys = $derived.by(() => {
    if (!searchQuery.trim()) return keys;
    const query = searchQuery.toLowerCase();
    return keys.filter(
      (key) =>
        key.name.toLowerCase().includes(query) ||
        key.key_suffix?.toLowerCase().includes(query) ||
        key.scope_id?.toLowerCase().includes(query)
    );
  });

  onMount(() => {
    void Promise.all([loadScopeResources(), loadKeys({ reset: true })]);
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
            <div class="relative">
              <Search
                class="text-muted pointer-events-none absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2"
              />
              <Input.Text
                bind:value={searchQuery}
                placeholder={m.api_keys_admin_search_placeholder()}
                aria-label={m.api_keys_admin_search_placeholder()}
                class="!h-11 !pl-10"
              />
              {#if searchQuery}
                <button
                  type="button"
                  onclick={() => (searchQuery = "")}
                  class="hover:bg-hover text-muted hover:text-default absolute top-1/2 right-3 -translate-y-1/2 rounded p-1 transition-colors"
                >
                  <X class="h-4 w-4" />
                </button>
              {/if}
            </div>

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
                label={m.api_keys_admin_label_created_by()}
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
                      filtered: filteredKeys.length,
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
                        filtered: filteredKeys.length,
                        total: totalCount
                      })
                    : loading
                      ? m.api_keys_admin_loading_keys()
                      : m.api_keys_admin_keys_count_simple({ count: filteredKeys.length })}
                </p>
              </div>
            </div>
          </div>
        </div>

        <div class="p-4">
          <AdminApiKeyTable
            keys={filteredKeys}
            {loading}
            scopeNames={scopeNamesById}
            onChanged={() => loadKeys({ reset: true })}
            onSecret={handleSecret}
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

<Dialog.Root bind:isOpen={secretDialogOpen} alert>
  <Dialog.Content width="medium">
    <Dialog.Title class="flex items-center gap-3">
      <div
        class="flex h-10 w-10 items-center justify-center rounded-xl bg-green-100 dark:bg-green-900/30"
      >
        <Key class="h-5 w-5 text-green-600 dark:text-green-400" />
      </div>
      <span>{m.api_key()}</span>
    </Dialog.Title>
    <Dialog.Description>
      <div class="mt-2 flex items-start gap-2 text-yellow-700 dark:text-yellow-300">
        <AlertCircle class="mt-0.5 h-4 w-4 flex-shrink-0" />
        <span>{@html m.generate_api_key_warning()}</span>
      </div>
    </Dialog.Description>
    {#if latestSecret}
      <div class="mt-5">
        <CodeBlock code={latestSecret} />
        <div class="mt-4 flex items-center gap-3">
          <Button
            variant="primary"
            on:click={() => {
              navigator.clipboard.writeText(latestSecret ?? "");
            }}
            class="gap-2"
          >
            {m.api_keys_admin_copy_key()}
          </Button>
        </div>
      </div>
    {/if}
    <Dialog.Controls let:close>
      <Button is={close} variant="outlined">{m.close()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
