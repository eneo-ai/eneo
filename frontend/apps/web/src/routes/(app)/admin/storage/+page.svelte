<script lang="ts">
  import { onMount } from "svelte";
  import {
    EneoError,
    type DeploymentPolicy,
    type DeploymentPolicyUpdate,
    type MoveQueueResult,
    type ObjectContentInventory,
    type ObjectContentMoves
  } from "@eneo/eneo-js";
  import { AlertCircle, CheckCircle2, Database, HardDrive, Info, Loader2 } from "lucide-svelte";
  import { Page, Settings } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { getAppContext } from "$lib/core/AppContext.js";
  import { getEneo } from "$lib/core/Eneo";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";

  type StorageTarget = DeploymentPolicy["policy"]["new_write_storage_target"];
  type ReadinessCode = DeploymentPolicy["capabilities"][number]["readiness_code"];
  type UploadUseCase = DeploymentPolicy["limits"][number]["use_case"];
  type ContentState = ObjectContentInventory["inventory"][number]["state"];
  type MoveState = ObjectContentMoves["moves"][number]["state"];
  type MoveFailureCode = NonNullable<ObjectContentMoves["moves"][number]["failure_code"]>;
  type InventoryStatus = "idle" | "loading" | "error";
  type MoveAction = "queue" | "pause" | null;

  const DEPLOYMENT_POLICY_CONFLICT_ERROR_CODE = 9046;
  const OBJECT_STORE_NOT_SELECTABLE_ERROR_CODE = 9047;

  const eneo = getEneo();
  const { user } = getAppContext();

  let deploymentPolicy = $state<DeploymentPolicy | null>(null);
  let contentInventory = $state<ObjectContentInventory | null>(null);
  let inventoryStatus = $state<InventoryStatus>("idle");
  let contentMoves = $state<ObjectContentMoves | null>(null);
  let moveStatus = $state<InventoryStatus>("idle");
  let moveTarget = $state<StorageTarget>("object_store");
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

  let storageTarget = $state<StorageTarget>("postgres_inline");
  let sessionFileLimitBytes = $state(1);
  let sessionImageLimitBytes = $state(1);
  let knowledgeFileLimitBytes = $state(1);
  let transcriptionAudioLimitBytes = $state(1);

  const canEdit = $derived(user.is_platform_admin === true && !authorityRevoked);
  const objectStoreCapability = $derived(
    deploymentPolicy?.capabilities.find((capability) => capability.target === "object_store")
  );
  const objectStoreUnavailable = $derived(objectStoreCapability?.selectable !== true);
  const validMoveLimit = $derived(
    Number.isSafeInteger(moveLimit) && moveLimit >= 1 && moveLimit <= 100
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
    ].every((value) => Number.isSafeInteger(value) && value > 0)
  );
  const dirty = $derived(
    deploymentPolicy !== null &&
      (storageTarget !== deploymentPolicy.policy.new_write_storage_target ||
        sessionFileLimitBytes !== deploymentPolicy.policy.session_file_limit_bytes ||
        sessionImageLimitBytes !== deploymentPolicy.policy.session_image_limit_bytes ||
        knowledgeFileLimitBytes !== deploymentPolicy.policy.knowledge_file_limit_bytes ||
        transcriptionAudioLimitBytes !== deploymentPolicy.policy.transcription_audio_limit_bytes)
  );

  function applyPolicy(next: DeploymentPolicy) {
    deploymentPolicy = next;
    if (contentMoves !== null) {
      contentMoves = {
        ...contentMoves,
        policy_revision: next.policy.revision,
        paused: next.policy.moves_paused
      };
    }
    storageTarget = next.policy.new_write_storage_target;
    sessionFileLimitBytes = next.policy.session_file_limit_bytes;
    sessionImageLimitBytes = next.policy.session_image_limit_bytes;
    knowledgeFileLimitBytes = next.policy.knowledge_file_limit_bytes;
    transcriptionAudioLimitBytes = next.policy.transcription_audio_limit_bytes;
  }

  async function loadPolicy() {
    const initialLoad = deploymentPolicy === null;
    if (initialLoad) loading = true;
    else reloading = true;
    loadError = false;

    try {
      const nextPolicy = await eneo.objectContentPolicy.get();
      applyPolicy(nextPolicy);
      stale = false;
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

    contentInventory = null;
    inventoryStatus = "loading";
    try {
      contentInventory = await eneo.objectContentPolicy.getInventory();
      inventoryStatus = "idle";
    } catch (error: unknown) {
      contentInventory = null;
      if (hasStatus(error, 403)) {
        authorityRevoked = true;
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

    contentMoves = null;
    moveStatus = "loading";
    try {
      contentMoves = await eneo.objectContentPolicy.getMoves();
      moveStatus = "idle";
    } catch (error: unknown) {
      contentMoves = null;
      if (hasStatus(error, 403)) {
        authorityRevoked = true;
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
    if (
      !canEdit ||
      !deploymentPolicy ||
      !dirty ||
      !validDraft ||
      saving ||
      stale ||
      saveOutcomeUnknown
    )
      return;

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
    if (
      !canEdit ||
      objectStoreUnavailable ||
      !validMoveLimit ||
      moveStatus !== "idle" ||
      moveActionPending !== null
    )
      return;

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
    if (!canEdit || !contentMoves || moveStatus !== "idle" || moveActionPending !== null) return;

    moveActionPending = "pause";
    moveActionError = false;
    moveOutcomeUnknown = false;
    moveActionStale = false;
    moveQueueResult = null;
    try {
      const result = await eneo.objectContentPolicy.setMovesPaused({
        expected_revision: contentMoves.policy_revision,
        moves_paused: !contentMoves.paused
      });
      contentMoves = {
        ...contentMoves,
        policy_revision: result.policy_revision,
        paused: result.paused
      };
      if (deploymentPolicy !== null) {
        deploymentPolicy = {
          ...deploymentPolicy,
          policy: {
            ...deploymentPolicy.policy,
            revision: result.policy_revision,
            moves_paused: result.paused
          }
        };
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
        await loadMoves();
      }
    } finally {
      moveActionPending = null;
    }
  }

  function storageTargetLabel(target: StorageTarget | null): string {
    if (target === "postgres_inline") return m.storage_target_postgres_inline();
    if (target === "object_store") return m.storage_target_object_store();
    return m.storage_target_not_applicable();
  }

  function readinessLabel(code: ReadinessCode): string {
    const labels: Record<ReadinessCode, () => string> = {
      ready: m.storage_readiness_ready,
      object_store_not_configured: m.storage_readiness_object_store_not_configured,
      not_initialized: m.storage_readiness_not_initialized,
      configuration_required: m.storage_readiness_configuration_required,
      database_unavailable: m.storage_readiness_database_unavailable,
      store_degraded: m.storage_readiness_store_degraded
    };
    return labels[code]();
  }

  function useCaseLabel(useCase: UploadUseCase): string {
    const labels: Record<UploadUseCase, () => string> = {
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

  function moveStateLabel(state: MoveState): string {
    const labels: Record<MoveState, () => string> = {
      pending: m.storage_move_state_pending,
      target_verified: m.storage_move_state_target_verified,
      failed: m.storage_move_state_failed
    };
    return labels[state]();
  }

  function moveFailureLabel(code: MoveFailureCode | null): string {
    if (code === null) return m.storage_moves_failure_none();
    const labels: Record<MoveFailureCode, () => string> = {
      store_unavailable: m.storage_move_failure_store_unavailable,
      target_too_large: m.storage_move_failure_target_too_large,
      source_missing: m.storage_move_failure_source_missing,
      source_corrupt: m.storage_move_failure_source_corrupt,
      target_corrupt: m.storage_move_failure_target_corrupt,
      content_ineligible: m.storage_move_failure_content_ineligible
    };
    return labels[code]();
  }

  function storageDate(value: string | null): string {
    if (value === null) return m.storage_inventory_not_available();
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return m.storage_inventory_not_available();
    return new Intl.DateTimeFormat(getLocale() === "sv" ? "sv-SE" : "en-US", {
      dateStyle: "medium"
    }).format(date);
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
      <div class="space-y-8 pb-16">
        {#if loading}
          <div data-testid="storage-loading" class="space-y-5" aria-busy="true">
            <div class="space-y-2">
              <div class="bg-muted h-5 w-56 animate-pulse rounded-md"></div>
              <div class="bg-muted h-4 w-full max-w-xl animate-pulse rounded-md"></div>
            </div>
            <div class="bg-muted h-40 w-full animate-pulse rounded-lg"></div>
            <span class="sr-only">{m.storage_settings_loading()}</span>
          </div>
        {:else if loadError && !deploymentPolicy}
          <Alert.Root variant="destructive" aria-live="assertive">
            <AlertCircle />
            <Alert.Title>{m.storage_settings_load_error_title()}</Alert.Title>
            <Alert.Description>
              <p>{m.storage_settings_load_error_description()}</p>
              <Button class="mt-3" variant="outline" onclick={loadPolicy}>
                {m.retry()}
              </Button>
            </Alert.Description>
          </Alert.Root>
        {:else if deploymentPolicy}
          <div class="max-w-3xl space-y-2">
            <p class="text-secondary text-sm leading-6">
              {m.storage_settings_description()}
            </p>
            <p class="text-muted text-xs">
              {m.storage_settings_revision({ revision: deploymentPolicy.policy.revision })}
            </p>
          </div>

          {#if !canEdit}
            <Alert.Root>
              <Info />
              <Alert.Title>{m.storage_settings_read_only_title()}</Alert.Title>
              <Alert.Description>{m.storage_settings_read_only_description()}</Alert.Description>
            </Alert.Root>
          {/if}

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
            <Alert.Root variant="destructive" aria-live="assertive">
              <AlertCircle />
              <Alert.Title>{m.storage_settings_stale_title()}</Alert.Title>
              <Alert.Description>
                <p>{m.storage_settings_stale_description()}</p>
                <Button class="mt-3" variant="outline" disabled={reloading} onclick={loadPolicy}>
                  {#if reloading}
                    <Loader2 class="animate-spin" />
                    {m.storage_settings_reloading()}
                  {:else}
                    {m.storage_settings_reload_latest()}
                  {/if}
                </Button>
              </Alert.Description>
            </Alert.Root>
          {:else if loadError}
            <Alert.Root variant="destructive" aria-live="assertive">
              <AlertCircle />
              <Alert.Title>{m.storage_settings_reload_error_title()}</Alert.Title>
              <Alert.Description>{m.storage_settings_reload_error_description()}</Alert.Description>
            </Alert.Root>
          {/if}

          {#if targetUnavailable}
            <Alert.Root variant="destructive" aria-live="assertive">
              <AlertCircle />
              <Alert.Title>{m.storage_settings_target_unavailable_title()}</Alert.Title>
              <Alert.Description>
                {m.storage_settings_target_unavailable_description()}
              </Alert.Description>
            </Alert.Root>
          {/if}

          {#if saveOutcomeUnknown}
            <Alert.Root variant="destructive" aria-live="assertive">
              <AlertCircle />
              <Alert.Title>{m.storage_settings_save_outcome_unknown_title()}</Alert.Title>
              <Alert.Description>
                <p>{m.storage_settings_save_outcome_unknown_description()}</p>
                <Button class="mt-3" variant="outline" disabled={reloading} onclick={loadPolicy}>
                  {#if reloading}
                    <Loader2 class="animate-spin" />
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

          <form
            class="space-y-10"
            onsubmit={(event) => {
              event.preventDefault();
              void savePolicy();
            }}
          >
            <section class="border-default space-y-5 border-b pb-10">
              <div class="max-w-3xl space-y-1">
                <h2 class="text-lg font-semibold">{m.storage_settings_target_title()}</h2>
                <p class="text-secondary text-sm leading-6">
                  {m.storage_settings_target_description()}
                </p>
              </div>

              <fieldset class="grid gap-3 sm:grid-cols-2" aria-describedby="storage-target-help">
                <legend class="sr-only">{m.storage_settings_target_title()}</legend>
                <label
                  class="border-default has-[:checked]:border-accent-default has-[:checked]:bg-accent-dimmer flex items-start gap-3 rounded-lg border p-4"
                >
                  <input
                    type="radio"
                    name="storage-target"
                    value="postgres_inline"
                    checked={storageTarget === "postgres_inline"}
                    disabled={!canEdit || saving}
                    onchange={() => (storageTarget = "postgres_inline")}
                  />
                  <Database class="mt-0.5 size-5 shrink-0" aria-hidden="true" />
                  <span class="space-y-1">
                    <span class="block font-medium">{m.storage_target_postgres_inline()}</span>
                    <span class="text-secondary block text-sm">
                      {m.storage_target_postgres_inline_description()}
                    </span>
                  </span>
                </label>

                <label
                  class="border-default has-[:checked]:border-accent-default has-[:checked]:bg-accent-dimmer flex items-start gap-3 rounded-lg border p-4"
                  class:opacity-60={objectStoreUnavailable}
                >
                  <input
                    type="radio"
                    name="storage-target"
                    value="object_store"
                    checked={storageTarget === "object_store"}
                    disabled={!canEdit || saving || objectStoreUnavailable}
                    onchange={() => (storageTarget = "object_store")}
                  />
                  <HardDrive class="mt-0.5 size-5 shrink-0" aria-hidden="true" />
                  <span class="space-y-1">
                    <span class="flex flex-wrap items-center gap-2 font-medium">
                      {m.storage_target_object_store()}
                      {#if objectStoreUnavailable}
                        <Badge variant="secondary">{m.storage_target_unavailable()}</Badge>
                      {/if}
                    </span>
                    <span class="text-secondary block text-sm">
                      {m.storage_target_object_store_description()}
                    </span>
                    {#if objectStoreCapability}
                      <span class="text-muted block text-xs">
                        {readinessLabel(objectStoreCapability.readiness_code)}
                      </span>
                    {/if}
                  </span>
                </label>
              </fieldset>
              <p id="storage-target-help" class="text-muted text-xs">
                {m.storage_settings_target_help()}
              </p>
            </section>

            <section class="border-default space-y-5 border-b pb-10">
              <div class="max-w-3xl space-y-1">
                <h2 class="text-lg font-semibold">{m.storage_settings_limits_title()}</h2>
                <p class="text-secondary text-sm leading-6">
                  {m.storage_settings_limits_description()}
                </p>
              </div>

              <div class="grid gap-5 sm:grid-cols-2">
                <div class="space-y-2">
                  <label for="session-file-limit" class="text-sm font-medium">
                    {m.storage_limit_session_file()}
                  </label>
                  <Input
                    id="session-file-limit"
                    type="number"
                    min="1"
                    step="1"
                    required
                    disabled={!canEdit || saving}
                    bind:value={sessionFileLimitBytes}
                  />
                  <p class="text-muted text-xs">{m.storage_limit_bytes_help()}</p>
                </div>

                <div class="space-y-2">
                  <label for="session-image-limit" class="text-sm font-medium">
                    {m.storage_limit_session_image()}
                  </label>
                  <Input
                    id="session-image-limit"
                    type="number"
                    min="1"
                    step="1"
                    required
                    disabled={!canEdit || saving}
                    bind:value={sessionImageLimitBytes}
                  />
                  <p class="text-muted text-xs">{m.storage_limit_bytes_help()}</p>
                </div>

                <div class="space-y-2">
                  <label for="knowledge-file-limit" class="text-sm font-medium">
                    {m.storage_limit_knowledge_file()}
                  </label>
                  <Input
                    id="knowledge-file-limit"
                    type="number"
                    min="1"
                    step="1"
                    required
                    disabled={!canEdit || saving}
                    bind:value={knowledgeFileLimitBytes}
                  />
                  <p class="text-muted text-xs">{m.storage_limit_bytes_help()}</p>
                </div>

                <div class="space-y-2">
                  <label for="transcription-audio-limit" class="text-sm font-medium">
                    {m.storage_limit_transcription_audio()}
                  </label>
                  <Input
                    id="transcription-audio-limit"
                    type="number"
                    min="1"
                    step="1"
                    required
                    disabled={!canEdit || saving}
                    bind:value={transcriptionAudioLimitBytes}
                  />
                  <p class="text-muted text-xs">{m.storage_limit_audio_help()}</p>
                </div>
              </div>

              <div class="border-default overflow-hidden rounded-lg border">
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
                        <Table.Cell>{formatBytes(limit.configured_bytes)}</Table.Cell>
                        <Table.Cell>{formatBytes(limit.effective_bytes)}</Table.Cell>
                        <Table.Cell>{storageTargetLabel(limit.storage_target)}</Table.Cell>
                        <Table.Cell>
                          {limit.operator_ceiling_bytes === null
                            ? m.storage_effective_limits_no_ceiling()
                            : formatBytes(limit.operator_ceiling_bytes)}
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
            </section>

            {#if canEdit}
              <div class="flex flex-wrap items-center justify-end gap-3">
                <p class="text-muted mr-auto text-sm" aria-live="polite">
                  {dirty ? m.storage_settings_unsaved_changes() : m.storage_settings_no_changes()}
                </p>
                <Button
                  type="submit"
                  disabled={!dirty || !validDraft || saving || stale || saveOutcomeUnknown}
                >
                  {#if saving}
                    <Loader2 class="animate-spin" />
                    {m.storage_settings_saving()}
                  {:else}
                    {m.storage_settings_save()}
                  {/if}
                </Button>
              </div>
            {/if}
          </form>

          <section class="border-default space-y-4 border-t pt-8">
            <div class="max-w-3xl space-y-1">
              <h2 class="text-lg font-semibold">{m.storage_capabilities_title()}</h2>
              <p class="text-secondary text-sm leading-6">
                {m.storage_capabilities_description()}
              </p>
            </div>
            <div class="border-default overflow-hidden rounded-lg border">
              <Table.Root class="min-w-[560px]">
                <Table.Caption class="sr-only">
                  {m.storage_capabilities_caption()}
                </Table.Caption>
                <Table.Header>
                  <Table.Row>
                    <Table.Head>{m.storage_capabilities_target()}</Table.Head>
                    <Table.Head>{m.storage_capabilities_configured()}</Table.Head>
                    <Table.Head>{m.storage_capabilities_selectable()}</Table.Head>
                    <Table.Head>{m.storage_capabilities_status()}</Table.Head>
                  </Table.Row>
                </Table.Header>
                <Table.Body>
                  {#each deploymentPolicy.capabilities as capability (capability.target)}
                    <Table.Row>
                      <Table.Cell class="font-medium">
                        {storageTargetLabel(capability.target)}
                      </Table.Cell>
                      <Table.Cell>
                        {capability.configured ? m.yes() : m.no()}
                      </Table.Cell>
                      <Table.Cell>
                        {capability.selectable ? m.yes() : m.no()}
                      </Table.Cell>
                      <Table.Cell>{readinessLabel(capability.readiness_code)}</Table.Cell>
                    </Table.Row>
                  {/each}
                </Table.Body>
              </Table.Root>
            </div>
          </section>

          {#if user.is_platform_admin === true && !authorityRevoked}
            <Separator />
            <section class="space-y-5">
              <div class="max-w-3xl space-y-1">
                <div class="flex flex-wrap items-center gap-2">
                  <h2 class="text-lg font-semibold">{m.storage_moves_title()}</h2>
                  {#if contentMoves}
                    <Badge variant="secondary">
                      {contentMoves.paused
                        ? m.storage_moves_status_paused()
                        : m.storage_moves_status_running()}
                    </Badge>
                  {/if}
                </div>
                <p class="text-secondary text-sm leading-6">
                  {m.storage_moves_description()}
                </p>
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
                <Alert.Root variant="destructive" aria-live="assertive">
                  <AlertCircle />
                  <Alert.Title>{m.storage_moves_stale_title()}</Alert.Title>
                  <Alert.Description>
                    <p>{m.storage_moves_stale_description()}</p>
                    <Button class="mt-3" variant="outline" onclick={loadPolicy}>
                      {m.storage_settings_reload_latest()}
                    </Button>
                  </Alert.Description>
                </Alert.Root>
              {:else if moveActionError}
                <Alert.Root variant="destructive" aria-live="assertive">
                  <AlertCircle />
                  <Alert.Title>{m.storage_moves_action_error_title()}</Alert.Title>
                  <Alert.Description>{m.storage_moves_action_error_description()}</Alert.Description
                  >
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
                      queued: moveQueueResult.queued_count,
                      tooLarge: moveQueueResult.target_too_large_count
                    })}
                  </Alert.Title>
                </Alert.Root>
              {/if}

              <Field.Group class="grid gap-4 sm:grid-cols-2">
                <Field.Field data-disabled={moveActionPending !== null || undefined}>
                  <Field.Label for="move-target">{m.storage_moves_target()}</Field.Label>
                  <Select.Root
                    type="single"
                    bind:value={moveTarget}
                    disabled={moveActionPending !== null}
                  >
                    <Select.Trigger id="move-target" class="w-full">
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
                  disabled={objectStoreUnavailable ||
                    !validMoveLimit ||
                    moveStatus !== "idle" ||
                    moveActionPending !== null}
                  aria-busy={moveActionPending === "queue"}
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
                  disabled={contentMoves === null ||
                    moveStatus !== "idle" ||
                    moveActionPending !== null}
                  aria-busy={moveActionPending === "pause"}
                  onclick={setMovesPaused}
                >
                  {#if moveActionPending === "pause"}
                    <Loader2 data-icon="inline-start" class="animate-spin" />
                  {/if}
                  {contentMoves?.paused ? m.storage_moves_resume() : m.storage_moves_pause()}
                </Button>
              </div>

              {#if moveStatus === "loading"}
                <p class="text-secondary flex items-center gap-2 text-sm" aria-live="polite">
                  <Loader2 class="size-4 animate-spin" />
                  {m.storage_moves_loading()}
                </p>
              {:else if moveStatus === "error"}
                <Alert.Root variant="destructive" aria-live="assertive">
                  <AlertCircle />
                  <Alert.Title>{m.storage_moves_load_error_title()}</Alert.Title>
                  <Alert.Description>
                    <p>{m.storage_moves_load_error_description()}</p>
                    <Button class="mt-3" variant="outline" onclick={loadMoves}>
                      {m.storage_moves_retry()}
                    </Button>
                  </Alert.Description>
                </Alert.Root>
              {:else if contentMoves?.moves.length === 0}
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
                          <Table.Cell>{item.count}</Table.Cell>
                          <Table.Cell>{formatBytes(item.bytes)}</Table.Cell>
                          <Table.Cell>{storageDate(item.oldest_updated_at)}</Table.Cell>
                        </Table.Row>
                      {/each}
                    </Table.Body>
                  </Table.Root>
                </div>
              {/if}
            </section>
          {/if}

          {#if user.is_platform_admin === true && !authorityRevoked}
            <section class="space-y-4 pb-8">
              <div class="max-w-3xl space-y-1">
                <h2 class="text-lg font-semibold">{m.storage_inventory_title()}</h2>
                <p class="text-secondary text-sm leading-6">
                  {m.storage_inventory_description()}
                </p>
              </div>
              {#if inventoryStatus === "loading"}
                <p class="text-secondary flex items-center gap-2 text-sm" aria-live="polite">
                  <Loader2 class="size-4 animate-spin" />
                  {m.storage_inventory_loading()}
                </p>
              {:else if inventoryStatus === "error"}
                <Alert.Root variant="destructive" aria-live="assertive">
                  <AlertCircle />
                  <Alert.Title>{m.storage_inventory_error_title()}</Alert.Title>
                  <Alert.Description>
                    <p>{m.storage_inventory_error_description()}</p>
                    <Button class="mt-3" variant="outline" onclick={loadInventory}>
                      {m.retry()}
                    </Button>
                  </Alert.Description>
                </Alert.Root>
              {:else if contentInventory?.inventory.length === 0}
                <p class="border-default text-muted rounded-lg border px-4 py-3 text-sm">
                  {m.storage_inventory_empty()}
                </p>
              {:else if contentInventory}
                <div class="border-default overflow-hidden rounded-lg border">
                  <Table.Root class="min-w-[640px]">
                    <Table.Caption class="sr-only">
                      {m.storage_inventory_caption()}
                    </Table.Caption>
                    <Table.Header>
                      <Table.Row>
                        <Table.Head>{m.storage_inventory_target()}</Table.Head>
                        <Table.Head>{m.storage_inventory_state()}</Table.Head>
                        <Table.Head>{m.storage_inventory_count()}</Table.Head>
                        <Table.Head>{m.storage_inventory_bytes()}</Table.Head>
                        <Table.Head>{m.storage_inventory_oldest()}</Table.Head>
                      </Table.Row>
                    </Table.Header>
                    <Table.Body>
                      {#each contentInventory.inventory as item (`${item.target}-${item.state}`)}
                        <Table.Row>
                          <Table.Cell class="font-medium"
                            >{storageTargetLabel(item.target)}</Table.Cell
                          >
                          <Table.Cell>{contentStateLabel(item.state)}</Table.Cell>
                          <Table.Cell>{item.count}</Table.Cell>
                          <Table.Cell>{formatBytes(item.bytes)}</Table.Cell>
                          <Table.Cell>{storageDate(item.oldest_created_at)}</Table.Cell>
                        </Table.Row>
                      {/each}
                    </Table.Body>
                  </Table.Root>
                </div>
              {/if}
            </section>
          {/if}
        {/if}
      </div>
    </Settings.Page>
  </Page.Main>
</Page.Root>
