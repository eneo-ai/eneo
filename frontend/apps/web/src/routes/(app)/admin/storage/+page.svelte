<script lang="ts">
  import { onMount } from "svelte";
  import {
    DEPLOYMENT_POLICY_CONFLICT_ERROR_CODE,
    EneoError,
    OBJECT_STORE_NOT_SELECTABLE_ERROR_CODE,
    type ContentMoveFailureCode,
    type ContentMoveState,
    type ContentState,
    type DeploymentPolicy,
    type DeploymentPolicyUpdate,
    type MoveQueueResult,
    type ObjectContentInventory,
    type ObjectContentMoves,
    type ObjectContentReadinessCode,
    type StorageKind,
    type UploadLimitUseCase
  } from "@eneo/eneo-js";
  import AlertCircle from "lucide-svelte/icons/alert-circle";
  import ArrowRightLeft from "lucide-svelte/icons/arrow-right-left";
  import CheckCircle2 from "lucide-svelte/icons/check-circle-2";
  import Database from "lucide-svelte/icons/database";
  import ExternalLink from "lucide-svelte/icons/external-link";
  import Gauge from "lucide-svelte/icons/gauge";
  import HardDrive from "lucide-svelte/icons/hard-drive";
  import Info from "lucide-svelte/icons/info";
  import Loader2 from "lucide-svelte/icons/loader-2";
  import RefreshCw from "lucide-svelte/icons/refresh-cw";
  import { Page, Settings } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { getAppContext } from "$lib/core/AppContext.js";
  import { getEneo } from "$lib/core/Eneo";
  import PolicySection from "$lib/features/admin/PolicySection.svelte";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import ByteLimitField from "./ByteLimitField.svelte";
  import StorageInventorySection from "./StorageInventorySection.svelte";
  import StorageReadinessSection from "./StorageReadinessSection.svelte";

  type InventoryStatus = "idle" | "loading" | "error";
  type MoveAction = "queue" | "pause" | null;

  const eneo = getEneo();
  const { user } = getAppContext();

  let deploymentPolicy = $state<DeploymentPolicy | null>(null);
  let contentInventory = $state<ObjectContentInventory | null>(null);
  let inventoryStatus = $state<InventoryStatus>("idle");
  let inventoryRefreshedAt = $state<number | null>(null);
  let contentMoves = $state<ObjectContentMoves | null>(null);
  let moveStatus = $state<InventoryStatus>("idle");
  let movesRefreshedAt = $state<number | null>(null);
  let moveTarget = $state<StorageKind>("object_store");
  let moveLimit = $state(25);
  let moveActionPending = $state<MoveAction>(null);
  let moveActionError = $state(false);
  let moveOutcomeUnknown = $state(false);
  let moveActionStale = $state(false);
  let moveQueueResult = $state<MoveQueueResult | null>(null);
  let loading = $state(true);
  let reloading = $state(false);
  let loadError = $state(false);
  let saving = $state(false);
  let saveOutcomeUnknown = $state(false);
  let saveSuccess = $state(false);
  let stale = $state(false);
  let targetUnavailable = $state(false);
  let authorityRevoked = $state(false);

  let storageTarget = $state<StorageKind>("postgres_inline");
  let sessionFileLimitBytes = $state(1);
  let sessionImageLimitBytes = $state(1);
  let knowledgeFileLimitBytes = $state(1);
  let transcriptionAudioLimitBytes = $state(1);
  let policyAlertRef = $state<HTMLElement | null>(null);
  let moveAlertRef = $state<HTMLElement | null>(null);
  let moveStatusAlertRef = $state<HTMLElement | null>(null);

  const canEdit = $derived(user.is_platform_admin === true && !authorityRevoked);
  const policyMutationPending = $derived(saving || moveActionPending === "pause");
  const objectStoreCapability = $derived(
    deploymentPolicy?.capabilities.find((capability) => capability.target === "object_store")
  );
  const objectStoreUnavailable = $derived(objectStoreCapability?.selectable !== true);
  const validMoveLimit = $derived(
    Number.isSafeInteger(moveLimit) && moveLimit >= 1 && moveLimit <= 100
  );
  const queueUnavailable = $derived(
    (moveTarget === "object_store" && objectStoreUnavailable) ||
      !validMoveLimit ||
      moveStatus !== "idle" ||
      moveActionPending !== null
  );
  const selectedObjectStoreDegraded = $derived(
    deploymentPolicy?.policy.new_write_storage_target === "object_store" &&
      objectStoreCapability?.readiness_code !== "ready"
  );
  const validDraft = $derived(
    [
      sessionFileLimitBytes,
      sessionImageLimitBytes,
      knowledgeFileLimitBytes,
      transcriptionAudioLimitBytes
    ].every(isValidByteLimit)
  );
  const dirty = $derived(
    deploymentPolicy !== null &&
      (storageTarget !== deploymentPolicy.policy.new_write_storage_target ||
        sessionFileLimitBytes !== deploymentPolicy.policy.session_file_limit_bytes ||
        sessionImageLimitBytes !== deploymentPolicy.policy.session_image_limit_bytes ||
        knowledgeFileLimitBytes !== deploymentPolicy.policy.knowledge_file_limit_bytes ||
        transcriptionAudioLimitBytes !== deploymentPolicy.policy.transcription_audio_limit_bytes)
  );
  const saveUnavailable = $derived(
    !dirty || !validDraft || policyMutationPending || stale || saveOutcomeUnknown
  );

  function isValidByteLimit(value: number): boolean {
    return Number.isSafeInteger(value) && value > 0;
  }

  $effect(() => policyAlertRef?.focus());
  $effect(() => moveAlertRef?.focus());
  $effect(() => moveStatusAlertRef?.focus());

  function applyPolicy(next: DeploymentPolicy, preserveDraft = false): boolean {
    const currentRevision = deploymentPolicy?.policy.revision;
    if (currentRevision !== undefined && next.policy.revision < currentRevision) return true;

    if (contentMoves !== null && next.policy.revision >= contentMoves.policy_revision) {
      contentMoves = {
        ...contentMoves,
        policy_revision: next.policy.revision,
        paused: next.policy.moves_paused
      };
    }
    if (preserveDraft && currentRevision !== undefined && next.policy.revision > currentRevision)
      return false;

    deploymentPolicy = next;
    if (currentRevision === undefined) moveTarget = next.policy.new_write_storage_target;
    if (!preserveDraft) {
      storageTarget = next.policy.new_write_storage_target;
      sessionFileLimitBytes = next.policy.session_file_limit_bytes;
      sessionImageLimitBytes = next.policy.session_image_limit_bytes;
      knowledgeFileLimitBytes = next.policy.knowledge_file_limit_bytes;
      transcriptionAudioLimitBytes = next.policy.transcription_audio_limit_bytes;
    }
    return true;
  }

  function discardPolicyDraft(): void {
    if (deploymentPolicy === null) return;
    storageTarget = deploymentPolicy.policy.new_write_storage_target;
    sessionFileLimitBytes = deploymentPolicy.policy.session_file_limit_bytes;
    sessionImageLimitBytes = deploymentPolicy.policy.session_image_limit_bytes;
    knowledgeFileLimitBytes = deploymentPolicy.policy.knowledge_file_limit_bytes;
    transcriptionAudioLimitBytes = deploymentPolicy.policy.transcription_audio_limit_bytes;
    stale = false;
    targetUnavailable = false;
    saveOutcomeUnknown = false;
  }

  function updateStorageTarget(value: string): void {
    if (value === "postgres_inline" || value === "object_store") storageTarget = value;
  }

  async function loadPolicy(preserveDraft = false) {
    const initialLoad = deploymentPolicy === null;
    if (initialLoad) loading = true;
    else reloading = true;
    loadError = false;

    try {
      const nextPolicy = await eneo.objectContentPolicy.get();
      const policyApplied = applyPolicy(nextPolicy, preserveDraft);
      stale = !policyApplied;
      targetUnavailable = false;
      saveOutcomeUnknown = false;
      saveSuccess = false;
      moveActionError = false;
      moveOutcomeUnknown = false;
      moveActionStale = false;
    } catch (error: unknown) {
      if (hasStatus(error, 403)) {
        authorityRevoked = true;
        contentInventory = null;
        inventoryStatus = "idle";
        contentMoves = null;
        moveStatus = "idle";
      }
      loadError = true;
      return;
    } finally {
      loading = false;
      reloading = false;
    }

    await loadInventory();
    await loadMoves();
  }

  async function loadInventory() {
    if (user.is_platform_admin !== true || authorityRevoked) {
      contentInventory = null;
      inventoryStatus = "idle";
      return;
    }
    if (inventoryStatus === "loading") return;

    inventoryStatus = "loading";
    try {
      contentInventory = await eneo.objectContentPolicy.getInventory();
      inventoryRefreshedAt = Date.now();
      inventoryStatus = "idle";
    } catch (error: unknown) {
      if (hasStatus(error, 403)) {
        authorityRevoked = true;
        contentInventory = null;
        inventoryStatus = "idle";
      } else {
        inventoryStatus = "error";
      }
    }
  }

  async function loadMoves() {
    if (user.is_platform_admin !== true || authorityRevoked) {
      contentMoves = null;
      moveStatus = "idle";
      return;
    }
    if (moveStatus === "loading") return;

    const previousMoves = contentMoves;
    moveStatus = "loading";
    try {
      const nextMoves = await eneo.objectContentPolicy.getMoves();
      contentMoves =
        previousMoves !== null &&
        nextMoves.policy_revision < previousMoves.policy_revision &&
        (deploymentPolicy === null ||
          previousMoves.policy_revision >= deploymentPolicy.policy.revision)
          ? previousMoves
          : deploymentPolicy !== null &&
              nextMoves.policy_revision < deploymentPolicy.policy.revision
            ? {
                ...nextMoves,
                policy_revision: deploymentPolicy.policy.revision,
                paused: deploymentPolicy.policy.moves_paused
              }
            : nextMoves;
      movesRefreshedAt = Date.now();
      moveStatus = "idle";
    } catch (error: unknown) {
      if (hasStatus(error, 403)) {
        authorityRevoked = true;
        contentMoves = null;
        moveStatus = "idle";
      } else {
        moveStatus = "error";
      }
    }
  }

  function hasStatus(error: unknown, status: number): boolean {
    return (
      typeof error === "object" && error !== null && "status" in error && error.status === status
    );
  }

  async function savePolicy() {
    if (!canEdit || !deploymentPolicy || saveUnavailable) return;

    const replacement: DeploymentPolicyUpdate = {
      expected_revision: deploymentPolicy.policy.revision,
      new_write_storage_target: storageTarget,
      session_file_limit_bytes: sessionFileLimitBytes,
      session_image_limit_bytes: sessionImageLimitBytes,
      knowledge_file_limit_bytes: knowledgeFileLimitBytes,
      transcription_audio_limit_bytes: transcriptionAudioLimitBytes
    };

    saving = true;
    saveOutcomeUnknown = false;
    saveSuccess = false;
    stale = false;
    targetUnavailable = false;
    try {
      applyPolicy(await eneo.objectContentPolicy.replace(replacement));
      saveSuccess = true;
    } catch (error: unknown) {
      if (hasStatus(error, 403)) {
        authorityRevoked = true;
        contentInventory = null;
        inventoryStatus = "idle";
      } else if (
        error instanceof EneoError &&
        error.code === DEPLOYMENT_POLICY_CONFLICT_ERROR_CODE
      ) {
        stale = true;
      } else if (
        error instanceof EneoError &&
        error.code === OBJECT_STORE_NOT_SELECTABLE_ERROR_CODE
      ) {
        targetUnavailable = true;
      } else saveOutcomeUnknown = true;
    } finally {
      saving = false;
    }
  }

  async function queueContentMoves() {
    if (!canEdit || queueUnavailable) return;

    moveActionPending = "queue";
    moveActionError = false;
    moveOutcomeUnknown = false;
    moveActionStale = false;
    moveQueueResult = null;
    try {
      moveQueueResult = await eneo.objectContentPolicy.queueMoves({
        target: moveTarget,
        limit: moveLimit
      });
      await loadMoves();
    } catch (error: unknown) {
      if (hasStatus(error, 403)) {
        authorityRevoked = true;
        contentInventory = null;
        contentMoves = null;
        inventoryStatus = "idle";
        moveStatus = "idle";
      } else if (hasStatus(error, 503)) {
        moveActionError = true;
      } else {
        moveOutcomeUnknown = true;
        await loadMoves();
      }
    } finally {
      moveActionPending = null;
    }
  }

  async function setMovesPaused() {
    if (!canEdit || !contentMoves || moveStatus !== "idle" || policyMutationPending) return;

    const preservePolicyDraft = dirty;
    moveActionPending = "pause";
    moveActionError = false;
    moveOutcomeUnknown = false;
    moveActionStale = false;
    moveQueueResult = null;
    try {
      const policyBaselineWasCurrent =
        deploymentPolicy?.policy.revision === contentMoves.policy_revision;
      const result = await eneo.objectContentPolicy.setMovesPaused({
        expected_revision: contentMoves.policy_revision,
        moves_paused: !contentMoves.paused
      });
      contentMoves = {
        ...contentMoves,
        policy_revision: result.policy_revision,
        paused: result.paused
      };
      if (deploymentPolicy !== null && policyBaselineWasCurrent) {
        deploymentPolicy = {
          ...deploymentPolicy,
          policy: {
            ...deploymentPolicy.policy,
            revision: result.policy_revision,
            moves_paused: result.paused
          }
        };
      } else if (deploymentPolicy !== null) {
        await loadPolicy(preservePolicyDraft);
      }
    } catch (error: unknown) {
      if (hasStatus(error, 403)) {
        authorityRevoked = true;
        contentInventory = null;
        contentMoves = null;
        inventoryStatus = "idle";
        moveStatus = "idle";
      } else if (hasStatus(error, 409)) {
        moveActionStale = true;
      } else {
        moveOutcomeUnknown = true;
        await loadPolicy(preservePolicyDraft);
        moveOutcomeUnknown = true;
      }
    } finally {
      moveActionPending = null;
    }
  }

  function storageTargetLabel(target: StorageKind | null): string {
    if (target === "postgres_inline") return m.storage_target_postgres_inline();
    if (target === "object_store") return m.storage_target_object_store();
    return m.storage_target_not_applicable();
  }

  function readinessLabel(code: ObjectContentReadinessCode): string {
    const labels: Record<ObjectContentReadinessCode, () => string> = {
      ready: m.storage_readiness_ready,
      object_store_not_configured: m.storage_readiness_object_store_not_configured,
      not_initialized: m.storage_readiness_not_initialized,
      configuration_required: m.storage_readiness_configuration_required,
      database_unavailable: m.storage_readiness_database_unavailable,
      store_degraded: m.storage_readiness_store_degraded
    };
    return labels[code]();
  }

  function useCaseLabel(useCase: UploadLimitUseCase): string {
    const labels: Record<UploadLimitUseCase, () => string> = {
      session_file: m.storage_use_case_session_file,
      session_image: m.storage_use_case_session_image,
      session_audio: m.storage_use_case_session_audio,
      knowledge_file: m.storage_use_case_knowledge_file,
      knowledge_audio: m.storage_use_case_knowledge_audio
    };
    return labels[useCase]();
  }

  function contentStateLabel(state: ContentState): string {
    const labels: Record<ContentState, () => string> = {
      pending: m.storage_content_state_pending,
      available: m.storage_content_state_available,
      retained: m.storage_content_state_retained,
      failed: m.storage_content_state_failed,
      delete_pending: m.storage_content_state_delete_pending,
      tombstoned: m.storage_content_state_tombstoned
    };
    return labels[state]();
  }

  function moveStateLabel(state: ContentMoveState): string {
    const labels: Record<ContentMoveState, () => string> = {
      pending: m.storage_move_state_pending,
      target_verified: m.storage_move_state_target_verified,
      failed: m.storage_move_state_failed
    };
    return labels[state]();
  }

  function moveFailureLabel(code: ContentMoveFailureCode | null): string {
    if (code === null) return m.storage_moves_failure_none();
    const labels: Record<ContentMoveFailureCode, () => string> = {
      store_unavailable: m.storage_move_failure_store_unavailable,
      target_too_large: m.storage_move_failure_target_too_large,
      source_missing: m.storage_move_failure_source_missing,
      source_corrupt: m.storage_move_failure_source_corrupt,
      target_corrupt: m.storage_move_failure_target_corrupt,
      content_ineligible: m.storage_move_failure_content_ineligible
    };
    return labels[code]();
  }

  function policyActorLabel(actor: DeploymentPolicy["policy"]["updated_by_actor"]): string {
    const labels: Record<DeploymentPolicy["policy"]["updated_by_actor"], () => string> = {
      migration: m.storage_policy_actor_migration,
      platform_admin: m.storage_policy_actor_platform_admin
    };
    return labels[actor]();
  }

  function storageLocale(): string {
    return getLocale() === "sv" ? "sv-SE" : "en-US";
  }

  function storageCount(value: number): string {
    return new Intl.NumberFormat(storageLocale()).format(value);
  }

  function policyBytes(value: number): string {
    const units = [
      { bytes: 1024 ** 3, label: m.storage_unit_gb },
      { bytes: 1024 ** 2, label: m.storage_unit_mb },
      { bytes: 1024, label: m.storage_unit_kb }
    ];
    const unit = units.find((candidate) => value % candidate.bytes === 0);
    return unit
      ? `${storageCount(value / unit.bytes)} ${unit.label()}`
      : `${storageCount(value)} ${m.storage_unit_b()}`;
  }

  function storageBytes(value: number): string {
    const units = [
      { bytes: 1024 ** 3, label: m.storage_unit_gb },
      { bytes: 1024 ** 2, label: m.storage_unit_mb },
      { bytes: 1024, label: m.storage_unit_kb },
      { bytes: 1, label: m.storage_unit_b }
    ];
    const unit = units.find((candidate) => value >= candidate.bytes) ?? units[units.length - 1];
    return `${new Intl.NumberFormat(storageLocale(), { maximumFractionDigits: 0 }).format(
      value / unit.bytes
    )} ${unit.label()}`;
  }

  function storageDate(value: string | null): string {
    if (value === null) return m.storage_inventory_not_available();
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return m.storage_inventory_not_available();
    return new Intl.DateTimeFormat(storageLocale(), {
      dateStyle: "medium"
    }).format(date);
  }

  function storageTime(value: number): string {
    return new Intl.DateTimeFormat(storageLocale(), {
      timeStyle: "short"
    }).format(value);
  }

  onMount(() => {
    void loadPolicy();
  });
</script>

<svelte:head>
  <title>{m.storage_settings_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.storage_settings_title()} />
  </Page.Header>

  <Page.Main>
    <Settings.Page>
      <div class="flex flex-col gap-6 pb-16">
        {#if loading}
          <div data-testid="storage-loading" class="flex flex-col gap-5" aria-busy="true">
            <div class="flex flex-col gap-2">
              <Skeleton class="h-5 w-56" />
              <Skeleton class="h-4 w-full max-w-xl" />
            </div>
            <Skeleton class="h-40 w-full rounded-lg" />
            <span class="sr-only">{m.storage_settings_loading()}</span>
          </div>
        {:else if loadError && !deploymentPolicy}
          <Alert.Root
            bind:ref={policyAlertRef}
            data-testid="policy-recovery-alert"
            tabindex={-1}
            variant="destructive"
            aria-live="assertive"
          >
            <AlertCircle />
            <Alert.Title>{m.storage_settings_load_error_title()}</Alert.Title>
            <Alert.Description>
              <p>{m.storage_settings_load_error_description()}</p>
              <Button class="mt-3" variant="outline" onclick={() => loadPolicy()}>
                {m.retry()}
              </Button>
            </Alert.Description>
          </Alert.Root>
        {:else if deploymentPolicy}
          <div class="flex max-w-3xl flex-col gap-2">
            <p class="text-secondary text-sm leading-6">
              {m.storage_settings_description()}
            </p>
            <p class="text-muted text-xs">
              {m.storage_settings_last_changed({
                date: storageDate(deploymentPolicy.policy.updated_at),
                actor: policyActorLabel(deploymentPolicy.policy.updated_by_actor),
                revision: deploymentPolicy.policy.revision
              })}
            </p>
          </div>

          {#if !canEdit}
            <Alert.Root>
              <Info />
              <Alert.Title>{m.storage_settings_read_only_title()}</Alert.Title>
              <Alert.Description>{m.storage_settings_read_only_description()}</Alert.Description>
            </Alert.Root>
          {/if}

          <form
            class="flex flex-col gap-6"
            onsubmit={(event) => {
              event.preventDefault();
              void savePolicy();
            }}
          >
            <PolicySection
              id="storage-target"
              title={m.storage_settings_target_title()}
              description={m.storage_settings_target_description()}
              summary={storageTargetLabel(
                canEdit ? storageTarget : deploymentPolicy.policy.new_write_storage_target
              )}
              summaryVariant={selectedObjectStoreDegraded ? "destructive" : "default"}
            >
              {#snippet icon()}
                <Database class="size-5" aria-hidden="true" />
              {/snippet}

              {#if selectedObjectStoreDegraded}
                <Alert.Root variant="destructive">
                  <AlertCircle />
                  <Alert.Title>{m.storage_settings_selected_target_degraded_title()}</Alert.Title>
                  <Alert.Description>
                    {m.storage_settings_selected_target_degraded_description()}
                  </Alert.Description>
                </Alert.Root>
              {/if}

              <Alert.Root>
                <Info />
                <Alert.Title>{m.storage_settings_new_writes_only_title()}</Alert.Title>
                <Alert.Description>
                  <p>{m.storage_settings_no_move_notice()}</p>
                  <p>{m.storage_settings_no_fallback_notice()}</p>
                </Alert.Description>
              </Alert.Root>

              {#if stale}
                <Alert.Root
                  bind:ref={policyAlertRef}
                  data-testid="policy-recovery-alert"
                  tabindex={-1}
                  variant="destructive"
                  aria-live="assertive"
                >
                  <AlertCircle />
                  <Alert.Title>{m.storage_settings_stale_title()}</Alert.Title>
                  <Alert.Description>
                    <p>{m.storage_settings_stale_description()}</p>
                    <Button
                      class="mt-3"
                      variant="outline"
                      disabled={reloading}
                      onclick={() => loadPolicy()}
                    >
                      {#if reloading}
                        <Loader2 data-icon="inline-start" class="animate-spin" />
                        {m.storage_settings_reloading()}
                      {:else}
                        {m.storage_settings_reload_latest()}
                      {/if}
                    </Button>
                  </Alert.Description>
                </Alert.Root>
              {:else if loadError}
                <Alert.Root
                  bind:ref={policyAlertRef}
                  data-testid="policy-recovery-alert"
                  tabindex={-1}
                  variant="destructive"
                  aria-live="assertive"
                >
                  <AlertCircle />
                  <Alert.Title>{m.storage_settings_reload_error_title()}</Alert.Title>
                  <Alert.Description>
                    {m.storage_settings_reload_error_description()}
                  </Alert.Description>
                </Alert.Root>
              {/if}

              {#if targetUnavailable}
                <Alert.Root
                  bind:ref={policyAlertRef}
                  data-testid="policy-recovery-alert"
                  tabindex={-1}
                  variant="destructive"
                  aria-live="assertive"
                >
                  <AlertCircle />
                  <Alert.Title>{m.storage_settings_target_unavailable_title()}</Alert.Title>
                  <Alert.Description>
                    {m.storage_settings_target_unavailable_description()}
                  </Alert.Description>
                </Alert.Root>
              {/if}

              {#if saveOutcomeUnknown}
                <Alert.Root
                  bind:ref={policyAlertRef}
                  data-testid="policy-recovery-alert"
                  tabindex={-1}
                  variant="destructive"
                  aria-live="assertive"
                >
                  <AlertCircle />
                  <Alert.Title>{m.storage_settings_save_outcome_unknown_title()}</Alert.Title>
                  <Alert.Description>
                    <p>{m.storage_settings_save_outcome_unknown_description()}</p>
                    <Button
                      class="mt-3"
                      variant="outline"
                      disabled={reloading}
                      onclick={() => loadPolicy()}
                    >
                      {#if reloading}
                        <Loader2 data-icon="inline-start" class="animate-spin" />
                        {m.storage_settings_reloading()}
                      {:else}
                        {m.storage_settings_reload_latest()}
                      {/if}
                    </Button>
                  </Alert.Description>
                </Alert.Root>
              {/if}

              {#if saveSuccess}
                <Alert.Root aria-live="polite">
                  <CheckCircle2 />
                  <Alert.Title>{m.storage_settings_save_success()}</Alert.Title>
                </Alert.Root>
              {/if}

              {#if canEdit}
                <Field.Set>
                  <Field.Legend class="sr-only">{m.storage_settings_target_title()}</Field.Legend>
                  <RadioGroup.Root
                    bind:value={() => storageTarget, updateStorageTarget}
                    class="grid gap-3 sm:grid-cols-2"
                    disabled={policyMutationPending}
                    aria-invalid={storageTarget === "object_store" && objectStoreUnavailable}
                    aria-describedby="storage-target-help"
                  >
                    <Field.Label
                      for="storage-target-postgres"
                      class="border-default has-data-[state=checked]:border-accent-default has-data-[state=checked]:bg-accent-dimmer w-auto cursor-pointer items-start rounded-lg border p-4"
                    >
                      <RadioGroup.Item
                        id="storage-target-postgres"
                        value="postgres_inline"
                        class="mt-0.5"
                      />
                      <Database class="mt-0.5 size-5 shrink-0" aria-hidden="true" />
                      <span class="flex flex-col gap-1">
                        <span class="font-medium">{m.storage_target_postgres_inline()}</span>
                        <span class="text-secondary text-sm">
                          {m.storage_target_postgres_inline_description()}
                        </span>
                      </span>
                    </Field.Label>

                    <Field.Label
                      for="storage-target-object-store"
                      class="border-default has-data-[state=checked]:border-accent-default has-data-[state=checked]:bg-accent-dimmer data-[disabled=true]:opacity-60 w-auto cursor-pointer items-start rounded-lg border p-4"
                      data-disabled={objectStoreUnavailable}
                    >
                      <RadioGroup.Item
                        id="storage-target-object-store"
                        value="object_store"
                        disabled={objectStoreUnavailable}
                        class="mt-0.5"
                      />
                      <HardDrive class="mt-0.5 size-5 shrink-0" aria-hidden="true" />
                      <span class="flex flex-col gap-1">
                        <span class="flex flex-wrap items-center gap-2 font-medium">
                          {m.storage_target_object_store()}
                          {#if objectStoreUnavailable}
                            <Badge variant="secondary">{m.storage_target_unavailable()}</Badge>
                          {/if}
                        </span>
                        <span class="text-secondary text-sm">
                          {m.storage_target_object_store_description()}
                        </span>
                        {#if objectStoreCapability}
                          <span class="text-muted text-xs">
                            {readinessLabel(objectStoreCapability.readiness_code)}
                          </span>
                        {/if}
                        {#if objectStoreUnavailable}
                          <Button
                            href="https://docs.eneo.ai/guides/object-content-storage"
                            target="_blank"
                            rel="noreferrer"
                            variant="link"
                            size="sm"
                            class="h-auto w-fit px-0"
                            onclick={(event) => event.stopPropagation()}
                          >
                            {m.storage_settings_object_store_docs()}
                            <ExternalLink data-icon="inline-end" aria-hidden="true" />
                          </Button>
                        {/if}
                      </span>
                    </Field.Label>
                  </RadioGroup.Root>
                  <Field.Description id="storage-target-help">
                    {m.storage_settings_target_help()}
                  </Field.Description>
                </Field.Set>
              {:else}
                <div class="flex items-start gap-3">
                  {#if deploymentPolicy.policy.new_write_storage_target === "postgres_inline"}
                    <Database class="mt-0.5 size-5 shrink-0" aria-hidden="true" />
                  {:else}
                    <HardDrive class="mt-0.5 size-5 shrink-0" aria-hidden="true" />
                  {/if}
                  <div class="flex flex-col gap-1">
                    <p class="font-medium">
                      {storageTargetLabel(deploymentPolicy.policy.new_write_storage_target)}
                    </p>
                    <p class="text-secondary text-sm">
                      {deploymentPolicy.policy.new_write_storage_target === "postgres_inline"
                        ? m.storage_target_postgres_inline_description()
                        : m.storage_target_object_store_description()}
                    </p>
                  </div>
                </div>
              {/if}
            </PolicySection>

            <PolicySection
              id="storage-limits"
              title={m.storage_settings_limits_title()}
              description={m.storage_settings_limits_description()}
              summary={m.storage_settings_revision({ revision: deploymentPolicy.policy.revision })}
              summaryVariant="outline"
            >
              {#snippet icon()}
                <Gauge class="size-5" aria-hidden="true" />
              {/snippet}

              {#if canEdit}
                <Field.Group class="grid gap-5 sm:grid-cols-2">
                  <ByteLimitField
                    id="session-file-limit"
                    label={m.storage_limit_session_file()}
                    description={m.storage_limit_bytes_help()}
                    bind:bytes={sessionFileLimitBytes}
                    storedBytes={deploymentPolicy.policy.session_file_limit_bytes}
                    disabled={policyMutationPending}
                  />
                  <ByteLimitField
                    id="session-image-limit"
                    label={m.storage_limit_session_image()}
                    description={m.storage_limit_bytes_help()}
                    bind:bytes={sessionImageLimitBytes}
                    storedBytes={deploymentPolicy.policy.session_image_limit_bytes}
                    disabled={policyMutationPending}
                  />
                  <ByteLimitField
                    id="knowledge-file-limit"
                    label={m.storage_limit_knowledge_file()}
                    description={m.storage_limit_bytes_help()}
                    bind:bytes={knowledgeFileLimitBytes}
                    storedBytes={deploymentPolicy.policy.knowledge_file_limit_bytes}
                    disabled={policyMutationPending}
                  />
                  <ByteLimitField
                    id="transcription-audio-limit"
                    label={m.storage_limit_transcription_audio()}
                    description={m.storage_limit_audio_help()}
                    bind:bytes={transcriptionAudioLimitBytes}
                    storedBytes={deploymentPolicy.policy.transcription_audio_limit_bytes}
                    disabled={policyMutationPending}
                  />
                </Field.Group>
              {:else}
                <dl class="grid gap-5 sm:grid-cols-2">
                  <div class="flex flex-col gap-1">
                    <dt class="text-sm font-medium">{m.storage_limit_session_file()}</dt>
                    <dd class="text-secondary text-sm">
                      {policyBytes(deploymentPolicy.policy.session_file_limit_bytes)}
                    </dd>
                  </div>
                  <div class="flex flex-col gap-1">
                    <dt class="text-sm font-medium">{m.storage_limit_session_image()}</dt>
                    <dd class="text-secondary text-sm">
                      {policyBytes(deploymentPolicy.policy.session_image_limit_bytes)}
                    </dd>
                  </div>
                  <div class="flex flex-col gap-1">
                    <dt class="text-sm font-medium">{m.storage_limit_knowledge_file()}</dt>
                    <dd class="text-secondary text-sm">
                      {policyBytes(deploymentPolicy.policy.knowledge_file_limit_bytes)}
                    </dd>
                  </div>
                  <div class="flex flex-col gap-1">
                    <dt class="text-sm font-medium">{m.storage_limit_transcription_audio()}</dt>
                    <dd class="text-secondary text-sm">
                      {policyBytes(deploymentPolicy.policy.transcription_audio_limit_bytes)}
                    </dd>
                  </div>
                </dl>
              {/if}

              <div class="border-default overflow-x-auto rounded-lg border">
                <Table.Root class="min-w-[760px]">
                  <Table.Caption class="sr-only">
                    {m.storage_effective_limits_caption()}
                  </Table.Caption>
                  <Table.Header>
                    <Table.Row>
                      <Table.Head>{m.storage_effective_limits_use_case()}</Table.Head>
                      <Table.Head>{m.storage_effective_limits_configured()}</Table.Head>
                      <Table.Head>{m.storage_effective_limits_effective()}</Table.Head>
                      <Table.Head>{m.storage_effective_limits_target()}</Table.Head>
                      <Table.Head>{m.storage_effective_limits_ceiling()}</Table.Head>
                      <Table.Head>{m.storage_effective_limits_source()}</Table.Head>
                    </Table.Row>
                  </Table.Header>
                  <Table.Body>
                    {#each deploymentPolicy.limits as limit (limit.use_case)}
                      <Table.Row>
                        <Table.Cell class="font-medium">{useCaseLabel(limit.use_case)}</Table.Cell>
                        <Table.Cell>{policyBytes(limit.configured_bytes)}</Table.Cell>
                        <Table.Cell>{policyBytes(limit.effective_bytes)}</Table.Cell>
                        <Table.Cell>{storageTargetLabel(limit.storage_target)}</Table.Cell>
                        <Table.Cell>
                          {limit.operator_ceiling_bytes === null
                            ? m.storage_effective_limits_no_ceiling()
                            : policyBytes(limit.operator_ceiling_bytes)}
                        </Table.Cell>
                        <Table.Cell>
                          {limit.constraining_source === "operator_ceiling"
                            ? m.storage_constraint_operator_ceiling()
                            : m.storage_constraint_admin_policy()}
                        </Table.Cell>
                      </Table.Row>
                    {/each}
                  </Table.Body>
                </Table.Root>
              </div>

              {#if canEdit}
                <Settings.Row
                  fullWidth
                  title={m.storage_settings_save()}
                  description={dirty
                    ? m.storage_settings_unsaved_changes()
                    : m.storage_settings_no_changes()}
                  hasChanges={dirty}
                  revertFn={discardPolicyDraft}
                >
                  <div class="flex justify-end">
                    <Button
                      type="submit"
                      disabled={saveUnavailable && !saving && !saveSuccess}
                      aria-disabled={saveUnavailable}
                      class={saveUnavailable && (saving || saveSuccess)
                        ? "pointer-events-none opacity-50"
                        : undefined}
                    >
                      {#if saving}
                        <Loader2 data-icon="inline-start" class="animate-spin" />
                        {m.storage_settings_saving()}
                      {:else}
                        {m.storage_settings_save()}
                      {/if}
                    </Button>
                  </div>
                </Settings.Row>
              {/if}
            </PolicySection>
          </form>

          <StorageReadinessSection
            capabilities={deploymentPolicy.capabilities}
            {storageTargetLabel}
            {readinessLabel}
          />

          {#if user.is_platform_admin === true && !authorityRevoked}
            <PolicySection
              id="storage-moves"
              title={m.storage_moves_title()}
              description={m.storage_moves_description()}
              summary={contentMoves
                ? contentMoves.paused
                  ? m.storage_moves_status_paused()
                  : m.storage_moves_status_running()
                : moveStatus === "loading"
                  ? m.loading()
                  : m.storage_inventory_not_available()}
              summaryVariant={moveStatus === "error"
                ? "destructive"
                : contentMoves?.paused
                  ? "outline"
                  : "default"}
            >
              {#snippet icon()}
                <ArrowRightLeft class="size-5" aria-hidden="true" />
              {/snippet}

              <div class="flex flex-wrap items-center justify-end gap-3">
                {#if movesRefreshedAt !== null}
                  <span class="text-muted text-xs">
                    {m.storage_last_refreshed({ time: storageTime(movesRefreshedAt) })}
                  </span>
                {/if}
                <Button
                  type="button"
                  variant="outline"
                  disabled={moveActionPending !== null}
                  aria-disabled={moveStatus === "loading" || moveActionPending !== null}
                  aria-busy={moveStatus === "loading"}
                  class={moveStatus === "loading" ? "pointer-events-none opacity-50" : undefined}
                  onclick={loadMoves}
                >
                  <RefreshCw
                    data-icon="inline-start"
                    class={moveStatus === "loading" ? "animate-spin" : undefined}
                    aria-hidden="true"
                  />
                  {m.storage_moves_refresh()}
                </Button>
              </div>

              {#if objectStoreUnavailable}
                <Alert.Root>
                  <Info />
                  <Alert.Title>{m.storage_moves_store_unavailable()}</Alert.Title>
                  <Alert.Description>
                    {m.storage_moves_store_unavailable_description()}
                  </Alert.Description>
                </Alert.Root>
              {/if}

              {#if moveActionStale}
                <Alert.Root
                  bind:ref={moveAlertRef}
                  data-testid="move-recovery-alert"
                  tabindex={-1}
                  variant="destructive"
                  aria-live="assertive"
                >
                  <AlertCircle />
                  <Alert.Title>{m.storage_moves_stale_title()}</Alert.Title>
                  <Alert.Description>
                    <p>{m.storage_moves_stale_description()}</p>
                    <Button class="mt-3" variant="outline" onclick={() => loadPolicy()}>
                      {m.storage_settings_reload_latest()}
                    </Button>
                  </Alert.Description>
                </Alert.Root>
              {:else if moveActionError}
                <Alert.Root
                  bind:ref={moveAlertRef}
                  data-testid="move-recovery-alert"
                  tabindex={-1}
                  variant="destructive"
                  aria-live="assertive"
                >
                  <AlertCircle />
                  <Alert.Title>{m.storage_moves_action_error_title()}</Alert.Title>
                  <Alert.Description>
                    {m.storage_moves_action_error_description()}
                  </Alert.Description>
                </Alert.Root>
              {:else if moveOutcomeUnknown}
                <Alert.Root aria-live="polite">
                  <Info />
                  <Alert.Title>{m.storage_moves_outcome_unknown_title()}</Alert.Title>
                  <Alert.Description>
                    {m.storage_moves_outcome_unknown_description()}
                  </Alert.Description>
                </Alert.Root>
              {:else if moveQueueResult}
                <Alert.Root aria-live="polite">
                  <CheckCircle2 />
                  <Alert.Title>
                    {m.storage_moves_queue_result({
                      queued: storageCount(moveQueueResult.queued_count),
                      tooLarge: storageCount(moveQueueResult.target_too_large_count)
                    })}
                  </Alert.Title>
                </Alert.Root>
              {/if}

              <Field.Group class="grid gap-4 sm:grid-cols-2">
                <Field.Field
                  data-disabled={moveActionPending !== null || undefined}
                  data-invalid={moveTarget === "object_store" && objectStoreUnavailable
                    ? true
                    : undefined}
                >
                  <Field.Label for="move-target">{m.storage_moves_target()}</Field.Label>
                  <Select.Root
                    type="single"
                    bind:value={moveTarget}
                    disabled={moveActionPending !== null}
                  >
                    <Select.Trigger
                      id="move-target"
                      class="w-full"
                      aria-invalid={moveTarget === "object_store" && objectStoreUnavailable}
                      aria-describedby="move-target-description"
                    >
                      <span data-slot="select-value">{storageTargetLabel(moveTarget)}</span>
                    </Select.Trigger>
                    <Select.Content>
                      <Select.Group>
                        <Select.Item value="object_store" label={m.storage_target_object_store()}>
                          {m.storage_target_object_store()}
                        </Select.Item>
                        <Select.Item
                          value="postgres_inline"
                          label={m.storage_target_postgres_inline()}
                        >
                          {m.storage_target_postgres_inline()}
                        </Select.Item>
                      </Select.Group>
                    </Select.Content>
                  </Select.Root>
                  <Field.Description id="move-target-description">
                    {m.storage_settings_target_help()}
                  </Field.Description>
                </Field.Field>
                <Field.Field
                  data-disabled={moveActionPending !== null || undefined}
                  data-invalid={!validMoveLimit || undefined}
                >
                  <Field.Label for="move-limit">{m.storage_moves_limit()}</Field.Label>
                  <Input
                    id="move-limit"
                    type="number"
                    min="1"
                    max="100"
                    step="1"
                    disabled={moveActionPending !== null}
                    aria-invalid={!validMoveLimit}
                    aria-describedby="move-limit-description"
                    bind:value={moveLimit}
                  />
                  <Field.Description id="move-limit-description">
                    {m.storage_moves_limit_help()}
                  </Field.Description>
                </Field.Field>
              </Field.Group>

              <div class="flex flex-wrap gap-3">
                <Button
                  type="button"
                  disabled={queueUnavailable && moveActionPending !== "queue"}
                  aria-disabled={queueUnavailable}
                  aria-busy={moveActionPending === "queue"}
                  class={queueUnavailable && moveActionPending === "queue"
                    ? "pointer-events-none opacity-50"
                    : undefined}
                  onclick={queueContentMoves}
                >
                  {#if moveActionPending === "queue"}
                    <Loader2 data-icon="inline-start" class="animate-spin" />
                  {/if}
                  {m.storage_moves_queue()}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={(contentMoves === null ||
                    moveStatus !== "idle" ||
                    policyMutationPending) &&
                    moveActionPending !== "pause"}
                  aria-disabled={contentMoves === null ||
                    moveStatus !== "idle" ||
                    policyMutationPending}
                  aria-busy={moveActionPending === "pause"}
                  class={moveActionPending === "pause"
                    ? "pointer-events-none opacity-50"
                    : undefined}
                  onclick={setMovesPaused}
                >
                  {#if moveActionPending === "pause"}
                    <Loader2 data-icon="inline-start" class="animate-spin" />
                  {/if}
                  {contentMoves?.paused ? m.storage_moves_resume() : m.storage_moves_pause()}
                </Button>
              </div>

              {#if moveStatus === "error"}
                <Alert.Root
                  bind:ref={moveStatusAlertRef}
                  data-testid="move-status-recovery-alert"
                  tabindex={-1}
                  variant="destructive"
                  aria-live="assertive"
                >
                  <AlertCircle />
                  <Alert.Title>{m.storage_moves_load_error_title()}</Alert.Title>
                  <Alert.Description>
                    <p>{m.storage_moves_load_error_description()}</p>
                    <Button class="mt-3" variant="outline" onclick={loadMoves}>
                      {m.storage_moves_retry()}
                    </Button>
                  </Alert.Description>
                </Alert.Root>
              {/if}

              {#if contentMoves?.moves.length === 0}
                <p class="border-default text-muted rounded-lg border px-4 py-3 text-sm">
                  {m.storage_moves_empty()}
                </p>
              {:else if contentMoves}
                <div class="border-default overflow-x-auto rounded-lg border">
                  <Table.Root class="min-w-[760px]">
                    <Table.Caption class="sr-only">{m.storage_moves_caption()}</Table.Caption>
                    <Table.Header>
                      <Table.Row>
                        <Table.Head>{m.storage_moves_target()}</Table.Head>
                        <Table.Head>{m.storage_moves_state()}</Table.Head>
                        <Table.Head>{m.storage_moves_failure()}</Table.Head>
                        <Table.Head>{m.storage_moves_count()}</Table.Head>
                        <Table.Head>{m.storage_moves_bytes()}</Table.Head>
                        <Table.Head>{m.storage_moves_oldest_update()}</Table.Head>
                      </Table.Row>
                    </Table.Header>
                    <Table.Body>
                      {#each contentMoves.moves as item (`${item.target}-${item.state}-${item.failure_code}`)}
                        <Table.Row>
                          <Table.Cell class="font-medium">
                            {storageTargetLabel(item.target)}
                          </Table.Cell>
                          <Table.Cell>{moveStateLabel(item.state)}</Table.Cell>
                          <Table.Cell>{moveFailureLabel(item.failure_code)}</Table.Cell>
                          <Table.Cell>{storageCount(item.count)}</Table.Cell>
                          <Table.Cell>{storageBytes(item.bytes)}</Table.Cell>
                          <Table.Cell>{storageDate(item.oldest_updated_at)}</Table.Cell>
                        </Table.Row>
                      {/each}
                    </Table.Body>
                  </Table.Root>
                </div>
              {:else if moveStatus === "loading"}
                <p class="text-secondary flex items-center gap-2 text-sm" aria-live="polite">
                  <Loader2 class="size-4 animate-spin" />
                  {m.storage_moves_loading()}
                </p>
              {/if}
            </PolicySection>

            <StorageInventorySection
              inventory={contentInventory}
              status={inventoryStatus}
              lastRefreshed={inventoryRefreshedAt === null
                ? null
                : storageTime(inventoryRefreshedAt)}
              onRetry={loadInventory}
              onRefresh={loadInventory}
              {storageTargetLabel}
              {contentStateLabel}
              {storageDate}
              {storageCount}
              {storageBytes}
            />
          {/if}
        {/if}
      </div>
    </Settings.Page>
  </Page.Main>
</Page.Root>
