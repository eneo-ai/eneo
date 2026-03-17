<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { Button, Dialog, Input, Select } from "@intric/ui";
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import { writable, type Writable } from "svelte/store";
  import type { ModelProviderPublic } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";
  import { Loader2 } from "lucide-svelte";
  import ProviderGlyph from "./components/ProviderGlyph.svelte";
  import { toast } from "$lib/components/toast";
  import { onMount } from "svelte";

  export let openController: Writable<boolean>;
  /** If provided, dialog is in edit mode. If null/undefined, dialog is in add mode. */
  export let provider: ModelProviderPublic | null = null;

  const intric = getIntric();

  // --- Capabilities ---
  interface FieldDef {
    name: string;
    required: boolean;
    secret: boolean;
    in: "credentials" | "config";
  }

  interface Capabilities {
    providers: Record<string, { modes: string[]; models: Record<string, any[]>; fields: FieldDef[] }>;
    default_fields: FieldDef[];
  }

  let capabilities: Capabilities | null = null;

  onMount(async () => {
    try {
      capabilities = await intric.modelProviders.getCapabilities() as Capabilities;
    } catch {
      // Silently fail — fall back to hardcoded defaults
    }
  });

  // Build provider type options from capabilities (or fallback)
  const fallbackProviderTypes = [
    { value: "openai", label: "OpenAI" },
    { value: "azure", label: "Azure OpenAI" },
    { value: "anthropic", label: "Anthropic" },
    { value: "gemini", label: "Google Gemini" },
    { value: "cohere", label: "Cohere" },
    { value: "mistral", label: "Mistral AI" },
    { value: "hosted_vllm", label: "vLLM" },
  ];

  function formatProviderName(type: string): string {
    const knownLabels: Record<string, string> = {
      openai: "OpenAI",
      azure: "Azure OpenAI",
      anthropic: "Anthropic",
      gemini: "Google Gemini",
      cohere: "Cohere",
      mistral: "Mistral AI",
      hosted_vllm: "vLLM",
    };
    return knownLabels[type] ?? type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }

  $: providerTypes = capabilities
    ? Object.keys(capabilities.providers)
        .map((type) => ({ value: type, label: formatProviderName(type) }))
        .sort((a, b) => a.label.localeCompare(b.label))
    : fallbackProviderTypes;

  // Get field definitions for the current provider type
  $: currentFields = (() => {
    if (!capabilities) return fallbackFields;
    const cap = capabilities.providers[providerType];
    return cap?.fields ?? capabilities.default_fields;
  })();

  // Fallback fields when capabilities haven't loaded
  const fallbackFields: FieldDef[] = [
    { name: "api_key", required: true, secret: true, in: "credentials" },
    { name: "endpoint", required: false, secret: false, in: "config" },
  ];

  // Determine mode
  $: isEditMode = provider !== null;

  let providerName = "";
  let providerType = "openai";
  let isActive = true;
  let isSubmitting = false;
  let error: string | null = null;
  let isEditingApiKey = false;

  // Dynamic field values — keyed by field name
  let fieldValues: Record<string, string> = {};

  const providerTypeStore = writable<{ value: string; label: string }>(fallbackProviderTypes[0]);

  // Sync the store with providerType variable (both add and edit modes)
  $: if ($providerTypeStore && $providerTypeStore.value) {
    providerType = $providerTypeStore.value;
  }

  // Reset field values when provider type changes (add mode only)
  $: if (!isEditMode) {
    fieldValues = {};
    for (const field of currentFields) {
      if (!(field.name in fieldValues)) {
        fieldValues[field.name] = "";
      }
    }
  }

  // Initialize form when provider changes (for edit mode)
  $: if (provider) {
    initializeFromProvider(provider);
  }

  function initializeFromProvider(p: ModelProviderPublic) {
    providerName = p.name;
    providerType = p.provider_type;
    isActive = p.is_active;
    isEditingApiKey = false;

    // Initialize field values from provider's credentials and config
    fieldValues = {};
    // API key is not returned — leave empty (user can update if needed)
    fieldValues["api_key"] = "";
    // Config fields
    if (p.config) {
      for (const [key, val] of Object.entries(p.config)) {
        fieldValues[key] = typeof val === "string" ? val : String(val ?? "");
      }
    }

    // Set the store to match the provider type (for display)
    const matchingType = providerTypes.find(t => t.value === p.provider_type);
    if (matchingType) {
      providerTypeStore.set(matchingType);
    }
  }

  function formatFieldLabel(name: string): string {
    const labels: Record<string, string> = {
      api_key: m.api_key(),
      endpoint: m.endpoint_url(),
      api_version: m.api_version(),
      deployment_name: m.deployment_name(),
    };
    return labels[name] ?? name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }

  function getFieldPlaceholder(name: string): string {
    const placeholders: Record<string, string> = {
      api_key: m.enter_api_key(),
      endpoint: providerType === "azure"
        ? "https://your-resource.openai.azure.com"
        : "https://api.example.com/v1",
      api_version: m.api_version_placeholder(),
      deployment_name: m.deployment_name_placeholder(),
    };
    return placeholders[name] ?? "";
  }

  function getFieldHint(name: string): string {
    if (name === "api_key" && !isEditMode) return m.will_be_encrypted();
    if (name === "endpoint") {
      if (providerType === "openai") return m.endpoint_optional_openai();
      if (providerType === "azure") return m.endpoint_required_azure();
      return m.endpoint_optional_default();
    }
    if (name === "api_version") return m.api_version_required();
    if (name === "deployment_name") return m.deployment_name_required();
    return "";
  }

  async function handleSubmit() {
    error = null;

    if (!providerName.trim()) {
      error = m.provider_name_required();
      return;
    }

    // In add mode, validate required fields
    if (!isEditMode) {
      for (const field of currentFields) {
        if (field.required && !(fieldValues[field.name] ?? "").trim()) {
          error = `${formatFieldLabel(field.name)} is required`;
          return;
        }
      }
    }

    // In edit mode, API key is only required if user is editing it
    if (!isEditMode && !(fieldValues["api_key"] ?? "").trim()) {
      error = m.api_key_required();
      return;
    }

    try {
      isSubmitting = true;

      // Build credentials and config from field values
      const credentials: Record<string, string> = {};
      const config: Record<string, string> = {};

      for (const field of currentFields) {
        const value = (fieldValues[field.name] ?? "").trim();
        if (field.name === "api_key") {
          // In edit mode, only include api_key if user provided a new one
          if (isEditMode && !isEditingApiKey) continue;
          if (value) credentials[field.name] = value;
        } else if (value) {
          if (field.in === "credentials") {
            credentials[field.name] = value;
          } else {
            config[field.name] = value;
          }
        }
      }

      if (isEditMode && provider) {
        // Update existing provider
        const updateData: any = {
          name: providerName,
          config,
          is_active: isActive,
        };

        if (Object.keys(credentials).length > 0) {
          updateData.credentials = credentials;
        }

        await intric.modelProviders.update({ id: provider.id }, updateData);
      } else {
        // Create new provider
        await intric.modelProviders.create({
          name: providerName,
          provider_type: providerType,
          credentials,
          config,
          is_active: true,
        });
      }

      // Reload providers
      await invalidate("admin:model-providers:load");

      // Show success toast
      toast.success(isEditMode ? m.provider_updated_success() : m.provider_created_success());

      // Close dialog
      openController.set(false);

      // Reset form
      resetForm();
    } catch (e: any) {
      error = e.message || (isEditMode ? m.failed_to_update_provider() : m.failed_to_create_provider());
      toast.error(isEditMode ? m.failed_to_update_provider() : m.failed_to_create_provider());
    } finally {
      isSubmitting = false;
    }
  }

  function resetForm() {
    providerName = "";
    providerTypeStore.set(providerTypes[0]);
    providerType = "openai";
    fieldValues = {};
    isActive = true;
    isEditingApiKey = false;
  }

  function handleCancel() {
    openController.set(false);
    resetForm();
    error = null;
  }
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="large" form>
    <Dialog.Title>{isEditMode ? m.edit_provider() : m.add_model_provider()}</Dialog.Title>

    <Dialog.Section>
      <form on:submit|preventDefault={handleSubmit} class="flex flex-col gap-4 p-4 pb-6">
        {#if error}
          <div class="border-negative-default bg-negative-dimmer text-negative-stronger border-l-2 px-4 py-2 text-sm rounded-r">
            {error}
          </div>
        {/if}

        <!-- Provider Type -->
        <div class="flex flex-col gap-2">
          <label class="text-sm font-medium text-secondary">{m.provider_type()}</label>

          {#if isEditMode}
            <!-- Read-only display in edit mode -->
            <div class="flex items-center gap-3 rounded-lg border border-dimmer bg-secondary px-4 py-2.5">
              <ProviderGlyph providerType={providerType} size="sm" />
              <span class="text-sm">{formatProviderName(providerType)}</span>
            </div>
          {:else}
            <!-- Custom trigger wrapper with glyph overlay -->
            <div class="provider-type-select">
              <!-- Glyph positioned inside the trigger visually, centered vertically -->
              <div class="absolute left-3 top-0 h-10 z-10 pointer-events-none flex items-center">
                <ProviderGlyph providerType={providerType} size="sm" />
              </div>

              <Select.Root customStore={providerTypeStore}>
                <Select.Trigger />
                <Select.Options>
                  {#each providerTypes as type}
                    <Select.Item value={type} label={type.label}>
                      <div class="flex items-center gap-3 py-0.5">
                        <ProviderGlyph providerType={type.value} size="sm" />
                        <span class="flex-1">{type.label}</span>
                      </div>
                    </Select.Item>
                  {/each}
                </Select.Options>
              </Select.Root>
            </div>
          {/if}
        </div>

        <!-- Provider Name -->
        <div class="flex flex-col gap-2">
          <label for="provider-name" class="text-sm font-medium text-secondary">{m.provider_name()}</label>
          <Input.Text
            id="provider-name"
            bind:value={providerName}
            placeholder={m.provider_name_placeholder()}
            required
          />
          <p class="text-muted-foreground text-xs mt-1">
            {m.provider_name_hint()}
          </p>
        </div>

        <!-- Dynamic Fields -->
        {#each currentFields as field (field.name)}
          {#if field.name === "api_key"}
            <!-- Special handling for API key: masked display in edit mode -->
            <div class="flex flex-col gap-2">
              <label for="field-{field.name}" class="text-sm font-medium text-secondary">{formatFieldLabel(field.name)}</label>
              {#if isEditMode && provider?.masked_api_key && !isEditingApiKey}
                <div class="flex items-center justify-between rounded-lg border border-dimmer bg-secondary px-4 py-3 transition-colors duration-150 hover:border-default">
                  <span class="font-mono text-sm text-muted">
                    {provider.masked_api_key}
                  </span>
                  <Button
                    variant="outlined"
                    size="sm"
                    on:click={() => isEditingApiKey = true}
                  >
                    {m.change()}
                  </Button>
                </div>
              {:else}
                <Input.Text
                  id="field-{field.name}"
                  type="password"
                  bind:value={fieldValues[field.name]}
                  placeholder={getFieldPlaceholder(field.name)}
                  required={!isEditMode || !provider?.masked_api_key}
                />
                {#if isEditMode && provider?.masked_api_key}
                  <button
                    type="button"
                    class="text-muted-foreground text-xs underline text-left hover:text-primary transition-colors"
                    on:click={() => { isEditingApiKey = false; fieldValues["api_key"] = ""; }}
                  >
                    {m.cancel_keep_current_key()} ({provider.masked_api_key})
                  </button>
                {:else}
                  {@const hint = getFieldHint(field.name)}
                  {#if hint}
                    <p class="text-muted-foreground text-xs mt-1">{hint}</p>
                  {/if}
                {/if}
              {/if}
            </div>
          {:else}
            {@const hint = getFieldHint(field.name)}
            <!-- Generic field rendering -->
            <div class="flex flex-col gap-2">
              <label for="field-{field.name}" class="text-sm font-medium text-secondary">
                {formatFieldLabel(field.name)}
                {#if !field.required}
                  <span class="text-muted font-normal text-xs ml-1">(optional)</span>
                {/if}
              </label>
              <Input.Text
                id="field-{field.name}"
                type={field.secret ? "password" : "text"}
                bind:value={fieldValues[field.name]}
                placeholder={getFieldPlaceholder(field.name)}
                required={field.required}
              />
              {#if hint}
                <p class="text-muted-foreground text-xs mt-1">{hint}</p>
              {/if}
            </div>
          {/if}
        {/each}

        <!-- Provider Active Toggle -->
        {#if isEditMode}
          <div class="border-t border-dimmer pt-5 mt-4">
            <Input.Switch bind:value={isActive}>
              <span class="text-sm font-medium">{m.provider_is_active()}</span>
            </Input.Switch>
          </div>
        {/if}

        <!-- Bottom spacer for scroll breathing room -->
        <div class="h-4" aria-hidden="true"></div>
      </form>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button variant="outlined" on:click={handleCancel}>{m.cancel()}</Button>
      <Button
        variant="primary"
        on:click={handleSubmit}
        disabled={isSubmitting}
        class="min-w-[120px]"
      >
        {#if isSubmitting}
          <Loader2 class="w-4 h-4 mr-2 animate-spin" />
          {isEditMode ? m.saving() : m.creating()}
        {:else}
          {isEditMode ? m.save_changes() : m.create_provider()}
        {/if}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<style>
  .provider-type-select {
    position: relative;
  }

  /* Target the button's first div child (the text container) to make room for glyph */
  .provider-type-select :global(button > div:first-child) {
    margin-left: 2rem;
  }
</style>
