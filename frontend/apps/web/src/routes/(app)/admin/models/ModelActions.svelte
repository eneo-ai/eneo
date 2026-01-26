<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@intric/intric-js";
  import { IconEllipsis } from "@intric/icons/ellipsis";
  import { Button, Dialog, Dropdown } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { invalidate } from "$app/navigation";
  import EditModelDialog from "./EditModelDialog.svelte";
  import { writable } from "svelte/store";
  import { Pencil, Trash2, AlertTriangle, Loader2, ArrowRight } from "lucide-svelte";
  import { IconCancel } from "@intric/icons/cancel";
  import { IconCheck } from "@intric/icons/check";
  import { IconArrowUpToLine } from "@intric/icons/arrow-up-to-line";
  import { IconArrowDownToLine } from "@intric/icons/arrow-down-to-line";
  import ModelClassificationDialog from "$lib/features/security-classifications/components/ModelClassificationDialog.svelte";
  import { IconLockClosed } from "@intric/icons/lock-closed";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import MigrateModelDialog from "./MigrateModelDialog.svelte";

  export let model: CompletionModel | EmbeddingModel | TranscriptionModel;
  export let type: "completionModel" | "embeddingModel" | "transcriptionModel";
  export let completionModels: CompletionModel[] = [];

  const intric = getIntric();

  async function togglePreferred() {
    if (!("is_org_default" in model)) return;
    try {
      model = await intric.models.update(
        //@ts-expect-error ts doesn't understand this
        {
          [type]: model,
          update: {
            is_org_default: !model.is_org_default
          }
        }
      );
      invalidate("admin:models:load");
    } catch (e) {
      toast.error(`${m.error_changing_model_status()} ${model.name}`);
    }
  }

  async function toggleEnabled() {
    try {
      model = await intric.models.update(
        //@ts-expect-error ts doesn't understand this
        {
          [type]: model,
          update: {
            is_org_enabled: !model.is_org_enabled
          }
        }
      );
      invalidate("admin:models:load");
    } catch (e) {
      toast.error(`${m.error_changing_model_status()} ${model.name}`);
    }
  }

  const showEditDialog = writable(false);
  const showSecurityDialog = writable(false);
  const showDeleteConfirm = writable(false);
  const showMigrateDialog = writable(false);
  let isDeleting = false;
  let deleteError: string | null = null;
  let deleteErrorStatus: number | null = null;

  async function handleDelete() {
    deleteError = null;
    deleteErrorStatus = null;
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
      $showDeleteConfirm = false;
    } catch (e: any) {
      deleteError = e.message || m.failed_to_delete_model();
      deleteErrorStatus = typeof e?.status === "number" ? e.status : null;
    } finally {
      isDeleting = false;
    }
  }

  $: showMigrationAction = type === "completionModel" && deleteErrorStatus === 400;
  $: completionModelTargets =
    type === "completionModel" ? completionModels : [];
</script>

<Dropdown.Root>
  <Dropdown.Trigger let:trigger asFragment>
    <Button variant="on-fill" is={trigger} disabled={false} padding="icon">
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
      <Pencil class="h-4 w-4" />{m.edit_model()}
    </Button>
    <Button
      is={item}
      padding="icon-leading"
      on:click={() => {
        $showSecurityDialog = true;
      }}
    >
      <IconLockClosed></IconLockClosed>{m.edit_security_classification()}
    </Button>
    {#if "is_org_default" in model}
      <Button is={item} on:click={togglePreferred} padding="icon-leading">
        {#if model.is_org_default}
          <IconArrowDownToLine></IconArrowDownToLine>{m.unset_default_status()}
        {:else}
          <IconArrowUpToLine></IconArrowUpToLine>{m.set_as_default_model()}
        {/if}
      </Button>
    {/if}
    <Button
      is={item}
      padding="icon-leading"
      on:click={toggleEnabled}
      variant={model.is_org_enabled ? "destructive" : "positive-outlined"}
      disabled={model.is_locked && !model.is_org_enabled}
    >
      {#if model.is_org_enabled}
        <IconCancel></IconCancel>
        <span>{m.disable_model()}</span>
      {:else}
        <IconCheck></IconCheck>
        {m.enable_model()}
      {/if}
    </Button>
    <Button
      is={item}
      padding="icon-leading"
      variant="destructive"
      on:click={() => {
        deleteError = null;
        deleteErrorStatus = null;
        $showDeleteConfirm = true;
      }}
    >
      <Trash2 class="h-4 w-4" />
      {m.delete_model()}
    </Button>
  </Dropdown.Menu>
</Dropdown.Root>

<EditModelDialog {model} {type} openController={showEditDialog} />

<ModelClassificationDialog {model} {type} openController={showSecurityDialog}
></ModelClassificationDialog>

<Dialog.Root openController={showDeleteConfirm}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.delete_model()}</Dialog.Title>
    <Dialog.Section>
      <div class="flex flex-col gap-5 p-4">
        <!-- Error Alert with Migration Option -->
        {#if deleteError}
          <div class="relative overflow-hidden rounded-lg border border-negative-default/30 bg-negative-dimmer/50">
            <div class="absolute inset-y-0 left-0 w-1 bg-negative-default"></div>
            <div class="flex items-start gap-3 p-4 pl-5">
              <div class="flex-shrink-0 rounded-full bg-negative-default/10 p-1.5">
                <AlertTriangle class="h-4 w-4 text-negative-default" />
              </div>
              <div class="flex-1 min-w-0">
                <p class="text-sm font-medium text-negative-stronger">{m.failed_to_delete_model()}</p>
                <p class="mt-1 text-sm text-negative-default/90">{deleteError}</p>
              </div>
            </div>
            {#if showMigrationAction}
              <div class="border-t border-negative-default/20 bg-negative-dimmer/30 px-4 py-3">
                <button
                  class="group flex w-full items-center justify-between rounded-md bg-primary/5 px-3 py-2.5 text-sm font-medium text-primary transition-all hover:bg-primary/10"
                  on:click={() => {
                    $showDeleteConfirm = false;
                    $showMigrateDialog = true;
                  }}
                >
                  <span>{m.migrate_model_usage()}</span>
                  <ArrowRight class="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                </button>
              </div>
            {/if}
          </div>
        {/if}

        <!-- Confirmation Text -->
        <div class="space-y-2">
          <p class="text-sm text-primary">
            {m.delete_model_confirm({
              name: "nickname" in model && model.nickname ? model.nickname : model.name
            })}
          </p>
          <p class="text-sm text-muted">
            {m.delete_model_warning()}
          </p>
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
        disabled={isDeleting}
      >
        {#if isDeleting}
          <Loader2 class="h-4 w-4 animate-spin mr-2" />
          {m.deleting()}
        {:else}
          {m.delete_model()}
        {/if}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

{#if type === "completionModel"}
  <MigrateModelDialog
    openController={showMigrateDialog}
    sourceModel={model as CompletionModel}
    models={completionModelTargets}
  />
{/if}
