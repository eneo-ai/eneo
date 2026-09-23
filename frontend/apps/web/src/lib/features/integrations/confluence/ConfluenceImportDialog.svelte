<script lang="ts">
  import { tick } from "svelte";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { getEneo } from "$lib/core/Eneo";
  import SelectEmbeddingModel from "$lib/features/ai-models/components/SelectEmbeddingModel.svelte";
  import { getJobManager } from "$lib/features/jobs/JobManager";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { IconSearch } from "@eneo/icons/search";
  import { type IntegrationKnowledgePreview } from "@eneo/eneo-js";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Command from "$lib/components/ui/command/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import type { IntegrationImportDialogProps } from "../IntegrationData";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { toastError } from "$lib/core/errors";

  let { goBack, openController, integration }: IntegrationImportDialogProps = $props();

  const eneo = getEneo();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();
  const { startUpdatePolling, updateJobs } = getJobManager();

  const uid = $props.id();
  let filter = $state("");
  let pickerOpen = $state(false);
  let pickerTrigger = $state<HTMLButtonElement | null>(null);
  let selectedResource = $state<IntegrationKnowledgePreview | undefined>();
  let availableResources = $state<IntegrationKnowledgePreview[] | null>(null);
  let filteredResources = $derived.by(() => {
    return (availableResources ?? []).filter((resource) =>
      resource.name.toLowerCase().startsWith(filter.toLowerCase())
    );
  });

  let selectedEmbeddingModel = $state<{ id: string } | null>(null);

  const loadPreview = createAsyncState(async () => {
    const { id } = integration;

    if (!id) {
      toast.warning(m.you_need_to_configure_this_integration_before_using_it());
      goBack();
      return;
    }

    const preview = await eneo.integrations.knowledge.preview({ id });
    availableResources = preview;
  });

  function selectResource(resource: IntegrationKnowledgePreview) {
    selectedResource = resource;
    pickerOpen = false;
    filter = "";
    void tick().then(() => pickerTrigger?.focus());
  }

  const importKnowledge = createAsyncState(async () => {
    if (!selectedResource) return;
    if (!selectedEmbeddingModel) return;
    // Need to destructure for ts narrowing
    const { id } = integration;
    if (!id) return;

    try {
      await eneo.integrations.knowledge.import({
        integration: { id },
        preview: selectedResource,
        embedding_model: selectedEmbeddingModel,
        space: $currentSpace
      });

      refreshCurrentSpace();
      updateJobs();
      // Make sure we're also polling for further updates (polling will stop once all jobs are finished)
      startUpdatePolling();
      selectedResource = undefined; // Reset in case something else should be added
      $openController = false;
    } catch (error) {
      toastError(error);
    }
  });

  $effect(() => {
    if ($openController && availableResources === null) {
      loadPreview();
    }
  });
</script>

<Dialog.Root bind:open={$openController}>
  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{m.import_knowledge_from_confluence()}</Dialog.Title>
    </Dialog.Header>

    <div class={dialogLayout.body}>
      <div class={dialogLayout.section}>
        {#if $currentSpace.embedding_models.length < 1}
          <p
            class="label-warning border-label-default bg-label-dimmer text-label-stronger m-4 rounded-md border px-2 py-1 text-sm"
          >
            <span class="font-bold">{m.warning()}:</span>
            {m.warning_no_embedding_models()}
          </p>
          <div class="border-default border-t"></div>
        {/if}

        <Field.Field class="p-4">
          <Field.Label id={`${uid}-resource-label`} for={`${uid}-resource`}
            >{m.import_knowledge_from()}</Field.Label
          >
          <Popover.Root bind:open={pickerOpen}>
            <Popover.Trigger>
              {#snippet child({ props })}
                <button
                  {...props}
                  bind:this={pickerTrigger}
                  id={`${uid}-resource`}
                  aria-labelledby={`${uid}-resource-label ${uid}-resource`}
                  type="button"
                  class={buttonVariants({
                    variant: "outline",
                    class: "w-full justify-between font-normal"
                  })}
                >
                  <span class="truncate" class:text-muted={!selectedResource}>
                    {selectedResource?.name ?? m.find_confluence_space()}
                  </span>
                  <IconSearch />
                </button>
              {/snippet}
            </Popover.Trigger>
            <Popover.Content align="start" class="w-(--bits-popover-anchor-width) p-0">
              <Command.Root shouldFilter={false}>
                <Command.Input bind:value={filter} placeholder={m.find_confluence_space()} />
                <Command.List>
                  {#if loadPreview.isLoading}
                    <div class="flex gap-2 px-2 py-1.5 text-sm">
                      <IconLoadingSpinner class="animate-spin"></IconLoadingSpinner>
                      {m.loading_available_spaces()}
                    </div>
                  {:else}
                    {#each filteredResources as resource (resource.key)}
                      <Command.Item value={resource.key} onSelect={() => selectResource(resource)}>
                        <span class="truncate">{resource.name}</span>
                      </Command.Item>
                    {:else}
                      <p class="text-secondary px-2 py-1.5 text-sm">
                        {m.no_matching_spaces_found()}
                      </p>
                    {/each}
                  {/if}
                </Command.List>
              </Command.Root>
            </Popover.Content>
          </Popover.Root>
        </Field.Field>

        {#if $currentSpace.embedding_models.length > 1}
          <div class="border-default w-full border-b"></div>
        {/if}

        <SelectEmbeddingModel
          hideWhenNoOptions
          bind:value={selectedEmbeddingModel}
          selectableModels={$currentSpace.embedding_models}
        ></SelectEmbeddingModel>
      </div>
    </div>

    <Dialog.Footer class={dialogLayout.footer}>
      <Button variant="ghost" onclick={goBack}>{m.back()}</Button>
      <Button
        disabled={importKnowledge.isLoading ||
          !selectedResource ||
          $currentSpace.embedding_models.length === 0}
        onclick={importKnowledge}
      >
        {importKnowledge.isLoading ? m.importing() : m.import_space()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
