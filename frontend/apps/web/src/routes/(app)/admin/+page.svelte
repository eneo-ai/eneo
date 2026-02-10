<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page, Settings } from "$lib/components/layout/index.js";
  import { Button, Dialog, Input } from "@intric/ui";
  import { getAppContext } from "$lib/core/AppContext.js";
  import { getIntric } from "$lib/core/Intric.js";
  import StorageOverviewBar from "./usage/storage/StorageOverviewBar.svelte";
  import TokenOverviewBar from "./usage/tokens/TokenOverviewBar.svelte";
  import { m } from "$lib/paraglide/messages";
  import { invalidate, invalidateAll } from "$app/navigation";
  import { writable } from "svelte/store";

  const { tenant } = getAppContext();
  const intric = getIntric();
  let { data } = $props();

  // Initialize from server data
  let usingTemplates = $state(data.settings.using_templates);
  let auditLoggingEnabled = $state(data.settings.audit_logging_enabled);
  let provisioningEnabled = $state(data.settings.provisioning ?? false);
  let scopeEnforcementEnabled = $state(data.settings.api_key_scope_enforcement ?? true);
  let strictModeEnabled = $state(data.settings.api_key_strict_mode ?? false);

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

  // Handle scope enforcement toggle change
  const showDisableScopeDialog = writable(false);
  let pendingScopeToggle: { current: boolean; next: boolean } | null = null;

  async function handleToggleScopeEnforcement({ current, next }: { current: boolean; next: boolean }) {
    // When disabling, show confirmation dialog first
    if (next === false) {
      pendingScopeToggle = { current, next };
      $showDisableScopeDialog = true;
      return;
    }
    await applyScopeEnforcementToggle(next);
  }

  async function confirmDisableScopeEnforcement() {
    $showDisableScopeDialog = false;
    if (pendingScopeToggle) {
      await applyScopeEnforcementToggle(pendingScopeToggle.next);
      pendingScopeToggle = null;
    }
  }

  async function applyScopeEnforcementToggle(next: boolean) {
    const previousValue = scopeEnforcementEnabled;
    scopeEnforcementEnabled = next; // Optimistic UI update

    try {
      const updatedSettings = await intric.settings.updateScopeEnforcement(next);
      scopeEnforcementEnabled = updatedSettings.api_key_scope_enforcement ?? true;
      await invalidateAll();
    } catch (error) {
      console.error("[Admin] Error updating scope enforcement setting:", error);
      scopeEnforcementEnabled = previousValue; // Revert on error
    }
  }

  // Handle strict mode toggle change
  const showDisableStrictModeDialog = writable(false);
  let pendingStrictModeToggle: { current: boolean; next: boolean } | null = null;

  async function handleToggleStrictMode({ current, next }: { current: boolean; next: boolean }) {
    if (next === false) {
      pendingStrictModeToggle = { current, next };
      $showDisableStrictModeDialog = true;
      return;
    }
    await applyStrictModeToggle(next);
  }

  async function confirmDisableStrictMode() {
    $showDisableStrictModeDialog = false;
    if (pendingStrictModeToggle) {
      await applyStrictModeToggle(pendingStrictModeToggle.next);
      pendingStrictModeToggle = null;
    }
  }

  async function applyStrictModeToggle(next: boolean) {
    const previousValue = strictModeEnabled;
    strictModeEnabled = next; // Optimistic UI update

    try {
      const updatedSettings = await intric.settings.updateStrictMode(next);
      strictModeEnabled = updatedSettings.api_key_strict_mode ?? false;
      await invalidateAll();
    } catch (error) {
      console.error("[Admin] Error updating strict mode setting:", error);
      strictModeEnabled = previousValue; // Revert on error
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
        <Settings.Row title={m.enable_scope_enforcement()} description={m.enable_scope_enforcement_description()}>
          <Input.Switch bind:value={scopeEnforcementEnabled} sideEffect={handleToggleScopeEnforcement} />
        </Settings.Row>
        <Settings.Row
          title={m.enable_strict_mode()}
          description={scopeEnforcementEnabled ? m.enable_strict_mode_description() : m.enable_strict_mode_requires_scope_enforcement()}
        >
          <Input.Switch
            bind:value={strictModeEnabled}
            sideEffect={handleToggleStrictMode}
            disabled={!scopeEnforcementEnabled}
          />
        </Settings.Row>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>

<Dialog.Root alert openController={showDisableScopeDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.disable_scope_enforcement_warning_title()}</Dialog.Title>
    <Dialog.Description>
      {m.disable_scope_enforcement_warning_body()}
    </Dialog.Description>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={confirmDisableScopeEnforcement}>{m.disable()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root alert openController={showDisableStrictModeDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.disable_strict_mode_warning_title()}</Dialog.Title>
    <Dialog.Description>
      {m.disable_strict_mode_warning_body()}
    </Dialog.Description>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={confirmDisableStrictMode}>{m.disable()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
