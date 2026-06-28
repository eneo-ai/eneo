<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page, Settings } from "$lib/components/layout/index.js";
  import { Input } from "@eneo/ui";
  import { getAppContext } from "$lib/core/AppContext.js";
  import { getEneo } from "$lib/core/Eneo.js";
  import { m } from "$lib/paraglide/messages";
  import { invalidate, invalidateAll } from "$app/navigation";

  const { tenant, updateTenant } = getAppContext();
  const eneo = getEneo();
  let { data } = $props();

  // Initialize from server data, re-sync after invalidateAll() refreshes props
  let usingTemplates = $state<boolean | undefined>(undefined);
  let auditLoggingEnabled = $state<boolean | undefined>(undefined);
  let provisioningEnabled = $state(false);
  $effect.pre(() => {
    usingTemplates = data.settings.using_templates;
    auditLoggingEnabled = data.settings.audit_logging_enabled;
    provisioningEnabled = data.settings.provisioning ?? false;
  });

  // Org-wide model pricing visibility lives on the tenant (not settings).
  let showModelPricing = $state(tenant.show_model_pricing ?? true);

  // Handle toggle change - receives new value from Switch component
  async function handleToggleTemplates({ current, next }: { current: boolean; next: boolean }) {
    console.log(`[Admin] Toggling templates from ${current} to ${next}`);

    const previousValue = usingTemplates;
    usingTemplates = next; // Optimistic UI update

    try {
      const updatedSettings = await eneo.settings.updateTemplates(next);
      console.log(`[Admin] Backend returned using_templates:`, updatedSettings.using_templates);

      // Update from server response
      usingTemplates = updatedSettings.using_templates;

      // Invalidate all page data to refresh template visibility across all routes
      await Promise.all([
        invalidate("app:settings"), // Trigger template list refresh
        invalidateAll() // Refresh all other data
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
      const updatedSettings = await eneo.settings.updateAuditLogging(next);
      console.log(
        `[Admin] Backend returned audit_logging_enabled:`,
        updatedSettings.audit_logging_enabled
      );

      // Update from server response
      auditLoggingEnabled = updatedSettings.audit_logging_enabled;

      // Invalidate all page data to refresh audit logging state
      await Promise.all([
        invalidate("admin:layout"), // Trigger audit config refresh
        invalidateAll() // Refresh all other data
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
      const updatedSettings = await eneo.settings.updateProvisioning(next);
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

  // Toggle whether model input/output prices are shown to regular users.
  async function handleToggleModelPricing({ next }: { current: boolean; next: boolean }) {
    const previousValue = showModelPricing;
    showModelPricing = next; // Optimistic UI update

    try {
      const updated = await eneo.settings.updateModelPricingVisibility(next);
      showModelPricing = updated.show_model_pricing;
      updateTenant({ show_model_pricing: updated.show_model_pricing });
      await invalidateAll();
    } catch (error) {
      console.error("[Admin] Error updating model pricing visibility:", error);
      showModelPricing = previousValue; // Revert on error
    }
  }
</script>

<svelte:head>
  <title>Eneo.ai – {tenant.display_name}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.organisation()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.features()}>
        <Settings.Row title={m.enable_templates()} description={m.enable_templates_description()}>
          <Input.Switch bind:value={usingTemplates} sideEffect={handleToggleTemplates} />
        </Settings.Row>
        <Settings.Row
          title={m.enable_audit_logging()}
          description={m.enable_audit_logging_description()}
        >
          <Input.Switch bind:value={auditLoggingEnabled} sideEffect={handleToggleAuditLogging} />
        </Settings.Row>
        <Settings.Row
          title={m.enable_provisioning()}
          description={m.enable_provisioning_description()}
        >
          <Input.Switch bind:value={provisioningEnabled} sideEffect={handleToggleProvisioning} />
        </Settings.Row>
      </Settings.Group>
      <Settings.Group title={m.model_pricing()}>
        <Settings.Row
          title={m.show_model_pricing()}
          description={m.show_model_pricing_description()}
        >
          <Input.Switch bind:value={showModelPricing} sideEffect={handleToggleModelPricing} />
        </Settings.Row>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>
