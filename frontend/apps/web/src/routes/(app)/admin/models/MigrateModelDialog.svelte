<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import type { CompletionModel } from "@intric/intric-js";
  import { Button, Dialog, Select } from "@intric/ui";
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { Loader2, Bot, AppWindow, MessageSquare, LayoutGrid, ChevronDown, AlertTriangle, ShieldAlert } from "lucide-svelte";
  import type { Writable } from "svelte/store";
  import { bumpModelMigrationHistoryVersion } from "./migrationHistoryRefresh";

  export let openController: Writable<boolean>;
  export let sourceModel: CompletionModel;
  export let models: CompletionModel[] = [];

  const intric = getIntric();

  let targetModelId = "";
  let isSubmitting = false;
  let isLoadingImpact = false;
  let submitError: string | null = null;

  type UsageDetail = {
    entity_id: string;
    entity_name: string;
    entity_type: string;
    space_name: string | null;
    owner_name: string | null;
  };

  let impactTotal = 0;
  let impactDetails: UsageDetail[] = [];
  let spacesCount = 0;
  let expandedSections: Record<string, boolean> = {};

  // --- Target selection & compatibility ---

  $: availableTargets = models
    .filter((mod) => mod.id !== sourceModel.id)
    .filter((mod) => mod.provider_id != null)
    .filter((mod) => mod.is_org_enabled);

  $: targetOptions = availableTargets.map((mod) => ({
    value: mod.id,
    label: mod.nickname ? mod.nickname : mod.name
  }));

  // Server-side validation state
  let compatWarnings: string[] = [];
  let hasSecurityBlocker = false;
  let isValidating = false;
  let acknowledged = false;
  let validationError = false;
  $: hasWarnings = compatWarnings.length > 0;
  $: canMigrate = targetModelId && !hasSecurityBlocker && !isValidating && !validationError && (!hasWarnings || acknowledged);

  function translateWarningCode(code: string): string {
    if (code === "target_deprecated") return m.migration_warn_target_deprecated();
    if (code.startsWith("lower_token_limit:")) return m.migration_warn_lower_token_limit({ limit: code.split(":")[1] });
    if (code.startsWith("different_family:")) { const p = code.split(":"); return m.migration_warn_different_family({ from: p[1], to: p[2] }); }
    if (code === "lacks_vision") return m.migration_warn_lacks_vision();
    if (code === "lacks_reasoning") return m.migration_warn_lacks_reasoning();
    if (code === "lacks_tool_calling") return m.migration_warn_lacks_tool_calling();
    if (code === "kwargs_reset") return m.migration_warn_kwargs_reset();
    if (code.startsWith("security_classification_insufficient:")) {
      const p = code.split(":"); return m.migration_blocked_security({ count: p[1], classification: p[2] });
    }
    return code;
  }

  // Track which target the current validation is for (prevents stale responses)
  let validatingForTarget = "";

  // Run server-side validation when target changes
  $: if (targetModelId) {
    acknowledged = false;
    submitError = null;
    validationError = false;
    runValidation(targetModelId);
  } else {
    compatWarnings = [];
    hasSecurityBlocker = false;
    validationError = false;
  }

  async function runValidation(toId: string) {
    validatingForTarget = toId;
    isValidating = true;
    compatWarnings = [];
    hasSecurityBlocker = false;
    validationError = false;
    try {
      const result = await intric.models.validateMigration({
        fromId: sourceModel.id,
        toId
      });
      // Discard stale response if target changed during request
      if (validatingForTarget !== toId) return;
      const validation = result as { compatible: boolean; warnings: string[]; warning_codes: string[]; requires_confirmation: boolean };
      // Use warning_codes for translated display, fall back to warnings (human-readable) if no codes
      const codes = validation.warning_codes ?? [];
      compatWarnings = codes.length > 0 ? codes.map(translateWarningCode) : validation.warnings;
      hasSecurityBlocker = codes.some((w: string) => w.startsWith("security_classification_insufficient"));
    } catch (err: any) {
      if (validatingForTarget !== toId) return;
      console.error("[MigrateModelDialog] Validation failed:", err?.message ?? err);
      submitError = err?.message || m.migration_failed();
      validationError = true;
    } finally {
      if (validatingForTarget === toId) isValidating = false;
    }
  }

  // --- Impact loading ---

  $: if ($openController) {
    submitError = null;
    acknowledged = false;
    expandedSections = {};
    impactTotal = 0;
    impactDetails = [];
    spacesCount = 0;
    if (!targetOptions.find((opt) => opt.value === targetModelId)) {
      targetModelId = "";
    }
    loadImpact();
  }

  async function loadImpact() {
    isLoadingImpact = true;
    try {
      const details = await intric.models.getUsageDetails({ modelId: sourceModel.id, limit: 100 });
      const detailsResponse = details as any;
      impactDetails = detailsResponse?.items ?? [];
      // Use backend total (accounts for pagination), not just items.length
      impactTotal = detailsResponse?.total ?? impactDetails.length;

      try {
        const stats = await intric.models.getUsageStats({ modelId: sourceModel.id });
        spacesCount = (stats as any).spaces_count || 0;
      } catch {
        spacesCount = 0;
      }
    } catch (err: any) {
      console.error("[MigrateModelDialog] Failed to load impact:", err?.message ?? err);
    } finally {
      isLoadingImpact = false;
    }
  }

  // --- Migration execution ---

  async function handleMigrate() {
    submitError = null;
    isSubmitting = true;

    try {
      await intric.models.migrateCompletion({
        fromId: sourceModel.id,
        toId: targetModelId,
        // If user acknowledged warnings, send confirmMigration=true
        confirmMigration: acknowledged || !hasWarnings
      });

      // Success — delete source model
      try {
        await intric.tenantModels.deleteCompletion({ id: sourceModel.id });
        toast.success(m.migration_success());
      } catch {
        toast.warning(m.migration_success_delete_failed());
      }

      bumpModelMigrationHistoryVersion();
      await invalidate("admin:model-providers:load");
      openController.set(false);
    } catch (e: any) {
      bumpModelMigrationHistoryVersion();
      submitError = e.message || m.migration_failed();
    } finally {
      isSubmitting = false;
    }
  }

  // --- Grouped details ---

  $: groupedDetails = groupByType(impactDetails);

  function groupByType(details: UsageDetail[]): Record<string, UsageDetail[]> {
    const groups: Record<string, UsageDetail[]> = {};
    for (const d of details) {
      if (!groups[d.entity_type]) groups[d.entity_type] = [];
      groups[d.entity_type].push(d);
    }
    return groups;
  }

  function toggleSection(type: string) {
    expandedSections = { ...expandedSections, [type]: !expandedSections[type] };
  }

  const sectionConfig: Record<string, { label: () => string; icon: any }> = {
    assistant: { label: () => m.migration_summary_assistants(), icon: Bot },
    app: { label: () => m.migration_summary_apps(), icon: AppWindow },
    service: { label: () => m.migration_summary_services(), icon: LayoutGrid },
    question: { label: () => m.migration_summary_questions(), icon: MessageSquare },
    assistant_template: { label: () => m.migration_summary_assistants(), icon: Bot },
    app_template: { label: () => m.migration_summary_apps(), icon: AppWindow }
  };
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="large" form>
    <Dialog.Title>{m.migrate_model_title()}</Dialog.Title>
    <Dialog.Section>
      <div class="flex flex-col gap-5 p-5">

        <p class="text-sm text-muted">

          {m.migrate_model_description({
            name: sourceModel.nickname ? sourceModel.nickname : sourceModel.name
          })}
        </p>

        <!-- 1. Impact preview -->
        {#if isLoadingImpact}
          <div class="flex items-center gap-2 text-sm text-muted py-3">
            <Loader2 class="h-4 w-4 animate-spin" />
            <span>{m.loading()}</span>
          </div>
        {:else if impactTotal > 0}
          <div class="rounded-lg border border-default overflow-hidden">
            <div class="flex items-center gap-4 bg-surface-dimmer px-4 py-3 border-b border-dimmer">
              <span class="text-sm font-medium">{m.migration_impact_title({ count: impactTotal })}</span>
            </div>
            <div class="divide-y divide-dimmer">
              {#each Object.entries(groupedDetails) as [type, entities]}
                {@const config = sectionConfig[type] ?? { label: () => type, icon: Bot }}
                <div>
                  <button
                    class="flex items-center justify-between w-full px-4 py-2.5 text-sm hover:bg-hover-dimmer transition-colors text-left"
                    on:click={() => toggleSection(type)}
                  >
                    <div class="flex items-center gap-2">
                      <svelte:component this={config.icon} size={15} class="text-muted" />
                      <span class="font-medium">{config.label()}</span>
                      <span class="text-muted">({entities.length})</span>
                    </div>
                    <ChevronDown
                      size={16}
                      class="text-muted transition-transform {expandedSections[type] ? 'rotate-0' : '-rotate-90'}"
                    />
                  </button>
                  {#if expandedSections[type]}
                    <div class="border-t border-dimmer bg-surface-dimmer/30">
                      <table class="w-full text-sm">
                        <thead>
                          <tr class="text-xs text-muted uppercase tracking-wider">
                            <th class="px-4 py-2 text-left font-medium">{m.name()}</th>
                            <th class="px-4 py-2 text-left font-medium">Space</th>
                            <th class="px-4 py-2 text-left font-medium">{m.migration_impact_owner()}</th>
                          </tr>
                        </thead>
                        <tbody class="divide-y divide-dimmer">
                          {#each entities as entity}
                            <tr>
                              <td class="px-4 py-2">{entity.entity_name}</td>
                              <td class="px-4 py-2 text-muted">{entity.space_name ?? "–"}</td>
                              <td class="px-4 py-2 text-muted">{entity.owner_name ?? "–"}</td>
                            </tr>
                          {/each}
                        </tbody>
                      </table>
                    </div>
                  {/if}
                </div>
              {/each}
              {#if spacesCount > 0}
                <div class="flex items-center gap-2 px-4 py-3 text-sm text-muted bg-surface-dimmer/30">
                  <LayoutGrid size={15} class="flex-shrink-0" />
                  <span>{m.migration_spaces_info({ count: spacesCount })}</span>
                </div>
              {/if}
            </div>
          </div>
        {:else if !isLoadingImpact}
          <div class="rounded-lg border border-dimmer px-4 py-3 text-sm text-muted">
            {m.migration_no_impact()}
          </div>
        {/if}

        <!-- 2. Target model selection -->
        <Select.Simple
          options={targetOptions}
          bind:value={targetModelId}
          resourceName={m.resource_model()}
          {...{ placeholder: m.migrate_model_target_placeholder() }}
          fitViewport={true}
          class="border-default hover:bg-hover-dimmer rounded-t-md border-b px-4 py-4"
        >
          {m.migrate_model_target_label()}
        </Select.Simple>
        {#if targetOptions.length === 0}
          <p class="text-sm text-muted">{m.migrate_model_no_targets()}</p>
        {/if}

        <!-- 3. Validation results (server-side, shown on target selection) -->
        {#if isValidating}
          <div class="flex items-center gap-2 text-sm text-muted py-2">
            <Loader2 class="h-4 w-4 animate-spin" />
            <span>{m.loading()}</span>
          </div>
        {:else if hasSecurityBlocker}
          <div class="flex items-start gap-3 rounded-lg border border-negative-default/30 bg-negative-dimmer/40 px-4 py-3 text-sm text-negative-stronger">
            <ShieldAlert size={18} class="flex-shrink-0 mt-0.5" />
            <div>
              <p class="font-medium">{m.migration_blocked_title()}</p>
              {#each compatWarnings as w}
                <p class="mt-1 text-negative-default">{w}</p>
              {/each}
            </div>
          </div>
        {:else if hasWarnings}
          <div class="rounded-lg border border-warning-default/30 bg-warning-dimmer/30 px-4 py-3 text-sm">
            <ul class="space-y-1.5">
              {#each compatWarnings as w}
                <li class="flex items-start gap-2 text-warning-stronger">
                  <AlertTriangle size={14} class="flex-shrink-0 mt-0.5" />
                  <span>{w}</span>
                </li>
              {/each}
            </ul>
            <label class="flex items-start gap-3 mt-3 pt-3 border-t border-warning-default/20 text-warning-stronger cursor-pointer">
              <input
                type="checkbox"
                bind:checked={acknowledged}
                class="mt-0.5 h-4 w-4 rounded accent-warning-default"
              />
              <span>{m.migrate_model_confirm_label()}</span>
            </label>
          </div>
        {/if}

        <!-- 5. Submit error from backend (unexpected failures) -->
        {#if submitError}
          <div class="border-negative-default bg-negative-dimmer/50 text-negative-stronger border-l-2 px-4 py-3 text-sm rounded-r-md">
            {submitError}
          </div>
        {/if}

      </div>
    </Dialog.Section>
    <Dialog.Controls>
      <Button variant="outlined" on:click={() => openController.set(false)}>
        {m.cancel()}
      </Button>
      <Button
        variant="outlined"
        on:click={handleMigrate}
        disabled={isSubmitting || !canMigrate}
      >
        {#if isSubmitting}
          <Loader2 class="h-4 w-4 animate-spin" />
          {m.migrating()}
        {:else}
          {m.migrate_model_usage()}
        {/if}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
