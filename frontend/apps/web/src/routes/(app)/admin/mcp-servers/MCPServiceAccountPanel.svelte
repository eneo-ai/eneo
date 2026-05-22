<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import { getIntric } from "$lib/core/Intric";
  import { Button } from "@intric/ui";
  import { Lock, RefreshCw, AlertCircle, CheckCircle2 } from "lucide-svelte";

  type ServiceAccountState = {
    configured: boolean;
    client_id: string | null;
    client_secret_preview: string | null;
    default_target: string | null;
  };

  const intric = getIntric();

  let state = $state<ServiceAccountState>({
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
      const data = (await intric.client.fetch(
        "/api/v1/mcp-servers/service-account/" as any,
        { method: "get" } as any
      )) as ServiceAccountState;
      state = data;
      formClientId = data.client_id ?? "";
      formDefaultTarget = data.default_target ?? "";
    } catch (error: unknown) {
      const err = error as { message?: string };
      errorMessage = err?.message ?? "Kunde inte hämta tjänstkontot.";
    } finally {
      loading = false;
    }
    /* eslint-enable @typescript-eslint/no-explicit-any */
  }

  async function save() {
    if (!formClientId.trim() || !formClientSecret.trim()) {
      errorMessage = "Både client_id och client_secret krävs.";
      return;
    }
    saving = true;
    errorMessage = "";
    successMessage = "";
    try {
      /* eslint-disable @typescript-eslint/no-explicit-any */
      const data = (await intric.client.fetch(
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
      state = data;
      editing = false;
      formClientSecret = "";
      successMessage = "Tjänstkontot uppdaterades.";
    } catch (error: unknown) {
      const err = error as { message?: string; body?: { message?: string } };
      errorMessage = err?.body?.message ?? err?.message ?? "Kunde inte spara.";
    } finally {
      saving = false;
    }
    /* eslint-enable @typescript-eslint/no-explicit-any */
  }

  async function saveDefaultTarget() {
    if (!formDefaultTarget.trim()) {
      errorMessage = "Standard audience/scope krävs.";
      return;
    }
    savingDefault = true;
    errorMessage = "";
    successMessage = "";
    try {
      /* eslint-disable @typescript-eslint/no-explicit-any */
      const data = (await intric.client.fetch(
        "/api/v1/mcp-servers/sso-defaults/" as any,
        {
          method: "put" as any,
          requestBody: {
            "application/json": { default_target: formDefaultTarget.trim() }
          } as any
        } as any
      )) as ServiceAccountState;
      state = data;
      editingDefault = false;
      successMessage = "Standardvärde uppdaterades.";
    } catch (error: unknown) {
      const err = error as { message?: string; body?: { message?: string } };
      errorMessage = err?.body?.message ?? err?.message ?? "Kunde inte spara.";
    } finally {
      savingDefault = false;
    }
    /* eslint-enable @typescript-eslint/no-explicit-any */
  }

  async function clearDefaultTarget() {
    if (
      !confirm(
        "Ta bort standard audience/scope? SSO-servrar utan egen override " +
          "faller tillbaka till sin egen URL (Keycloak) eller misslyckas (Entra)."
      )
    ) {
      return;
    }
    savingDefault = true;
    errorMessage = "";
    successMessage = "";
    try {
      /* eslint-disable @typescript-eslint/no-explicit-any */
      await intric.client.fetch(
        "/api/v1/mcp-servers/sso-defaults/" as any,
        {
          method: "delete"
        } as any
      );
      state = { ...state, default_target: null };
      formDefaultTarget = "";
      successMessage = "Standardvärde raderades.";
    } catch (error: unknown) {
      const err = error as { message?: string };
      errorMessage = err?.message ?? "Kunde inte radera standardvärdet.";
    } finally {
      savingDefault = false;
    }
    /* eslint-enable @typescript-eslint/no-explicit-any */
  }

  async function clearCredentials() {
    if (
      !confirm(
        "Ta bort MCP-tjänstkontot? Per-tenant-flöden slutar fungera tills nya uppgifter sätts."
      )
    ) {
      return;
    }
    saving = true;
    errorMessage = "";
    successMessage = "";
    try {
      /* eslint-disable @typescript-eslint/no-explicit-any */
      await intric.client.fetch(
        "/api/v1/mcp-servers/service-account/" as any,
        {
          method: "delete"
        } as any
      );
      state = {
        ...state,
        configured: false,
        client_id: null,
        client_secret_preview: null
      };
      formClientId = "";
      formClientSecret = "";
      successMessage = "Tjänstkontot raderades.";
    } catch (error: unknown) {
      const err = error as { message?: string };
      errorMessage = err?.message ?? "Kunde inte radera tjänstkontot.";
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
      MCP-tjänstkonto (per-tenant)
    </h3>
    {#if state.configured}
      <span
        class="bg-positive-dimmer text-positive-stronger inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium"
      >
        <CheckCircle2 class="h-3 w-3" />
        Konfigurerat
      </span>
    {:else}
      <span
        class="bg-secondary text-muted inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium"
      >
        Ej konfigurerat
      </span>
    {/if}
  </header>

  <p class="text-muted mb-4 text-sm">
    Klienten som ska användas vid <span class="font-mono">client_credentials</span>-flödet mot
    organisationens IdP för MCP-servrar med <span class="font-mono">auth_scope=per_tenant</span>.
    Hemligheten lagras krypterad (Fernet) i tenant.federation_config.
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
      Hämtar konfiguration...
    </div>
  {:else if !editing}
    <dl class="text-muted mb-4 grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
      <div>
        <dt class="text-xs font-medium tracking-wider uppercase">client_id</dt>
        <dd class="font-mono">{state.client_id ?? "—"}</dd>
      </div>
      <div>
        <dt class="text-xs font-medium tracking-wider uppercase">client_secret</dt>
        <dd class="font-mono">{state.client_secret_preview ?? "—"}</dd>
      </div>
    </dl>
    <div class="flex flex-wrap gap-2">
      <Button
        variant="primary"
        onclick={() => {
          editing = true;
          formClientId = state.client_id ?? "";
          formClientSecret = "";
          successMessage = "";
        }}
      >
        {state.configured ? "Rotera uppgifter" : "Konfigurera"}
      </Button>
      {#if state.configured}
        <Button variant="destructive" onclick={clearCredentials} disabled={saving}>Radera</Button>
      {/if}
    </div>
  {:else}
    <div class="space-y-3">
      <div>
        <label for="mcp-sa-client-id" class="text-default mb-1.5 block text-sm font-medium">
          client_id
          <span class="text-negative-default" aria-hidden="true">*</span>
        </label>
        <input
          id="mcp-sa-client-id"
          type="text"
          bind:value={formClientId}
          autocomplete="off"
          placeholder="eneo-mcp-svc"
          class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 font-mono text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
        />
      </div>
      <div>
        <label for="mcp-sa-client-secret" class="text-default mb-1.5 block text-sm font-medium">
          client_secret
          <span class="text-negative-default" aria-hidden="true">*</span>
        </label>
        <input
          id="mcp-sa-client-secret"
          type="password"
          bind:value={formClientSecret}
          autocomplete="off"
          placeholder={state.configured
            ? "Ange ny hemlighet för att rotera"
            : "Ange klient-hemligheten"}
          class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 font-mono text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
        />
        <p class="text-muted mt-1.5 text-xs">
          Lagras krypterad (Fernet). Den tidigare hemligheten ersätts utan möjlighet att återställa.
        </p>
      </div>
      <div class="flex flex-wrap gap-2 pt-1">
        <Button variant="primary" onclick={save} disabled={saving}>
          {saving ? "Sparar..." : "Spara"}
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
          Avbryt
        </Button>
      </div>
    </div>
  {/if}

  {#if !loading}
    <div class="border-default mt-5 border-t pt-4">
      <h4 class="text-default mb-2 text-sm font-semibold">Standard audience / scope</h4>
      <p class="text-muted mb-3 text-xs">
        Värdet som alla SSO-MCP-servrar utan egen override ärver. Sätt en gång här så slipper du
        konfigurera per server. Keycloak: använd en gemensam audience (t.ex. <span class="font-mono"
          >eneo-mcp</span
        >). Entra: API-scope (t.ex.
        <span class="font-mono">api://&lt;app-id&gt;/.default</span>).
      </p>

      {#if !editingDefault}
        <dl class="text-muted mb-3 text-sm">
          <dt class="text-xs font-medium tracking-wider uppercase">Värde</dt>
          <dd class="font-mono break-all">{state.default_target ?? "—"}</dd>
        </dl>
        <div class="flex flex-wrap gap-2">
          <Button
            variant="primary"
            onclick={() => {
              editingDefault = true;
              formDefaultTarget = state.default_target ?? "";
              successMessage = "";
              errorMessage = "";
            }}
          >
            {state.default_target ? "Ändra" : "Sätt standardvärde"}
          </Button>
          {#if state.default_target}
            <Button variant="destructive" onclick={clearDefaultTarget} disabled={savingDefault}>
              Radera
            </Button>
          {/if}
        </div>
      {:else}
        <div class="space-y-3">
          <div>
            <label for="mcp-default-target" class="text-default mb-1.5 block text-sm font-medium">
              Audience / scope
              <span class="text-negative-default" aria-hidden="true">*</span>
            </label>
            <input
              id="mcp-default-target"
              type="text"
              bind:value={formDefaultTarget}
              placeholder="eneo-mcp  eller  api://abc/.default"
              autocomplete="off"
              class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 font-mono text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
            />
          </div>
          <div class="flex flex-wrap gap-2 pt-1">
            <Button variant="primary" onclick={saveDefaultTarget} disabled={savingDefault}>
              {savingDefault ? "Sparar..." : "Spara"}
            </Button>
            <Button
              variant="outlined"
              onclick={() => {
                editingDefault = false;
                formDefaultTarget = state.default_target ?? "";
                errorMessage = "";
              }}
              disabled={savingDefault}
            >
              Avbryt
            </Button>
          </div>
        </div>
      {/if}
    </div>
  {/if}
</section>
