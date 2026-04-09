<script lang="ts">
  import type { ApiKeyCreatedResponse, ApiKeyUpdateRequest, ApiKeyV2 } from "@intric/intric-js";
  import {
    AlertCircle,
    Ban,
    ChevronDown,
    MoreVertical,
    Pencil,
    RefreshCw,
    RotateCcw
  } from "lucide-svelte";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "svelte-sonner";
  import TagInput from "../../account/api-keys/TagInput.svelte";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";

  const intric = getIntric();

  let { apiKey, onChanged, onSecret } = $props<{
    apiKey: ApiKeyV2;
    onChanged: () => void;
    onSecret: (response: ApiKeyCreatedResponse) => void;
  }>();

  let showRevokeDialog = $state(false);
  let showSuspendDialog = $state(false);
  let showEditDialog = $state(false);
  let actionPending = $state(false);
  let errorMessage = $state<string | null>(null);
  let reasonText = $state("");
  let editName = $state("");
  let editDescription = $state("");
  let editPermission = $state<"read" | "write" | "admin">("read");
  let editRateLimit = $state("");
  let editAllowedOrigins = $state<string[]>([]);
  let editAllowedIps = $state<string[]>([]);
  let showAdvanced = $state(false);

  const isActive = $derived(apiKey.state === "active");
  const isSuspended = $derived(apiKey.state === "suspended");
  const canRotate = $derived(apiKey.state === "active");
  const canEditPermission = $derived(apiKey.state === "active" || apiKey.state === "suspended");
  const canEditGuardrails = $derived(apiKey.state === "active" || apiKey.state === "suspended");
  const scopeLabel = $derived.by(() => {
    switch (apiKey.scope_type) {
      case "space":
        return m.api_keys_admin_scope_space();
      case "assistant":
        return m.api_keys_admin_scope_assistant();
      case "app":
        return m.api_keys_admin_scope_app();
      default:
        return m.api_keys_admin_scope_tenant();
    }
  });
  const keyTypeLabel = $derived(
    apiKey.key_type === "pk_"
      ? m.api_keys_admin_key_type_public_label()
      : m.api_keys_admin_key_type_secret_label()
  );
  const permissionOptions = $derived([
    { value: "read", label: m.api_keys_permission_read() },
    { value: "write", label: m.api_keys_permission_write() },
    { value: "admin", label: m.api_keys_permission_admin() }
  ]);

  function normalizeTags(values: string[] | null | undefined): string[] {
    return (values ?? []).map((value) => value.trim()).filter(Boolean);
  }

  function isSameStringArray(a: string[], b: string[]): boolean {
    if (a.length !== b.length) return false;
    return a.every((value, index) => value === b[index]);
  }

  function openEditDialog() {
    editName = apiKey.name;
    editDescription = apiKey.description ?? "";
    editPermission = apiKey.permission;
    editRateLimit = apiKey.rate_limit?.toString() ?? "";
    editAllowedOrigins = normalizeTags(apiKey.allowed_origins);
    editAllowedIps = normalizeTags(apiKey.allowed_ips);
    showAdvanced = Boolean(
      apiKey.rate_limit || editAllowedOrigins.length > 0 || editAllowedIps.length > 0
    );
    errorMessage = null;
    showEditDialog = true;
  }

  async function updateKey() {
    errorMessage = null;

    const trimmedName = editName.trim();
    if (!trimmedName) {
      errorMessage = m.api_keys_name_required();
      return;
    }

    const updates: ApiKeyUpdateRequest = {};
    if (trimmedName !== apiKey.name) {
      updates.name = trimmedName;
    }

    const normalizedDescription = editDescription.trim();
    const currentDescription = apiKey.description ?? "";
    if (normalizedDescription !== currentDescription) {
      updates.description = normalizedDescription || null;
    }

    if (canEditPermission && editPermission !== apiKey.permission) {
      updates.permission = editPermission;
    }

    if (canEditGuardrails) {
      const normalizedRateLimit = editRateLimit.trim();
      const parsedRateLimit = normalizedRateLimit ? Number(normalizedRateLimit) : null;
      if (
        normalizedRateLimit &&
        (!Number.isInteger(parsedRateLimit) || (parsedRateLimit ?? 0) <= 0)
      ) {
        errorMessage = m.api_keys_admin_edit_rate_limit_invalid();
        return;
      }
      const currentRateLimit = apiKey.rate_limit ?? null;
      if (parsedRateLimit !== currentRateLimit) {
        updates.rate_limit = parsedRateLimit;
      }

      if (apiKey.key_type === "pk_") {
        const nextOrigins = normalizeTags(editAllowedOrigins);
        const currentOrigins = normalizeTags(apiKey.allowed_origins);
        if (!isSameStringArray(nextOrigins, currentOrigins)) {
          updates.allowed_origins = nextOrigins.length > 0 ? nextOrigins : null;
        }
      }

      if (apiKey.key_type === "sk_") {
        const nextIps = normalizeTags(editAllowedIps);
        const currentIps = normalizeTags(apiKey.allowed_ips);
        if (!isSameStringArray(nextIps, currentIps)) {
          updates.allowed_ips = nextIps.length > 0 ? nextIps : null;
        }
      }
    }

    if (Object.keys(updates).length === 0) {
      showEditDialog = false;
      return;
    }

    actionPending = true;
    try {
      await intric.apiKeys.admin.update({
        id: apiKey.id,
        update: updates
      });
      onChanged();
      showEditDialog = false;
    } catch (error) {
      console.error(error);
      errorMessage = getErrorMessage(error);
    } finally {
      actionPending = false;
    }
  }

  async function rotateKey() {
    try {
      const response = await intric.apiKeys.admin.rotate({ id: apiKey.id });
      if (!response?.secret) {
        throw new Error("rotate_missing_secret");
      }
      onSecret(response);
    } catch (error) {
      console.error(error);
      toast.error(getErrorMessage(error));
    }
  }

  async function revokeKey() {
    errorMessage = null;
    actionPending = true;
    try {
      await intric.apiKeys.admin.revoke({
        id: apiKey.id,
        request: {
          reason_code: "admin_action",
          reason_text: reasonText || undefined
        }
      });
      onChanged();
      showRevokeDialog = false;
      reasonText = "";
    } catch (error) {
      console.error(error);
      errorMessage = getErrorMessage(error);
      toast.error(getErrorMessage(error));
    } finally {
      actionPending = false;
    }
  }

  async function suspendKey() {
    errorMessage = null;
    actionPending = true;
    try {
      await intric.apiKeys.admin.suspend({
        id: apiKey.id,
        request: {
          reason_code: "admin_action",
          reason_text: reasonText || undefined
        }
      });
      onChanged();
      showSuspendDialog = false;
      reasonText = "";
    } catch (error) {
      console.error(error);
      errorMessage = getErrorMessage(error);
      toast.error(getErrorMessage(error));
    } finally {
      actionPending = false;
    }
  }

  async function reactivateKey() {
    try {
      await intric.apiKeys.admin.reactivate({ id: apiKey.id });
      onChanged();
    } catch (error) {
      console.error(error);
      toast.error(getErrorMessage(error));
    }
  }
</script>

<DropdownMenu.Root>
  <DropdownMenu.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="ghost" size="icon" aria-label={m.actions()}>
        <MoreVertical />
      </Button>
    {/snippet}
  </DropdownMenu.Trigger>

  <DropdownMenu.Content align="end">
    <DropdownMenu.Item onclick={openEditDialog}>
      <Pencil />
      {m.api_keys_admin_action_edit()}
    </DropdownMenu.Item>

    {#if canRotate}
      <DropdownMenu.Item onclick={rotateKey}>
        <RotateCcw />
        {m.api_keys_admin_action_rotate()}
      </DropdownMenu.Item>
    {/if}

    {#if isActive}
      <DropdownMenu.Item
        onclick={() => {
          showSuspendDialog = true;
        }}
      >
        <Ban />
        {m.api_keys_admin_action_suspend()}
      </DropdownMenu.Item>
    {/if}

    {#if isSuspended}
      <DropdownMenu.Item onclick={reactivateKey}>
        <RefreshCw />
        {m.api_keys_admin_action_reactivate()}
      </DropdownMenu.Item>
    {/if}

    {#if apiKey.state !== "revoked"}
      <DropdownMenu.Separator />

      <DropdownMenu.Item
        variant="destructive"
        onclick={() => {
          showRevokeDialog = true;
        }}
      >
        <Ban />
        {m.api_keys_admin_action_revoke()}
      </DropdownMenu.Item>
    {/if}
  </DropdownMenu.Content>
</DropdownMenu.Root>

<Dialog.Root bind:open={showEditDialog}>
  <Dialog.Content class="sm:max-w-lg">
    <Dialog.Header>
      <Dialog.Title>{m.api_keys_admin_edit_title()}</Dialog.Title>
      <Dialog.Description>{m.api_keys_admin_edit_description()}</Dialog.Description>
    </Dialog.Header>

    {#if errorMessage}
      <Alert.Root variant="destructive">
        <AlertCircle />
        <Alert.Description>{errorMessage}</Alert.Description>
      </Alert.Root>
    {/if}

    <div class="space-y-4">
      <Field.Field>
        <Field.Label for="edit-name">{m.name()}</Field.Label>
        <Input id="edit-name" bind:value={editName} />
      </Field.Field>

      <Field.Field>
        <Field.Label for="edit-description">{m.description()}</Field.Label>
        <Textarea id="edit-description" bind:value={editDescription} rows={3} />
      </Field.Field>

      {#if canEditPermission}
        <Field.Field>
          <Field.Label for="edit-permission">
            {m.api_keys_admin_edit_permission_label()}
          </Field.Label>
          <Select.Root type="single" bind:value={editPermission}>
            <Select.Trigger id="edit-permission">
              {permissionOptions.find((o) => o.value === editPermission)?.label}
            </Select.Trigger>
            <Select.Content>
              {#each permissionOptions as opt (opt.value)}
                <Select.Item value={opt.value} label={opt.label}>{opt.label}</Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        </Field.Field>
      {:else}
        <div>
          <p class="text-secondary mb-1 text-xs">{m.api_keys_admin_edit_permission_label()}</p>
          <div class="border-default bg-subtle text-default rounded-md border px-3 py-2 text-sm">
            {editPermission}
          </div>
          <p class="text-secondary mt-1 text-xs">
            {m.api_keys_admin_edit_permission_disabled_hint()}
          </p>
        </div>
      {/if}

      <div class="grid gap-3 sm:grid-cols-2">
        <div>
          <p class="text-secondary mb-1 text-xs">{m.api_keys_admin_edit_scope_readonly_label()}</p>
          <div class="border-default bg-subtle text-default rounded-md border px-3 py-2 text-sm">
            {scopeLabel}
          </div>
        </div>
        <div>
          <p class="text-secondary mb-1 text-xs">
            {m.api_keys_admin_edit_key_type_readonly_label()}
          </p>
          <div class="border-default bg-subtle text-default rounded-md border px-3 py-2 text-sm">
            {keyTypeLabel}
          </div>
        </div>
      </div>
      <p class="text-secondary text-xs">{m.api_keys_admin_edit_immutable_hint()}</p>

      <Collapsible.Root bind:open={showAdvanced}>
        <Collapsible.Trigger
          class="group/trigger text-default hover:text-accent-default inline-flex w-full items-center justify-between rounded-md px-1 py-1.5 text-left text-sm font-medium transition-colors"
        >
          <span>{m.api_keys_admin_edit_advanced_title()}</span>
          <ChevronDown
            class="h-4 w-4 transition-transform duration-200 group-data-[state=open]/trigger:rotate-180"
          />
        </Collapsible.Trigger>
        <p class="text-secondary mt-1 mb-2 text-xs">
          {m.api_keys_admin_edit_advanced_description()}
        </p>

        <Collapsible.Content>
          <div class="border-default bg-subtle/40 space-y-3 rounded-lg border p-3">
            <Field.Field>
              <Field.Label for="edit-rate-limit">{m.api_keys_rate_limit()}</Field.Label>
              <Input
                id="edit-rate-limit"
                bind:value={editRateLimit}
                placeholder={m.api_keys_rate_limit_placeholder()}
                disabled={!canEditGuardrails}
              />
              <p class="text-secondary text-xs">{m.api_keys_rate_limit_help()}</p>
            </Field.Field>

            {#if apiKey.key_type === "pk_"}
              <TagInput
                type="origin"
                bind:value={editAllowedOrigins}
                label={m.api_keys_allowed_origins()}
                description={m.api_keys_allowed_origins_desc()}
                disabled={!canEditGuardrails}
              />
            {/if}

            {#if apiKey.key_type === "sk_"}
              <TagInput
                type="ip"
                bind:value={editAllowedIps}
                label={m.api_keys_allowed_ips()}
                description={m.api_keys_allowed_ips_desc()}
                disabled={!canEditGuardrails}
              />
            {/if}

            {#if !canEditGuardrails}
              <p class="text-secondary text-xs">
                {m.api_keys_admin_edit_guardrails_disabled_hint()}
              </p>
            {/if}
          </div>
        </Collapsible.Content>
      </Collapsible.Root>
    </div>

    <Dialog.Footer>
      <Dialog.Close>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>{m.cancel()}</Button>
        {/snippet}
      </Dialog.Close>
      <Button onclick={updateKey} disabled={actionPending}>{m.save()}</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root bind:open={showSuspendDialog}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>{m.api_keys_admin_suspend_title()}</Dialog.Title>
      <Dialog.Description>{m.api_keys_admin_suspend_description()}</Dialog.Description>
    </Dialog.Header>

    {#if errorMessage}
      <Alert.Root variant="destructive">
        <AlertCircle />
        <Alert.Description>{errorMessage}</Alert.Description>
      </Alert.Root>
    {/if}

    <Field.Field>
      <Field.Label for="admin-suspend-reason">{m.api_keys_admin_reason_optional()}</Field.Label>
      <Input id="admin-suspend-reason" bind:value={reasonText} />
    </Field.Field>

    <Dialog.Footer>
      <Dialog.Close>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>{m.cancel()}</Button>
        {/snippet}
      </Dialog.Close>
      <Button variant="destructive" onclick={suspendKey} disabled={actionPending}>
        {m.api_keys_admin_action_suspend()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root bind:open={showRevokeDialog}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>{m.api_keys_admin_revoke_title()}</Dialog.Title>
      <Dialog.Description>{m.api_keys_admin_revoke_description()}</Dialog.Description>
    </Dialog.Header>

    {#if errorMessage}
      <Alert.Root variant="destructive">
        <AlertCircle />
        <Alert.Description>{errorMessage}</Alert.Description>
      </Alert.Root>
    {/if}

    <Field.Field>
      <Field.Label for="admin-revoke-reason">{m.api_keys_admin_reason_optional()}</Field.Label>
      <Input id="admin-revoke-reason" bind:value={reasonText} />
    </Field.Field>

    <Dialog.Footer>
      <Dialog.Close>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>{m.cancel()}</Button>
        {/snippet}
      </Dialog.Close>
      <Button variant="destructive" onclick={revokeKey} disabled={actionPending}>
        {m.api_keys_admin_action_revoke()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
