<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { Button, Input } from "@intric/ui";
  import { createEventDispatcher, onMount } from "svelte";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import ProviderGlyph from "../components/ProviderGlyph.svelte";
  import { ArrowLeft, Loader2 } from "lucide-svelte";

  export let providerType: string;

  /** Dynamic field definitions from capabilities (passed by AddWizard) */
  export let providerFields: Array<{
    name: string;
    required: boolean;
    secret: boolean;
    in: "credentials" | "config";
  }> | null = null;

  const dispatch = createEventDispatcher<{
    complete: { providerId: string };
    back: void;
  }>();

  const intric = getIntric();

  // Dynamic field values — keyed by field name
  let fieldValues: Record<string, string> = {};

  // Provider name (always shown, not part of providerFields)
  let providerName = "";

  // State
  let isSubmitting = false;
  let error: string | null = null;

  // Fallback fields when capabilities haven't loaded yet
  const fallbackFields: typeof providerFields = [
    { name: "api_key", required: true, secret: true, in: "credentials" },
    { name: "endpoint", required: false, secret: false, in: "config" },
  ];

  $: fields = providerFields ?? fallbackFields;

  // Initialize field values when fields change
  $: {
    for (const field of fields) {
      if (!(field.name in fieldValues)) {
        fieldValues[field.name] = "";
      }
    }
  }

  // Validation: name must be filled + all required fields
  $: isValid = providerName.trim() !== "" &&
    fields.every(f => !f.required || (fieldValues[f.name] ?? "").trim() !== "");

  // Auto-focus first input and prefill provider name on mount
  onMount(() => {
    if (!providerName) {
      providerName = formatProviderLabel(providerType);
    }
    setTimeout(() => {
      const input = document.getElementById("cred-provider-name") as HTMLInputElement;
      input?.focus();
      input?.select();
    }, 100);
  });

  function formatProviderLabel(type: string): string {
    // Known display names for common providers
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
        : providerType === "hosted_vllm"
          ? "https://your-vllm-server.com"
          : "https://api.example.com/v1",
      api_version: m.api_version_placeholder(),
      deployment_name: m.deployment_name_placeholder(),
    };
    return placeholders[name] ?? "";
  }

  function getFieldHint(name: string, required: boolean): string {
    if (name === "api_key") return m.will_be_encrypted();
    if (name === "endpoint") {
      if (providerType === "azure") return m.endpoint_required_azure();
      if (providerType === "hosted_vllm") return m.endpoint_required_vllm();
      if (!required) return m.endpoint_optional_generic();
    }
    if (name === "api_version") return m.api_version_required();
    if (name === "deployment_name") return m.deployment_name_required();
    return required ? "" : "";
  }

  async function handleSubmit() {
    if (!isValid) return;

    isSubmitting = true;
    error = null;

    try {
      // Build credentials and config from field values based on field.in
      const credentials: Record<string, string> = {};
      const config: Record<string, string> = {};

      for (const field of fields) {
        const value = (fieldValues[field.name] ?? "").trim();
        if (value) {
          if (field.in === "credentials") {
            credentials[field.name] = value;
          } else {
            config[field.name] = value;
          }
        }
      }

      const provider = await intric.modelProviders.create({
        name: providerName,
        provider_type: providerType,
        credentials,
        config,
        is_active: true,
      });

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
      <h3 class="font-medium text-primary">{formatProviderLabel(providerType)}</h3>
      <p class="text-sm text-muted">{m.enter_provider_credentials()}</p>
    </div>
  </div>

  {#if error}
    <div class="border-error bg-error-dimmer text-error-stronger border-l-2 px-4 py-2 text-sm">
      {error}
    </div>
  {/if}

  <form on:submit|preventDefault={handleSubmit} class="flex flex-col gap-4 p-4 rounded-lg border border-dimmer bg-surface-dimmer/30">
    <!-- Provider Name (always first) -->
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

    <!-- Dynamic fields -->
    {#each fields as field (field.name)}
      {@const hint = getFieldHint(field.name, field.required)}
      <div class="flex flex-col gap-2">
        <label for="cred-{field.name}" class="text-sm font-medium">
          {formatFieldLabel(field.name)}
          {#if !field.required}
            <span class="text-muted font-normal text-xs ml-1">(optional)</span>
          {/if}
        </label>
        <Input.Text
          id="cred-{field.name}"
          type={field.secret ? "password" : "text"}
          bind:value={fieldValues[field.name]}
          placeholder={getFieldPlaceholder(field.name)}
          required={field.required}
        />
        {#if hint}
          <p class="text-muted-foreground text-xs">{hint}</p>
        {/if}
      </div>
    {/each}
  </form>

  <!-- Navigation -->
  <div class="flex items-center justify-between border-t border-dimmer pt-4">
    <Button variant="outlined" on:click={handleBack} class="gap-2 focus-visible:!outline-none focus-visible:ring-2 focus-visible:ring-accent-default/70 focus-visible:ring-offset-1 focus-visible:ring-offset-surface">
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
