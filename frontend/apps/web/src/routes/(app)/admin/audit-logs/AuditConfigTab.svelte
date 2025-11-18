<script lang="ts">
  import { Button, Input } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import * as m from "$lib/paraglide/messages";
  import { ChevronDown, ChevronRight, Search, Check, X } from "lucide-svelte";
  import { onMount } from "svelte";

  const intric = getIntric();

  // State
  let categoryConfig = $state([]);
  let actionConfig = $state([]);
  let expandedCategories = $state(new Set());
  let searchQuery = $state("");
  let isLoading = $state(true);
  let showLoading = $state(false); // Only show loading spinner after 200ms delay
  let isSaving = $state(false);
  let hasChanges = $state(false);
  let originalCategoryConfig = [];
  let originalActionConfig = [];

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
    const filtered = actionConfig.filter(action =>
      action.action.toLowerCase().includes(query) ||
      action.name_sv?.toLowerCase().includes(query) ||
      action.description_sv?.toLowerCase().includes(query)
    );

    return groupActionsByCategory(filtered);
  });

  // Group actions by category
  function groupActionsByCategory(actions) {
    const grouped = {};
    for (const action of actions) {
      if (!grouped[action.category]) {
        grouped[action.category] = [];
      }
      grouped[action.category].push(action);
    }
    return grouped;
  }

  // Get category display name
  function getCategoryName(category) {
    const key = `audit_category_${category}`;
    return (m)[key]?.() || category;
  }

  // Get category description from config
  function getCategoryDescription(category) {
    const cat = categoryConfig.find(c => c.category === category);
    return cat?.description || "";
  }

  // Toggle category expansion
  function toggleCategory(category) {
    if (expandedCategories.has(category)) {
      expandedCategories.delete(category);
    } else {
      expandedCategories.add(category);
    }
    expandedCategories = new Set(expandedCategories);
  }

  // Toggle all actions in a category with proper Svelte 5 reactivity
  function toggleAllInCategory(category, enabled) {
    // Create new array with updated actions
    actionConfig = actionConfig.map(action => {
      if (action.category === category) {
        return { ...action, enabled };
      }
      return action;
    });

    // Update category enabled state
    categoryConfig = categoryConfig.map(cat => {
      if (cat.category === category) {
        return { ...cat, enabled };
      }
      return cat;
    });

    checkForChanges();
  }

  // Toggle individual action with proper Svelte 5 reactivity
  function toggleAction(actionId, categoryId) {
    // Find the current action to get its state
    const currentAction = actionConfig.find(a => a.action === actionId);
    if (!currentAction) return;

    const newEnabledState = !currentAction.enabled;

    // Create new array with updated action
    actionConfig = actionConfig.map(a => {
      if (a.action === actionId) {
        return { ...a, enabled: newEnabledState };
      }
      return a;
    });

    // Check if all actions in the category have the same state
    const categoryActions = actionConfig.filter(a => a.category === categoryId);
    const allEnabled = categoryActions.every(a => a.enabled);
    const allDisabled = categoryActions.every(a => !a.enabled);

    // Update category state based on actions
    categoryConfig = categoryConfig.map(cat => {
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
    const categoryChanged = JSON.stringify(categoryConfig) !== JSON.stringify(originalCategoryConfig);
    const actionChanged = JSON.stringify(actionConfig) !== JSON.stringify(originalActionConfig);
    hasChanges = categoryChanged || actionChanged;
  }

  // Count enabled actions in a category
  function countEnabledInCategory(category) {
    const actions = actionConfig.filter(a => a.category === category);
    const enabled = actions.filter(a => a.enabled).length;
    return { enabled, total: actions.length };
  }

  // Load configuration
  async function loadConfig() {
    try {
      isLoading = true;

      // Load both category and action config in parallel
      const [catConfig, actConfig] = await Promise.all([
        intric.audit.getConfig(),
        intric.audit.getActionConfig()
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
      const categoryUpdates = categoryConfig.map(cat => ({
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
        updates.push(intric.audit.updateConfig({ updates: categoryUpdates }));
      }
      if (actionUpdates.length > 0) {
        updates.push(intric.audit.updateActionConfig({ updates: actionUpdates }));
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
    expandedCategories = new Set(expandedCategories);
  }

  // Collapse all categories
  function collapseAll() {
    expandedCategories.clear();
    expandedCategories = new Set(expandedCategories);
  }

  onMount(() => {
    loadConfig();
  });
</script>

{#if isLoading && showLoading}
  <div class="flex items-center justify-center py-20">
    <div class="flex flex-col items-center gap-4">
      <div class="h-10 w-10 animate-spin rounded-full border-4 border-accent-default border-t-transparent"></div>
      <p class="text-sm font-medium text-muted">Laddar konfiguration...</p>
    </div>
  </div>
{:else if !isLoading}
  <!-- Header Section with improved styling -->
  <div class="mb-6 rounded-xl border border-default bg-subtle p-6 shadow-sm">
    <div class="mb-5">
      <h3 class="text-lg font-semibold text-default mb-2">{m.audit_config_header()}</h3>
      <p class="text-sm text-muted leading-relaxed">{m.audit_config_description()}</p>
    </div>

    <!-- Search and Controls with better spacing -->
    <div class="flex flex-col sm:flex-row gap-3">
      <div class="flex-1 relative">
        <Search class="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted pointer-events-none" />
        <Input.Text
          bind:value={searchQuery}
          placeholder={m.audit_config_search_placeholder()}
          class="pl-10 h-11 text-sm"
        />
      </div>
      <div class="flex gap-2">
        <Button variant="ghost" onclick={expandAll} size="sm" class="h-11 px-4 text-sm font-medium">
          {m.audit_config_expand_all()}
        </Button>
        <Button variant="ghost" onclick={collapseAll} size="sm" class="h-11 px-4 text-sm font-medium">
          {m.audit_config_collapse_all()}
        </Button>
      </div>
    </div>
  </div>

  <!-- Categories and Actions with improved styling -->
  <div class="space-y-3">
    {#each categoryConfig as category (category.category)}
      {@const actions = filteredActionsByCategory[category.category] || []}
      {@const { enabled: enabledCount, total: totalCount } = countEnabledInCategory(category.category)}
      {@const isExpanded = expandedCategories.has(category.category)}

      {#if actions.length > 0 || !searchQuery}
        <div class="rounded-xl border border-default bg-primary overflow-hidden shadow-sm hover:shadow transition-all duration-200">
          <!-- Category Header with improved layout -->
          <div class="px-6 py-4 bg-subtle border-b border-default">
            <div class="flex items-center justify-between gap-4">
              <button
                onclick={() => toggleCategory(category.category)}
                class="flex-1 flex items-center gap-3 text-left hover:text-accent-default transition-colors group min-w-0"
              >
                <div class="rounded-md p-1 group-hover:bg-hover transition-colors flex-shrink-0">
                  {#if isExpanded}
                    <ChevronDown class="h-4 w-4 text-default" />
                  {:else}
                    <ChevronRight class="h-4 w-4 text-muted" />
                  {/if}
                </div>
                <span class="font-semibold text-default text-sm truncate">{getCategoryName(category.category)}</span>
                <span class="inline-flex items-center gap-1.5 rounded-full bg-primary px-3 py-1 text-xs font-semibold text-muted border border-default flex-shrink-0">
                  <span class={enabledCount > 0 ? 'text-accent-default' : ''}>{enabledCount}</span>
                  <span class="text-muted/50">/</span>
                  <span>{totalCount}</span>
                </span>
              </button>
              <div class="flex items-center gap-3 flex-shrink-0">
                <Input.Switch
                  value={category.enabled}
                  sideEffect={() => toggleAllInCategory(category.category, !category.enabled)}
                />
              </div>
            </div>
            {#if category.description}
              <p class="text-sm text-muted mt-3 ml-9 leading-relaxed">{category.description}</p>
            {/if}
          </div>

          <!-- Actions List with improved styling -->
          {#if isExpanded && actions.length > 0}
            <div class="divide-y divide-default bg-primary">
              {#each actions as action (action.action)}
                <div class="px-6 py-5 hover:bg-hover/30 transition-colors">
                  <div class="flex items-start justify-between gap-6">
                    <div class="flex-1 min-w-0">
                      <div class="flex items-center gap-2.5 mb-1.5 flex-wrap">
                        <span class="text-sm font-semibold text-default">
                          {action.name_sv || action.action}
                        </span>
                        {#if !action.enabled}
                          <span class="inline-flex items-center gap-1 rounded-full bg-red-50 dark:bg-red-950 px-2.5 py-1 text-xs font-semibold text-red-700 dark:text-red-300 border border-red-200 dark:border-red-800 flex-shrink-0">
                            <X class="h-3.5 w-3.5" />
                            {m.audit_config_disabled()}
                          </span>
                        {/if}
                      </div>
                      {#if action.description_sv}
                        <p class="text-sm text-muted leading-relaxed mb-2">{action.description_sv}</p>
                      {/if}
                      <code class="inline-block text-xs font-mono bg-accent-default/5 text-accent-default/90 dark:bg-accent-default/10 dark:text-accent-default px-2.5 py-1 rounded-md border border-accent-default/20">{action.action}</code>
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
    <div class="sticky bottom-4 mt-6">
      <div class="rounded-lg border border-accent-default bg-accent-default/5 backdrop-blur-sm p-4 shadow-lg">
        <div class="flex items-center justify-between flex-wrap gap-3">
          <div class="flex items-center gap-3">
            <div class="rounded-md bg-accent-default/15 p-2">
              <Check class="h-4 w-4 text-accent-default" />
            </div>
            <div>
              <p class="text-sm text-default font-semibold">
                {m.audit_config_unsaved_changes()}
              </p>
              <p class="text-xs text-muted mt-0.5">
                Ändringar träder i kraft omedelbart
              </p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <Button variant="ghost" onclick={resetChanges} size="sm" class="h-10 px-4 text-sm font-medium">
              {m.audit_config_reset()}
            </Button>
            <Button variant="primary" onclick={saveConfig} disabled={isSaving} size="sm" class="h-10 px-5 text-sm font-semibold">
              {#if isSaving}
                <div class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></div>
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