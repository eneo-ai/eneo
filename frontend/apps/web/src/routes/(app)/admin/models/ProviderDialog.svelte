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

  const providerTypes = [
    { value: "hosted_vllm", label: "OpenAI Compatible (Self-Hosted)" },
    { value: "openai", label: "OpenAI" },
    { value: "azure", label: "Azure OpenAI" },
    { value: "anthropic", label: "Anthropic (Claude)" },
    { value: "gemini", label: "Google Gemini" },
    { value: "cohere", label: "Cohere" },
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
      error = "Provider name is required";
      return;
    }

    // API key is required only in add mode
    if (!isEditMode && !apiKey.trim()) {
      error = "API key is required";
      return;
    }

    if (requiresEndpoint && !endpoint.trim()) {
      if (providerType === "azure") {
        error = "Endpoint is required for Azure OpenAI";
      } else if (providerType === "hosted_vllm") {
        error = "Endpoint is required for self-hosted OpenAI-compatible providers";
      }
      return;
    }

    if (providerType === "azure") {
      if (!apiVersion.trim()) {
        error = "API Version is required for Azure OpenAI";
        return;
      }
      if (!deploymentName.trim()) {
        error = "Deployment Name is required for Azure OpenAI";
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
      error = e.message || (isEditMode ? "Failed to update provider" : "Failed to create provider");
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
    <Dialog.Title>{isEditMode ? "Edit Provider" : "Add Model Provider"}</Dialog.Title>

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
            <label class="text-sm font-medium">Provider Type</label>
            <div class="bg-muted rounded px-3 py-2 text-sm">
              {getProviderTypeLabel(providerType)}
            </div>
            <p class="text-muted-foreground text-xs">
              Provider type cannot be changed after creation
            </p>
          {:else}
            <!-- In add mode, show dropdown -->
            <Select.Root customStore={providerTypeStore} class="border-b border-dimmer">
              <Select.Label>Provider Type</Select.Label>
              <Select.Trigger placeholder="Select provider type"></Select.Trigger>
              <Select.Options>
                {#each providerTypes as type}
                  <Select.Item value={type} label={type.label}>{type.label}</Select.Item>
                {/each}
              </Select.Options>
            </Select.Root>
          {/if}
        </div>

        <div class="flex flex-col gap-2">
          <label for="provider-name" class="text-sm font-medium">Provider Name</label>
          <Input.Text
            id="provider-name"
            bind:value={providerName}
            placeholder="e.g., My Azure Instance, GDM"
            required
          />
          <p class="text-muted-foreground text-xs">
            A unique name to identify this provider instance
          </p>
        </div>

        <div class="flex flex-col gap-2">
          <label for="api-key" class="text-sm font-medium">API Key</label>
          <Input.Text
            id="api-key"
            type="password"
            bind:value={apiKey}
            placeholder={isEditMode ? "Leave empty to keep current key" : "Enter API key"}
            required={!isEditMode}
          />
          <p class="text-muted-foreground text-xs">
            {#if isEditMode}
              Leave empty to keep the current API key, or enter a new one to update it
            {:else}
              Will be encrypted before storage
            {/if}
          </p>
        </div>

        <div class="flex flex-col gap-2">
          <label for="endpoint" class="text-sm font-medium">Endpoint URL</label>
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
              <strong>Required</strong> for self-hosted. Common examples: vLLM (http://localhost:8000/v1), Ollama (http://localhost:11434/v1), llama.cpp (http://localhost:8080/v1)
            </p>
          {:else if providerType === "openai"}
            <p class="text-muted-foreground text-xs">
              Optional. Leave empty to use default OpenAI endpoint (https://api.openai.com/v1)
            </p>
          {:else if providerType === "azure"}
            <p class="text-muted-foreground text-xs">
              <strong>Required</strong>. Your Azure OpenAI resource endpoint
            </p>
          {:else}
            <p class="text-muted-foreground text-xs">
              Optional. Leave empty to use default endpoint for this provider
            </p>
          {/if}
        </div>

        {#if providerType === "azure"}
          <div class="flex flex-col gap-2">
            <label for="api-version" class="text-sm font-medium">API Version</label>
            <Input.Text
              id="api-version"
              bind:value={apiVersion}
              placeholder="e.g., 2024-02-15-preview"
              required
            />
            <p class="text-muted-foreground text-xs">
              <strong>Required</strong>. The Azure OpenAI API version to use
            </p>
          </div>

          <div class="flex flex-col gap-2">
            <label for="deployment-name" class="text-sm font-medium">Deployment Name</label>
            <Input.Text
              id="deployment-name"
              bind:value={deploymentName}
              placeholder="e.g., gpt-4-deployment"
              required
            />
            <p class="text-muted-foreground text-xs">
              <strong>Required</strong>. Your Azure OpenAI deployment name
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
            <label for="is-active" class="text-sm font-medium">Provider is active</label>
          </div>
        {/if}
      </form>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button variant="outlined" on:click={handleCancel}>Cancel</Button>
      <Button
        variant="primary"
        on:click={handleSubmit}
        disabled={isSubmitting}
      >
        {#if isSubmitting}
          {isEditMode ? "Saving..." : "Creating..."}
        {:else}
          {isEditMode ? "Save Changes" : "Create Provider"}
        {/if}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
