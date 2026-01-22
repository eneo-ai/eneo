<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type {
    CompletionModel,
    EmbeddingModel,
    TranscriptionModel,
    TenantCompletionModelUpdate,
    TenantEmbeddingModelUpdate,
    TenantTranscriptionModelUpdate
  } from "@intric/intric-js";
  import { Button, Dialog, Input } from "@intric/ui";
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import { writable, type Writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";

  export let openController: Writable<boolean>;
  export let model: CompletionModel | EmbeddingModel | TranscriptionModel;
  export let type: "completionModel" | "embeddingModel" | "transcriptionModel";

  const intric = getIntric();

  // Form state - initialized from model
  let modelIdentifier = "";
  let displayName = "";
  let description = "";
  let tokenLimitStr = "128000";
  let vision = false;
  let reasoning = false;
  let family = "";
  let hosting: "eu" | "usa" = "eu";
  let openSource = false;
  let isSubmitting = false;
  let error: string | null = null;

  // Hosting options
  const hostingOptions = [
    { value: "eu", label: m.hosting_eu() },
    { value: "usa", label: m.hosting_usa() }
  ];

  // Initialize form values when dialog opens or model changes
  $: if ($openController && model) {
    initializeForm();
  }

  function initializeForm() {
    modelIdentifier = model.name;
    displayName = "nickname" in model ? (model.nickname || "") : model.name;
    description = model.description || "";
    hosting = model.hosting as "eu" | "usa";
    openSource = model.open_source ?? false;

    if ("token_limit" in model && model.token_limit !== null) {
      tokenLimitStr = String(model.token_limit);
    }
    if ("vision" in model) {
      vision = model.vision;
    }
    if ("reasoning" in model) {
      reasoning = model.reasoning;
    }
    if ("family" in model) {
      family = model.family || "";
    }
  }

  async function handleSubmit() {
    error = null;

    if (!displayName.trim()) {
      error = m.display_name_required();
      return;
    }

    isSubmitting = true;

    try {
      if (type === "completionModel") {
        const update: TenantCompletionModelUpdate = {
          name: modelIdentifier.trim(),
          display_name: displayName.trim(),
          description: description.trim(),
          hosting,
          open_source: openSource,
          token_limit: parseInt(tokenLimitStr, 10),
          vision,
          reasoning
        };
        await intric.tenantModels.updateCompletion({ id: model.id }, update);
      } else if (type === "embeddingModel") {
        const update: TenantEmbeddingModelUpdate = {
          display_name: displayName.trim(),
          description: description.trim(),
          hosting,
          open_source: openSource,
          family: family.trim() || undefined
        };
        await intric.tenantModels.updateEmbedding({ id: model.id }, update);
      } else if (type === "transcriptionModel") {
        const update: TenantTranscriptionModelUpdate = {
          display_name: displayName.trim(),
          description: description.trim(),
          hosting,
          open_source: openSource
        };
        await intric.tenantModels.updateTranscription({ id: model.id }, update);
      }

      // Invalidate to reload data
      await invalidate("admin:model-providers:load");

      // Close dialog
      openController.set(false);
    } catch (e: any) {
      error = e.message || m.failed_to_update_model();
    } finally {
      isSubmitting = false;
    }
  }

  function handleCancel() {
    openController.set(false);
    error = null;
  }
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="large" form>
    <Dialog.Title>{m.edit_model()}</Dialog.Title>

    <Dialog.Section>
      <form on:submit|preventDefault={handleSubmit} class="flex flex-col gap-4 p-4">
        {#if error}
          <div class="border-error bg-error-dimmer text-error-stronger border-l-2 px-4 py-2 text-sm">
            {error}
          </div>
        {/if}

        <!-- Model identifier (editable for completion models, read-only for others) -->
        <div class="flex flex-col gap-2">
          <label for="model-identifier" class="text-sm font-medium">{m.model_identifier()}</label>
          {#if type === "completionModel"}
            <Input.Text
              id="model-identifier"
              bind:value={modelIdentifier}
              required
            />
          {:else}
            <Input.Text
              id="model-identifier"
              value={model.name}
              disabled
              class="opacity-60"
            />
            <p class="text-muted-foreground text-xs">
              {m.model_identifier_readonly()}
            </p>
          {/if}
        </div>

        <!-- Display name (editable) -->
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

        <!-- Description -->
        <div class="flex flex-col gap-2">
          <label for="description" class="text-sm font-medium">{m.description()}</label>
          <textarea
            id="description"
            bind:value={description}
            placeholder={m.model_description_placeholder()}
            rows="3"
            class="rounded border border-dimmer bg-surface px-3 py-2 text-sm resize-none"
          ></textarea>
        </div>

        <!-- Completion model specific fields -->
        {#if type === "completionModel"}
          <div class="flex flex-col gap-2">
            <label for="token-limit" class="text-sm font-medium">{m.token_limit()}</label>
            <Input.Text
              id="token-limit"
              type="number"
              bind:value={tokenLimitStr}
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
        {/if}

        <!-- Embedding model specific fields -->
        {#if type === "embeddingModel"}
          <div class="flex flex-col gap-2">
            <label for="family" class="text-sm font-medium">{m.embedding_family()}</label>
            <Input.Text
              id="family"
              bind:value={family}
              placeholder={m.embedding_family_placeholder()}
            />
            <p class="text-muted-foreground text-xs">
              {m.embedding_family_hint()}
            </p>
          </div>
        {/if}

        <!-- Common detail fields -->
        <div class="border-t border-dimmer pt-4 mt-2">
          <h3 class="text-sm font-semibold mb-3">{m.model_details()}</h3>

          <!-- Hosting -->
          <div class="flex flex-col gap-2">
            <label for="hosting" class="text-sm font-medium">{m.hosting_region()}</label>
            <select
              id="hosting"
              bind:value={hosting}
              class="rounded border border-dimmer bg-surface px-3 py-2 text-sm"
            >
              {#each hostingOptions as option}
                <option value={option.value}>{option.label}</option>
              {/each}
            </select>
          </div>

          <!-- Open source -->
          <div class="mt-4">
            <label class="flex items-center gap-2 text-sm">
              <input type="checkbox" bind:checked={openSource} />
              <span>{m.model_label_open_source()}</span>
            </label>
          </div>
        </div>
      </form>
    </Dialog.Section>

    <Dialog.Controls>
      <Button variant="outlined" on:click={handleCancel}>{m.cancel()}</Button>
      <Button
        variant="primary"
        on:click={handleSubmit}
        disabled={isSubmitting}
      >
        {isSubmitting ? m.saving() : m.save()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
