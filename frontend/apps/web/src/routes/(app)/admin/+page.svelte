<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page, Settings } from "$lib/components/layout/index.js";
  import { Input, Dialog, Button } from "@intric/ui";
  import { getAppContext } from "$lib/core/AppContext.js";
  import { getIntric } from "$lib/core/Intric.js";
  import StorageOverviewBar from "./usage/storage/StorageOverviewBar.svelte";
  import TokenOverviewBar from "./usage/tokens/TokenOverviewBar.svelte";
  import { m } from "$lib/paraglide/messages";
  import { invalidate, invalidateAll } from "$app/navigation";

  const { tenant } = getAppContext();
  const intric = getIntric();
  let { data } = $props();

  // High-priority categories that require confirmation before disabling
  const HIGH_PRIORITY = ['admin_actions', 'security_events'];

  // Initialize from server data
  let usingTemplates = $state(data.settings.using_templates);
  let auditConfig = $state(data.auditConfig.categories);
  let confirmModal = $state<{ open: boolean; category: any | null; newValue: boolean }>({
    open: false,
    category: null,
    newValue: false
  });

  // Handle toggle change - receives new value from Switch component
  async function handleToggleTemplates({ current, next }: { current: boolean; next: boolean }) {
    console.log(`[Admin] Toggling templates from ${current} to ${next}`);

    const previousValue = usingTemplates;
    usingTemplates = next; // Optimistic UI update

    try {
      const updatedSettings = await intric.settings.updateTemplates(next);
      console.log(`[Admin] Backend returned using_templates:`, updatedSettings.using_templates);

      // Update from server response
      usingTemplates = updatedSettings.using_templates;

      // Invalidate all page data to refresh template visibility across all routes
      await Promise.all([
        invalidate('app:settings'),  // Trigger template list refresh
        invalidateAll()              // Refresh all other data
      ]);
    } catch (error) {
      console.error("[Admin] Error updating templates setting:", error);
      usingTemplates = previousValue; // Revert on error
    }
  }

  // Handle audit category toggle - with confirmation modal for high-priority categories
  async function handleToggleCategory(category: any, { current, next }: { current: boolean; next: boolean }) {
    // If disabling a high-priority category, show confirmation modal
    if (HIGH_PRIORITY.includes(category.category) && !next) {
      confirmModal = { open: true, category, newValue: next };
      return; // Don't update yet - wait for confirmation
    }

    // For non-critical categories, update immediately
    await updateCategory(category.category, next);
  }

  // Actually update the category after confirmation
  async function updateCategory(categoryName: string, enabled: boolean) {
    console.log(`[Admin] Updating audit category ${categoryName} to ${enabled}`);

    const previousConfig = [...auditConfig];
    // Optimistic update
    auditConfig = auditConfig.map(c =>
      c.category === categoryName ? { ...c, enabled } : c
    );

    try {
      const updated = await intric.audit.updateConfig({
        updates: [{ category: categoryName, enabled }]
      });
      auditConfig = updated.categories;
      console.log(`[Admin] Audit config updated successfully`);
    } catch (error) {
      console.error("[Admin] Error updating audit config:", error);
      auditConfig = previousConfig; // Rollback on error
    }
  }

  // Confirm disable high-priority category
  async function confirmDisable() {
    if (!confirmModal.category) return;

    await updateCategory(confirmModal.category.category, confirmModal.newValue);
    confirmModal = { open: false, category: null, newValue: false };
  }

  // Cancel disable
  function cancelDisable() {
    confirmModal = { open: false, category: null, newValue: false };
  }

  // Get localized category name
  function getCategoryName(category: string): string {
    const key = `audit_category_${category}`;
    return (m as any)[key]?.() || category;
  }
</script>

<svelte:head>
  <title>Eneo.ai - {tenant.display_name}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.organisation()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.usage()}>
        <StorageOverviewBar storageStats={data.storageStats}></StorageOverviewBar>
        <TokenOverviewBar tokenStats={data.tokenStats}></TokenOverviewBar>
      </Settings.Group>

      <Settings.Group title={m.features()}>
        <Settings.Row title={m.enable_templates()} description={m.enable_templates_description()}>
          <Input.Switch bind:value={usingTemplates} sideEffect={handleToggleTemplates} />
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.audit_category_config_title()} description={m.audit_category_config_description()}>
        {#each auditConfig as category (category.category)}
          <Settings.Row
            title={getCategoryName(category.category)}
            description={category.description}
          >
            <div class="flex items-center gap-3">
              <span class="text-xs text-gray-500 dark:text-gray-400">
                {m.audit_category_action_count({ count: category.action_count })}
              </span>
              <Input.Switch
                value={category.enabled}
                sideEffect={(params) => handleToggleCategory(category, params)}
              />
            </div>
          </Settings.Row>
        {/each}
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>

<!-- Confirmation Dialog for High-Priority Categories -->
<Dialog.Root bind:isOpen={confirmModal.open}>
  <Dialog.Content>
    <Dialog.Title>{m.audit_confirm_disable_title()}</Dialog.Title>
    <Dialog.Description>
      <div class="space-y-4">
        <p>
          {m.audit_disable_warning({ category: confirmModal.category ? getCategoryName(confirmModal.category.category) : '' })}
        </p>

        {#if confirmModal.category}
          <ul class="list-disc list-inside text-sm text-gray-600 dark:text-gray-400">
            {#each confirmModal.category.example_actions.slice(0, 5) as action}
              <li>{action}</li>
            {/each}
            {#if confirmModal.category.action_count > 5}
              <li class="text-gray-500">...and {confirmModal.category.action_count - 5} more</li>
            {/if}
          </ul>
        {/if}

        <div class="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-md p-3">
          <p class="text-sm text-yellow-800 dark:text-yellow-200">
            <strong>Warning:</strong> {m.audit_compliance_warning()}
          </p>
        </div>
      </div>
    </Dialog.Description>
    <Dialog.Controls>
      <Button variant="outlined" onclick={cancelDisable}>
        {m.audit_modal_cancel()}
      </Button>
      <Button variant="destructive" onclick={confirmDisable}>
        {m.audit_modal_confirm_disable()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
