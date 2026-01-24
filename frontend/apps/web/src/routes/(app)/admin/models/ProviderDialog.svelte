<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { Button, Dialog, Input, Select } from "@intric/ui";
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import { writable, type Writable } from "svelte/store";
  import type { ModelProviderPublic } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";
  import { Loader2, AlertTriangle } from "lucide-svelte";
  import ProviderGlyph from "./components/ProviderGlyph.svelte";
  import { toast } from "$lib/components/toast";

  export let openController: Writable<boolean>;
  /** If provided, dialog is in edit mode. If null/undefined, dialog is in add mode. */
  export let provider: ModelProviderPublic | null = null;

  const intric = getIntric();

  // Determine mode
  $: isEditMode = provider !== null;

  let providerName = "";
  let providerType = "openai";
  let originalProviderType = "openai"; // Track original for change detection
  let apiKey = "";
  let endpoint = "";
  let apiVersion = "";
  let deploymentName = "";
  let isActive = true;
  let isSubmitting = false;
  let error: string | null = null;
  let isEditingApiKey = false;

  // Provider type options with i18n labels
  const providerTypes = [
    { value: "openai", label: m.provider_type_openai() },
    { value: "azure", label: m.provider_type_azure() },
    { value: "anthropic", label: m.provider_type_anthropic() },
    { value: "gemini", label: m.provider_type_gemini() },
    { value: "cohere", label: m.provider_type_cohere() },
  ];

  const providerTypeStore = writable(providerTypes[0]);

  // Sync the store with providerType variable (both add and edit modes)
  $: if ($providerTypeStore && $providerTypeStore.value) {
    const value = typeof $providerTypeStore.value === 'object'
      ? $providerTypeStore.value.value
      : $providerTypeStore.value;
    providerType = value;
  }

  // Check if provider type has changed from original
  $: hasProviderTypeChanged = isEditMode && providerType !== originalProviderType;

  // Initialize form when provider changes (for edit mode)
  $: if (provider) {
    initializeFromProvider(provider);
  }

  function initializeFromProvider(p: ModelProviderPublic) {
    providerName = p.name;
    providerType = p.provider_type;
    originalProviderType = p.provider_type; // Store original for change detection
    isActive = p.is_active;
    // API key is not returned from server - leave empty (user can update if needed)
    apiKey = "";
    // Config fields
    endpoint = p.config?.endpoint || "";
    apiVersion = p.config?.api_version || "";
    deploymentName = p.config?.deployment_name || "";

    // Set the store to match the provider type (for display)
    const matchingType = providerTypes.find(t => t.value === p.provider_type);
    if (matchingType) {
      providerTypeStore.set(matchingType);
    }
  }

  function getProviderTypeLabel(type: string): string {
    return providerTypes.find(t => t.value === type)?.label || type;
  }

  async function handleSubmit() {
    error = null;

    if (!providerName.trim()) {
      error = m.provider_name_required();
      return;
    }

    // API key is required only in add mode
    if (!isEditMode && !apiKey.trim()) {
      error = m.api_key_required();
      return;
    }

    if (requiresEndpoint && !endpoint.trim()) {
      error = m.endpoint_required_for_azure();
      return;
    }

    if (providerType === "azure") {
      if (!apiVersion.trim()) {
        error = m.api_version_required_for_azure();
        return;
      }
      if (!deploymentName.trim()) {
        error = m.deployment_name_required_for_azure();
        return;
      }
    }

    try {
      isSubmitting = true;

      if (isEditMode && provider) {
        // Update existing provider
        const updateData: any = {
          name: providerName,
          config: {},
          is_active: isActive
        };

        // Include provider_type if it has changed
        if (hasProviderTypeChanged) {
          updateData.provider_type = providerType;
        }

        // Only include credentials if user provided a new API key
        if (apiKey.trim()) {
          updateData.credentials = { api_key: apiKey };
        }

        // Add endpoint to config if provided
        if (endpoint.trim()) {
          updateData.config.endpoint = endpoint;
        }

        // Add Azure-specific fields to config
        if (providerType === "azure") {
          if (apiVersion.trim()) {
            updateData.config.api_version = apiVersion;
          }
          if (deploymentName.trim()) {
            updateData.config.deployment_name = deploymentName;
          }
        }

        await intric.modelProviders.update({ id: provider.id }, updateData);
      } else {
        // Create new provider
        const providerData: any = {
          name: providerName,
          provider_type: providerType,
          credentials: { api_key: apiKey },
          config: {},
          is_active: true
        };

        // Add endpoint to config if provided
        if (endpoint.trim()) {
          providerData.config.endpoint = endpoint;
        }

        // Add Azure-specific fields to config
        if (providerType === "azure") {
          if (apiVersion.trim()) {
            providerData.config.api_version = apiVersion;
          }
          if (deploymentName.trim()) {
            providerData.config.deployment_name = deploymentName;
          }
        }

        await intric.modelProviders.create(providerData);
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
    originalProviderType = "openai";
    apiKey = "";
    endpoint = "";
    apiVersion = "";
    deploymentName = "";
    isActive = true;
    isEditingApiKey = false;
  }

  function handleCancel() {
    openController.set(false);
    resetForm();
    error = null;
  }

  // Endpoint is required only for Azure
  $: requiresEndpoint = providerType === "azure";
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

          <!-- Custom trigger wrapper with glyph overlay -->
          <div class="provider-type-select">
            <!-- Glyph positioned inside the trigger visually, centered vertically -->
            <div class="absolute left-3 top-0 bottom-0 z-10 pointer-events-none flex items-center">
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

          <!-- Contextual warning - only shows when type differs from original in edit mode -->
          {#if hasProviderTypeChanged}
            <div class="flex items-start gap-2.5 px-3 py-2.5 rounded-md bg-warning-dimmer border border-warning-default/20 transition-all duration-200">
              <AlertTriangle class="w-4 h-4 text-warning-default flex-shrink-0 mt-px" />
              <p class="text-xs text-warning-default leading-relaxed">
                {m.provider_type_change_warning()}
              </p>
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

        <!-- API Key -->
        <div class="flex flex-col gap-2">
          <label for="api-key" class="text-sm font-medium text-secondary">{m.api_key()}</label>
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
              id="api-key"
              type="password"
              bind:value={apiKey}
              placeholder={m.enter_api_key()}
              required={!isEditMode || !provider?.masked_api_key}
            />
            {#if isEditMode && provider?.masked_api_key}
              <button
                type="button"
                class="text-muted-foreground text-xs underline text-left hover:text-primary transition-colors"
                on:click={() => { isEditingApiKey = false; apiKey = ""; }}
              >
                {m.cancel_keep_current_key()} ({provider.masked_api_key})
              </button>
            {:else}
              <p class="text-muted-foreground text-xs mt-1">
                {m.will_be_encrypted()}
              </p>
            {/if}
          {/if}
        </div>

        <!-- Endpoint URL -->
        <div class="flex flex-col gap-2">
          <label for="endpoint" class="text-sm font-medium text-secondary">{m.endpoint_url()}</label>
          <Input.Text
            id="endpoint"
            bind:value={endpoint}
            placeholder={providerType === "azure"
              ? "https://your-resource.openai.azure.com"
              : "https://api.openai.com/v1 (default) or custom endpoint"}
            required={requiresEndpoint}
          />
          {#if providerType === "openai"}
            <p class="text-muted-foreground text-xs mt-1">
              {m.endpoint_optional_openai()}
            </p>
          {:else if providerType === "azure"}
            <p class="text-muted-foreground text-xs mt-1">
              {m.endpoint_required_azure()}
            </p>
          {:else}
            <p class="text-muted-foreground text-xs mt-1">
              {m.endpoint_optional_default()}
            </p>
          {/if}
        </div>

        <!-- Azure-specific fields -->
        {#if providerType === "azure"}
          <div class="flex flex-col gap-2">
            <label for="api-version" class="text-sm font-medium text-secondary">{m.api_version()}</label>
            <Input.Text
              id="api-version"
              bind:value={apiVersion}
              placeholder={m.api_version_placeholder()}
              required
            />
            <p class="text-muted-foreground text-xs mt-1">
              {m.api_version_required()}
            </p>
          </div>

          <div class="flex flex-col gap-2">
            <label for="deployment-name" class="text-sm font-medium text-secondary">{m.deployment_name()}</label>
            <Input.Text
              id="deployment-name"
              bind:value={deploymentName}
              placeholder={m.deployment_name_placeholder()}
              required
            />
            <p class="text-muted-foreground text-xs mt-1">
              {m.deployment_name_required()}
            </p>
          </div>
        {/if}

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
