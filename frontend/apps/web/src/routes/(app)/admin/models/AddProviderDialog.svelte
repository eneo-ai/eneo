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

  const intric = getIntric();

  let providerName = "";
  let providerType = "hosted_vllm";
  let apiKey = "";
  let endpoint = "";
  let apiVersion = "";
  let deploymentName = "";
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

  // Sync the store with providerType variable
  $: {
    if ($providerTypeStore && $providerTypeStore.value) {
      const value = typeof $providerTypeStore.value === 'object'
        ? $providerTypeStore.value.value
        : $providerTypeStore.value;
      providerType = value;
    }
  }

  async function handleSubmit() {
    error = null;

    if (!providerName.trim()) {
      error = "Provider name is required";
      return;
    }

    if (!apiKey.trim()) {
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

      // Reload providers
      await invalidate("admin:model-providers:load");

      // Close dialog
      openController.set(false);

      // Reset form
      resetForm();
    } catch (e: any) {
      error = e.message || "Failed to create provider";
    } finally {
      isSubmitting = false;
    }
  }

  function resetForm() {
    providerName = "";
    providerTypeStore.set(providerTypes[0]);
    apiKey = "";
    endpoint = "";
    apiVersion = "";
    deploymentName = "";
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
    <Dialog.Title>Add Model Provider</Dialog.Title>

    <Dialog.Section>
      <form on:submit|preventDefault={handleSubmit} class="flex flex-col gap-4 p-4">
        {#if error}
          <div class="border-error bg-error-dimmer text-error-stronger border-l-2 px-4 py-2 text-sm">
            {error}
          </div>
        {/if}

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
      </form>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button variant="outlined" on:click={handleCancel}>Cancel</Button>
      <Button
        variant="primary"
        on:click={handleSubmit}
        disabled={isSubmitting}
      >
        {isSubmitting ? "Creating..." : "Create Provider"}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
