<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Dialog, Input, Select } from "@intric/ui";
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import { writable, type Writable } from "svelte/store";
  import type { ModelProviderPublic } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";

  export let openController: Writable<boolean>;
  /** If provided, dialog is in edit mode. If null/undefined, dialog is in add mode. */
  export let provider: ModelProviderPublic | null = null;

  const intric = getIntric();

  // Determine mode
  $: isEditMode = provider !== null;

  let providerName = "";
  let providerType = "hosted_vllm";
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
    { value: "hosted_vllm", label: m.provider_type_hosted_vllm() },
    { value: "openai", label: m.provider_type_openai() },
    { value: "azure", label: m.provider_type_azure() },
    { value: "anthropic", label: m.provider_type_anthropic() },
    { value: "gemini", label: m.provider_type_gemini() },
    { value: "cohere", label: m.provider_type_cohere() },
  ];

  const providerTypeStore = writable(providerTypes[0]);

  // Sync the store with providerType variable (only in add mode)
  $: if (!isEditMode && $providerTypeStore && $providerTypeStore.value) {
    const value = typeof $providerTypeStore.value === 'object'
      ? $providerTypeStore.value.value
      : $providerTypeStore.value;
    providerType = value;
  }

  // Initialize form when provider changes (for edit mode)
  $: if (provider) {
    initializeFromProvider(provider);
  }

  function initializeFromProvider(p: ModelProviderPublic) {
    providerName = p.name;
    providerType = p.provider_type;
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
      if (providerType === "azure") {
        error = m.endpoint_required_for_azure();
      } else if (providerType === "hosted_vllm") {
        error = m.endpoint_required_for_vllm();
      }
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

      // Close dialog
      openController.set(false);

      // Reset form
      resetForm();
    } catch (e: any) {
      error = e.message || (isEditMode ? m.failed_to_update_provider() : m.failed_to_create_provider());
    } finally {
      isSubmitting = false;
    }
  }

  function resetForm() {
    providerName = "";
    providerTypeStore.set(providerTypes[0]);
    providerType = "hosted_vllm";
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

  // Endpoint is required for Azure and self-hosted OpenAI-compatible
  $: requiresEndpoint = providerType === "azure" || providerType === "hosted_vllm";
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="large" form>
    <Dialog.Title>{isEditMode ? m.edit_provider() : m.add_model_provider()}</Dialog.Title>

    <Dialog.Section>
      <form on:submit|preventDefault={handleSubmit} class="flex flex-col gap-4 p-4">
        {#if error}
          <div class="border-error bg-error-dimmer text-error-stronger border-l-2 px-4 py-2 text-sm">
            {error}
          </div>
        {/if}

        <div class="flex flex-col gap-2">
          {#if isEditMode}
            <!-- In edit mode, show provider type as read-only -->
            <label class="text-sm font-medium">{m.provider_type()}</label>
            <div class="bg-muted rounded px-3 py-2 text-sm">
              {getProviderTypeLabel(providerType)}
            </div>
            <p class="text-muted-foreground text-xs">
              {m.provider_type_cannot_be_changed()}
            </p>
          {:else}
            <!-- In add mode, show dropdown -->
            <Select.Root customStore={providerTypeStore} class="border-b border-dimmer">
              <Select.Label>{m.provider_type()}</Select.Label>
              <Select.Trigger placeholder={m.select_provider_type()}></Select.Trigger>
              <Select.Options>
                {#each providerTypes as type}
                  <Select.Item value={type} label={type.label}>{type.label}</Select.Item>
                {/each}
              </Select.Options>
            </Select.Root>
          {/if}
        </div>

        <div class="flex flex-col gap-2">
          <label for="provider-name" class="text-sm font-medium">{m.provider_name()}</label>
          <Input.Text
            id="provider-name"
            bind:value={providerName}
            placeholder={m.provider_name_placeholder()}
            required
          />
          <p class="text-muted-foreground text-xs">
            {m.provider_name_hint()}
          </p>
        </div>

        <div class="flex flex-col gap-2">
          <label for="api-key" class="text-sm font-medium">{m.api_key()}</label>
          {#if isEditMode && provider?.masked_api_key && !isEditingApiKey}
            <!-- Show masked key with edit button -->
            <div class="flex items-center gap-2">
              <span class="bg-muted rounded px-3 py-2 text-sm font-mono">
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
            <!-- Show input field -->
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
                class="text-muted-foreground text-xs underline text-left"
                on:click={() => { isEditingApiKey = false; apiKey = ""; }}
              >
                {m.cancel_keep_current_key()} ({provider.masked_api_key})
              </button>
            {:else}
              <p class="text-muted-foreground text-xs">
                {m.will_be_encrypted()}
              </p>
            {/if}
          {/if}
        </div>

        <div class="flex flex-col gap-2">
          <label for="endpoint" class="text-sm font-medium">{m.endpoint_url()}</label>
          <Input.Text
            id="endpoint"
            bind:value={endpoint}
            placeholder={providerType === "azure"
              ? "https://your-resource.openai.azure.com"
              : providerType === "anthropic"
                ? "https://api.anthropic.com (default)"
                : "https://api.openai.com (default) or custom endpoint"}
            required={requiresEndpoint}
          />
          {#if providerType === "hosted_vllm"}
            <p class="text-muted-foreground text-xs">
              {m.endpoint_required_vllm()}
            </p>
          {:else if providerType === "openai"}
            <p class="text-muted-foreground text-xs">
              {m.endpoint_optional_openai()}
            </p>
          {:else if providerType === "azure"}
            <p class="text-muted-foreground text-xs">
              {m.endpoint_required_azure()}
            </p>
          {:else}
            <p class="text-muted-foreground text-xs">
              {m.endpoint_optional_default()}
            </p>
          {/if}
        </div>

        {#if providerType === "azure"}
          <div class="flex flex-col gap-2">
            <label for="api-version" class="text-sm font-medium">{m.api_version()}</label>
            <Input.Text
              id="api-version"
              bind:value={apiVersion}
              placeholder={m.api_version_placeholder()}
              required
            />
            <p class="text-muted-foreground text-xs">
              {m.api_version_required()}
            </p>
          </div>

          <div class="flex flex-col gap-2">
            <label for="deployment-name" class="text-sm font-medium">{m.deployment_name()}</label>
            <Input.Text
              id="deployment-name"
              bind:value={deploymentName}
              placeholder={m.deployment_name_placeholder()}
              required
            />
            <p class="text-muted-foreground text-xs">
              {m.deployment_name_required()}
            </p>
          </div>
        {/if}

        {#if isEditMode}
          <div class="flex items-center gap-3">
            <input
              type="checkbox"
              id="is-active"
              bind:checked={isActive}
              class="h-4 w-4 rounded border-gray-300"
            />
            <label for="is-active" class="text-sm font-medium">{m.provider_is_active()}</label>
          </div>
        {/if}
      </form>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button variant="outlined" on:click={handleCancel}>{m.cancel()}</Button>
      <Button
        variant="primary"
        on:click={handleSubmit}
        disabled={isSubmitting}
      >
        {#if isSubmitting}
          {isEditMode ? m.saving() : m.creating()}
        {:else}
          {isEditMode ? m.save_changes() : m.create_provider()}
        {/if}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
