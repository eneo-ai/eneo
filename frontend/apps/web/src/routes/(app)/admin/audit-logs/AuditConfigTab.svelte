<script lang="ts">
  import { Button, Input } from "@eneo/ui";
  import { getEneo } from "$lib/core/Eneo";
  import * as m from "$lib/paraglide/messages";
  import type { components } from "@eneo/eneo-js";
  import { getActionLabel, getActionDescription } from "./audit-action-labels";
  import { getCategoryLabel, getCategoryDescription } from "./audit-category-labels";
  import { ChevronRight, Search, Check, X } from "lucide-svelte";
  import { onMount } from "svelte";
  import { slide, fly } from "svelte/transition";
  import { SvelteSet } from "svelte/reactivity";

  const eneo = getEneo();

  // Display text is resolved from translation keys, not the API payload.
  type CategoryConfigItem = components["schemas"]["CategoryConfig"];
  type ActionConfigItem = components["schemas"]["ActionConfig"];

  // State
  let categoryConfig = $state<CategoryConfigItem[]>([]);
  let actionConfig = $state<ActionConfigItem[]>([]);
  const expandedCategories = new SvelteSet<string>();
  let searchQuery = $state("");
  let isLoading = $state(true);
  let showLoading = $state(false); // Only show loading spinner after 200ms delay
  let isSaving = $state(false);
  let hasChanges = $state(false);
  let originalCategoryConfig: CategoryConfigItem[] = [];
  let originalActionConfig: ActionConfigItem[] = [];

  // Show loading indicator only after 200ms delay (prevents flash for fast loads)
  $effect(() => {
    if (isLoading) {
      const timeoutId = setTimeout(() => {
        showLoading = true;
      }, 200);
      return () => clearTimeout(timeoutId);
    } else {
      showLoading = false;
    }
  });

  // Filtered actions based on search
  let filteredActionsByCategory = $derived.by(() => {
    if (!searchQuery) {
      return groupActionsByCategory(actionConfig);
    }

    const query = searchQuery.toLowerCase();
    const filtered = actionConfig.filter(
      (action) =>
        action.action.toLowerCase().includes(query) ||
        getActionLabel(action.action).toLowerCase().includes(query) ||
        getActionDescription(action.action).toLowerCase().includes(query)
    );

    return groupActionsByCategory(filtered);
  });

  // Group actions by category
  function groupActionsByCategory(actions: ActionConfigItem[]): Record<string, ActionConfigItem[]> {
    const grouped: Record<string, ActionConfigItem[]> = {};
    for (const action of actions) {
      if (!grouped[action.category]) {
        grouped[action.category] = [];
      }
      grouped[action.category].push(action);
    }
    return grouped;
  }

  // Toggle category expansion
  function toggleCategory(category: string) {
    if (expandedCategories.has(category)) {
      expandedCategories.delete(category);
    } else {
      expandedCategories.add(category);
    }
  }

  // Toggle all actions in a category with proper Svelte 5 reactivity
  function toggleAllInCategory(category: string, enabled: boolean) {
    // Create new array with updated actions
    actionConfig = actionConfig.map((action) => {
      if (action.category === category) {
        return { ...action, enabled };
      }
      return action;
    });

    // Update category enabled state
    categoryConfig = categoryConfig.map((cat) => {
      if (cat.category === category) {
        return { ...cat, enabled };
      }
      return cat;
    });

    checkForChanges();
  }

  // Toggle individual action with proper Svelte 5 reactivity
  function toggleAction(actionId: string, categoryId: string) {
    // Find the current action to get its state
    const currentAction = actionConfig.find((a) => a.action === actionId);
    if (!currentAction) return;

    const newEnabledState = !currentAction.enabled;

    // Create new array with updated action
    actionConfig = actionConfig.map((a) => {
      if (a.action === actionId) {
        return { ...a, enabled: newEnabledState };
      }
      return a;
    });

    // Check if all actions in the category have the same state
    const categoryActions = actionConfig.filter((a) => a.category === categoryId);
    const allEnabled = categoryActions.every((a) => a.enabled);
    const allDisabled = categoryActions.every((a) => !a.enabled);

    // Update category state based on actions
    categoryConfig = categoryConfig.map((cat) => {
      if (cat.category === categoryId) {
        if (allEnabled) {
          return { ...cat, enabled: true };
        } else if (allDisabled) {
          return { ...cat, enabled: false };
        }
        return cat;
      }
      return cat;
    });

    checkForChanges();
  }

  // Check if there are unsaved changes
  function checkForChanges() {
    const categoryChanged =
      JSON.stringify(categoryConfig) !== JSON.stringify(originalCategoryConfig);
    const actionChanged = JSON.stringify(actionConfig) !== JSON.stringify(originalActionConfig);
    hasChanges = categoryChanged || actionChanged;
  }

  // Count enabled actions in a category
  function countEnabledInCategory(category: string) {
    const actions = actionConfig.filter((a) => a.category === category);
    const enabled = actions.filter((a) => a.enabled).length;
    return { enabled, total: actions.length };
  }

  // Load configuration
  async function loadConfig() {
    try {
      isLoading = true;

      // Load both category and action config in parallel
      const [catConfig, actConfig] = await Promise.all([
        eneo.audit.getConfig(),
        eneo.audit.getActionConfig()
      ]);

      categoryConfig = catConfig.categories;
      actionConfig = actConfig.actions;

      // Store originals for change detection
      originalCategoryConfig = JSON.parse(JSON.stringify(catConfig.categories));
      originalActionConfig = JSON.parse(JSON.stringify(actConfig.actions));
    } catch (error) {
      console.error("Failed to load audit configuration:", error);
    } finally {
      isLoading = false;
    }
  }

  // Save configuration
  async function saveConfig() {
    try {
      isSaving = true;

      // Prepare category updates
      const categoryUpdates = categoryConfig.map((cat) => ({
        category: cat.category,
        enabled: cat.enabled
      }));

      // Prepare action updates (only send changed actions)
      const actionUpdates = [];
      for (let i = 0; i < actionConfig.length; i++) {
        if (actionConfig[i].enabled !== originalActionConfig[i].enabled) {
          actionUpdates.push({
            action: actionConfig[i].action,
            enabled: actionConfig[i].enabled
          });
        }
      }

      // Update both in parallel if there are changes
      const updates = [];
      if (JSON.stringify(categoryConfig) !== JSON.stringify(originalCategoryConfig)) {
        updates.push(eneo.audit.updateConfig({ updates: categoryUpdates }));
      }
      if (actionUpdates.length > 0) {
        updates.push(eneo.audit.updateActionConfig({ updates: actionUpdates }));
      }

      if (updates.length > 0) {
        await Promise.all(updates);

        // Reload to get fresh data
        await loadConfig();
        hasChanges = false;
      }
    } catch (error) {
      console.error("Failed to save audit configuration:", error);
    } finally {
      isSaving = false;
    }
  }

  // Reset to original
  function resetChanges() {
    categoryConfig = JSON.parse(JSON.stringify(originalCategoryConfig));
    actionConfig = JSON.parse(JSON.stringify(originalActionConfig));
    hasChanges = false;
  }

  // Expand all categories
  function expandAll() {
    for (const category of categoryConfig) {
      expandedCategories.add(category.category);
    }
  }

  // Collapse all categories
  function collapseAll() {
    expandedCategories.clear();
  }

  onMount(() => {
    loadConfig();
  });
</script>

{#if isLoading && showLoading}
  <div class="animate-pulse space-y-3">
    <!-- Skeleton header card -->
    <div class="border-default bg-subtle rounded-xl border p-6">
      <div class="bg-default/10 mb-3 h-6 w-48 rounded"></div>
      <div class="bg-default/10 mb-5 h-4 w-96 rounded"></div>
      <div class="flex gap-3">
        <div class="bg-default/10 h-11 flex-1 rounded"></div>
        <div class="bg-default/10 h-11 w-24 rounded"></div>
        <div class="bg-default/10 h-11 w-24 rounded"></div>
      </div>
    </div>
    <!-- Skeleton category cards -->
    {#each Array(5) as _, i (i)}
      <div class="border-default bg-primary h-20 rounded-xl border"></div>
    {/each}
  </div>
{:else if !isLoading}
  <!-- Header Section with improved styling -->
  <div class="border-default bg-subtle mb-6 rounded-xl border p-6 shadow-sm">
    <div class="mb-5">
      <h3 class="text-default mb-2 text-lg font-semibold">{m.audit_config_header()}</h3>
      <p class="text-muted text-sm leading-relaxed">{m.audit_config_description()}</p>
    </div>

    <!-- Search and Controls with better spacing -->
    <div class="flex flex-col gap-3 sm:flex-row">
      <div class="relative flex-1">
        <Search
          class="text-muted pointer-events-none absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2"
        />
        <Input.Text
          bind:value={searchQuery}
          placeholder={m.audit_config_search_placeholder()}
          class="h-11 pl-10 text-sm"
        />
      </div>
      <div class="flex gap-2">
        <Button
          variant="simple"
          onclick={expandAll}
          size="sm"
          class="h-11 px-4 text-sm font-medium"
        >
          {m.audit_config_expand_all()}
        </Button>
        <Button
          variant="simple"
          onclick={collapseAll}
          size="sm"
          class="h-11 px-4 text-sm font-medium"
        >
          {m.audit_config_collapse_all()}
        </Button>
      </div>
    </div>
  </div>

  <!-- Categories and Actions with improved styling -->
  <div class="space-y-3">
    {#each categoryConfig as category (category.category)}
      {@const actions = filteredActionsByCategory[category.category] || []}
      {@const { enabled: enabledCount, total: totalCount } = countEnabledInCategory(
        category.category
      )}
      {@const isExpanded = expandedCategories.has(category.category)}

      {#if actions.length > 0 || !searchQuery}
        <div
          class="border-default bg-primary overflow-hidden rounded-xl border shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md"
        >
          <!-- Category Header with improved layout -->
          <div class="bg-subtle border-default border-b px-6 py-4">
            <div class="flex items-center justify-between gap-4">
              <button
                onclick={() => toggleCategory(category.category)}
                class="hover:text-accent-default group flex min-w-0 flex-1 items-center gap-3 text-left transition-colors"
              >
                <div
                  class="group-hover:bg-hover flex-shrink-0 rounded-md p-1 transition-all duration-200"
                >
                  <ChevronRight
                    class={`h-4 w-4 transition-transform duration-200 ${isExpanded ? "text-default rotate-90" : "text-muted"}`}
                  />
                </div>
                <span class="text-default truncate text-sm font-semibold"
                  >{getCategoryLabel(category.category)}</span
                >
                <span
                  class="bg-primary text-muted border-default inline-flex flex-shrink-0 items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold"
                >
                  <span class={enabledCount > 0 ? "text-accent-default" : ""}>{enabledCount}</span>
                  <span class="text-muted/50">/</span>
                  <span>{totalCount}</span>
                </span>
              </button>
              <div class="flex flex-shrink-0 items-center gap-3">
                <Input.Switch
                  value={category.enabled}
                  sideEffect={() => toggleAllInCategory(category.category, !category.enabled)}
                />
              </div>
            </div>
            {#if getCategoryDescription(category.category)}
              <p class="text-muted mt-3 ml-9 text-sm leading-relaxed">
                {getCategoryDescription(category.category)}
              </p>
            {/if}
          </div>

          <!-- Actions List with improved styling -->
          {#if isExpanded && actions.length > 0}
            <div transition:slide={{ duration: 200 }} class="divide-default bg-primary divide-y">
              {#each actions as action (action.action)}
                <div class="hover:bg-hover/50 px-6 py-5 transition-colors duration-150">
                  <div class="flex items-start justify-between gap-6">
                    <div class="min-w-0 flex-1">
                      <div class="mb-1.5 flex flex-wrap items-center gap-2.5">
                        <span class="text-default text-sm font-semibold">
                          {getActionLabel(action.action)}
                        </span>
                        {#if !action.enabled}
                          <span
                            class="inline-flex flex-shrink-0 items-center gap-1 rounded-full border border-red-200 bg-red-50 px-2.5 py-1 text-xs font-semibold text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300"
                          >
                            <X class="h-3.5 w-3.5" />
                            {m.audit_config_disabled()}
                          </span>
                        {/if}
                      </div>
                      {#if getActionDescription(action.action)}
                        <p class="text-muted mb-2 text-sm leading-relaxed">
                          {getActionDescription(action.action)}
                        </p>
                      {/if}
                      <code
                        class="bg-accent-default/5 text-accent-default/90 dark:bg-accent-default/10 dark:text-accent-default border-accent-default/20 inline-block rounded-md border px-2.5 py-1 font-mono text-xs"
                        >{action.action}</code
                      >
                    </div>
                    <div class="flex-shrink-0 pt-0.5">
                      <Input.Checkbox
                        checked={action.enabled}
                        onCheckedChange={(next) => {
                          if (next !== action.enabled) {
                            toggleAction(action.action, action.category);
                          }
                        }}
                      />
                    </div>
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      {/if}
    {/each}
  </div>

  <!-- Save Bar with refined styling -->
  {#if hasChanges}
    <div transition:fly={{ y: 20, duration: 200 }} class="sticky bottom-4 mt-6">
      <div
        class="border-accent-default bg-accent-default/5 rounded-lg border p-4 shadow-lg backdrop-blur-sm"
      >
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-3">
            <div class="bg-accent-default/15 rounded-md p-2">
              <Check class="text-accent-default h-4 w-4" />
            </div>
            <div>
              <p class="text-default text-sm font-semibold">
                {m.audit_config_unsaved_changes()}
              </p>
              <p class="text-muted mt-0.5 text-xs">{m.audit_changes_immediate()}</p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <Button
              variant="simple"
              onclick={resetChanges}
              size="sm"
              class="h-10 px-4 text-sm font-medium"
            >
              {m.audit_config_reset()}
            </Button>
            <Button
              variant="primary"
              onclick={saveConfig}
              disabled={isSaving}
              size="sm"
              class="h-10 px-5 text-sm font-semibold"
            >
              {#if isSaving}
                <div
                  class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
                ></div>
                {m.audit_config_saving()}
              {:else}
                <Check class="h-4 w-4" />
                {m.audit_config_save()}
              {/if}
            </Button>
          </div>
        </div>
      </div>
    </div>
  {/if}
{/if}
