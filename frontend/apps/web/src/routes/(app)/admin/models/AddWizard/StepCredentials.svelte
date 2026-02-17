<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { Button, Input } from "@intric/ui";
  import { createEventDispatcher, onMount } from "svelte";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import ProviderGlyph from "../components/ProviderGlyph.svelte";
  import { ArrowLeft, Loader2 } from "lucide-svelte";

  // Auto-focus first input on mount and prefill provider name
  onMount(() => {
    if (!providerName) {
      providerName = providerLabels[providerType] ??
        providerType.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    }
    setTimeout(() => {
      const input = document.getElementById("cred-provider-name") as HTMLInputElement;
      input?.focus();
      input?.select();
    }, 100);
  });

  export let providerType: string;
  export let providerName: string = "";
  export let apiKey: string = "";
  export let endpoint: string = "";
  export let apiVersion: string = "";
  export let deploymentName: string = "";

  const dispatch = createEventDispatcher<{
    complete: { providerId: string };
    back: void;
  }>();

  const intric = getIntric();

  // Provider type display info
  const providerLabels: Record<string, string> = {
    openai: "OpenAI",
    azure: "Azure OpenAI",
    anthropic: "Anthropic",
    gemini: "Google Gemini",
    cohere: "Cohere",
    mistral: "Mistral AI",
    hosted_vllm: "vLLM"
  };

  // State
  let isSubmitting = false;
  let error: string | null = null;

  // Validation
  $: isAzure = providerType === "azure";
  $: isVllm = providerType === "hosted_vllm";
  $: isKnownProvider = ["openai", "azure", "anthropic", "gemini", "cohere", "mistral", "hosted_vllm"].includes(providerType);
  $: requiresEndpoint = isAzure || isVllm;
  $: isValid =
    providerName.trim() !== "" &&
    apiKey.trim() !== "" &&
    (!requiresEndpoint || endpoint.trim() !== "") &&
    (!isAzure || (apiVersion.trim() !== "" && deploymentName.trim() !== ""));

  async function handleSubmit() {
    if (!isValid) return;

    isSubmitting = true;
    error = null;

    try {
      const providerData: any = {
        name: providerName,
        provider_type: providerType,
        credentials: { api_key: apiKey },
        config: {},
        is_active: true
      };

      if (endpoint.trim()) {
        providerData.config.endpoint = endpoint;
      }

      if (isAzure) {
        providerData.config.api_version = apiVersion;
        providerData.config.deployment_name = deploymentName;
      }

      const provider = await intric.modelProviders.create(providerData);

      toast.success(m.provider_created_success());
      dispatch("complete", { providerId: provider.id });
    } catch (e: any) {
      error = e.message || m.failed_to_create_provider();
      toast.error(m.failed_to_create_provider());
    } finally {
      isSubmitting = false;
    }
  }

  function handleBack() {
    dispatch("back");
  }
</script>

<div class="flex flex-col gap-6">
  <!-- Header with Provider Type -->
  <div class="flex items-center gap-4 rounded-lg bg-surface-dimmer p-4">
    <ProviderGlyph type={providerType} size="lg" />
    <div>
      <h3 class="font-medium text-primary">{providerLabels[providerType] || providerType}</h3>
      <p class="text-sm text-muted">{m.enter_provider_credentials()}</p>
    </div>
  </div>

  {#if error}
    <div class="border-error bg-error-dimmer text-error-stronger border-l-2 px-4 py-2 text-sm">
      {error}
    </div>
  {/if}

  <form on:submit|preventDefault={handleSubmit} class="flex flex-col gap-4 p-4 rounded-lg border border-dimmer bg-surface-dimmer/30">
    <!-- Provider Name -->
    <div class="flex flex-col gap-2">
      <label for="cred-provider-name" class="text-sm font-medium">{m.provider_name()}</label>
      <Input.Text
        id="cred-provider-name"
        bind:value={providerName}
        placeholder={m.provider_name_placeholder()}
        required
      />
      <p class="text-muted-foreground text-xs">
        {m.provider_name_hint()}
      </p>
    </div>

    <!-- API Key -->
    <div class="flex flex-col gap-2">
      <label for="cred-api-key" class="text-sm font-medium">{m.api_key()}</label>
      <Input.Text
        id="cred-api-key"
        type="password"
        bind:value={apiKey}
        placeholder={m.enter_api_key()}
        required
      />
      <p class="text-muted-foreground text-xs">
        {m.will_be_encrypted()}
      </p>
    </div>

    <!-- Endpoint -->
    {#if requiresEndpoint || providerType === "openai" || !isKnownProvider}
      <div class="flex flex-col gap-2">
        <label for="cred-endpoint" class="text-sm font-medium">{m.endpoint_url()}</label>
        <Input.Text
          id="cred-endpoint"
          bind:value={endpoint}
          placeholder={isAzure
            ? "https://your-resource.openai.azure.com"
            : isVllm
              ? "https://your-vllm-server.com"
              : !isKnownProvider
                ? m.endpoint_optional_generic()
                : "https://api.openai.com/v1 (default)"}
          required={requiresEndpoint}
        />
        <p class="text-muted-foreground text-xs">
          {#if isAzure}
            {m.endpoint_required_azure()}
          {:else if isVllm}
            {m.endpoint_required_vllm()}
          {:else if !isKnownProvider}
            {m.endpoint_optional_generic()}
          {:else}
            {m.endpoint_optional_openai()}
          {/if}
        </p>
      </div>
    {/if}

    <!-- Azure-specific fields -->
    {#if isAzure}
      <div class="flex flex-col gap-2">
        <label for="cred-api-version" class="text-sm font-medium">{m.api_version()}</label>
        <Input.Text
          id="cred-api-version"
          bind:value={apiVersion}
          placeholder={m.api_version_placeholder()}
          required
        />
        <p class="text-muted-foreground text-xs">
          {m.api_version_required()}
        </p>
      </div>

      <div class="flex flex-col gap-2">
        <label for="cred-deployment-name" class="text-sm font-medium">{m.deployment_name()}</label>
        <Input.Text
          id="cred-deployment-name"
          bind:value={deploymentName}
          placeholder={m.deployment_name_placeholder()}
          required
        />
        <p class="text-muted-foreground text-xs">
          {m.deployment_name_required()}
        </p>
      </div>
    {/if}

  </form>

  <!-- Navigation -->
  <div class="flex items-center justify-between border-t border-dimmer pt-4">
    <Button variant="ghost" on:click={handleBack} class="gap-2 focus-visible:!outline-none focus-visible:ring-2 focus-visible:ring-accent-default/70 focus-visible:ring-offset-1 focus-visible:ring-offset-surface">
      <ArrowLeft class="h-4 w-4" />
      {m.back()}
    </Button>

    <Button
      variant="primary"
      on:click={handleSubmit}
      disabled={!isValid || isSubmitting}
      class="focus-visible:!outline-none focus-visible:ring-2 focus-visible:ring-accent-default/50 focus-visible:ring-offset-1 focus-visible:ring-offset-surface"
    >
      {#if isSubmitting}
        <Loader2 class="h-4 w-4 animate-spin mr-2" />
        {m.creating()}
      {:else}
        {m.create_and_continue()}
      {/if}
    </Button>
  </div>
</div>
