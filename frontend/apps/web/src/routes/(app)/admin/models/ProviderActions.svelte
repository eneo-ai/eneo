<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import type { ModelProviderPublic } from "@intric/intric-js";
  import { IconEllipsis } from "@intric/icons/ellipsis";
  import { Button, Dropdown, Dialog } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { invalidate } from "$app/navigation";
  import { writable } from "svelte/store";
  import { Plus, Pencil, Trash2, AlertTriangle, Loader2, Box, Sparkles, AudioLines } from "lucide-svelte";
  import ProviderDialog from "./ProviderDialog.svelte";
  import { m } from "$lib/paraglide/messages";

  export let provider: ModelProviderPublic;
  /** Pass this to open AddCompletionModelDialog with this provider pre-selected */
  export let onAddModel: ((providerId: string) => void) | undefined = undefined;

  const intric = getIntric();

  const showEditDialog = writable(false);
  const showDeleteConfirm = writable(false);
  let isDeleting = false;
  let deleteError: string | null = null;
  let isLoadingModels = false;
  let modelsLoadError: string | null = null;
  let providerModels: Array<{ name: string; type: string; typeRaw: string; icon: typeof Sparkles }> = [];

  async function handleDelete() {
    deleteError = null;
    isDeleting = true;
    try {
      await intric.modelProviders.delete({ id: provider.id });
      await invalidate("admin:model-providers:load");
      $showDeleteConfirm = false;
    } catch (e: any) {
      deleteError = e.message || m.failed_to_delete_provider();
    } finally {
      isDeleting = false;
    }
  }

  function getModelName(model: any): string {
    if ("nickname" in model && model.nickname) {
      return model.nickname;
    }
    if ("model_name" in model && model.model_name) {
      return model.model_name;
    }
    return model.name;
  }

  function getModelTypeLabel(model: any): string {
    if ("token_limit" in model || "vision" in model || "reasoning" in model) {
      return m.completion_model();
    }
    if ("family" in model) {
      return m.embedding_model();
    }
    return m.transcription_model();
  }

  function getModelTypeIcon(model: any): typeof Sparkles {
    if ("token_limit" in model || "vision" in model || "reasoning" in model) {
      return Sparkles;
    }
    if ("family" in model) {
      return Box;
    }
    return AudioLines;
  }

  function getModelTypeRaw(model: any): "completion" | "embedding" | "transcription" {
    if ("token_limit" in model || "vision" in model || "reasoning" in model) {
      return "completion";
    }
    if ("family" in model) {
      return "embedding";
    }
    return "transcription";
  }

  async function loadProviderModels() {
    isLoadingModels = true;
    modelsLoadError = null;
    providerModels = [];

    try {
      const models = await intric.models.list();
      const allModels = [
        ...models.completionModels,
        ...models.embeddingModels,
        ...models.transcriptionModels
      ];

      providerModels = allModels
        .filter((model) => model.provider_id === provider.id)
        .map((model) => ({
          name: getModelName(model),
          type: getModelTypeLabel(model),
          typeRaw: getModelTypeRaw(model),
          icon: getModelTypeIcon(model)
        }))
        .sort((a, b) => a.name.localeCompare(b.name));
    } catch (e: any) {
      modelsLoadError = e.message || m.failed_to_load_models();
    } finally {
      isLoadingModels = false;
    }
  }
</script>

<Dropdown.Root>
  <Dropdown.Trigger let:trigger asFragment>
    <Button variant="on-fill" is={trigger} padding="icon" class="transition-colors duration-150 hover:bg-hover-dimmer rounded-md">
      <IconEllipsis />
    </Button>
  </Dropdown.Trigger>
  <Dropdown.Menu let:item>
    <Button
      is={item}
      padding="icon-leading"
      on:click={() => {
        $showEditDialog = true;
      }}
    >
      <Pencil class="h-4 w-4" />
      {m.edit_provider()}
    </Button>
    <Button
      is={item}
      padding="icon-leading"
      variant="destructive"
      on:click={() => {
        deleteError = null;
        $showDeleteConfirm = true;
        loadProviderModels();
      }}
    >
      <Trash2 class="h-4 w-4" />
      {m.delete_provider()}
    </Button>
  </Dropdown.Menu>
</Dropdown.Root>

<!-- Edit Provider Dialog -->
<ProviderDialog openController={showEditDialog} {provider} />

<!-- Delete Confirmation Dialog -->
<Dialog.Root openController={showDeleteConfirm}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.delete_provider()}</Dialog.Title>
    <Dialog.Section>
      <div class="flex flex-col gap-5 p-4">
        <!-- Error Alert -->
        {#if deleteError}
          <div class="relative overflow-hidden rounded-lg border border-negative-default/30 bg-negative-dimmer/50">
            <div class="absolute inset-y-0 left-0 w-1 bg-negative-default"></div>
            <div class="flex items-start gap-3 p-4 pl-5">
              <div class="flex-shrink-0 rounded-full bg-negative-default/10 p-1.5">
                <AlertTriangle class="h-4 w-4 text-negative-default" />
              </div>
              <div class="flex-1 min-w-0">
                <p class="text-sm font-medium text-negative-stronger">{m.failed_to_delete_provider()}</p>
                <p class="mt-1 text-sm text-negative-default/90">{deleteError}</p>
              </div>
            </div>
          </div>
        {/if}

        <!-- Models List Section -->
        {#if isLoadingModels}
          <div class="flex items-center justify-center gap-3 py-6">
            <Loader2 class="h-5 w-5 animate-spin text-muted" />
            <span class="text-sm text-muted">{m.loading()}</span>
          </div>
        {:else if modelsLoadError}
          <div class="relative overflow-hidden rounded-lg border border-negative-default/30 bg-negative-dimmer/50">
            <div class="absolute inset-y-0 left-0 w-1 bg-negative-default"></div>
            <div class="flex items-start gap-3 p-4 pl-5">
              <div class="flex-shrink-0 rounded-full bg-negative-default/10 p-1.5">
                <AlertTriangle class="h-4 w-4 text-negative-default" />
              </div>
              <p class="text-sm text-negative-default/90">{modelsLoadError}</p>
            </div>
          </div>
        {:else if providerModels.length > 0}
          <div class="rounded-lg border border-negative-default/30 bg-negative-dimmer/30">
            <div class="flex items-center gap-2 border-b border-negative-default/20 px-4 py-3">
              <AlertTriangle class="h-4 w-4 text-negative-default" />
              <p class="text-sm font-medium text-negative-stronger">
                {providerModels.length === 1
                  ? m.provider_model_count_one({ count: providerModels.length })
                  : m.provider_model_count_other({ count: providerModels.length })}
              </p>
            </div>
            <ul class="divide-y divide-negative-default/10">
              {#each providerModels as model}
                <li class="flex items-center gap-3 px-4 py-2.5">
                  <div
                    class="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md"
                    class:bg-accent-dimmer={model.typeRaw === "completion"}
                    class:text-accent-default={model.typeRaw === "completion"}
                    class:bg-positive-dimmer={model.typeRaw === "embedding"}
                    class:text-positive-default={model.typeRaw === "embedding"}
                    class:bg-dynamic-dimmer={model.typeRaw === "transcription"}
                    class:text-dynamic-default={model.typeRaw === "transcription"}
                  >
                    <svelte:component this={model.icon} class="h-3.5 w-3.5" />
                  </div>
                  <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium text-primary truncate">{model.name}</p>
                    <p class="text-xs text-muted">{model.type}</p>
                  </div>
                </li>
              {/each}
            </ul>
            <!-- Blocking message -->
            <div class="border-t border-negative-default/20 bg-negative-dimmer/50 px-4 py-3">
              <p class="text-sm text-negative-stronger font-medium">
                {m.delete_provider_blocked()}
              </p>
            </div>
          </div>
        {:else}
          <div class="flex items-center gap-3 rounded-lg border border-positive-default/30 bg-positive-dimmer/30 px-4 py-3">
            <div class="flex h-6 w-6 items-center justify-center rounded-full bg-positive-default/10">
              <svg class="h-3.5 w-3.5 text-positive-default" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <p class="text-sm text-positive-stronger">{m.no_models_in_provider()}</p>
          </div>
        {/if}

        <!-- Confirmation Text -->
        <div class="space-y-2">
          <p class="text-sm text-primary">
            {m.delete_provider_confirm({ name: provider.name })}
          </p>
          {#if providerModels.length === 0 && !isLoadingModels}
            <p class="text-sm text-muted">
              {m.delete_provider_warning()}
            </p>
          {/if}
        </div>
      </div>
    </Dialog.Section>
    <Dialog.Controls>
      <Button variant="outlined" on:click={() => ($showDeleteConfirm = false)}>
        {m.cancel()}
      </Button>
      <Button
        variant="destructive"
        on:click={handleDelete}
        disabled={isDeleting || providerModels.length > 0}
      >
        {#if isDeleting}
          <Loader2 class="h-4 w-4 animate-spin mr-2" />
          {m.deleting()}
        {:else}
          {m.delete_provider()}
        {/if}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
