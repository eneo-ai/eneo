<script lang="ts">
  import type { ApiKeyCreatedResponse, ApiKeyUpdateRequest, ApiKeyV2 } from "@intric/intric-js";
  import { Button, Dialog, Dropdown, Input, Select } from "@intric/ui";
  import { Ban, ChevronDown, MoreVertical, Pencil, RefreshCw, RotateCcw } from "lucide-svelte";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { writable } from "svelte/store";
  import TagInput from "../../account/api-keys/TagInput.svelte";

  const intric = getIntric();

  let { apiKey, onChanged, onSecret } = $props<{
    apiKey: ApiKeyV2;
    onChanged: () => void;
    onSecret: (response: ApiKeyCreatedResponse) => void;
  }>();

  const showRevokeDialog = writable(false);
  const showSuspendDialog = writable(false);
  const showEditDialog = writable(false);
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
    $showEditDialog = true;
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
      $showEditDialog = false;
      return;
    }

    try {
      await intric.apiKeys.admin.update({
        id: apiKey.id,
        update: updates
      });
      onChanged();
      $showEditDialog = false;
    } catch (error) {
      console.error(error);
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
    }
  }

  async function rotateKey() {
    errorMessage = null;
    try {
      const response = await intric.apiKeys.admin.rotate({ id: apiKey.id });
      if (!response?.secret) {
        throw new Error("rotate_missing_secret");
      }
      onSecret(response);
    } catch (error) {
      console.error(error);
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
    }
  }

  async function revokeKey() {
    errorMessage = null;
    try {
      await intric.apiKeys.admin.revoke({
        id: apiKey.id,
        request: {
          reason_code: "admin_action",
          reason_text: reasonText || undefined
        }
      });
      onChanged();
      $showRevokeDialog = false;
      reasonText = "";
    } catch (error) {
      console.error(error);
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
    }
  }

  async function suspendKey() {
    errorMessage = null;
    try {
      await intric.apiKeys.admin.suspend({
        id: apiKey.id,
        request: {
          reason_code: "admin_action",
          reason_text: reasonText || undefined
        }
      });
      onChanged();
      $showSuspendDialog = false;
      reasonText = "";
    } catch (error) {
      console.error(error);
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
    }
  }

  async function reactivateKey() {
    errorMessage = null;
    try {
      await intric.apiKeys.admin.reactivate({ id: apiKey.id });
      onChanged();
    } catch (error) {
      console.error(error);
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
    }
  }
</script>

<Dropdown.Root>
  <Dropdown.Trigger asFragment let:trigger>
    <Button is={trigger} padding="icon" aria-label={m.actions()}>
      <MoreVertical size={16} />
    </Button>
  </Dropdown.Trigger>

  <Dropdown.Menu let:item>
    <Button is={item} padding="icon-leading" on:click={openEditDialog}>
      <Pencil size={16} />
      {m.api_keys_admin_action_edit()}
    </Button>

    {#if canRotate}
      <Button is={item} padding="icon-leading" on:click={rotateKey}>
        <RotateCcw size={16} />
        {m.api_keys_admin_action_rotate()}
      </Button>
    {/if}

    {#if isActive}
      <Button
        is={item}
        padding="icon-leading"
        on:click={() => {
          $showSuspendDialog = true;
        }}
      >
        <Ban size={16} />
        {m.api_keys_admin_action_suspend()}
      </Button>
    {/if}

    {#if isSuspended}
      <Button is={item} padding="icon-leading" on:click={reactivateKey}>
        <RefreshCw size={16} />
        {m.api_keys_admin_action_reactivate()}
      </Button>
    {/if}

    <Button
      is={item}
      variant="destructive"
      padding="icon-leading"
      on:click={() => {
        $showRevokeDialog = true;
      }}
    >
      <Ban size={16} />
      {m.api_keys_admin_action_revoke()}
    </Button>
  </Dropdown.Menu>
</Dropdown.Root>

{#if errorMessage}
  <div class="text-xs text-red-600">{errorMessage}</div>
{/if}

<Dialog.Root openController={showEditDialog}>
  <Dialog.Content width="medium">
    <Dialog.Title>{m.api_keys_admin_edit_title()}</Dialog.Title>
    <Dialog.Description>
      {m.api_keys_admin_edit_description()}
    </Dialog.Description>
    <div class="mt-3 space-y-3">
      <Input.Text bind:value={editName} label={m.name()} />
      <Input.TextArea bind:value={editDescription} label={m.description()} rows={3} />
      {#if canEditPermission}
        <Select.Simple
          bind:value={editPermission}
          options={permissionOptions}
          resourceName="permission"
        >
          {m.api_keys_admin_edit_permission_label()}
        </Select.Simple>
      {:else}
        <div>
          <p class="text-muted mb-1 text-xs">{m.api_keys_admin_edit_permission_label()}</p>
          <div class="border-default bg-subtle text-default rounded-md border px-3 py-2 text-sm">
            {editPermission}
          </div>
        </div>
        <p class="text-muted text-xs">{m.api_keys_admin_edit_permission_disabled_hint()}</p>
      {/if}

      <div class="grid gap-3 sm:grid-cols-2">
        <div>
          <p class="text-muted mb-1 text-xs">{m.api_keys_admin_edit_scope_readonly_label()}</p>
          <div class="border-default bg-subtle text-default rounded-md border px-3 py-2 text-sm">
            {scopeLabel}
          </div>
        </div>
        <div>
          <p class="text-muted mb-1 text-xs">{m.api_keys_admin_edit_key_type_readonly_label()}</p>
          <div class="border-default bg-subtle text-default rounded-md border px-3 py-2 text-sm">
            {keyTypeLabel}
          </div>
        </div>
      </div>
      <p class="text-muted text-xs">{m.api_keys_admin_edit_immutable_hint()}</p>

      <div class="border-default/70 pt-2">
        <button
          type="button"
          onclick={() => (showAdvanced = !showAdvanced)}
          class="text-default hover:text-accent-default inline-flex w-full items-center justify-between rounded-md px-1 py-1.5 text-left text-sm font-medium transition-colors"
          aria-expanded={showAdvanced}
        >
          <span>{m.api_keys_admin_edit_advanced_title()}</span>
          <ChevronDown class="h-4 w-4 transition-transform {showAdvanced ? 'rotate-180' : ''}" />
        </button>
        <p class="text-muted mt-1 text-xs">{m.api_keys_admin_edit_advanced_description()}</p>
      </div>

      {#if showAdvanced}
        <div class="border-default bg-subtle/40 space-y-3 rounded-lg border p-3">
          <Input.Text
            bind:value={editRateLimit}
            label={m.api_keys_rate_limit()}
            placeholder={m.api_keys_rate_limit_placeholder()}
            disabled={!canEditGuardrails}
          />
          <p class="text-muted -mt-1 text-xs">{m.api_keys_rate_limit_help()}</p>

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
            <p class="text-muted text-xs">{m.api_keys_admin_edit_guardrails_disabled_hint()}</p>
          {/if}
        </div>
      {/if}
    </div>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button on:click={updateKey}>{m.save()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root openController={showSuspendDialog} alert>
  <Dialog.Content width="small">
    <Dialog.Title>{m.api_keys_admin_suspend_title()}</Dialog.Title>
    <Dialog.Description>
      {m.api_keys_admin_suspend_description()}
    </Dialog.Description>
    <Input.Text bind:value={reasonText} label={m.api_keys_admin_reason_optional()} />
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={suspendKey}
        >{m.api_keys_admin_action_suspend()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root openController={showRevokeDialog} alert>
  <Dialog.Content width="small">
    <Dialog.Title>{m.api_keys_admin_revoke_title()}</Dialog.Title>
    <Dialog.Description>
      {m.api_keys_admin_revoke_description()}
    </Dialog.Description>
    <Input.Text bind:value={reasonText} label={m.api_keys_admin_reason_optional()} />
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={revokeKey}>{m.api_keys_admin_action_revoke()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
