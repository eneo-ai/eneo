<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Edit an existing model provider. Provider creation now happens through the
  AddWizard's StepCredentials, so this dialog only handles edits.

  Field metadata (which fields, required, secret, in credentials/config) is
  read from the cached `/capabilities` endpoint via `modelProviderCapabilities`.
  Labels, placeholders and hints come from the same shared helpers as the
  wizard so the two surfaces stay in sync.
-->

<script lang="ts">
  import type { ModelProviderPublic } from "@intric/intric-js";
  import type { Writable } from "svelte/store";
  import { onMount } from "svelte";
  import { Loader2 } from "lucide-svelte";

  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { toastError } from "$lib/core/errors";

  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { Button } from "$lib/components/ui/button/index.js";

  import ProviderGlyph from "./components/ProviderGlyph.svelte";
  import {
    formatProviderLabel,
    formatFieldLabel,
    getFieldHint,
    getFieldPlaceholder,
    getModelProviderCapabilities,
    resolveProviderFields,
    type ModelProviderCapabilities,
    type ModelProviderFieldDef
  } from "./modelProviderCapabilities";

  let {
    openController,
    provider
  }: {
    openController: Writable<boolean>;
    provider: ModelProviderPublic | null;
  } = $props();

  const intric = getIntric();

  // --- Open-state bridge (Writable<boolean> ↔ runes) -------------------------
  let dialogOpen = $state(false);
  onMount(() => openController.subscribe((v) => (dialogOpen = v)));
  $effect(() => {
    openController.set(dialogOpen);
  });

  // --- Capabilities (lazy, cached) -------------------------------------------
  let capabilities = $state<ModelProviderCapabilities | null>(null);
  let capabilitiesLoading = $state(false);

  async function loadCapabilities() {
    if (capabilities || capabilitiesLoading) return;
    capabilitiesLoading = true;
    try {
      capabilities = await getModelProviderCapabilities(intric);
    } catch {
      // Silently fall back — `resolveProviderFields` returns sensible defaults.
    } finally {
      capabilitiesLoading = false;
    }
  }

  $effect(() => {
    if (dialogOpen) void loadCapabilities();
  });

  const fields: ModelProviderFieldDef[] = $derived(
    resolveProviderFields(capabilities, provider?.provider_type ?? "")
  );

  // --- Form state ------------------------------------------------------------
  let providerName = $state("");
  let isActive = $state(true);
  let isEditingApiKey = $state(false);
  let fieldValues = $state<Record<string, string>>({});

  let isSubmitting = $state(false);
  let error = $state<string | null>(null);

  // Re-seed every time the dialog opens for a particular provider. We seed on
  // the falling edge of dialogOpen too so a closed-then-reopened dialog
  // forgets unsaved edits — matches the EditModelDialog behaviour.
  let lastSeededFor: { id: string; open: boolean } | null = null;
  $effect(() => {
    if (!dialogOpen) {
      lastSeededFor = null;
      return;
    }
    if (!provider) return;
    if (lastSeededFor?.id === provider.id && lastSeededFor.open) return;

    providerName = provider.name;
    isActive = provider.is_active;
    isEditingApiKey = false;
    error = null;

    // Seed config fields. The api_key field intentionally starts empty —
    // the existing key is shown masked and only replaced if the user clicks
    // "Change" and types a new value.
    const next: Record<string, string> = { api_key: "" };
    if (provider.config) {
      for (const [key, val] of Object.entries(provider.config)) {
        next[key] = typeof val === "string" ? val : String(val ?? "");
      }
    }
    fieldValues = next;

    lastSeededFor = { id: provider.id, open: true };
  });

  // --- Submit ----------------------------------------------------------------

  function buildPayload(): {
    name: string;
    config: Record<string, string>;
    is_active: boolean;
    credentials?: Record<string, string>;
  } {
    const credentials: Record<string, string> = {};
    const config: Record<string, string> = {};

    for (const field of fields) {
      const value = (fieldValues[field.name] ?? "").trim();

      if (field.name === "api_key") {
        // Only include the API key when the user is actively editing it.
        if (!isEditingApiKey || !value) continue;
        credentials[field.name] = value;
        continue;
      }

      if (!value) continue;
      if (field.in === "credentials") credentials[field.name] = value;
      else config[field.name] = value;
    }

    const payload: ReturnType<typeof buildPayload> = {
      name: providerName,
      config,
      is_active: isActive
    };
    if (Object.keys(credentials).length > 0) payload.credentials = credentials;
    return payload;
  }

  async function handleSubmit() {
    if (!provider) return;
    error = null;

    if (!providerName.trim()) {
      error = m.provider_name_required();
      return;
    }

    isSubmitting = true;
    try {
      await intric.modelProviders.update({ id: provider.id }, buildPayload());
      await invalidate("admin:model-providers:load");
      toast.success(m.provider_updated_success());
      dialogOpen = false;
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : m.failed_to_update_provider();
      toastError(e, m.failed_to_update_provider());
    } finally {
      isSubmitting = false;
    }
  }

  function handleCancel() {
    dialogOpen = false;
  }
</script>

<Dialog.Root bind:open={dialogOpen}>
  <Dialog.Content class="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-2xl">
    <Dialog.Header class="px-6 pt-6 pb-2">
      <Dialog.Title>{m.edit_provider()}</Dialog.Title>
    </Dialog.Header>

    <form
      onsubmit={(event) => {
        event.preventDefault();
        void handleSubmit();
      }}
      class="flex min-h-0 flex-1 flex-col"
    >
      <div class="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-6 py-4">
        {#if error}
          <div
            class="border-destructive bg-destructive/10 text-destructive border-l-2 px-4 py-2 text-sm"
            role="alert"
          >
            {error}
          </div>
        {/if}

        {#if provider}
          <!-- Provider type — read-only in edit mode -->
          <Field.Field>
            <Field.Label>{m.provider_type()}</Field.Label>
            <div
              class="border-border bg-muted/40 flex items-center gap-3 rounded-lg border px-4 py-2.5"
            >
              <ProviderGlyph providerType={provider.provider_type} size="sm" />
              <span class="text-sm">{formatProviderLabel(provider.provider_type)}</span>
            </div>
          </Field.Field>

          <Field.Field>
            <Field.Label for="provider-name">{m.provider_name()}</Field.Label>
            <Input
              id="provider-name"
              bind:value={providerName}
              placeholder={m.provider_name_placeholder()}
              required
            />
            <Field.Description>{m.provider_name_hint()}</Field.Description>
          </Field.Field>

          {#each fields as field (field.name)}
            {#if field.name === "api_key"}
              <Field.Field>
                <Field.Label for="provider-{field.name}">
                  {formatFieldLabel(field.name)}
                </Field.Label>

                {#if provider.masked_api_key && !isEditingApiKey}
                  <div
                    class="border-border bg-muted/40 hover:border-foreground/30 flex items-center justify-between rounded-lg border px-4 py-2.5 transition-colors duration-150"
                  >
                    <span class="text-muted-foreground font-mono text-sm">
                      {provider.masked_api_key}
                    </span>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onclick={() => (isEditingApiKey = true)}
                    >
                      {m.change()}
                    </Button>
                  </div>
                {:else}
                  <Input
                    id="provider-{field.name}"
                    type="password"
                    bind:value={fieldValues[field.name]}
                    placeholder={getFieldPlaceholder(field.name, provider.provider_type)}
                    required={!provider.masked_api_key}
                  />
                  {#if provider.masked_api_key}
                    <button
                      type="button"
                      class="text-muted-foreground hover:text-primary text-left text-xs underline transition-colors"
                      onclick={() => {
                        isEditingApiKey = false;
                        fieldValues[field.name] = "";
                      }}
                    >
                      {m.cancel_keep_current_key()} ({provider.masked_api_key})
                    </button>
                  {:else}
                    {@const hint = getFieldHint(
                      field.name,
                      field.required,
                      provider.provider_type,
                      "edit"
                    )}
                    {#if hint}<Field.Description>{hint}</Field.Description>{/if}
                  {/if}
                {/if}
              </Field.Field>
            {:else}
              {@const hint = getFieldHint(
                field.name,
                field.required,
                provider.provider_type,
                "edit"
              )}
              <Field.Field>
                <Field.Label for="provider-{field.name}">
                  {formatFieldLabel(field.name)}
                  {#if !field.required}
                    <span class="text-muted-foreground ml-1 text-xs font-normal"
                      >({m.optional()})</span
                    >
                  {/if}
                </Field.Label>
                <Input
                  id="provider-{field.name}"
                  type={field.secret ? "password" : "text"}
                  bind:value={fieldValues[field.name]}
                  placeholder={getFieldPlaceholder(field.name, provider.provider_type)}
                  required={field.required}
                />
                {#if hint}<Field.Description>{hint}</Field.Description>{/if}
              </Field.Field>
            {/if}
          {/each}

          <Field.Field orientation="horizontal" class="border-border mt-2 border-t pt-4">
            <Switch
              id="provider-is-active"
              checked={isActive}
              onCheckedChange={(v) => (isActive = v)}
            />
            <Field.Label for="provider-is-active">{m.provider_is_active()}</Field.Label>
          </Field.Field>
        {/if}
      </div>

      <div class="border-border flex justify-end gap-2 border-t px-6 py-4">
        <Button type="button" variant="outline" onclick={handleCancel}>{m.cancel()}</Button>
        <Button type="submit" disabled={isSubmitting || capabilitiesLoading}>
          {#if isSubmitting}
            <Loader2 class="animate-spin" aria-hidden="true" />
            {m.saving()}
          {:else}
            {m.save_changes()}
          {/if}
        </Button>
      </div>
    </form>
  </Dialog.Content>
</Dialog.Root>
