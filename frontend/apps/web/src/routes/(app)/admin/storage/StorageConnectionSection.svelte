<script lang="ts">
  import { onMount } from "svelte";
  import {
    EneoError,
    type ObjectStoreConnection,
    type ObjectStoreConnectionCreate,
    type ObjectStoreCredentialRotation,
    type ObjectContentReadinessCode
  } from "@eneo/eneo-js";
  import {
    AlertCircle,
    ArrowLeftRight,
    CheckCircle2,
    ChevronDown,
    HardDrive,
    KeyRound,
    Loader2,
    Settings2
  } from "lucide-svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import PolicySection from "$lib/features/admin/PolicySection.svelte";
  import { m } from "$lib/paraglide/messages";

  type Capability = {
    configured: boolean;
    selectable: boolean;
    readiness_code: ObjectContentReadinessCode;
  };
  type DialogMode = "create" | "rotate" | "switch";
  type SuccessKind = DialogMode | "switch-back";
  type LoadStatus = "idle" | "loading" | "error";

  type Props = {
    capability: Capability | undefined;
    canEdit: boolean;
    readinessLabel: (code: ObjectContentReadinessCode) => string;
    onConnectionChanged?: () => Promise<void>;
    onAuthorityRevoked?: () => void;
  };

  let { capability, canEdit, readinessLabel, onConnectionChanged, onAuthorityRevoked }: Props =
    $props();

  const eneo = getEneo();

  let connection = $state<ObjectStoreConnection | null>(null);
  let loadStatus = $state<LoadStatus>("idle");
  let dialogOpen = $state(false);
  let dialogMode = $state<DialogMode>("create");
  let advancedOpen = $state(false);
  let submitting = $state(false);
  let submissionCode = $state<string | null>(null);
  let submissionUnknown = $state(false);
  let mutationOutcomeUnknown = $state(false);
  let connectionAlreadyConfigured = $state(false);
  let connectionRevisionConflict = $state(false);
  let success = $state<SuccessKind | null>(null);
  let switchInFlight = $state(false);
  let alertRef = $state<HTMLElement | null>(null);

  let endpointUrl = $state("");
  let bucket = $state("");
  let region = $state("");
  let accessKeyId = $state("");
  let secretAccessKey = $state("");
  let addressingStyle = $state<"path" | "virtual">("path");

  const configured = $derived(connection?.configured ?? capability?.configured ?? false);
  const degraded = $derived(configured && capability?.readiness_code !== "ready");
  const summary = $derived.by(() => {
    if (loadStatus === "loading") return m.storage_connection_summary_loading();
    if (connection?.source === "environment") return m.storage_connection_summary_environment();
    if (configured) return m.storage_connection_summary_configured();
    return m.storage_connection_summary_unconfigured();
  });
  const canCreate = $derived(
    canEdit &&
      loadStatus === "idle" &&
      connection?.source === "unconfigured" &&
      connection.credentials_can_be_managed === true
  );
  const canRotate = $derived(
    canEdit &&
      loadStatus === "idle" &&
      connection?.source === "admin" &&
      connection.credentials_can_be_managed === true &&
      connection.revision !== null
  );
  const canSwitch = $derived(canRotate);
  const previousDestination = $derived(connection?.previous_destination ?? null);
  const formValid = $derived(
    accessKeyId.trim().length > 0 &&
      secretAccessKey.length > 0 &&
      (dialogMode === "rotate" ||
        (endpointUrl.trim().length > 0 && bucket.trim().length > 0 && region.trim().length > 0))
  );

  $effect(() => alertRef?.focus());

  function hasStatus(error: unknown, status: number): boolean {
    return (
      typeof error === "object" && error !== null && "status" in error && error.status === status
    );
  }

  async function loadConnection(): Promise<boolean> {
    if (!canEdit || loadStatus === "loading") return false;
    loadStatus = "loading";
    try {
      connection = await eneo.objectStoreConnection.get();
      loadStatus = "idle";
      return true;
    } catch (error: unknown) {
      if (hasStatus(error, 403)) onAuthorityRevoked?.();
      loadStatus = "error";
      return false;
    }
  }

  async function recoverConnection(): Promise<void> {
    if (
      (await loadConnection()) &&
      (mutationOutcomeUnknown || connectionAlreadyConfigured || connectionRevisionConflict)
    ) {
      await onConnectionChanged?.();
    }
  }

  function resetSecrets(): void {
    accessKeyId = "";
    secretAccessKey = "";
  }

  function openCreateDialog(): void {
    dialogMode = "create";
    endpointUrl = "";
    bucket = "";
    region = "";
    addressingStyle = "path";
    resetSecrets();
    resetSubmissionState();
    mutationOutcomeUnknown = false;
    connectionAlreadyConfigured = false;
    connectionRevisionConflict = false;
    advancedOpen = false;
    dialogOpen = true;
  }

  function openRotationDialog(): void {
    if (!connection) return;
    dialogMode = "rotate";
    endpointUrl = connection.endpoint_url ?? "";
    bucket = connection.bucket ?? "";
    region = connection.region ?? "";
    addressingStyle = connection.addressing_style ?? "path";
    resetSecrets();
    resetSubmissionState();
    mutationOutcomeUnknown = false;
    connectionAlreadyConfigured = false;
    connectionRevisionConflict = false;
    advancedOpen = false;
    dialogOpen = true;
  }

  function openSwitchDialog(): void {
    dialogMode = "switch";
    endpointUrl = "";
    bucket = "";
    region = "";
    addressingStyle = "path";
    resetSecrets();
    resetSubmissionState();
    mutationOutcomeUnknown = false;
    connectionAlreadyConfigured = false;
    connectionRevisionConflict = false;
    advancedOpen = false;
    dialogOpen = true;
  }

  async function switchBackDestination(): Promise<void> {
    if (switchInFlight) return;
    switchInFlight = true;
    resetSubmissionState();
    try {
      connection = await eneo.objectStoreConnection.switchBackDestination();
      success = "switch-back";
      await onConnectionChanged?.();
    } catch (error: unknown) {
      if (hasStatus(error, 403)) {
        onAuthorityRevoked?.();
      } else {
        success = null;
        submissionCode =
          error instanceof EneoError && typeof error.response?.code === "string"
            ? error.response.code
            : null;
        submissionUnknown = submissionCode === null;
        await loadConnection();
      }
    } finally {
      switchInFlight = false;
    }
  }

  async function forgetPreviousDestination(): Promise<void> {
    if (switchInFlight) return;
    switchInFlight = true;
    resetSubmissionState();
    try {
      await eneo.objectStoreConnection.forgetPreviousDestination();
      await loadConnection();
    } catch (error: unknown) {
      if (hasStatus(error, 403)) onAuthorityRevoked?.();
      else await loadConnection();
    } finally {
      switchInFlight = false;
    }
  }

  function resetSubmissionState(): void {
    submissionCode = null;
    submissionUnknown = false;
  }

  function handleDialogOpenChange(nextOpen: boolean): void {
    if (submitting) return;
    dialogOpen = nextOpen;
    if (!nextOpen) resetSecrets();
  }

  async function submitConnection(): Promise<void> {
    if (!formValid || submitting) return;

    submitting = true;
    resetSubmissionState();
    try {
      if (dialogMode === "create") {
        const candidate: ObjectStoreConnectionCreate = {
          endpoint_url: endpointUrl.trim(),
          bucket: bucket.trim(),
          region: region.trim(),
          access_key_id: accessKeyId.trim(),
          secret_access_key: secretAccessKey,
          addressing_style: addressingStyle
        };
        connection = await eneo.objectStoreConnection.create(candidate);
      } else if (dialogMode === "switch") {
        const destination: ObjectStoreConnectionCreate = {
          endpoint_url: endpointUrl.trim(),
          bucket: bucket.trim(),
          region: region.trim(),
          access_key_id: accessKeyId.trim(),
          secret_access_key: secretAccessKey,
          addressing_style: addressingStyle
        };
        connection = await eneo.objectStoreConnection.replaceDestination(destination);
      } else {
        if (connection?.revision === null || connection?.revision === undefined) return;
        const credentials: ObjectStoreCredentialRotation = {
          expected_revision: connection.revision,
          access_key_id: accessKeyId.trim(),
          secret_access_key: secretAccessKey
        };
        connection = await eneo.objectStoreConnection.rotateCredentials(credentials);
      }
      const completedMode = dialogMode;
      resetSecrets();
      dialogOpen = false;
      success = completedMode;
      mutationOutcomeUnknown = false;
      connectionAlreadyConfigured = false;
      connectionRevisionConflict = false;
      await onConnectionChanged?.();
    } catch (error: unknown) {
      if (hasStatus(error, 403)) {
        onAuthorityRevoked?.();
        dialogOpen = false;
      } else {
        const reasonCode =
          error instanceof EneoError && typeof error.response?.code === "string"
            ? error.response.code
            : null;
        if (reasonCode === "object_store_connection_mutation_outcome_unknown") {
          resetSecrets();
          dialogOpen = false;
          success = null;
          mutationOutcomeUnknown = true;
          await recoverConnection();
        } else if (reasonCode === "object_store_connection_already_configured") {
          resetSecrets();
          dialogOpen = false;
          success = null;
          connectionAlreadyConfigured = true;
          await recoverConnection();
        } else if (reasonCode === "object_store_connection_revision_conflict") {
          resetSecrets();
          dialogOpen = false;
          success = null;
          connectionRevisionConflict = true;
          await recoverConnection();
        } else {
          submissionCode = reasonCode;
          submissionUnknown = reasonCode === null;
        }
      }
    } finally {
      submitting = false;
    }
  }

  function errorTitle(code: string | null): string {
    if (code === null) return m.storage_connection_error_unknown_title();
    if (code === "object_store_probe_authentication_failed")
      return m.storage_connection_error_auth_title();
    if (code === "object_store_probe_tls_failed") return m.storage_connection_error_tls_title();
    if (code === "object_store_plain_http_not_permitted")
      return m.storage_connection_error_http_title();
    if (code === "object_store_endpoint_not_permitted")
      return m.storage_connection_error_endpoint_not_permitted_title();
    if (code === "object_store_probe_binding_mismatch")
      return m.storage_connection_error_binding_title();
    if (code === "object_store_probe_integrity_failed")
      return m.storage_connection_error_integrity_title();
    if (code === "object_store_credential_encryption_unavailable")
      return m.storage_connection_error_encryption_title();
    if (code === "object_store_connection_revision_conflict")
      return m.storage_connection_error_conflict_title();
    if (code === "object_store_destination_switch_blocked")
      return m.storage_switch_error_blocked_title();
    if (code === "object_store_new_writes_not_redirected")
      return m.storage_switch_error_new_writes_title();
    return m.storage_connection_error_unavailable_title();
  }

  function errorDescription(code: string | null): string {
    if (code === null) return m.storage_connection_error_unknown_description();
    if (code === "object_store_probe_authentication_failed")
      return m.storage_connection_error_auth_description();
    if (code === "object_store_probe_tls_failed")
      return m.storage_connection_error_tls_description();
    if (code === "object_store_plain_http_not_permitted")
      return m.storage_connection_error_http_description();
    if (code === "object_store_endpoint_not_permitted")
      return m.storage_connection_error_endpoint_not_permitted_description();
    if (code === "object_store_probe_binding_mismatch")
      return m.storage_connection_error_binding_description();
    if (code === "object_store_probe_integrity_failed")
      return m.storage_connection_error_integrity_description();
    if (code === "object_store_credential_encryption_unavailable")
      return m.storage_connection_error_encryption_description();
    if (code === "object_store_connection_revision_conflict")
      return m.storage_connection_error_conflict_description();
    if (code === "object_store_destination_switch_blocked")
      return m.storage_switch_error_blocked_description();
    if (code === "object_store_new_writes_not_redirected")
      return m.storage_switch_error_new_writes_description();
    return m.storage_connection_error_unavailable_description();
  }

  onMount(() => {
    if (canEdit) void loadConnection();
  });
</script>

<PolicySection
  id="storage-connection"
  title={m.storage_connection_title()}
  description={m.storage_connection_description()}
  {summary}
  summaryVariant={degraded ? "destructive" : configured ? "default" : "outline"}
>
  {#snippet icon()}
    <HardDrive class="size-5" aria-hidden="true" />
  {/snippet}

  {#if success !== null}
    <Alert.Root aria-live="polite">
      <CheckCircle2 />
      <Alert.Title>
        {success === "create"
          ? m.storage_connection_created_title()
          : success === "switch"
            ? m.storage_switch_done_title()
            : success === "switch-back"
              ? m.storage_switch_back_done_title()
              : m.storage_connection_rotated_title()}
      </Alert.Title>
      <Alert.Description>
        {success === "create"
          ? m.storage_connection_created_description()
          : success === "switch"
            ? m.storage_switch_done_description()
            : success === "switch-back"
              ? m.storage_switch_back_done_description()
              : m.storage_connection_rotated_description()}
      </Alert.Description>
    </Alert.Root>
  {/if}

  {#if mutationOutcomeUnknown}
    <Alert.Root aria-live="polite">
      <AlertCircle />
      <Alert.Title>{m.storage_connection_mutation_outcome_unknown_title()}</Alert.Title>
      <Alert.Description>
        {m.storage_connection_mutation_outcome_unknown_description()}
      </Alert.Description>
    </Alert.Root>
  {/if}

  {#if connectionAlreadyConfigured}
    <Alert.Root aria-live="polite">
      <CheckCircle2 />
      <Alert.Title>{m.storage_connection_already_configured_title()}</Alert.Title>
      <Alert.Description>
        {m.storage_connection_already_configured_description()}
      </Alert.Description>
    </Alert.Root>
  {/if}

  {#if connectionRevisionConflict && loadStatus === "idle"}
    <Alert.Root aria-live="polite">
      <AlertCircle />
      <Alert.Title>{m.storage_connection_error_conflict_title()}</Alert.Title>
      <Alert.Description>{m.storage_connection_error_conflict_description()}</Alert.Description>
    </Alert.Root>
  {/if}

  {#if degraded}
    <Alert.Root variant="destructive">
      <AlertCircle />
      <Alert.Title>{m.storage_connection_degraded_title()}</Alert.Title>
      <Alert.Description>
        {m.storage_connection_degraded_description({
          status: capability ? readinessLabel(capability.readiness_code) : ""
        })}
      </Alert.Description>
    </Alert.Root>
  {/if}

  {#if !canEdit}
    <div class="flex flex-col gap-1">
      <p class="text-sm font-medium">
        {capability?.configured
          ? m.storage_connection_health_configured()
          : m.storage_connection_health_unconfigured()}
      </p>
      <p class="text-secondary text-sm">
        {capability
          ? readinessLabel(capability.readiness_code)
          : m.storage_connection_health_unknown()}
      </p>
      <p class="text-muted mt-1 text-xs">{m.storage_connection_platform_admin_only()}</p>
    </div>
  {:else if loadStatus === "loading"}
    <div class="flex flex-col gap-3" aria-busy="true">
      <Skeleton class="h-5 w-52" />
      <Skeleton class="h-16 w-full" />
      <span class="sr-only">{m.storage_connection_loading()}</span>
    </div>
  {:else if loadStatus === "error"}
    <Alert.Root variant="destructive">
      <AlertCircle />
      <Alert.Title>{m.storage_connection_load_error_title()}</Alert.Title>
      <Alert.Description>
        <p>{m.storage_connection_load_error_description()}</p>
        <Button class="mt-3" variant="outline" onclick={recoverConnection}>
          {m.retry()}
        </Button>
      </Alert.Description>
    </Alert.Root>
  {:else if connection?.source === "admin"}
    <div class="flex flex-col gap-4">
      <dl class="grid gap-x-8 gap-y-4 sm:grid-cols-2">
        <div class="min-w-0">
          <dt class="text-secondary text-sm">{m.storage_connection_endpoint()}</dt>
          <dd class="mt-1 truncate text-sm font-medium" title={connection.endpoint_url ?? ""}>
            {connection.endpoint_url}
          </dd>
        </div>
        <div class="min-w-0">
          <dt class="text-secondary text-sm">{m.storage_connection_bucket()}</dt>
          <dd class="mt-1 truncate text-sm font-medium" title={connection.bucket ?? ""}>
            {connection.bucket}
          </dd>
        </div>
        <div>
          <dt class="text-secondary text-sm">{m.storage_connection_region()}</dt>
          <dd class="mt-1 text-sm font-medium">{connection.region}</dd>
        </div>
        <div>
          <dt class="text-secondary text-sm">{m.storage_connection_addressing_style()}</dt>
          <dd class="mt-1 flex items-center gap-2 text-sm font-medium">
            {connection.addressing_style === "virtual"
              ? m.storage_connection_addressing_virtual()
              : m.storage_connection_addressing_path()}
            <Badge variant="outline">
              {m.storage_connection_revision({ revision: connection.revision ?? 0 })}
            </Badge>
          </dd>
        </div>
      </dl>

      <div
        class="border-default flex flex-col gap-3 border-t pt-4 sm:flex-row sm:items-center sm:justify-between"
      >
        <p class="text-secondary max-w-[68ch] text-sm leading-5">
          {m.storage_connection_rotation_description()}
        </p>
        <div class="flex shrink-0 flex-col gap-2 sm:flex-row">
          <Button variant="outline" onclick={openRotationDialog} disabled={!canRotate}>
            <KeyRound data-icon="inline-start" aria-hidden="true" />
            {m.storage_connection_rotate_action()}
          </Button>
          <Button variant="outline" onclick={openSwitchDialog} disabled={!canSwitch}>
            <ArrowLeftRight data-icon="inline-start" aria-hidden="true" />
            {m.storage_switch_action()}
          </Button>
        </div>
      </div>

      {#if previousDestination}
        <div class="border-default rounded-md border p-4">
          <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div class="min-w-0">
              <p class="text-sm font-medium">{m.storage_switch_previous_title()}</p>
              <p class="text-secondary mt-1 truncate text-sm" title={previousDestination.bucket}>
                {previousDestination.endpoint_url} · {previousDestination.bucket}
              </p>
              <p class="text-secondary mt-2 max-w-[68ch] text-sm leading-5">
                {m.storage_switch_previous_description()}
              </p>
            </div>
            <div class="flex shrink-0 flex-col gap-2 sm:flex-row">
              <Button
                variant="outline"
                onclick={switchBackDestination}
                disabled={!canSwitch || switchInFlight}
                aria-busy={switchInFlight}
              >
                {#if switchInFlight}
                  <Loader2 data-icon="inline-start" class="animate-spin" aria-hidden="true" />
                {/if}
                {m.storage_switch_back_action()}
              </Button>
              <Button
                variant="ghost"
                onclick={forgetPreviousDestination}
                disabled={!canSwitch || switchInFlight}
              >
                {m.storage_switch_forget_action()}
              </Button>
            </div>
          </div>
        </div>
      {/if}
    </div>
  {:else if connection?.source === "environment"}
    <Alert.Root>
      <Settings2 />
      <Alert.Title>{m.storage_connection_environment_title()}</Alert.Title>
      <Alert.Description>{m.storage_connection_environment_description()}</Alert.Description>
    </Alert.Root>
  {:else}
    <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div class="max-w-xl">
        <p class="text-sm font-medium">{m.storage_connection_empty_title()}</p>
        <p class="text-secondary mt-1 text-sm">{m.storage_connection_empty_description()}</p>
      </div>
      <Button onclick={openCreateDialog} disabled={!canCreate}>
        {m.storage_connection_add_action()}
      </Button>
    </div>
    {#if connection && !connection.credentials_can_be_managed}
      <Alert.Root>
        <AlertCircle />
        <Alert.Title>{m.storage_connection_encryption_required_title()}</Alert.Title>
        <Alert.Description
          >{m.storage_connection_encryption_required_description()}</Alert.Description
        >
      </Alert.Root>
    {/if}
  {/if}
</PolicySection>

<Dialog.Root open={dialogOpen} onOpenChange={handleDialogOpenChange}>
  <Dialog.Content
    class={dialogMode === "rotate"
      ? "flex max-h-[calc(100dvh-2rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-xl"
      : "flex max-h-[calc(100dvh-2rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl"}
    showCloseButton={!submitting}
    closeLabel={m.close()}
  >
    <Dialog.Header class="px-6 pt-6 pb-2 pr-12">
      <Dialog.Title>
        {dialogMode === "create"
          ? m.storage_connection_dialog_create_title()
          : dialogMode === "switch"
            ? m.storage_switch_dialog_title()
            : m.storage_connection_dialog_rotate_title()}
      </Dialog.Title>
      <Dialog.Description>
        {dialogMode === "create"
          ? m.storage_connection_dialog_create_description()
          : dialogMode === "switch"
            ? m.storage_switch_dialog_description()
            : m.storage_connection_dialog_rotate_description()}
      </Dialog.Description>
    </Dialog.Header>

    <form
      class="flex min-h-0 flex-1 flex-col"
      onsubmit={(event) => {
        event.preventDefault();
        void submitConnection();
      }}
    >
      <div class="min-h-0 flex-1 overflow-y-auto px-6 py-4">
        <div class="flex flex-col gap-5">
          {#if submissionCode !== null || submissionUnknown}
            <Alert.Root
              bind:ref={alertRef}
              tabindex={-1}
              variant="destructive"
              aria-live="assertive"
            >
              <AlertCircle />
              <Alert.Title>{errorTitle(submissionCode)}</Alert.Title>
              <Alert.Description>{errorDescription(submissionCode)}</Alert.Description>
            </Alert.Root>
          {/if}

          {#if dialogMode === "switch"}
            <Alert.Root>
              <AlertCircle />
              <Alert.Title>{m.storage_switch_checklist_title()}</Alert.Title>
              <Alert.Description>
                <ul class="ml-4 list-disc space-y-1">
                  <li>{m.storage_switch_checklist_copied()}</li>
                  <li>{m.storage_switch_checklist_inline()}</li>
                  <li>{m.storage_switch_checklist_reversible()}</li>
                </ul>
              </Alert.Description>
            </Alert.Root>
          {/if}

          {#if dialogMode === "rotate"}
            <section
              class="border-default border-b pb-5"
              aria-labelledby="object-store-current-destination"
            >
              <h3 id="object-store-current-destination" class="text-sm font-medium">
                {m.storage_connection_current_destination()}
              </h3>
              <dl class="mt-3 grid gap-x-6 gap-y-3 sm:grid-cols-2">
                <div class="min-w-0">
                  <dt class="text-secondary text-sm">{m.storage_connection_endpoint()}</dt>
                  <dd class="mt-0.5 truncate text-sm font-medium" title={endpointUrl}>
                    {endpointUrl}
                  </dd>
                </div>
                <div class="min-w-0">
                  <dt class="text-secondary text-sm">{m.storage_connection_bucket()}</dt>
                  <dd class="mt-0.5 truncate text-sm font-medium" title={bucket}>{bucket}</dd>
                </div>
              </dl>
              <p class="text-secondary mt-3 max-w-[65ch] text-sm leading-5">
                {m.storage_connection_destination_locked_help()}
              </p>
            </section>
          {:else}
            <Field.Group class="grid gap-5 sm:grid-cols-2">
              <Field.Field class="sm:col-span-2">
                <Field.Label for="object-store-endpoint">
                  {m.storage_connection_endpoint()}
                </Field.Label>
                <Input
                  id="object-store-endpoint"
                  type="url"
                  bind:value={endpointUrl}
                  placeholder={m.storage_connection_endpoint_placeholder()}
                  autocomplete="url"
                  required
                  disabled={submitting}
                />
                <Field.Description>{m.storage_connection_endpoint_help()}</Field.Description>
              </Field.Field>

              <Field.Field>
                <Field.Label for="object-store-bucket">
                  {m.storage_connection_bucket()}
                </Field.Label>
                <Input
                  id="object-store-bucket"
                  bind:value={bucket}
                  placeholder={m.storage_connection_bucket_placeholder()}
                  autocomplete="off"
                  required
                  disabled={submitting}
                />
              </Field.Field>

              <Field.Field>
                <Field.Label for="object-store-region">
                  {m.storage_connection_region()}
                </Field.Label>
                <Input
                  id="object-store-region"
                  bind:value={region}
                  placeholder={m.storage_connection_region_placeholder()}
                  autocomplete="off"
                  required
                  disabled={submitting}
                />
                <Field.Description>{m.storage_connection_region_help()}</Field.Description>
              </Field.Field>
            </Field.Group>
          {/if}

          <Field.Group class="grid gap-5 sm:grid-cols-2">
            <Field.Field>
              <Field.Label for="object-store-access-key">
                {m.storage_connection_access_key()}
              </Field.Label>
              <Input
                id="object-store-access-key"
                type="text"
                bind:value={accessKeyId}
                autocomplete="off"
                required
                disabled={submitting}
              />
              <Field.Description>{m.storage_connection_access_key_help()}</Field.Description>
            </Field.Field>

            <Field.Field>
              <Field.Label for="object-store-secret-key">
                {m.storage_connection_secret_key()}
              </Field.Label>
              <Input
                id="object-store-secret-key"
                type="password"
                bind:value={secretAccessKey}
                autocomplete="new-password"
                required
                disabled={submitting}
              />
              <Field.Description>{m.storage_connection_secret_key_help()}</Field.Description>
            </Field.Field>
          </Field.Group>

          {#if dialogMode !== "rotate"}
            <Collapsible.Root bind:open={advancedOpen}>
              <Collapsible.Trigger
                class="hover:bg-muted/50 focus-visible:ring-ring flex w-full items-center justify-between rounded-md py-2 text-sm font-medium focus-visible:ring-2 focus-visible:outline-none"
              >
                <span>{m.storage_connection_advanced()}</span>
                <ChevronDown
                  class={advancedOpen
                    ? "size-4 rotate-180 transition-transform"
                    : "size-4 transition-transform"}
                  aria-hidden="true"
                />
              </Collapsible.Trigger>
              <Collapsible.Content class="pt-3">
                <Field.Field>
                  <Field.Label for="object-store-addressing-style">
                    {m.storage_connection_addressing_style()}
                  </Field.Label>
                  <Select.Root type="single" bind:value={addressingStyle} disabled={submitting}>
                    <Select.Trigger id="object-store-addressing-style" class="w-full">
                      {addressingStyle === "virtual"
                        ? m.storage_connection_addressing_virtual()
                        : m.storage_connection_addressing_path()}
                    </Select.Trigger>
                    <Select.Content>
                      <Select.Item value="path">
                        {m.storage_connection_addressing_path()}
                      </Select.Item>
                      <Select.Item value="virtual">
                        {m.storage_connection_addressing_virtual()}
                      </Select.Item>
                    </Select.Content>
                  </Select.Root>
                  <Field.Description>
                    {m.storage_connection_addressing_help()}
                  </Field.Description>
                </Field.Field>
              </Collapsible.Content>
            </Collapsible.Root>
          {/if}

          <div class="text-secondary flex items-start gap-3 text-sm">
            <CheckCircle2 class="text-primary mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <div class="min-w-0">
              <p class="text-primary font-medium">
                {dialogMode === "rotate"
                  ? m.storage_connection_probe_rotate_title()
                  : m.storage_connection_probe_create_title()}
              </p>
              <p class="mt-1 max-w-[65ch] leading-5">
                {dialogMode === "rotate"
                  ? m.storage_connection_probe_rotate_description()
                  : dialogMode === "switch"
                    ? m.storage_switch_probe_description()
                    : m.storage_connection_probe_create_description()}
              </p>
            </div>
          </div>
        </div>
      </div>

      <div
        class="border-default flex flex-col-reverse gap-2 border-t px-6 py-4 sm:flex-row sm:justify-end"
      >
        <Button
          type="button"
          variant="outline"
          onclick={() => handleDialogOpenChange(false)}
          disabled={submitting}
        >
          {m.cancel()}
        </Button>
        <Button type="submit" disabled={!formValid || submitting} aria-busy={submitting}>
          {#if submitting}
            <Loader2 data-icon="inline-start" class="animate-spin" aria-hidden="true" />
            {m.storage_connection_testing()}
          {:else if dialogMode === "create"}
            {m.storage_connection_test_and_save()}
          {:else if dialogMode === "switch"}
            {m.storage_switch_test_and_switch()}
          {:else}
            {m.storage_connection_test_and_rotate()}
          {/if}
        </Button>
      </div>
    </form>
  </Dialog.Content>
</Dialog.Root>
