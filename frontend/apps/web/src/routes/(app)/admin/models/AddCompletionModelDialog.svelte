<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Dialog, Input, Select } from "@intric/ui";
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import { writable, type Writable } from "svelte/store";

  export let openController: Writable<boolean>;
  export let providers: any[] = [];

  const intric = getIntric();

  const CREATE_NEW_PROVIDER = "__CREATE_NEW__";

  let selectedProviderId = "";
  let showProviderForm = false;
  let modelName = "";
  let displayName = "";
  let tokenLimit = 128000;
  let vision = false;
  let reasoning = false;
  let isActive = true;
  let isDefault = false;
  let isSubmitting = false;
  let error: string | null = null;

  // Provider creation fields
  let providerName = "";
  let providerType = "openai";
  let apiKey = "";
  let endpoint = "";

  const providerTypes = [
    { value: "openai", label: "OpenAI Compatible (Self-Hosted)" },
    { value: "openai", label: "OpenAI" },
    { value: "azure", label: "Azure OpenAI" },
    { value: "anthropic", label: "Anthropic (Claude)" },
    { value: "gemini", label: "Google Gemini" },
    { value: "cohere", label: "Cohere" },
  ];

  // Create options for provider select - add "Create New" option
  $: providerOptions = [
    ...providers.map(p => ({ value: p.id, label: p.name })),
    { value: CREATE_NEW_PROVIDER, label: "+ Create New Provider" }
  ];
  $: providerStore = writable(providerOptions[0] || { value: "", label: "Select provider" });

  // Sync selected provider ID and show/hide provider form
  $: {
    if ($providerStore && $providerStore.value) {
      const value = typeof $providerStore.value === 'object' ? $providerStore.value.value : $providerStore.value;
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

      await intric.tenantModels.createCompletion({
        provider_id: actualProviderId,
        name: modelName,
        display_name: displayName,
        token_limit: tokenLimit,
        vision: vision,
        reasoning: reasoning,
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
      error = e.message || "Failed to create model";
    } finally {
      isSubmitting = false;
    }
  }

  function resetForm() {
    modelName = "";
    displayName = "";
    tokenLimit = 128000;
    vision = false;
    reasoning = false;
    isActive = true;
    isDefault = false;
    providerName = "";
    providerType = "openai";
    apiKey = "";
    endpoint = "";
    showProviderForm = false;
    providerStore.set(providerOptions[0]);
  }

  function handleCancel() {
    openController.set(false);
    resetForm();
    error = null;
  }

  $: requiresEndpoint = providerType === "azure";
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="large" form>
    <Dialog.Title>Add Completion Model</Dialog.Title>

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

        <!-- Provider Creation Form (shown when "+ Create New Provider" is selected) -->
        {#if showProviderForm}
          <div class="rounded-lg border border-dimmer bg-surface-dimmer p-4 flex flex-col gap-4">
            <h3 class="text-sm font-semibold">New Provider Details</h3>

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
              <label for="provider-type" class="text-sm font-medium">Provider Type</label>
              <select
                id="provider-type"
                bind:value={providerType}
                class="rounded border border-dimmer bg-surface px-3 py-2 text-sm"
              >
                {#each providerTypes as type}
                  <option value={type.value}>{type.label}</option>
                {/each}
              </select>
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
              {#if providerType === "openai"}
                <p class="text-muted-foreground text-xs">
                  For self-hosted (vLLM, Ollama, llama.cpp): Required. Common ports: 8000 (vLLM), 11434 (Ollama), 8080 (llama.cpp)
                </p>
              {:else if providerType === "azure"}
                <p class="text-muted-foreground text-xs">
                  Required. Your Azure OpenAI resource endpoint
                </p>
              {:else}
                <p class="text-muted-foreground text-xs">
                  Optional. Leave empty to use default endpoint
                </p>
              {/if}
            </div>
          </div>
        {/if}

        <!-- Model Fields (always shown) -->
        {#if !showProviderForm || (showProviderForm && providerName && apiKey)}
          <div class="flex flex-col gap-4">
            <div class="flex flex-col gap-2">
              <label for="model-name" class="text-sm font-medium">Model Identifier</label>
              <Input.Text
                id="model-name"
                bind:value={modelName}
                placeholder="e.g., gpt-4o, meta-llama/Meta-Llama-3-70B-Instruct"
                required
              />
              <p class="text-muted-foreground text-xs">
                Enter the exact model identifier from your provider (can contain slashes)
              </p>
            </div>

            <div class="flex flex-col gap-2">
              <label for="display-name" class="text-sm font-medium">Display Name</label>
              <Input.Text
                id="display-name"
                bind:value={displayName}
                placeholder="e.g., GPT-4 Optimized, Llama 3 70B"
                required
              />
              <p class="text-muted-foreground text-xs">
                User-friendly name shown in the UI
              </p>
            </div>

            <div class="flex flex-col gap-2">
              <label for="token-limit" class="text-sm font-medium">Token Limit</label>
              <Input.Text
                id="token-limit"
                type="number"
                bind:value={tokenLimit}
                min="1024"
                max="1000000"
                required
              />
              <p class="text-muted-foreground text-xs">
                Maximum context window in tokens
              </p>
            </div>

            <div class="flex gap-4">
              <label class="flex items-center gap-2 text-sm">
                <input type="checkbox" bind:checked={vision} />
                <span>Vision Support</span>
              </label>

              <label class="flex items-center gap-2 text-sm">
                <input type="checkbox" bind:checked={reasoning} />
                <span>Reasoning Support</span>
              </label>
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
