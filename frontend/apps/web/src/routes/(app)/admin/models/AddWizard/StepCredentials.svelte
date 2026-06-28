<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Step 2 — provide credentials for a brand-new provider and create it.

  Field metadata (which fields, required, secret, in credentials/config) comes
  from `capabilities.providers[providerType].fields`. Labels, placeholders and
  hints come from the shared `modelProviderCapabilities` helpers so they stay
  in sync with the standalone ProviderDialog.
-->

<script lang="ts">
  import { onMount, tick, untrack } from "svelte";
  import { ArrowLeft, Loader2 } from "lucide-svelte";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { toastError } from "$lib/core/errors";

  import { Input } from "$lib/components/ui/input/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";

  import ProviderGlyph from "../components/ProviderGlyph.svelte";
  import {
    formatProviderLabel,
    formatFieldLabel,
    getFieldPlaceholder,
    getFieldHint,
    resolveProviderFields,
    type ModelProviderCapabilities
  } from "../modelProviderCapabilities";

  let {
    providerType,
    capabilities = null,
    onComplete,
    onBack
  }: {
    providerType: string;
    capabilities?: ModelProviderCapabilities | null;
    onComplete: (detail: { providerId: string }) => void;
    onBack: () => void;
  } = $props();

  const eneo = getEneo();

  // Field definitions resolve eagerly even before capabilities load — the
  // helper provides a sensible fallback so the form mounts immediately.
  const fields = $derived(resolveProviderFields(capabilities, providerType));

  // Seed the editable name once from the provider type. Subsequent changes
  // to providerType would only happen via a remount (the wizard rekeys steps),
  // so we explicitly untrack the read to silence the "captures initial value"
  // warning that $state would otherwise emit.
  let providerName = $state(untrack(() => formatProviderLabel(providerType)));
  let fieldValues = $state<Record<string, string>>({});

  let isSubmitting = $state(false);
  let error = $state<string | null>(null);

  // Seed any new fields the resolved schema introduces. We never delete keys
  // here — switching provider types is impossible at this step (the wizard
  // doesn't go back-and-forth between credentials and provider type), so
  // dangling values would only matter on rapid edits and have no effect on
  // submission since we only read keys present in `fields`.
  $effect(() => {
    for (const field of fields) {
      if (!(field.name in fieldValues)) {
        fieldValues[field.name] = "";
      }
    }
  });

  const isValid = $derived(
    providerName.trim() !== "" &&
      fields.every((f) => !f.required || (fieldValues[f.name] ?? "").trim() !== "")
  );

  onMount(async () => {
    await tick();
    document.getElementById("cred-provider-name")?.focus();
  });

  async function submit() {
    if (!isValid || isSubmitting) return;

    isSubmitting = true;
    error = null;

    try {
      const credentials: Record<string, string> = {};
      const config: Record<string, string> = {};
      for (const field of fields) {
        const value = (fieldValues[field.name] ?? "").trim();
        if (!value) continue;
        if (field.in === "credentials") credentials[field.name] = value;
        else config[field.name] = value;
      }

      const provider = await eneo.modelProviders.create({
        name: providerName,
        provider_type: providerType,
        credentials,
        config,
        is_active: true
      });

      toast.success(m.provider_created_success());
      onComplete({ providerId: provider.id });
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : m.failed_to_create_provider();
      toastError(e, m.failed_to_create_provider());
    } finally {
      isSubmitting = false;
    }
  }

  function handleFormSubmit(event: SubmitEvent) {
    event.preventDefault();
    void submit();
  }
</script>

<div class="flex flex-col gap-6">
  <div class="border-border flex items-center gap-4 rounded-lg border p-4">
    <ProviderGlyph {providerType} size="lg" />
    <div>
      <h3 class="text-foreground font-medium">{formatProviderLabel(providerType)}</h3>
      <p class="text-muted-foreground text-sm">{m.enter_provider_credentials()}</p>
    </div>
  </div>

  {#if error}
    <div
      class="border-destructive bg-destructive/10 text-destructive border-l-2 px-4 py-2 text-sm"
      role="alert"
    >
      {error}
    </div>
  {/if}

  <form onsubmit={handleFormSubmit} class="flex flex-col gap-4">
    <Field.Field>
      <Field.Label for="cred-provider-name">{m.provider_name()}</Field.Label>
      <Input
        id="cred-provider-name"
        bind:value={providerName}
        placeholder={m.provider_name_placeholder()}
        required
      />
      <Field.Description>{m.provider_name_hint()}</Field.Description>
    </Field.Field>

    {#each fields as field (field.name)}
      {@const hint = getFieldHint(field.name, field.required, providerType, "create")}
      <Field.Field>
        <Field.Label for="cred-{field.name}">
          {formatFieldLabel(field.name)}
          {#if !field.required}
            <span class="text-muted-foreground ml-1 text-xs font-normal">({m.optional()})</span>
          {/if}
        </Field.Label>
        <Input
          id="cred-{field.name}"
          type={field.secret ? "password" : "text"}
          bind:value={fieldValues[field.name]}
          placeholder={getFieldPlaceholder(field.name, providerType)}
          required={field.required}
        />
        {#if hint}
          <Field.Description>{hint}</Field.Description>
        {/if}
      </Field.Field>
    {/each}
  </form>

  <div class="border-border flex items-center justify-between border-t pt-4">
    <Button type="button" variant="outline" onclick={onBack}>
      <ArrowLeft aria-hidden="true" />
      {m.back()}
    </Button>

    <Button type="button" onclick={() => void submit()} disabled={!isValid || isSubmitting}>
      {#if isSubmitting}
        <Loader2 class="animate-spin" aria-hidden="true" />
        {m.creating()}
      {:else}
        {m.create_and_continue()}
      {/if}
    </Button>
  </div>
</div>
