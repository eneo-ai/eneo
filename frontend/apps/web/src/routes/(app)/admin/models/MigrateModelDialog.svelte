<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Migrate all usage of a soon-to-be-decommissioned model to a replacement.
  Shared by completion and transcription (`modelType` prop) — same layout and
  flow, only the SDK endpoints differ. The dialog has three jobs:

    1. Show what will be affected (the entities using the model) before commit.
    2. Validate compatibility against the chosen target server-side and
       surface security blockers / warnings.
    3. Hand off to the migrate endpoint and refresh the migration history panel.
-->

<script lang="ts">
  import { onMount, untrack } from "svelte";
  import type { CompletionModel, TranscriptionModel } from "@intric/intric-js";
  import type { Writable } from "svelte/store";
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { Loader2, AlertTriangle, ShieldAlert, Info } from "lucide-svelte";

  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";

  import { bumpModelMigrationHistoryVersion } from "./migrationHistoryRefresh";
  import { classifyMigrationCode, translateMigrationWarning } from "./migrationWarnings";
  import ModelUsageBreakdown from "./ModelUsageBreakdown.svelte";
  import type { UsageDetail } from "./usage";

  type MigratableModel = CompletionModel | TranscriptionModel;

  let {
    openController,
    sourceModel,
    models = [],
    modelType = "completionModel"
  }: {
    openController: Writable<boolean>;
    sourceModel: MigratableModel;
    models?: MigratableModel[];
    // The dialog is identical for both types — same impact preview, same
    // validation and confirm flow. Only which SDK endpoints get called differs
    // (gated on modelType in loadImpact / runValidation / handleMigrate).
    modelType?: "completionModel" | "transcriptionModel";
  } = $props();

  const intric = getIntric();

  // --- Open-state bridge -------------------------------------------------
  let dialogOpen = $state(false);
  onMount(() => openController.subscribe((value) => (dialogOpen = value)));
  $effect(() => {
    openController.set(dialogOpen);
  });

  // --- Form state --------------------------------------------------------
  let targetModelId = $state("");
  let isSubmitting = $state(false);
  let isLoadingImpact = $state(false);
  let hasLoadedImpact = $state(false);
  let impactLoadError = $state<string | null>(null);
  let submitError = $state<string | null>(null);

  let impactTotal = $state(0);
  let impactDetails = $state<UsageDetail[]>([]);
  let spacesCount = $state(0);

  // --- Target eligibility -----------------------------------------------
  const availableTargets = $derived(
    models
      .filter((mod) => mod.id !== sourceModel.id)
      .filter((mod) => mod.provider_id != null)
      .filter((mod) => mod.is_org_enabled)
      .filter((mod) => !mod.is_deprecated)
      .filter((mod) => !mod.migrated_to_model_id)
  );

  function labelFor(mod: MigratableModel): string {
    return mod.nickname ? mod.nickname : mod.name;
  }

  const selectedTargetLabel = $derived(
    availableTargets.find((mod) => mod.id === targetModelId)
      ? labelFor(availableTargets.find((mod) => mod.id === targetModelId)!)
      : ""
  );
  const sourceAlreadyMigrated = $derived(!!sourceModel.migrated_to_model_id);

  // --- Validation -------------------------------------------------------
  // Keep the raw codes from the backend and split them into severity tiers
  // so each renders in its own section (error / warning / info) instead of
  // everything landing in one red box.
  let validationCodes = $state<string[]>([]);
  // Defensive fallback if the backend ever returns warnings without codes.
  let fallbackWarnings = $state<string[]>([]);
  let isValidating = $state(false);
  let acknowledged = $state(false);
  let validationError = $state(false);

  const blockerMsgs = $derived(
    validationCodes
      .filter((c) => classifyMigrationCode(c) === "blocker")
      .map(translateMigrationWarning)
  );
  const warningMsgs = $derived([
    ...validationCodes
      .filter((c) => classifyMigrationCode(c) === "warning")
      .map(translateMigrationWarning),
    ...fallbackWarnings
  ]);
  const infoMsgs = $derived(
    validationCodes
      .filter((c) => classifyMigrationCode(c) === "info")
      .map(translateMigrationWarning)
  );
  const hasSecurityBlocker = $derived(blockerMsgs.length > 0);

  // Compatibility warnings + info (different_family, lower token limit,
  // kwargs reset, …) concern resource-level state (assistant prompts,
  // kwargs). With zero resources to re-bind they are vacuous — even if the
  // model is still enabled on spaces (those just get repointed). Security
  // blockers gate the action regardless of count (they concern spaces).
  const hasResourceImpact = $derived(impactTotal > 0);
  const showWarnings = $derived(warningMsgs.length > 0 && hasResourceImpact);
  const showInfo = $derived(infoMsgs.length > 0 && hasResourceImpact);
  const anyValidationSection = $derived(hasSecurityBlocker || showWarnings || showInfo);
  // A single checkbox gates everything that would otherwise block: security
  // blockers (via force_override) and compatibility warnings (via confirm).
  const needsAck = $derived(hasSecurityBlocker || showWarnings);
  const canMigrate = $derived(
    !!targetModelId &&
      !isLoadingImpact &&
      hasLoadedImpact &&
      !impactLoadError &&
      !isValidating &&
      !validationError &&
      !sourceAlreadyMigrated &&
      (!needsAck || acknowledged)
  );

  // Track which target the current validation is for to discard stale responses.
  let validatingForTarget = "";

  $effect(() => {
    if (!targetModelId || sourceAlreadyMigrated) {
      validationCodes = [];
      fallbackWarnings = [];
      validationError = false;
      return;
    }
    acknowledged = false;
    submitError = null;
    validationError = false;
    void runValidation(targetModelId);
  });

  async function runValidation(toId: string) {
    validatingForTarget = toId;
    isValidating = true;
    validationCodes = [];
    fallbackWarnings = [];
    validationError = false;
    try {
      const result = (await (modelType === "transcriptionModel"
        ? intric.models.validateTranscriptionMigration({ fromId: sourceModel.id, toId })
        : intric.models.validateMigration({ fromId: sourceModel.id, toId }))) as {
        compatible: boolean;
        warnings: string[];
        warning_codes: string[];
        requires_confirmation: boolean;
      };
      if (validatingForTarget !== toId) return;
      const codes = result.warning_codes ?? [];
      validationCodes = codes;
      fallbackWarnings = codes.length === 0 ? (result.warnings ?? []) : [];
    } catch (err: unknown) {
      if (validatingForTarget !== toId) return;
      console.error("[MigrateModelDialog] Validation failed:", err);
      submitError = err instanceof Error ? err.message : m.migration_failed();
      validationError = true;
    } finally {
      if (validatingForTarget === toId) isValidating = false;
    }
  }

  // --- Reset form when dialog opens -------------------------------------
  // Tracks `dialogOpen` only — `loadImpact()` is wrapped in `untrack` so the
  // read of `sourceModel.id` inside it doesn't pull this effect's deps wider.
  $effect(() => {
    if (!dialogOpen) return;
    submitError = null;
    impactLoadError = null;
    hasLoadedImpact = false;
    acknowledged = false;
    impactTotal = 0;
    impactDetails = [];
    spacesCount = 0;
    targetModelId = "";
    if (sourceAlreadyMigrated) return;
    untrack(() => void loadImpact());
  });

  // --- Discard a stale target when the eligible list shifts -------------
  // Runs whenever `availableTargets` recomputes (e.g. after an upstream
  // invalidate of the model list). Only clears `targetModelId` if it has
  // become invalid — does not touch any other form state, so it cannot
  // wipe an in-progress edit.
  $effect(() => {
    if (!dialogOpen) return;
    if (!targetModelId) return;
    if (!availableTargets.find((mod) => mod.id === targetModelId)) {
      targetModelId = "";
    }
  });

  // Both endpoints return 200 with empty/zero counts for models without
  // usage rows (verified in `completion_model_usage_service.get_model_usage_statistics`
  // which constructs an empty `ModelUsageStatistics` when no row exists).
  // A failure here therefore signals a real backend or network problem —
  // surface it and block migration until the admin retries, since the
  // impact summary is what they'd otherwise be acknowledging blindly.
  async function loadImpact() {
    isLoadingImpact = true;
    hasLoadedImpact = false;
    impactLoadError = null;
    impactTotal = 0;
    impactDetails = [];
    spacesCount = 0;
    // Same impact preview for both model types — only the endpoint differs.
    // Transcription's details are its apps; spaces come from the aggregate
    // usage count (a many-to-many, like completion).
    const isTranscription = modelType === "transcriptionModel";
    try {
      const details = (await (isTranscription
        ? intric.models.getTranscriptionUsageDetails({ modelId: sourceModel.id, limit: 100 })
        : intric.models.getUsageDetails({ modelId: sourceModel.id, limit: 100 }))) as {
        items?: UsageDetail[];
        total?: number;
      };
      impactDetails = details?.items ?? [];
      // Use backend total (handles pagination), not just items.length
      impactTotal = details?.total ?? impactDetails.length;
      const stats = (await (isTranscription
        ? intric.models.getTranscriptionUsageStats({ modelId: sourceModel.id })
        : intric.models.getUsageStats({ modelId: sourceModel.id }))) as {
        spaces_count?: number;
      };
      spacesCount = stats.spaces_count ?? 0;
      hasLoadedImpact = true;
    } catch (err: unknown) {
      console.error("[MigrateModelDialog] Failed to load impact:", err);
      impactLoadError = err instanceof Error ? err.message : m.migration_impact_load_failed();
    } finally {
      isLoadingImpact = false;
    }
  }

  // --- Migrate ---------------------------------------------------------
  async function handleMigrate() {
    submitError = null;
    isSubmitting = true;
    try {
      // Match the UI gate: spaces-only warning cases are allowed without a
      // manual acknowledgement because no resources are rebound.
      // Security blockers only clear when the admin actively acknowledges
      // (force_override); both model types support the same escape hatch.
      if (modelType === "transcriptionModel") {
        await intric.models.migrateTranscription({
          fromId: sourceModel.id,
          toId: targetModelId,
          confirmMigration: !needsAck || acknowledged,
          forceOverride: hasSecurityBlocker && acknowledged
        });
      } else {
        await intric.models.migrateCompletion({
          fromId: sourceModel.id,
          toId: targetModelId,
          confirmMigration: !needsAck || acknowledged,
          forceOverride: hasSecurityBlocker && acknowledged
        });
      }
      toast.success(m.migration_success());
      bumpModelMigrationHistoryVersion();
      await invalidate("admin:model-providers:load");
      dialogOpen = false;
    } catch (e: unknown) {
      submitError = e instanceof Error ? e.message : m.migration_failed();
    } finally {
      isSubmitting = false;
    }
  }
</script>

<Dialog.Root bind:open={dialogOpen}>
  <Dialog.Content class="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-3xl">
    <Dialog.Header class="px-6 pt-6 pb-2">
      <Dialog.Title>{m.migrate_model_title()}</Dialog.Title>
    </Dialog.Header>

    <div class="min-h-0 flex-1 overflow-y-auto px-6 py-4">
      <div class="flex flex-col gap-5">
        <p class="text-muted-foreground text-sm">
          {m.migrate_model_description({
            name: sourceModel.nickname ? sourceModel.nickname : sourceModel.name
          })}
        </p>

        {#if sourceAlreadyMigrated}
          <div
            class="border-negative-default bg-negative-dimmer/50 text-negative-stronger rounded-r-md border-l-2 px-4 py-3 text-sm"
            role="alert"
          >
            {m.model_tooltip_migrated()}
          </div>
        {/if}

        <!-- 1. Impact preview -->
        {#if !sourceAlreadyMigrated && isLoadingImpact}
          <div class="text-muted-foreground flex items-center gap-2 py-3 text-sm">
            <Loader2 class="size-4 animate-spin" aria-hidden="true" />
            <span>{m.loading()}</span>
          </div>
        {:else if !sourceAlreadyMigrated && impactLoadError}
          <div
            class="border-negative-default bg-negative-dimmer/50 text-negative-stronger rounded-r-md border-l-2 px-4 py-3 text-sm"
            role="alert"
          >
            <div class="flex items-center justify-between gap-4">
              <span>{impactLoadError}</span>
              <Button variant="outline" size="sm" onclick={loadImpact}>{m.retry()}</Button>
            </div>
          </div>
        {:else if !sourceAlreadyMigrated && impactTotal > 0}
          <ModelUsageBreakdown
            details={impactDetails}
            {spacesCount}
            title={m.migration_impact_title({ count: impactTotal })}
            spacesText={m.migration_spaces_info({ count: spacesCount })}
          />
        {:else if !sourceAlreadyMigrated}
          <div class="border-border text-muted-foreground rounded-lg border px-4 py-3 text-sm">
            {m.migration_no_impact()}
          </div>
        {/if}

        <!-- 2. Target model selection -->
        {#if !sourceAlreadyMigrated}
          <Field.Field>
            <Field.Label for="migrate-target">{m.migrate_model_target_label()}</Field.Label>
            <Select.Root
              type="single"
              bind:value={targetModelId}
              disabled={availableTargets.length === 0}
            >
              <Select.Trigger id="migrate-target" class="w-full">
                <span data-slot="select-value">
                  {selectedTargetLabel || m.migrate_model_target_placeholder()}
                </span>
              </Select.Trigger>
              <Select.Content>
                {#each availableTargets as target (target.id)}
                  <Select.Item value={target.id} label={labelFor(target)}>
                    {labelFor(target)}
                  </Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
            {#if availableTargets.length === 0}
              <Field.Description>{m.migrate_model_no_targets()}</Field.Description>
            {/if}
          </Field.Field>
        {/if}

        <!-- 3. Validation results — split by severity -->
        {#if isValidating}
          <div class="text-muted-foreground flex items-center gap-2 py-2 text-sm">
            <Loader2 class="size-4 animate-spin" aria-hidden="true" />
            <span>{m.loading()}</span>
          </div>
        {:else if anyValidationSection}
          <div class="flex flex-col gap-3">
            <!-- Errors: hard blockers (security classification) -->
            {#if hasSecurityBlocker}
              <div
                class="border-negative-default/30 bg-negative-dimmer/40 text-negative-stronger flex items-start gap-3 rounded-lg border px-4 py-3 text-sm"
                role="alert"
              >
                <ShieldAlert size={18} class="mt-0.5 flex-shrink-0" aria-hidden="true" />
                <div>
                  <p class="font-medium">{m.migration_blocked_title()}</p>
                  {#each blockerMsgs as w, i (i)}
                    <p class="text-negative-default mt-1">{w}</p>
                  {/each}
                </div>
              </div>
            {/if}

            <!-- Warnings: compatibility issues -->
            {#if showWarnings}
              <div
                class="border-warning-default/30 bg-warning-dimmer/30 rounded-lg border px-4 py-3 text-sm"
                role="alert"
              >
                <p class="text-warning-stronger mb-1.5 font-medium">
                  {m.migration_warnings_title()}
                </p>
                <ul class="space-y-1.5">
                  {#each warningMsgs as w, i (i)}
                    <li class="text-warning-stronger flex items-start gap-2">
                      <AlertTriangle size={14} class="mt-0.5 flex-shrink-0" aria-hidden="true" />
                      <span>{w}</span>
                    </li>
                  {/each}
                </ul>
              </div>
            {/if}

            <!-- Info: purely informational notices -->
            {#if showInfo}
              <div
                class="border-border bg-muted/30 text-muted-foreground rounded-lg border px-4 py-3 text-sm"
              >
                <p class="text-default mb-1.5 font-medium">{m.migration_info_title()}</p>
                <ul class="space-y-1.5">
                  {#each infoMsgs as w, i (i)}
                    <li class="flex items-start gap-2">
                      <Info size={14} class="mt-0.5 flex-shrink-0" aria-hidden="true" />
                      <span>{w}</span>
                    </li>
                  {/each}
                </ul>
              </div>
            {/if}

            <!-- Single acknowledgement gating both blockers and warnings -->
            {#if needsAck}
              <div
                class="rounded-lg border px-4 py-3 {hasSecurityBlocker
                  ? 'border-negative-default/30 bg-negative-dimmer/30'
                  : 'border-warning-default/30 bg-warning-dimmer/20'}"
              >
                <Field.Field
                  orientation="horizontal"
                  class="{hasSecurityBlocker
                    ? 'text-negative-stronger'
                    : 'text-warning-stronger'} w-fit"
                >
                  <Checkbox id="migrate-acknowledge" bind:checked={acknowledged} />
                  <Field.Label
                    for="migrate-acknowledge"
                    class="{hasSecurityBlocker
                      ? 'text-negative-stronger'
                      : 'text-warning-stronger'} cursor-pointer"
                  >
                    {hasSecurityBlocker
                      ? m.migrate_model_override_security_label()
                      : m.migrate_model_confirm_label()}
                  </Field.Label>
                </Field.Field>
              </div>
            {/if}
          </div>
        {/if}

        <!-- 4. Submit error -->
        {#if submitError}
          <div
            class="border-negative-default bg-negative-dimmer/50 text-negative-stronger rounded-r-md border-l-2 px-4 py-3 text-sm"
            role="alert"
          >
            {submitError}
          </div>
        {/if}
      </div>
    </div>

    <div class="border-border flex justify-end gap-2 border-t px-6 py-4">
      <Button variant="outline" onclick={() => (dialogOpen = false)}>{m.cancel()}</Button>
      <Button onclick={handleMigrate} disabled={isSubmitting || !canMigrate}>
        {#if isSubmitting}
          <Loader2 class="size-4 animate-spin" aria-hidden="true" />
          {m.migrating()}
        {:else}
          {m.migrate_model_usage()}
        {/if}
      </Button>
    </div>
  </Dialog.Content>
</Dialog.Root>
