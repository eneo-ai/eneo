<script lang="ts">
  import { onMount, tick } from "svelte";
  import { invalidate } from "$app/navigation";
  import {
    DEPLOYMENT_POLICY_CONFLICT_ERROR_CODE,
    EneoError,
    OBJECT_STORE_NOT_SELECTABLE_ERROR_CODE,
    type ContentOwner,
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
  import {
    AlertCircle,
    ArrowRightLeft,
    CheckCircle2,
    ChevronDown,
    Database,
    ExternalLink,
    Gauge,
    HardDrive,
    Info,
    Loader2,
    RefreshCw
  } from "lucide-svelte";
  import { Page, Settings } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { getAppContext } from "$lib/core/AppContext.js";
  import { getEneo } from "$lib/core/Eneo";
  import PolicySection from "$lib/features/admin/PolicySection.svelte";
  import { hasPermission } from "$lib/core/hasPermission.js";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { toast } from "svelte-sonner";
  import ByteLimitField from "./ByteLimitField.svelte";
  import StorageConnectionSection from "./StorageConnectionSection.svelte";
  import StorageOverviewSection from "./StorageOverviewSection.svelte";

  type InventoryStatus = "idle" | "loading" | "error";
  type MoveAction = "queue" | "pause" | null;

  const eneo = getEneo();
  const { user } = getAppContext();

  let deploymentPolicy = $state<DeploymentPolicy | null>(null);
  let contentInventory = $state<ObjectContentInventory | null>(null);
  let inventoryStatus = $state<InventoryStatus>("idle");
  let contentMoves = $state<ObjectContentMoves | null>(null);
  let moveStatus = $state<InventoryStatus>("idle");
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
  let stale = $state(false);
  let targetUnavailable = $state(false);
  let authorityRevoked = $state(false);
  let targetConfirmationOpen = $state(false);
  let moveConfirmationOpen = $state(false);
  let limitsDetailsOpen = $state(false);

  let storageTarget = $state<StorageKind>("postgres_inline");
  let sessionFileLimitBytes = $state(1);
  let sessionImageLimitBytes = $state(1);
  let knowledgeFileLimitBytes = $state(1);
  let transcriptionAudioLimitBytes = $state(1);
  let policyAlertRef = $state<HTMLElement | null>(null);
  let policyStatusRef = $state<HTMLElement | null>(null);
  let moveAlertRef = $state<HTMLElement | null>(null);
  let moveStatusAlertRef = $state<HTMLElement | null>(null);

  const canAdministerStorage = $derived(hasPermission(user)("storage"));
  const canEdit = $derived(canAdministerStorage && !authorityRevoked);
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
  const targetChanged = $derived(
    deploymentPolicy !== null && storageTarget !== deploymentPolicy.policy.new_write_storage_target
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
  const pauseUnavailable = $derived(moveStatus !== "idle" || policyMutationPending);
  const refreshing = $derived(
    reloading || inventoryStatus === "loading" || moveStatus === "loading"
  );
  const refreshUnavailable = $derived(refreshing || policyMutationPending);

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

  async function discardPolicyDraft(): Promise<void> {
    if (deploymentPolicy === null) return;
    storageTarget = deploymentPolicy.policy.new_write_storage_target;
    sessionFileLimitBytes = deploymentPolicy.policy.session_file_limit_bytes;
    sessionImageLimitBytes = deploymentPolicy.policy.session_image_limit_bytes;
    knowledgeFileLimitBytes = deploymentPolicy.policy.knowledge_file_limit_bytes;
    transcriptionAudioLimitBytes = deploymentPolicy.policy.transcription_audio_limit_bytes;
    stale = false;
    targetUnavailable = false;
    saveOutcomeUnknown = false;
    await tick();
    policyStatusRef?.focus();
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
    if (!canAdministerStorage || authorityRevoked) {
      contentInventory = null;
      inventoryStatus = "idle";
      return;
    }
    if (inventoryStatus === "loading") return;

    inventoryStatus = "loading";
    try {
      contentInventory = await eneo.objectContentPolicy.getInventory();
      inventoryStatus = "idle";
    } catch (error: unknown) {
      if (hasStatus(error, 403)) {
        authorityRevoked = true;
        contentInventory = null;
        inventoryStatus = "idle";
      } else {
        contentInventory = null;
        inventoryStatus = "error";
      }
    }
  }

  async function loadMoves() {
    if (!canAdministerStorage || authorityRevoked) {
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
    stale = false;
    targetUnavailable = false;
    let saved = false;
    try {
      applyPolicy(await eneo.objectContentPolicy.replace(replacement));
      saved = true;
      toast.success(m.storage_settings_save_success());
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
      targetConfirmationOpen = false;
      saving = false;
    }
    if (saved) {
      await tick();
      policyStatusRef?.focus();
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
      moveConfirmationOpen = false;
      moveActionPending = null;
    }
  }

  async function setMovesPaused() {
    if (!canEdit || !contentMoves || pauseUnavailable) return;

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

  function storageTargetLabel(target: StorageKind): string {
    if (target === "postgres_inline") return m.storage_target_postgres_inline();
    return m.storage_target_object_store();
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

  function contentOwnerLabel(owner: ContentOwner): string {
    const labels: Record<ContentOwner, () => string> = {
      file_content: m.storage_inventory_owner_file_content,
      knowledge_file: m.storage_inventory_owner_knowledge_file,
      icon: m.storage_inventory_owner_icon,
      other: m.storage_inventory_owner_other
    };
    return labels[owner]();
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
      storage_admin: m.storage_policy_actor_storage_admin
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

  function storageBytes(value: number, maximumFractionDigits = 0): string {
    const units = [
      { bytes: 1024 ** 3, label: m.storage_unit_gb },
      { bytes: 1024 ** 2, label: m.storage_unit_mb },
      { bytes: 1024, label: m.storage_unit_kb },
      { bytes: 1, label: m.storage_unit_b }
    ];
    const unit = units.find((candidate) => value >= candidate.bytes) ?? units[units.length - 1];
    return `${new Intl.NumberFormat(storageLocale(), { maximumFractionDigits }).format(
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

  function storageDateTime(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return m.storage_inventory_not_available();
    return new Intl.DateTimeFormat(storageLocale(), {
      dateStyle: "long",
      timeStyle: "short"
    }).format(date);
  }

  function submitPolicyDraft(): void {
    if (saveUnavailable) return;
    if (targetChanged) {
      targetConfirmationOpen = true;
      return;
    }
    void savePolicy();
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
          <div class="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div class="flex max-w-3xl flex-col gap-2">
              <p class="text-secondary text-sm leading-6">
                {m.storage_settings_description()}
              </p>
              <p class="text-muted text-sm leading-5">
                {m.storage_settings_last_changed({
                  date: storageDateTime(deploymentPolicy.policy.updated_at),
                  actor: policyActorLabel(deploymentPolicy.policy.updated_by_actor)
                })}
              </p>
            </div>
            <Button
              variant="outline"
              aria-busy={refreshing}
              aria-disabled={refreshUnavailable}
              class={refreshUnavailable ? "pointer-events-none opacity-50" : undefined}
              onclick={() => {
                if (!refreshUnavailable) void loadPolicy(dirty);
              }}
            >
              <RefreshCw
                data-icon="inline-start"
                class={refreshing ? "animate-spin" : undefined}
                aria-hidden="true"
              />
              {m.storage_settings_refresh_status()}
            </Button>
          </div>

          {#if !canEdit}
            <Alert.Root>
              <Info />
              <Alert.Title>{m.storage_settings_read_only_title()}</Alert.Title>
              <Alert.Description>{m.storage_settings_read_only_description()}</Alert.Description>
            </Alert.Root>
          {/if}

          {#if canEdit}
            <StorageOverviewSection
              inventory={contentInventory}
              {inventoryStatus}
              {contentMoves}
              {moveStatus}
              activeTarget={deploymentPolicy.policy.new_write_storage_target}
              {objectStoreCapability}
              onInventoryRetry={loadInventory}
              {storageTargetLabel}
              {contentOwnerLabel}
              {contentStateLabel}
              {storageDate}
              {storageCount}
              {storageBytes}
              {readinessLabel}
            />
          {/if}

          <div class="flex flex-col gap-6">
            <PolicySection
              id="storage-target"
              title={m.storage_settings_target_title()}
              description={m.storage_settings_target_description()}
              summary={storageTargetLabel(deploymentPolicy.policy.new_write_storage_target)}
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

              <div class="text-secondary flex items-start gap-3 text-sm">
                <Info class="text-primary mt-0.5 size-4 shrink-0" aria-hidden="true" />
                <div class="max-w-[72ch] space-y-1 leading-5">
                  <p class="text-primary font-medium">
                    {m.storage_settings_new_writes_only_title()}
                  </p>
                  <p>{m.storage_settings_no_move_notice()}</p>
                  <p>{m.storage_settings_no_fallback_notice()}</p>
                </div>
              </div>

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

              {#if canEdit}
                <Field.Set>
                  <Field.Legend class="sr-only">{m.storage_settings_target_title()}</Field.Legend>
                  <RadioGroup.Root
                    bind:value={() => storageTarget, updateStorageTarget}
                    class="grid gap-3 lg:grid-cols-2"
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
                        <span class="flex flex-wrap items-center gap-2 font-medium">
                          {m.storage_target_postgres_inline()}
                          {#if deploymentPolicy.policy.new_write_storage_target === "postgres_inline"}
                            <Badge variant="outline">{m.storage_overview_active()}</Badge>
                          {/if}
                        </span>
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
                          {#if deploymentPolicy.policy.new_write_storage_target === "object_store"}
                            <Badge variant="outline">{m.storage_overview_active()}</Badge>
                          {:else if !objectStoreUnavailable}
                            <Badge
                              variant="outline"
                              class="border-positive-default/40 bg-positive-dimmer text-positive-stronger"
                            >
                              {m.storage_target_ready()}
                            </Badge>
                          {:else}
                            <Badge variant="secondary">{m.storage_target_unavailable()}</Badge>
                          {/if}
                        </span>
                        <span class="text-secondary text-sm">
                          {m.storage_target_object_store_description()}
                        </span>
                        {#if objectStoreCapability?.readiness_code !== "ready"}
                          <span class="text-muted text-xs">
                            {objectStoreCapability
                              ? readinessLabel(objectStoreCapability.readiness_code)
                              : m.storage_inventory_not_available()}
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
          </div>

          <StorageConnectionSection
            capability={objectStoreCapability}
            {canEdit}
            {readinessLabel}
            onConnectionChanged={async () => {
              await loadPolicy(dirty);
              // Connecting or removing a store flips a capability the rest of
              // the app reads from the root layout's settings (e.g. whether an
              // assistant may switch off inlined file text). Without this it
              // stays stale for the whole client-side session.
              await invalidate("global:state");
            }}
            onAuthorityRevoked={() => (authorityRevoked = true)}
          />

          <form
            class="flex flex-col gap-6"
            onsubmit={(event) => {
              event.preventDefault();
              submitPolicyDraft();
            }}
          >
            <PolicySection
              id="storage-limits"
              title={m.storage_settings_limits_title()}
              description={m.storage_settings_limits_description()}
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

              <Collapsible.Root bind:open={limitsDetailsOpen}>
                <Collapsible.Trigger
                  class="hover:bg-hover-dimmer focus-visible:ring-ring flex w-full items-center gap-2 rounded-md px-3 py-2 text-left focus-visible:ring-2 focus-visible:outline-none [&[data-state=open]>svg]:rotate-180"
                  aria-controls="storage-effective-limits"
                >
                  <span class="min-w-0 flex-1 text-sm font-medium">
                    {limitsDetailsOpen
                      ? m.storage_settings_limits_hide_technical()
                      : m.storage_settings_limits_show_technical()}
                  </span>
                  <ChevronDown
                    aria-hidden="true"
                    class="size-4 shrink-0 transition-transform motion-reduce:transition-none"
                  />
                </Collapsible.Trigger>
                <Collapsible.Content id="storage-effective-limits" class="pt-3">
                  <div class="border-default border-y [&_td]:px-3 [&_th]:px-3">
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
                            <Table.Cell class="font-medium">
                              {useCaseLabel(limit.use_case)}
                            </Table.Cell>
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
                </Collapsible.Content>
              </Collapsible.Root>

              {#if canEdit}
                <p
                  bind:this={policyStatusRef}
                  data-testid="policy-save-status"
                  tabindex="-1"
                  role="status"
                  class="text-muted text-sm"
                  class:sr-only={dirty}
                >
                  {dirty ? m.storage_settings_unsaved_changes() : m.storage_settings_no_changes()}
                </p>
              {/if}
            </PolicySection>

            {#if canEdit && dirty}
              <Card.Root class="sticky bottom-4 z-20 shadow-lg">
                <Card.Content
                  class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <p class="text-sm font-medium">{m.storage_settings_unsaved_changes()}</p>
                  <div class="flex flex-wrap justify-end gap-2">
                    <Button type="button" variant="outline" onclick={discardPolicyDraft}>
                      {m.discard_changes()}
                    </Button>
                    <Button type="submit" disabled={saveUnavailable} aria-busy={saving}>
                      {#if saving}
                        <Loader2 data-icon="inline-start" class="animate-spin" />
                        {m.storage_settings_saving()}
                      {:else}
                        {m.storage_settings_save()}
                      {/if}
                    </Button>
                  </div>
                </Card.Content>
              </Card.Root>
            {/if}
          </form>

          {#if canEdit}
            <PolicySection
              id="storage-moves"
              title={m.storage_moves_title()}
              description={m.storage_moves_description()}
            >
              {#snippet icon()}
                <ArrowRightLeft class="size-5" aria-hidden="true" />
              {/snippet}

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

              <Field.Group>
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
              </Field.Group>

              <Collapsible.Root>
                <Collapsible.Trigger
                  class="hover:bg-hover-dimmer focus-visible:ring-ring flex w-full items-center gap-2 rounded-md px-3 py-2 text-left focus-visible:ring-2 focus-visible:outline-none [&[data-state=open]>svg]:rotate-180"
                  aria-controls="storage-move-advanced"
                >
                  <span class="min-w-0 flex-1 text-sm font-medium">
                    {m.storage_moves_advanced()}
                  </span>
                  <ChevronDown
                    aria-hidden="true"
                    class="size-4 shrink-0 transition-transform motion-reduce:transition-none"
                  />
                </Collapsible.Trigger>
                <Collapsible.Content id="storage-move-advanced" class="pt-3">
                  <Field.Field
                    data-disabled={moveActionPending !== null || undefined}
                    data-invalid={!validMoveLimit || undefined}
                    class="max-w-md"
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
                </Collapsible.Content>
              </Collapsible.Root>

              <div class="flex flex-wrap gap-3">
                <Button
                  type="button"
                  disabled={queueUnavailable && moveActionPending !== "queue"}
                  aria-disabled={queueUnavailable}
                  aria-busy={moveActionPending === "queue"}
                  class={queueUnavailable && moveActionPending === "queue"
                    ? "pointer-events-none opacity-50"
                    : undefined}
                  onclick={() => (moveConfirmationOpen = true)}
                >
                  {#if moveActionPending === "queue"}
                    <Loader2 data-icon="inline-start" class="animate-spin" />
                  {/if}
                  {m.storage_moves_queue()}
                </Button>
                {#if contentMoves !== null}
                  <Button
                    type="button"
                    variant="outline"
                    disabled={pauseUnavailable && moveActionPending !== "pause"}
                    aria-disabled={pauseUnavailable}
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
                {/if}
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
                <Alert.Root>
                  <CheckCircle2 />
                  <Alert.Title>{m.storage_overview_move_idle()}</Alert.Title>
                  <Alert.Description>{m.storage_moves_empty()}</Alert.Description>
                </Alert.Root>
              {:else if contentMoves}
                <div class="border-default border-y [&_td]:px-3 [&_th]:px-3">
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
          {/if}
        {/if}
      </div>
    </Settings.Page>
  </Page.Main>
</Page.Root>

<AlertDialog.Root bind:open={targetConfirmationOpen}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.storage_settings_confirm_target_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.storage_settings_confirm_target_description()}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={saving}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action disabled={saving} onclick={() => void savePolicy()}>
        {#if saving}
          <Loader2 data-icon="inline-start" class="animate-spin" />
          {m.storage_settings_saving()}
        {:else if storageTarget === "object_store"}
          {m.storage_settings_confirm_object_store()}
        {:else}
          {m.storage_settings_confirm_postgres()}
        {/if}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root bind:open={moveConfirmationOpen}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.storage_moves_confirm_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.storage_moves_confirm_description({
          count: storageCount(moveLimit),
          target: storageTargetLabel(moveTarget)
        })}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={moveActionPending === "queue"}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action
        disabled={moveActionPending === "queue"}
        onclick={() => void queueContentMoves()}
      >
        {#if moveActionPending === "queue"}
          <Loader2 data-icon="inline-start" class="animate-spin" />
        {/if}
        {m.storage_moves_confirm_action()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
