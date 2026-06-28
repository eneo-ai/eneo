<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Per-provider action menu (edit / delete) shown in the table group header.
  The delete flow is blocked when the provider still has tenant-attached
  models — we surface the blocking list inside the confirmation so the
  admin sees exactly what to clean up first. Models are pre-loaded when
  the dropdown opens so the dialog never flickers through an empty/loading
  state.
-->

<script lang="ts">
  import type {
    CompletionModel,
    EmbeddingModel,
    ModelProviderPublic,
    TranscriptionModel
  } from "@eneo/eneo-js";
  import { getEneo } from "$lib/core/Eneo";
  import { invalidate } from "$app/navigation";
  import {
    Pencil,
    Trash2,
    AlertTriangle,
    Loader2,
    Box,
    Sparkles,
    AudioLines,
    MoreHorizontal,
    Check
  } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";

  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";

  type ModelKind = "completion" | "embedding" | "transcription";
  type ProviderModel = CompletionModel | EmbeddingModel | TranscriptionModel;

  type BlockingModel = {
    id: string;
    name: string;
    type: string;
    kind: ModelKind;
    icon: typeof Sparkles;
  };

  let {
    provider,
    onEditProvider
  }: {
    provider: ModelProviderPublic;
    onEditProvider?: (provider: ModelProviderPublic) => void;
  } = $props();

  const eneo = getEneo();

  let deleteOpen = $state(false);
  let isDeleting = $state(false);
  let deleteError = $state<string | null>(null);

  // Pre-loaded list of models attached to this provider. Dropdown open can
  // warm it, while delete open forces a fresh read before enabling deletion.
  let modelsLoaded = $state(false);
  let isLoadingModels = $state(false);
  let modelsLoadError = $state<string | null>(null);
  let providerModels = $state<BlockingModel[]>([]);

  const canDelete = $derived(modelsLoaded && providerModels.length === 0 && !isLoadingModels);

  async function handleDelete() {
    deleteError = null;
    isDeleting = true;
    try {
      await eneo.modelProviders.delete({ id: provider.id });
      await invalidate("admin:model-providers:load");
      deleteOpen = false;
    } catch (e: unknown) {
      deleteError = e instanceof Error ? e.message : m.failed_to_delete_provider();
    } finally {
      isDeleting = false;
    }
  }

  function getModelName(model: ProviderModel): string {
    return model.nickname || model.name;
  }

  function tagModels(
    models: ProviderModel[],
    kind: ModelKind,
    label: string,
    icon: typeof Sparkles
  ): BlockingModel[] {
    return models
      .filter((model) => model.provider_id === provider.id)
      .map((model) => ({ id: model.id, name: getModelName(model), type: label, kind, icon }));
  }

  async function loadProviderModels({ force = false }: { force?: boolean } = {}) {
    if (isLoadingModels || (modelsLoaded && !force)) return;

    if (force) {
      modelsLoaded = false;
      providerModels = [];
    }

    isLoadingModels = true;
    modelsLoadError = null;

    try {
      const models = await eneo.models.list();
      providerModels = [
        ...tagModels(models.completionModels, "completion", m.completion_model(), Sparkles),
        ...tagModels(models.embeddingModels, "embedding", m.embedding_model(), Box),
        ...tagModels(
          models.transcriptionModels,
          "transcription",
          m.transcription_model(),
          AudioLines
        )
      ].sort((a, b) => a.name.localeCompare(b.name));
      modelsLoaded = true;
    } catch (e: unknown) {
      modelsLoadError = e instanceof Error ? e.message : m.failed_to_load_models();
    } finally {
      isLoadingModels = false;
    }
  }

  function handleDropdownOpenChange(open: boolean) {
    if (open) void loadProviderModels();
  }

  function openDeleteDialog() {
    deleteError = null;
    deleteOpen = true;
    void loadProviderModels({ force: true });
  }
</script>

<DropdownMenu.Root onOpenChange={handleDropdownOpenChange}>
  <DropdownMenu.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="ghost" size="icon-sm" aria-label={m.actions()}>
        <MoreHorizontal />
      </Button>
    {/snippet}
  </DropdownMenu.Trigger>

  <DropdownMenu.Content align="end">
    <DropdownMenu.Item onclick={() => onEditProvider?.(provider)}>
      <Pencil />
      {m.edit_provider()}
    </DropdownMenu.Item>
    <DropdownMenu.Separator />
    <DropdownMenu.Item variant="destructive" onclick={openDeleteDialog}>
      <Trash2 />
      {m.delete_provider()}
    </DropdownMenu.Item>
  </DropdownMenu.Content>
</DropdownMenu.Root>

<AlertDialog.Root bind:open={deleteOpen}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.delete_provider()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.delete_provider_confirm({ name: provider.name })}
      </AlertDialog.Description>
    </AlertDialog.Header>

    <div class="flex flex-col gap-4">
      {#if deleteError}
        <div
          class="border-negative-default/30 bg-negative-dimmer/40 relative overflow-hidden rounded-lg border"
          role="alert"
        >
          <div class="bg-negative-default absolute inset-y-0 left-0 w-1" aria-hidden="true"></div>
          <div class="flex items-start gap-3 p-4 pl-5">
            <div class="bg-negative-default/10 flex-shrink-0 rounded-full p-1.5">
              <AlertTriangle class="text-negative-default size-4" aria-hidden="true" />
            </div>
            <div class="min-w-0 flex-1">
              <p class="text-negative-stronger text-sm font-medium">
                {m.failed_to_delete_provider()}
              </p>
              <p class="text-negative-default/90 mt-1 text-sm">{deleteError}</p>
            </div>
          </div>
        </div>
      {/if}

      {#if isLoadingModels}
        <div class="text-muted flex items-center justify-center gap-3 py-6">
          <Loader2 class="size-5 animate-spin" aria-hidden="true" />
          <span class="text-sm">{m.loading()}</span>
        </div>
      {:else if modelsLoadError}
        <div
          class="border-negative-default/30 bg-negative-dimmer/40 relative overflow-hidden rounded-lg border"
          role="alert"
        >
          <div class="bg-negative-default absolute inset-y-0 left-0 w-1" aria-hidden="true"></div>
          <div class="flex items-start gap-3 p-4 pl-5">
            <div class="bg-negative-default/10 flex-shrink-0 rounded-full p-1.5">
              <AlertTriangle class="text-negative-default size-4" aria-hidden="true" />
            </div>
            <p class="text-negative-default/90 text-sm">{modelsLoadError}</p>
          </div>
        </div>
      {:else if providerModels.length > 0}
        <div class="border-negative-default/30 bg-negative-dimmer/30 rounded-lg border">
          <div class="border-negative-default/20 flex items-center gap-2 border-b px-4 py-3">
            <AlertTriangle class="text-negative-default size-4" aria-hidden="true" />
            <p class="text-negative-stronger text-sm font-medium">
              {providerModels.length === 1
                ? m.provider_model_count_one({ count: providerModels.length })
                : m.provider_model_count_other({ count: providerModels.length })}
            </p>
          </div>

          <ul class="divide-negative-default/10 divide-y">
            {#each providerModels as model (`${model.kind}:${model.id}`)}
              <li class="flex items-center gap-3 px-4 py-2.5">
                <div
                  class="flex size-7 flex-shrink-0 items-center justify-center rounded-md"
                  class:bg-accent-dimmer={model.kind === "completion"}
                  class:text-accent-default={model.kind === "completion"}
                  class:bg-positive-dimmer={model.kind === "embedding"}
                  class:text-positive-default={model.kind === "embedding"}
                  class:bg-dynamic-dimmer={model.kind === "transcription"}
                  class:text-dynamic-default={model.kind === "transcription"}
                >
                  <model.icon class="size-3.5" aria-hidden="true" />
                </div>
                <div class="min-w-0 flex-1">
                  <p class="text-primary truncate text-sm font-medium">{model.name}</p>
                  <p class="text-muted text-xs">{model.type}</p>
                </div>
              </li>
            {/each}
          </ul>

          <div class="border-negative-default/20 bg-negative-dimmer/50 border-t px-4 py-3">
            <p class="text-negative-stronger text-sm font-medium">
              {m.delete_provider_blocked()}
            </p>
          </div>
        </div>
      {:else if modelsLoaded}
        <div
          class="border-positive-default/30 bg-positive-dimmer/30 flex items-center gap-3 rounded-lg border px-4 py-3"
        >
          <div class="bg-positive-default/10 flex size-6 items-center justify-center rounded-full">
            <Check class="text-positive-default size-3.5" aria-hidden="true" />
          </div>
          <p class="text-positive-stronger text-sm">{m.no_models_in_provider()}</p>
        </div>
      {/if}

      {#if canDelete}
        <p class="text-muted text-sm">{m.delete_provider_warning()}</p>
      {/if}
    </div>

    <AlertDialog.Footer>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action
        variant="destructive"
        onclick={handleDelete}
        disabled={isDeleting || !canDelete}
      >
        {#if isDeleting}
          <Loader2 class="size-4 animate-spin" aria-hidden="true" />
          {m.deleting()}
        {:else}
          {m.delete_provider()}
        {/if}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
