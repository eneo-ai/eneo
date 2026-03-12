<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import type { CompletionModel } from "@intric/intric-js";
  import { Button, Dialog, Select } from "@intric/ui";
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { Loader2 } from "lucide-svelte";
  import type { Writable } from "svelte/store";

  export let openController: Writable<boolean>;
  export let sourceModel: CompletionModel;
  export let models: CompletionModel[] = [];

  const intric = getIntric();

  let targetModelId = "";
  let confirmMigration = false;
  let isSubmitting = false;
  let error: string | null = null;

  $: availableTargets = models
    .filter((model) => model.id !== sourceModel.id)
    .filter((model) => model.provider_id != null)
    .filter((model) => model.is_org_enabled);

  $: targetOptions = availableTargets.map((model) => ({
    value: model.id,
    label: model.nickname ? model.nickname : model.name
  }));

  $: if ($openController) {
    error = null;
    confirmMigration = false;
    if (!targetOptions.find((option) => option.value === targetModelId)) {
      targetModelId = "";
    }
  }

  async function handleMigrate() {
    error = null;

    if (!targetModelId) {
      error = m.migrate_model_target_required();
      return;
    }

    isSubmitting = true;

    try {
      await intric.models.migrateCompletion({
        fromId: sourceModel.id,
        toId: targetModelId,
        confirmMigration: confirmMigration || undefined
      });

      // Delete the source model after successful migration
      let deleteSucceeded = true;
      try {
        await intric.tenantModels.deleteCompletion({ id: sourceModel.id });
      } catch {
        deleteSucceeded = false;
      }

      if (deleteSucceeded) {
        toast.success(m.migration_success());
      } else {
        toast.warning(m.migration_success_delete_failed());
      }
      await invalidate("admin:model-providers:load");
      openController.set(false);
    } catch (e: any) {
      const msg = e.message || "";
      if (msg.includes("compatibility issues")) {
        error = m.migration_compatibility_issues();
      } else {
        error = msg || m.migration_failed();
      }
      toast.error(m.migration_failed());
    } finally {
      isSubmitting = false;
    }
  }
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.migrate_model_title()}</Dialog.Title>
    <Dialog.Section>
      <div class="flex flex-col gap-4 p-4">
        {#if error}
          <div class="border-error bg-error-dimmer text-error-stronger border-l-2 px-4 py-2 text-sm">
            {error}
          </div>
        {/if}
        <p class="text-sm text-muted-foreground">
          {m.migrate_model_description({
            name: sourceModel.nickname ? sourceModel.nickname : sourceModel.name
          })}
        </p>
        <Select.Simple
          options={targetOptions}
          bind:value={targetModelId}
          resourceName={m.resource_model()}
          placeholder={m.migrate_model_target_placeholder()}
          fitViewport={true}
          class="border-default hover:bg-hover-dimmer rounded-t-md border-b px-4 py-4"
        >
          {m.migrate_model_target_label()}
        </Select.Simple>
        {#if targetOptions.length === 0}
          <p class="text-sm text-muted-foreground">
            {m.migrate_model_no_targets()}
          </p>
        {/if}
        <label class="flex items-start gap-3 text-sm text-muted-foreground">
          <input
            type="checkbox"
            bind:checked={confirmMigration}
            class="mt-0.5 h-4 w-4 rounded border-stronger accent-accent-default"
          />
          <span>{m.migrate_model_confirm_label()}</span>
        </label>
        <p class="text-xs text-muted-foreground">
          {m.migrate_model_warning()}
        </p>
      </div>
    </Dialog.Section>
    <Dialog.Controls>
      <Button variant="outlined" on:click={() => openController.set(false)}>
        {m.cancel()}
      </Button>
      <Button
        on:click={handleMigrate}
        disabled={isSubmitting || !targetModelId || targetOptions.length === 0}
      >
        {#if isSubmitting}
          <Loader2 class="h-4 w-4 animate-spin" />
          {m.migrating()}
        {:else}
          {m.migrate_model_usage()}
        {/if}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
