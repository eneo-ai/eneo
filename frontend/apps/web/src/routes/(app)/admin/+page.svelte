<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page, Settings } from "$lib/components/layout/index.js";
  import { Input } from "@intric/ui";
  import { getAppContext } from "$lib/core/AppContext.js";
  import { getIntric } from "$lib/core/Intric.js";
  import StorageOverviewBar from "./usage/storage/StorageOverviewBar.svelte";
  import TokenOverviewBar from "./usage/tokens/TokenOverviewBar.svelte";
  import { m } from "$lib/paraglide/messages";
  import { invalidate, invalidateAll } from "$app/navigation";

  const { tenant } = getAppContext();
  const intric = getIntric();
  let { data } = $props();

  // Initialize from server data
  let usingTemplates = $state(data.settings.using_templates);
  let auditLoggingEnabled = $state(data.settings.audit_logging_enabled);
  let provisioningEnabled = $state(data.settings.provisioning ?? false);

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

  // Handle audit logging toggle change
  async function handleToggleAuditLogging({ current, next }: { current: boolean; next: boolean }) {
    console.log(`[Admin] Toggling audit logging from ${current} to ${next}`);

    const previousValue = auditLoggingEnabled;
    auditLoggingEnabled = next; // Optimistic UI update

    try {
      const updatedSettings = await intric.settings.updateAuditLogging(next);
      console.log(`[Admin] Backend returned audit_logging_enabled:`, updatedSettings.audit_logging_enabled);

      // Update from server response
      auditLoggingEnabled = updatedSettings.audit_logging_enabled;

      // Invalidate all page data to refresh audit logging state
      await Promise.all([
        invalidate('admin:layout'),  // Trigger audit config refresh
        invalidateAll()              // Refresh all other data
      ]);
    } catch (error) {
      console.error("[Admin] Error updating audit logging setting:", error);
      auditLoggingEnabled = previousValue; // Revert on error
    }
  }

  // Handle provisioning toggle change
  async function handleToggleProvisioning({ current, next }: { current: boolean; next: boolean }) {
    console.log(`[Admin] Toggling provisioning from ${current} to ${next}`);

    const previousValue = provisioningEnabled;
    provisioningEnabled = next; // Optimistic UI update

    try {
      const updatedSettings = await intric.settings.updateProvisioning(next);
      console.log(`[Admin] Backend returned provisioning:`, updatedSettings.provisioning);

      // Update from server response
      provisioningEnabled = updatedSettings.provisioning ?? false;

      // Invalidate all page data
      await invalidateAll();
    } catch (error) {
      console.error("[Admin] Error updating provisioning setting:", error);
      provisioningEnabled = previousValue; // Revert on error
    }
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
        <Settings.Row title={m.enable_audit_logging()} description={m.enable_audit_logging_description()}>
          <Input.Switch bind:value={auditLoggingEnabled} sideEffect={handleToggleAuditLogging} />
        </Settings.Row>
        <Settings.Row title={m.enable_provisioning()} description={m.enable_provisioning_description()}>
          <Input.Switch bind:value={provisioningEnabled} sideEffect={handleToggleProvisioning} />
        </Settings.Row>
        <Settings.Row
          title="API key settings"
          description="Scope enforcement, strict mode, and expiry notification controls are now managed on the API keys admin page."
        >
          <a
            href="/admin/api-keys"
            class="text-accent-default hover:text-accent-default/80 text-sm font-medium"
          >
            Open `/admin/api-keys`
          </a>
        </Settings.Row>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>
