<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page, Settings } from "$lib/components/layout/index.js";
  import { Input, Button } from "@intric/ui";
  import { getAppContext } from "$lib/core/AppContext.js";
  import { getIntric } from "$lib/core/Intric.js";
  import StorageOverviewBar from "./usage/storage/StorageOverviewBar.svelte";
  import TokenOverviewBar from "./usage/tokens/TokenOverviewBar.svelte";
  import { m } from "$lib/paraglide/messages";
  import { invalidate, invalidateAll } from "$app/navigation";
  import { goto } from "$app/navigation";

  const { tenant } = getAppContext();
  const intric = getIntric();
  let { data } = $props();

  // Initialize from server data
  let usingTemplates = $state(data.settings.using_templates);

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

  // Navigate to audit configuration
  function goToAuditConfig() {
    goto('/admin/audit-logs?tab=config');
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

      <Settings.Group title={m.audit_logging_title()} description={m.audit_logging_description()}>
        <Settings.Row
          title={m.audit_logging_config_title()}
          description={m.audit_logging_config_description()}
        >
          <Button variant="primary" onclick={goToAuditConfig}>
            {m.audit_configure_button()}
          </Button>
        </Settings.Row>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>