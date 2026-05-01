<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import {
    IntricError,
    type CompletionModel,
    type EmbeddingModel,
    type TranscriptionModel
  } from "@intric/intric-js";
  import { IconEllipsis } from "@intric/icons/ellipsis";
  import { Button as LegacyButton, Dropdown } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { invalidate } from "$app/navigation";
  import { writable } from "svelte/store";
  import { Pencil, Trash2, AlertTriangle, Loader2, ArrowRight } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { getErrorMessage } from "$lib/core/errors";

  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";

  import EditModelDialog from "./EditModelDialog.svelte";
  import MigrateModelDialog from "./MigrateModelDialog.svelte";

  /** Backend error code for "model is referenced and can't be soft-deleted".
   *  Mirrors `ErrorCodes.MODEL_IN_USE` in `backend/src/intric/main/exceptions.py`. */
  const MODEL_IN_USE_CODE = 9039;

  // svelte-headless-table's `createRender` expects a class-based component,
  // so we keep this file on the legacy `export let` API. The shadcn dialog
  // below works just fine inside a non-runes parent.
  export let model: CompletionModel | EmbeddingModel | TranscriptionModel;
  export let type: "completionModel" | "embeddingModel" | "transcriptionModel";
  export let completionModels: CompletionModel[] = [];

  const intric = getIntric();

  const showEditDialog = writable(false);
  const showMigrateDialog = writable(false);

  // Delete confirm dialog state. Two-way bridge between an internal boolean
  // (driven by shadcn `bind:open`) and the legacy reactive flag pattern used
  // for the rest of this file.
  let deleteOpen = false;
  let isDeleting = false;
  let deleteError: string | null = null;
  let showMigrateOption = false;

  $: completionModelTargets = type === "completionModel" ? completionModels : [];
  $: modelLabel = "nickname" in model && model.nickname ? model.nickname : model.name;

  function openDelete() {
    deleteError = null;
    showMigrateOption = false;
    deleteOpen = true;
  }

  async function handleDelete() {
    deleteError = null;
    showMigrateOption = false;
    isDeleting = true;

    try {
      if (type === "completionModel") {
        await intric.tenantModels.deleteCompletion({ id: model.id });
      } else if (type === "embeddingModel") {
        await intric.tenantModels.deleteEmbedding({ id: model.id });
      } else {
        await intric.tenantModels.deleteTranscription({ id: model.id });
      }

      await invalidate("admin:model-providers:load");
      deleteOpen = false;
    } catch (e: unknown) {
      deleteError = getErrorMessage(e);
      showMigrateOption =
        type === "completionModel" && e instanceof IntricError && e.code === MODEL_IN_USE_CODE;
    } finally {
      isDeleting = false;
    }
  }
</script>

<Dropdown.Root>
  <Dropdown.Trigger let:trigger asFragment>
    <LegacyButton variant="on-fill" is={trigger} disabled={false} padding="icon">
      <IconEllipsis />
    </LegacyButton>
  </Dropdown.Trigger>
  <Dropdown.Menu let:item>
    <LegacyButton
      is={item}
      padding="icon-leading"
      on:click={() => {
        $showEditDialog = true;
      }}
    >
      <Pencil class="h-4 w-4" />{m.edit_model()}
    </LegacyButton>
    {#if type === "completionModel"}
      <LegacyButton
        is={item}
        padding="icon-leading"
        on:click={() => {
          $showMigrateDialog = true;
        }}
      >
        <ArrowRight class="h-4 w-4" />{m.migrate_model_usage()}
      </LegacyButton>
    {/if}
    <LegacyButton is={item} padding="icon-leading" variant="destructive" on:click={openDelete}>
      <Trash2 class="h-4 w-4" />
      {m.delete_model()}
    </LegacyButton>
  </Dropdown.Menu>
</Dropdown.Root>

<EditModelDialog {model} {type} openController={showEditDialog} />

<!-- Delete confirm — shadcn -->
<Dialog.Root bind:open={deleteOpen}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>{m.delete_model()}</Dialog.Title>
    </Dialog.Header>

    <div class="flex flex-col gap-5">
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
                {m.failed_to_delete_model()}
              </p>
              <p class="text-negative-default/90 mt-1 text-sm">{deleteError}</p>
            </div>
          </div>
          {#if showMigrateOption}
            <div class="border-negative-default/20 bg-negative-dimmer/30 border-t px-4 py-3">
              <button
                type="button"
                class="group bg-primary/5 text-primary hover:bg-primary/10 flex w-full items-center justify-between rounded-md px-3 py-2.5 text-sm font-medium transition-all"
                on:click={() => {
                  deleteOpen = false;
                  $showMigrateDialog = true;
                }}
              >
                <span>{m.migrate_model_usage()}</span>
                <ArrowRight
                  class="size-4 transition-transform group-hover:translate-x-0.5"
                  aria-hidden="true"
                />
              </button>
            </div>
          {/if}
        </div>
      {/if}

      <div class="space-y-2">
        <p class="text-foreground text-sm">{m.delete_model_confirm({ name: modelLabel })}</p>
        <p class="text-muted-foreground text-sm">{m.delete_model_warning()}</p>
      </div>
    </div>

    <Dialog.Footer>
      <Button variant="outline" onclick={() => (deleteOpen = false)}>{m.cancel()}</Button>
      <Button variant="destructive" onclick={handleDelete} disabled={isDeleting}>
        {#if isDeleting}
          <Loader2 class="size-4 animate-spin" aria-hidden="true" />
          {m.deleting()}
        {:else}
          {m.delete_model()}
        {/if}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

{#if type === "completionModel"}
  <MigrateModelDialog
    openController={showMigrateDialog}
    sourceModel={model as CompletionModel}
    models={completionModelTargets}
  />
{/if}
