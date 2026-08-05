<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import { getEneo } from "$lib/core/Eneo";
  import { Button } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import { Lock, RefreshCw, AlertCircle, CheckCircle2 } from "lucide-svelte";

  type ServiceAccountState = {
    configured: boolean;
    client_id: string | null;
    client_secret_preview: string | null;
    default_target: string | null;
  };

  const eneo = getEneo();

  let account = $state<ServiceAccountState>({
    configured: false,
    client_id: null,
    client_secret_preview: null,
    default_target: null
  });
  let loading = $state(true);
  let editing = $state(false);
  let saving = $state(false);
  let errorMessage = $state("");
  let successMessage = $state("");
  let formClientId = $state("");
  let formClientSecret = $state("");

  // Default audience / scope (shared across SSO MCP servers)
  let editingDefault = $state(false);
  let savingDefault = $state(false);
  let formDefaultTarget = $state("");

  async function load() {
    loading = true;
    errorMessage = "";
    try {
      /* eslint-disable @typescript-eslint/no-explicit-any */
      const data = (await eneo.client.fetch(
        "/api/v1/mcp-servers/service-account/" as any,
        { method: "get" } as any
      )) as ServiceAccountState;
      account = data;
      formClientId = data.client_id ?? "";
      formDefaultTarget = data.default_target ?? "";
    } catch (error: unknown) {
      const err = error as { message?: string };
      errorMessage = err?.message ?? m.mcp_sa_error_load();
    } finally {
      loading = false;
    }
    /* eslint-enable @typescript-eslint/no-explicit-any */
  }

  async function save() {
    if (!formClientId.trim() || !formClientSecret.trim()) {
      errorMessage = m.mcp_sa_error_required();
      return;
    }
    saving = true;
    errorMessage = "";
    successMessage = "";
    try {
      /* eslint-disable @typescript-eslint/no-explicit-any */
      const data = (await eneo.client.fetch(
        "/api/v1/mcp-servers/service-account/" as any,
        {
          method: "put" as any,
          requestBody: {
            "application/json": {
              client_id: formClientId,
              client_secret: formClientSecret
            }
          } as any
        } as any
      )) as ServiceAccountState;
      account = data;
      editing = false;
      formClientSecret = "";
      successMessage = m.mcp_sa_saved();
    } catch (error: unknown) {
      const err = error as { message?: string; body?: { message?: string } };
      errorMessage = err?.body?.message ?? err?.message ?? m.mcp_sa_error_save();
    } finally {
      saving = false;
    }
    /* eslint-enable @typescript-eslint/no-explicit-any */
  }

  async function saveDefaultTarget() {
    if (!formDefaultTarget.trim()) {
      errorMessage = m.mcp_sa_default_required();
      return;
    }
    savingDefault = true;
    errorMessage = "";
    successMessage = "";
    try {
      /* eslint-disable @typescript-eslint/no-explicit-any */
      const data = (await eneo.client.fetch(
        "/api/v1/mcp-servers/sso-defaults/" as any,
        {
          method: "put" as any,
          requestBody: {
            "application/json": { default_target: formDefaultTarget.trim() }
          } as any
        } as any
      )) as ServiceAccountState;
      account = data;
      editingDefault = false;
      successMessage = m.mcp_sa_default_saved();
    } catch (error: unknown) {
      const err = error as { message?: string; body?: { message?: string } };
      errorMessage = err?.body?.message ?? err?.message ?? m.mcp_sa_error_save();
    } finally {
      savingDefault = false;
    }
    /* eslint-enable @typescript-eslint/no-explicit-any */
  }

  async function clearDefaultTarget() {
    if (!confirm(m.mcp_sa_confirm_delete_default())) {
      return;
    }
    savingDefault = true;
    errorMessage = "";
    successMessage = "";
    try {
      /* eslint-disable @typescript-eslint/no-explicit-any */
      await eneo.client.fetch(
        "/api/v1/mcp-servers/sso-defaults/" as any,
        {
          method: "delete"
        } as any
      );
      account = { ...account, default_target: null };
      formDefaultTarget = "";
      successMessage = m.mcp_sa_default_deleted();
    } catch (error: unknown) {
      const err = error as { message?: string };
      errorMessage = err?.message ?? m.mcp_sa_error_delete();
    } finally {
      savingDefault = false;
    }
    /* eslint-enable @typescript-eslint/no-explicit-any */
  }

  async function clearCredentials() {
    if (!confirm(m.mcp_sa_confirm_delete())) {
      return;
    }
    saving = true;
    errorMessage = "";
    successMessage = "";
    try {
      /* eslint-disable @typescript-eslint/no-explicit-any */
      await eneo.client.fetch(
        "/api/v1/mcp-servers/service-account/" as any,
        {
          method: "delete"
        } as any
      );
      account = {
        ...account,
        configured: false,
        client_id: null,
        client_secret_preview: null
      };
      formClientId = "";
      formClientSecret = "";
      successMessage = m.mcp_sa_deleted();
    } catch (error: unknown) {
      const err = error as { message?: string };
      errorMessage = err?.message ?? m.mcp_sa_error_delete();
    } finally {
      saving = false;
    }
    /* eslint-enable @typescript-eslint/no-explicit-any */
  }

  onMount(() => {
    void load();
  });
</script>

<section class="border-default bg-primary rounded-xl border p-5 shadow-sm">
  <header class="mb-3 flex items-baseline justify-between gap-2">
    <h3 class="text-default flex items-center gap-2 text-base font-semibold">
      <Lock class="text-accent-default h-4 w-4" />
      {m.mcp_sa_title()}
    </h3>
    {#if account.configured}
      <span
        class="bg-positive-dimmer text-positive-stronger inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium"
      >
        <CheckCircle2 class="h-3 w-3" />
        {m.mcp_sa_configured()}
      </span>
    {:else}
      <span
        class="bg-secondary text-muted inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium"
      >
        {m.mcp_sa_not_configured()}
      </span>
    {/if}
  </header>

  <p class="text-muted mb-4 text-sm">
    {m.mcp_sa_description()}
  </p>

  {#if errorMessage}
    <div
      class="border-negative-default/30 bg-negative-dimmer text-negative-stronger mb-3 flex items-start gap-2 rounded-lg border px-3 py-2 text-sm"
      role="alert"
    >
      <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
      <div>{errorMessage}</div>
    </div>
  {/if}

  {#if successMessage}
    <div
      class="border-positive-default/30 bg-positive-dimmer text-positive-stronger mb-3 flex items-start gap-2 rounded-lg border px-3 py-2 text-sm"
      role="status"
    >
      <CheckCircle2 class="mt-0.5 h-4 w-4 shrink-0" />
      <div>{successMessage}</div>
    </div>
  {/if}

  {#if loading}
    <div class="text-muted flex items-center gap-2 text-sm">
      <RefreshCw class="h-4 w-4 animate-spin" />
      {m.mcp_sa_loading()}
    </div>
  {:else if !editing}
    <dl class="text-muted mb-4 grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
      <div>
        <dt class="text-xs font-medium tracking-wider uppercase">{m.mcp_sa_client_id_label()}</dt>
        <dd class="font-mono">{account.client_id ?? "—"}</dd>
      </div>
      <div>
        <dt class="text-xs font-medium tracking-wider uppercase">
          {m.mcp_sa_client_secret_label()}
        </dt>
        <dd class="font-mono">{account.client_secret_preview ?? "—"}</dd>
      </div>
    </dl>
    <div class="flex flex-wrap gap-2">
      <Button
        variant="primary"
        onclick={() => {
          editing = true;
          formClientId = account.client_id ?? "";
          formClientSecret = "";
          successMessage = "";
        }}
      >
        {account.configured ? m.mcp_sa_rotate() : m.mcp_sa_configure()}
      </Button>
      {#if account.configured}
        <Button variant="destructive" onclick={clearCredentials} disabled={saving}>
          {m.mcp_sa_delete()}
        </Button>
      {/if}
    </div>
  {:else}
    <div class="space-y-3">
      <div>
        <label for="mcp-sa-client-id" class="text-default mb-1.5 block text-sm font-medium">
          {m.mcp_sa_client_id_label()}
          <span class="text-negative-default" aria-hidden="true">*</span>
        </label>
        <input
          id="mcp-sa-client-id"
          type="text"
          bind:value={formClientId}
          autocomplete="off"
          placeholder={m.mcp_sa_client_id_placeholder()}
          class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 font-mono text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
        />
      </div>
      <div>
        <label for="mcp-sa-client-secret" class="text-default mb-1.5 block text-sm font-medium">
          {m.mcp_sa_client_secret_label()}
          <span class="text-negative-default" aria-hidden="true">*</span>
        </label>
        <input
          id="mcp-sa-client-secret"
          type="password"
          bind:value={formClientSecret}
          autocomplete="off"
          placeholder={account.configured
            ? m.mcp_sa_secret_placeholder_rotate()
            : m.mcp_sa_secret_placeholder_new()}
          class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 font-mono text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
        />
        <p class="text-muted mt-1.5 text-xs">
          {m.mcp_sa_secret_hint()}
        </p>
      </div>
      <div class="flex flex-wrap gap-2 pt-1">
        <Button variant="primary" onclick={save} disabled={saving}>
          {saving ? m.loading() : m.save()}
        </Button>
        <Button
          variant="outlined"
          onclick={() => {
            editing = false;
            formClientSecret = "";
            errorMessage = "";
          }}
          disabled={saving}
        >
          {m.cancel()}
        </Button>
      </div>
    </div>
  {/if}

  {#if !loading}
    <div class="border-default mt-5 border-t pt-4">
      <h4 class="text-default mb-2 text-sm font-semibold">{m.mcp_sa_default_target_title()}</h4>
      <p class="text-muted mb-3 text-xs">
        {m.mcp_sa_default_target_description()}
      </p>

      {#if !editingDefault}
        <dl class="text-muted mb-3 text-sm">
          <dt class="text-xs font-medium tracking-wider uppercase">{m.mcp_sa_value_label()}</dt>
          <dd class="font-mono break-all">{account.default_target ?? "—"}</dd>
        </dl>
        <div class="flex flex-wrap gap-2">
          <Button
            variant="primary"
            onclick={() => {
              editingDefault = true;
              formDefaultTarget = account.default_target ?? "";
              successMessage = "";
              errorMessage = "";
            }}
          >
            {account.default_target ? m.mcp_sa_change() : m.mcp_sa_set_default()}
          </Button>
          {#if account.default_target}
            <Button variant="destructive" onclick={clearDefaultTarget} disabled={savingDefault}>
              {m.mcp_sa_delete()}
            </Button>
          {/if}
        </div>
      {:else}
        <div class="space-y-3">
          <div>
            <label for="mcp-default-target" class="text-default mb-1.5 block text-sm font-medium">
              {m.mcp_auth_target_label()}
              <span class="text-negative-default" aria-hidden="true">*</span>
            </label>
            <input
              id="mcp-default-target"
              type="text"
              bind:value={formDefaultTarget}
              placeholder={m.mcp_sa_target_placeholder()}
              autocomplete="off"
              class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 font-mono text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
            />
          </div>
          <div class="flex flex-wrap gap-2 pt-1">
            <Button variant="primary" onclick={saveDefaultTarget} disabled={savingDefault}>
              {savingDefault ? m.loading() : m.save()}
            </Button>
            <Button
              variant="outlined"
              onclick={() => {
                editingDefault = false;
                formDefaultTarget = account.default_target ?? "";
                errorMessage = "";
              }}
              disabled={savingDefault}
            >
              {m.cancel()}
            </Button>
          </div>
        </div>
      {/if}
    </div>
  {/if}
</section>
