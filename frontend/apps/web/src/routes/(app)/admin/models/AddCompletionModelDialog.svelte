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

  export let openController: Writable<boolean>;
  export let providers: any[] = [];
  export let preSelectedProviderId: Writable<string | null> | undefined = undefined;

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

  $: providerTypes = [
    { value: "openai", label: "OpenAI" },
    { value: "azure", label: "Azure OpenAI" },
    { value: "anthropic", label: "Anthropic" },
    { value: "gemini", label: "Google Gemini" },
    { value: "cohere", label: "Cohere" },
    { value: "mistral", label: "Mistral AI" },
    { value: "hosted_vllm", label: "vLLM" },
  ];

  // Create options for provider select - add "Create New" option
  $: providerOptions = [
    ...providers.map(p => ({ value: p.id, label: p.name })),
    { value: CREATE_NEW_PROVIDER, label: m.create_new_provider() }
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
      throw new Error(m.provider_name_required());
    }
    if (!apiKey.trim()) {
      throw new Error(m.api_key_required());
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
        error = m.please_select_or_create_provider();
        return;
      }

      if (!modelName.trim()) {
        error = m.model_name_required();
        return;
      }

      if (!displayName.trim()) {
        error = m.display_name_required();
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
      error = e.message || m.failed_to_create_model();
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
    providerStore.set(providerOptions[0] || { value: "", label: m.select_provider() });
    preSelectedProviderId?.set(null);
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
    <Dialog.Title>{m.add_completion_model()}</Dialog.Title>

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
            <Select.Label>{m.provider()}</Select.Label>
            <Select.Trigger placeholder={m.select_or_create_provider()}></Select.Trigger>
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
            <h3 class="text-sm font-semibold">{m.new_provider_details()}</h3>

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
              <label for="provider-type" class="text-sm font-medium">{m.provider_type()}</label>
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
              <label for="api-key" class="text-sm font-medium">{m.api_key()}</label>
              <Input.Text
                id="api-key"
                type="password"
                bind:value={apiKey}
                placeholder={m.enter_api_key()}
                required
              />
              <p class="text-muted-foreground text-xs">
                {m.will_be_encrypted()}
              </p>
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
              {#if providerType === "openai"}
                <p class="text-muted-foreground text-xs">
                  {m.endpoint_hint_openai()}
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
          </div>
        {/if}

        <!-- Model Fields (always shown) -->
        {#if !showProviderForm || (showProviderForm && providerName && apiKey)}
          <div class="flex flex-col gap-4">
            <div class="flex flex-col gap-2">
              <label for="model-name" class="text-sm font-medium">{m.model_identifier()}</label>
              <Input.Text
                id="model-name"
                bind:value={modelName}
                placeholder={m.model_identifier_placeholder_completion()}
                required
              />
              <p class="text-muted-foreground text-xs">
                {m.model_identifier_hint()}
              </p>
            </div>

            <div class="flex flex-col gap-2">
              <label for="display-name" class="text-sm font-medium">{m.display_name()}</label>
              <Input.Text
                id="display-name"
                bind:value={displayName}
                placeholder={m.display_name_placeholder_completion()}
                required
              />
              <p class="text-muted-foreground text-xs">
                {m.display_name_hint()}
              </p>
            </div>

            <div class="flex flex-col gap-2">
              <label for="token-limit" class="text-sm font-medium">{m.token_limit()}</label>
              <Input.Text
                id="token-limit"
                type="number"
                bind:value={tokenLimit}
                min="1024"
                max="1000000"
                required
              />
              <p class="text-muted-foreground text-xs">
                {m.token_limit_hint()}
              </p>
            </div>

            <div class="flex gap-4">
              <label class="flex items-center gap-2 text-sm">
                <input type="checkbox" bind:checked={vision} />
                <span>{m.vision_support()}</span>
              </label>

              <label class="flex items-center gap-2 text-sm">
                <input type="checkbox" bind:checked={reasoning} />
                <span>{m.reasoning_support()}</span>
              </label>
            </div>

            <div class="flex gap-4">
              <label class="flex items-center gap-2 text-sm">
                <input type="checkbox" bind:checked={isActive} />
                <span>{m.enable_in_organization()}</span>
              </label>

              <label class="flex items-center gap-2 text-sm">
                <input type="checkbox" bind:checked={isDefault} />
                <span>{m.set_as_default()}</span>
              </label>
            </div>
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
        {isSubmitting ? (showProviderForm ? m.creating_provider_and_model() : m.creating_model()) : m.create()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
