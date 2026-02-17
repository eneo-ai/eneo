<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Dialog, Input, Select } from "@intric/ui";
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import { writable, type Writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";
  import { TriangleAlert } from "lucide-svelte";

  export let openController: Writable<boolean>;
  export let providers: any[] = [];
  export let preSelectedProviderId: Writable<string | null> | undefined = undefined;

  const intric = getIntric();

  const CREATE_NEW_PROVIDER = "__CREATE_NEW__";

  let selectedProviderId = "";
  let showProviderForm = false;
  let modelName = "";
  let displayName = "";
  let family = "openai";
  let isActive = true;
  let isDefault = false;
  let isSubmitting = false;
  let error: string | null = null;

  // Provider creation fields
  let providerName = "";
  let providerType = "openai";
  let apiKey = "";
  let endpoint = "";
  let apiVersion = "";
  let deploymentName = "";

  const providerTypes = [
    { value: "openai", label: "OpenAI Compatible (Self-Hosted)" },
    { value: "openai", label: "OpenAI" },
    { value: "azure", label: "Azure OpenAI" },
    { value: "anthropic", label: "Anthropic (Claude)" },
    { value: "gemini", label: "Google Gemini" },
    { value: "cohere", label: "Cohere" },
  ];

  const modelFamilies = [
    { value: "openai", label: "OpenAI (Standard)" },
    { value: "e5", label: "E5 (HuggingFace)" },
  ];

  const providerTypeStore = writable(providerTypes[0]);
  const modelFamilyStore = writable(modelFamilies[0]);

  // Sync the store with providerType variable
  $: {
    if ($providerTypeStore && $providerTypeStore.value) {
      const value = typeof $providerTypeStore.value === 'object'
        ? $providerTypeStore.value.value
        : $providerTypeStore.value;
      providerType = value;
    }
  }

  // Sync the store with family variable
  $: {
    if ($modelFamilyStore && $modelFamilyStore.value) {
      const value = typeof $modelFamilyStore.value === 'object'
        ? $modelFamilyStore.value.value
        : $modelFamilyStore.value;
      family = value;
    }
  }

  // Create options for provider select - add "Create New" option
  $: providerOptions = [
    ...providers.map(p => ({ value: p.id, label: p.name })),
    { value: CREATE_NEW_PROVIDER, label: "+ Create New Provider" }
  ];

  // Store for selected provider - initialized once
  const providerStore = writable<{ value: string; label: string }>({ value: "", label: m.select_provider() });

  // Initialize provider selection when dialog opens
  $: if ($openController && providerOptions.length > 0) {
    const preselectedId = preSelectedProviderId ? $preSelectedProviderId : null;
    if (preselectedId) {
      const matchingProvider = providerOptions.find(p => p.value === preselectedId);
      if (matchingProvider) {
        providerStore.set(matchingProvider);
      }
    } else if ($providerStore.value === "") {
      // Only set default if no selection has been made
      providerStore.set(providerOptions[0]);
    }
  }

  // Sync selected provider ID and show/hide provider form
  $: {
    if ($providerStore && $providerStore.value) {
      const value = typeof $providerStore.value === 'object' ? ($providerStore.value as any).value : $providerStore.value;
      selectedProviderId = value;
      showProviderForm = value === CREATE_NEW_PROVIDER;
    }
  }

  async function createProvider() {
    if (!providerName.trim()) {
      throw new Error("Provider name is required");
    }
    if (!apiKey.trim()) {
      throw new Error("API key is required");
    }

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

    const result = await intric.modelProviders.create(providerData);
    return result.id;
  }

  async function handleSubmit() {
    error = null;

    try {
      let actualProviderId = selectedProviderId;

      // If creating a new provider, do that first
      if (showProviderForm) {
        isSubmitting = true;
        actualProviderId = await createProvider();

        // Reload providers
        await invalidate("admin:model-providers:load");
      }

      if (!actualProviderId || actualProviderId === CREATE_NEW_PROVIDER) {
        error = "Please select or create a provider";
        return;
      }

      if (!modelName.trim()) {
        error = "Model name is required";
        return;
      }

      if (!displayName.trim()) {
        error = "Display name is required";
        return;
      }

      isSubmitting = true;

      await intric.tenantModels.createEmbedding({
        provider_id: actualProviderId,
        name: modelName,
        display_name: displayName,
        family: family,
        is_active: isActive,
        is_default: isDefault,
      });

      // Invalidate to reload data
      await invalidate("admin:model-providers:load");

      // Close dialog
      openController.set(false);

      // Reset form
      resetForm();
    } catch (e: any) {
      error = e.message || "Failed to create embedding model";
    } finally {
      isSubmitting = false;
    }
  }

  function resetForm() {
    modelName = "";
    displayName = "";
    family = "openai";
    isActive = true;
    isDefault = false;
    providerName = "";
    providerType = "openai";
    providerTypeStore.set(providerTypes[0]);
    modelFamilyStore.set(modelFamilies[0]);
    apiKey = "";
    endpoint = "";
    apiVersion = "";
    deploymentName = "";
    showProviderForm = false;
    providerStore.set(providerOptions[0] || { value: "", label: m.select_provider() });
    preSelectedProviderId?.set(null);
  }

  function handleCancel() {
    openController.set(false);
    resetForm();
    error = null;
  }

  $: requiresEndpoint = providerType === "azure";

  // Dynamic provider capabilities from LiteLLM
  let capabilities: Record<string, { modes: string[], models: Record<string, string[]> }> = {};
  async function loadCapabilities() {
    try {
      capabilities = await intric.modelProviders.getCapabilities();
    } catch {
      // Silently fail — warning just won't show
    }
  }
  $: if ($openController) loadCapabilities();

  // Available embedding models for the selected provider
  $: availableModels = (capabilities[selectedProviderType]?.models?.embedding ?? []).map((m: any) => typeof m === "string" ? m : m.name) as string[];

  function selectModel(model: string) {
    modelName = model;
    if (!displayName) {
      displayName = model;
    }
  }

  $: selectedProviderType = (() => {
    if (showProviderForm) return providerType;
    const p = providers.find(p => p.id === selectedProviderId);
    return p?.provider_type ?? "";
  })();

  $: providerHasNoSupport = selectedProviderType !== ""
    && Object.keys(capabilities).length > 0
    && selectedProviderType in capabilities
    && !capabilities[selectedProviderType]?.modes?.includes("embedding");
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="large" form>
    <Dialog.Title>Add Embedding Model</Dialog.Title>

    <Dialog.Section>
      <form on:submit|preventDefault={handleSubmit} class="flex flex-col gap-4 p-4">
        {#if error}
          <div class="border-error bg-error-dimmer text-error-stronger border-l-2 px-4 py-2 text-sm">
            {error}
          </div>
        {/if}

        <!-- Provider Selection -->
        <div class="flex flex-col gap-2">
          <Select.Root customStore={providerStore} class="border-b border-dimmer">
            <Select.Label>Provider</Select.Label>
            <Select.Trigger placeholder="Select or create provider"></Select.Trigger>
            <Select.Options>
              {#each providerOptions as provider}
                <Select.Item value={provider} label={provider.label}>{provider.label}</Select.Item>
              {/each}
            </Select.Options>
          </Select.Root>
        </div>

        {#if providerHasNoSupport}
          <div class="flex items-start gap-3 rounded-lg border border-label-default bg-label-dimmer px-4 py-3 text-sm label-warning">
            <TriangleAlert class="h-5 w-5 flex-shrink-0 text-label-stronger mt-0.5" />
            <div>
              <p class="font-medium text-label-stronger">{m.provider_no_support_title({ providerType: selectedProviderType })}</p>
              <p class="text-label-default mt-0.5">{m.provider_no_support_description({ modelType: "embedding" })}</p>
            </div>
          </div>
        {/if}

        <!-- Provider Creation Form (shown when "+ Create New Provider" is selected) -->
        {#if showProviderForm}
          <div class="rounded-lg border border-dimmer bg-surface-dimmer p-4 flex flex-col gap-4">
            <h3 class="text-sm font-semibold">New Provider Details</h3>

            <div class="flex flex-col gap-2">
              <Select.Root customStore={providerTypeStore} class="border-b border-dimmer">
                <Select.Label>Provider Type</Select.Label>
                <Select.Trigger placeholder="Select provider type"></Select.Trigger>
                <Select.Options>
                  {#each providerTypes as type}
                    <Select.Item value={type} label={type.label}>{type.label}</Select.Item>
                  {/each}
                </Select.Options>
              </Select.Root>
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
                placeholder="Enter API key"
                required
              />
              <p class="text-muted-foreground text-xs">
                Will be encrypted before storage
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
              {#if providerType === "azure"}
                <p class="text-muted-foreground text-xs">
                  <strong>Required</strong>. Your Azure OpenAI resource endpoint
                </p>
              {:else}
                <p class="text-muted-foreground text-xs">
                  Optional. Leave empty to use default endpoint
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
                  placeholder="e.g., text-embedding-ada-002-deployment"
                  required
                />
                <p class="text-muted-foreground text-xs">
                  <strong>Required</strong>. Your Azure OpenAI deployment name
                </p>
              </div>
            {/if}
          </div>
        {/if}

        <!-- Model Fields (always shown) -->
        {#if !showProviderForm || (showProviderForm && providerName && apiKey)}
          <div class="flex flex-col gap-4">
            {#if availableModels.length > 0}
              <div class="flex flex-col gap-2">
                <span class="text-sm font-medium">{m.suggested_models()}</span>
                <div class="flex flex-wrap gap-2">
                  {#each availableModels as model}
                    <button
                      type="button"
                      class="rounded-full border px-3 py-1.5 text-sm transition-all duration-150
                        {modelName === model
                          ? 'border-accent-default bg-accent-dimmer text-accent-stronger'
                          : 'border-dimmer hover:border-accent-default hover:bg-accent-dimmer'}"
                      on:click={() => selectModel(model)}
                    >
                      {model}
                    </button>
                  {/each}
                </div>
              </div>
            {/if}

            <div class="flex flex-col gap-2">
              <label for="model-name" class="text-sm font-medium">Model Identifier</label>
              <Input.Text
                id="model-name"
                bind:value={modelName}
                placeholder="e.g., text-embedding-3-large, text-embedding-ada-002"
                required
              />
              <p class="text-muted-foreground text-xs">
                Enter the exact model identifier or select one above
              </p>
            </div>

            <div class="flex flex-col gap-2">
              <label for="display-name" class="text-sm font-medium">Display Name</label>
              <Input.Text
                id="display-name"
                bind:value={displayName}
                placeholder="e.g., OpenAI Embeddings Large, Ada 002"
                required
              />
              <p class="text-muted-foreground text-xs">
                User-friendly name shown in the UI
              </p>
            </div>

            <div class="flex flex-col gap-2">
              <Select.Root customStore={modelFamilyStore} class="border-b border-dimmer">
                <Select.Label>Model Family</Select.Label>
                <Select.Trigger placeholder="Select model family"></Select.Trigger>
                <Select.Options>
                  {#each modelFamilies as modelFamily}
                    <Select.Item value={modelFamily} label={modelFamily.label}>{modelFamily.label}</Select.Item>
                  {/each}
                </Select.Options>
              </Select.Root>
              <p class="text-muted-foreground text-xs">
                The embedding model family determines input format (e.g., E5 requires "passage:" prefix)
              </p>
            </div>

            <div class="flex gap-4">
              <label class="flex items-center gap-2 text-sm">
                <input type="checkbox" bind:checked={isActive} />
                <span>Enable in Organization</span>
              </label>

              <label class="flex items-center gap-2 text-sm">
                <input type="checkbox" bind:checked={isDefault} />
                <span>Set as Default</span>
              </label>
            </div>
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
        {isSubmitting ? (showProviderForm ? "Creating Provider & Model..." : "Creating Model...") : "Create"}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
