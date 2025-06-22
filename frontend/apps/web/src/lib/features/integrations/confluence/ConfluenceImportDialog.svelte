<script lang="ts">
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { getIntric } from "$lib/core/Intric";
  import SelectEmbeddingModel from "$lib/features/ai-models/components/SelectEmbeddingModel.svelte";
  import { getJobManager } from "$lib/features/jobs/JobManager";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IconSearch } from "@intric/icons/search";
  import { IntricError, type IntegrationKnowledgePreview } from "@intric/intric-js";
  import { Button, Dialog } from "@intric/ui";
  import { createCombobox } from "@melt-ui/svelte";
  import type { IntegrationImportDialogProps } from "../IntegrationData";
  import { m } from "$lib/paraglide/messages";

  type PreviewOption = {
    label: string;
    value: IntegrationKnowledgePreview;
  };

  let { goBack, openController, integration }: IntegrationImportDialogProps = $props();

  const intric = getIntric();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();
  const { startUpdatePolling, updateJobs } = getJobManager();

  let availableResources = $state<PreviewOption[] | null>(null);
  let filteredResources = $derived.by(() => {
    return (availableResources ?? []).filter((resource) =>
      resource.value.name.toLowerCase().startsWith($inputValue.toLowerCase())
    );
  });

  let selectedEmbeddingModel = $state<{ id: string } | null>(null);

  const loadPreview = createAsyncState(async () => {
    const { id } = integration;

    if (!id) {
      alert(m.you_need_to_configure_this_integration_before_using_it());
      goBack();
      return;
    }

    const preview = await intric.integrations.knowledge.preview({ id });
    availableResources = preview.map((space) => {
      return {
        label: space.name,
        value: space
      };
    });
  });

  const {
    elements: { menu, input, option },
    states: { open, inputValue, selected }
  } = createCombobox<IntegrationKnowledgePreview>({
    portal: null,
    positioning: {
      sameWidth: true,
      fitViewport: true,
      placement: "bottom"
    }
  });

  const importKnowledge = createAsyncState(async () => {
    if (!$selected) return;
    if (!selectedEmbeddingModel) return;
    // Need to destructure for ts narrowing
    const { id } = integration;
    if (!id) return;

    try {
      await intric.integrations.knowledge.import({
        integration: { id },
        preview: $selected.value,
        embedding_model: selectedEmbeddingModel,
        space: $currentSpace
      });

      refreshCurrentSpace();
      updateJobs();
      // Make sure we're also polling for further updates (polling will stop once all jobs are finished)
      startUpdatePolling();
      $inputValue = ""; // Reset input in case something else should be added
      $openController = false;
    } catch (error) {
      const errorMessage =
        error instanceof IntricError ? error.getReadableMessage() : String(error);
      alert(errorMessage);
    }
  });

  $effect(() => {
    if (!$open) {
      $inputValue = $selected?.value.name ?? $inputValue;
    }

    if ($openController && availableResources === null) {
      loadPreview();
    }
  });

  let inputElement = $state<HTMLInputElement>();
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="medium">
    <Dialog.Title>{m.import_knowledge_from_confluence()}</Dialog.Title>

    <Dialog.Section scrollable={false}>
      {#if $currentSpace.embedding_models.length < 1}
        <p
          class="label-warning border-label-default bg-label-dimmer text-label-stronger m-4 rounded-md border px-2 py-1 text-sm"
        >
          <span class="font-bold">{m.warning()}:</span>
          {m.warning_no_embedding_models()}
        </p>
        <div class="border-default border-t"></div>
      {/if}

      <div class="flex flex-grow flex-col gap-1 rounded-md p-4">
        <div>
          <span class="pl-3 font-medium">{m.import_knowledge_from()}</span>
        </div>
        <div class="relative flex flex-grow">
          <input
            bind:this={inputElement}
            placeholder={m.find_confluence_space()}
            {...$input}
            required
            use:input
            class="border-stronger bg-primary ring-default placeholder:text-secondary disabled:bg-secondary disabled:text-muted relative
        h-10 w-full items-center justify-between overflow-hidden rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2 disabled:shadow-none disabled:hover:ring-0"
          />
          <button
            onclick={() => {
              inputElement?.focus();
              $open = true;
            }}
          >
            <IconSearch class="absolute top-2 right-4" />
          </button>
        </div>
        <ul
          class="shadow-bg-secondary border-stronger bg-primary relative z-10 flex flex-col gap-1 overflow-y-auto rounded-lg border p-1 shadow-md focus:!ring-0"
          {...$menu}
          use:menu
        >
          <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
          <div class="bg-primary text-primary flex flex-col gap-0" tabindex="0">
            {#if loadPreview.isLoading}
              <div class="flex gap-2 px-2 py-1">
                <IconLoadingSpinner class="animate-spin"></IconLoadingSpinner>
                {m.loading_available_spaces()}
              </div>
            {:else if filteredResources.length > 0}
              {#each filteredResources as previewItem (previewItem.value.key)}
                {@const item = $state.snapshot(previewItem)}
                <li
                  {...$option(item)}
                  use:option
                  class="hover:bg-hover-default flex items-center gap-1 rounded-md px-2 py-1 hover:cursor-pointer"
                >
                  <span class=" text-primary truncate py-1">
                    {item.value.name}
                  </span>
                </li>
              {/each}
            {:else}
              <span class="text-secondary px-2 py-1">{m.no_matching_spaces_found()}</span>
            {/if}
          </div>
        </ul>
      </div>

      {#if $currentSpace.embedding_models.length > 1}
        <div class="border-default w-full border-b"></div>
      {/if}

      <SelectEmbeddingModel
        hideWhenNoOptions
        bind:value={selectedEmbeddingModel}
        selectableModels={$currentSpace.embedding_models}
      ></SelectEmbeddingModel>
    </Dialog.Section>

    <Dialog.Controls>
      <Button onclick={goBack}>{m.back()}</Button>
      <Button
        variant="primary"
        disabled={importKnowledge.isLoading || $currentSpace.embedding_models.length === 0}
        onclick={importKnowledge}
      >
        {importKnowledge.isLoading ? m.importing() : m.import_space()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
