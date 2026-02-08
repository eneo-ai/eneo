<script lang="ts">
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { getIntric } from "$lib/core/Intric";
  import SelectEmbeddingModel from "$lib/features/ai-models/components/SelectEmbeddingModel.svelte";
  import { getJobManager } from "$lib/features/jobs/JobManager";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IconSearch } from "@intric/icons/search";
  import { IconUploadCloud } from "@intric/icons/upload-cloud";
  import { IconWeb } from "@intric/icons/web";
  import { IntricError, type IntegrationKnowledgePreview } from "@intric/intric-js";
  import { Button, Dialog } from "@intric/ui";
  import { createCombobox } from "@melt-ui/svelte";
  import type { IntegrationImportDialogProps } from "../IntegrationData";
  import { m } from "$lib/paraglide/messages";
  import SharePointFolderTree from "./SharePointFolderTree.svelte";

  type PreviewOption = {
    label: string;
    value: IntegrationKnowledgePreview;
  };

  type SelectedItem = {
    id: string;
    name: string;
    type: "file" | "folder" | "site_root";
    path: string;
    web_url?: string;
    size?: number;
  };

  let { goBack, openController, integration }: IntegrationImportDialogProps = $props();

  const intric = getIntric();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();
  const { addJob, startFastUpdatePolling } = getJobManager();

  let availableResources = $state<PreviewOption[] | null>(null);
  let filteredResources = $derived.by(() => {
    return (availableResources ?? []).filter((resource) =>
      resource.value.name.toLowerCase().startsWith($inputValue.toLowerCase())
    );
  });

  let selectedSite = $state<IntegrationKnowledgePreview | null>(null);
  let selectedItem = $state<SelectedItem | null>(null);
  let selectedEmbeddingModel = $state<{ id: string } | null>(null);

  const loadPreview = createAsyncState(async () => {
    const { id } = integration;

    if (!id) {
      alert(m.you_need_to_configure_this_integration_before_using_it());
      goBack();
      return;
    }

    const preview = await intric.integrations.knowledge.preview({ id });
    availableResources = preview.map((site) => {
      return {
        label: site.name,
        value: site
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
    },
    onSelectedChange({ next }) {
      if (next) {
        handleSiteSelect(next.value);
        $open = false;
      }
      return undefined; // Clear selection after handling
    }
  });

  const importKnowledge = createAsyncState(async () => {
    if (!selectedSite && !selectedItem) return;
    if (!selectedEmbeddingModel) return;
    const { id } = integration;
    if (!id) return;

    try {
      let importData: any = {
        integration: { id },
        embedding_model: selectedEmbeddingModel,
        space: $currentSpace
      };

      if (selectedItem && selectedItem.type === "site_root") {
        // "Import entire site" — same as selecting the site directly
        importData.preview = {
          ...selectedSite,
          resource_type: selectedSite?.type === "onedrive" ? "onedrive" : "site"
        };
      } else if (selectedItem) {
        importData.preview = {
          key: selectedSite?.key, // Use site ID for SharePoint, drive ID for OneDrive
          name: selectedItem.name,
          type: selectedItem.type,
          url: selectedItem.web_url || selectedItem.path,
          folder_id: selectedItem.id,
          folder_path: selectedItem.path,
          resource_type: selectedSite?.type === "onedrive" ? "onedrive" : "site"
        };
      } else if (selectedSite) {
        importData.preview = {
          ...selectedSite,
          resource_type: selectedSite.type === "onedrive" ? "onedrive" : "site"
        };
      }

      const job = await intric.integrations.knowledge.import(importData);

      // Add job to JobManager for real-time tracking and close dialog
      addJob(job);
      refreshCurrentSpace();
      startFastUpdatePolling(); // Use fast polling for quicker UI updates
      $inputValue = "";
      selectedSite = null;
      selectedItem = null;
      $openController = false;
    } catch (error) {
      const errorMessage =
        error instanceof IntricError ? error.getReadableMessage() : String(error);
      alert(errorMessage);
      // Don't close dialog on error - let user try again
    }
  });

  const handleSiteSelect = (site: IntegrationKnowledgePreview) => {
    selectedSite = site;
    $inputValue = site.name;
  };

  const handleFolderSelect = (item: { id: string; name: string; type: string; path: string; size?: number }) => {
    selectedItem = item as SelectedItem;
  };

  $effect(() => {
    if ($openController && availableResources === null) {
      loadPreview();
    }
  });

  let isOneDrive = $derived(selectedSite?.type === "onedrive");

  function formatSize(bytes?: number): string {
    if (bytes == null) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  let inputElement = $state<HTMLInputElement>();
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="medium">
    <Dialog.Title>{m.import_knowledge_from_sharepoint()}</Dialog.Title>

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

      {#if !selectedSite}
        <div class="flex flex-grow flex-col gap-1 rounded-md p-4">
          <div>
            <span class="pl-3 font-medium">{m.import_knowledge_from()}</span>
          </div>
          <div class="relative flex flex-grow">
            <input
              bind:this={inputElement}
              placeholder={m.find_sharepoint_site()}
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
                  {m.loading_available_sites()}
                </div>
              {:else if filteredResources.length > 0}
                {#each filteredResources as previewItem (previewItem.value.key)}
                  {@const item = $state.snapshot(previewItem)}
                  {@const isOneDrive = item.value.type === "onedrive"}
                  <li
                    {...$option(item)}
                    use:option
                    class="hover:bg-hover-default flex items-center gap-2 rounded-md px-2 py-1 hover:cursor-pointer"
                  >
                    {#if isOneDrive}
                      <IconUploadCloud class="w-4 h-4 text-secondary flex-shrink-0" />
                    {:else}
                      <IconWeb class="w-4 h-4 text-secondary flex-shrink-0" />
                    {/if}
                    <span class="text-primary truncate py-1">
                      {item.value.name}
                    </span>
                  </li>
                {/each}
              {:else}
                <span class="text-secondary px-2 py-1">{m.no_matching_sites_found()}</span>
              {/if}
            </div>
          </ul>
        </div>
      {:else}
        <div class="flex flex-col">
          <SharePointFolderTree
            userIntegrationId={integration.id || ""}
            spaceId={$currentSpace.id}
            siteId={selectedSite.type === "onedrive" ? undefined : selectedSite.key}
            driveId={selectedSite.type === "onedrive" ? selectedSite.key : undefined}
            siteName={selectedSite.name}
            isOneDrive={isOneDrive ?? false}
            selectedItemId={selectedItem?.id ?? undefined}
            onSelect={handleFolderSelect}
          />

          <!-- Selection summary bar -->
          {#if selectedItem}
            <div class="mx-4 mb-3 px-3 py-2 bg-accent-dimmer border border-accent rounded-md flex items-center gap-2 text-sm">
              <span class="font-medium truncate">{selectedItem.name}</span>
              {#if selectedItem.size != null}
                <span class="text-xs text-secondary flex-shrink-0">({formatSize(selectedItem.size)})</span>
              {/if}
              {#if selectedItem.type === "site_root"}
                <span class="text-xs text-secondary flex-shrink-0">
                  ({isOneDrive ? m.entire_onedrive() : m.entire_site()})
                </span>
              {/if}
            </div>
          {/if}
        </div>
      {/if}

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
      <Button onclick={() => {
        if (selectedSite) {
          selectedSite = null;
          selectedItem = null;
        } else {
          goBack();
        }
      }}>{m.back()}</Button>
      <Button
        variant="primary"
        disabled={importKnowledge.isLoading || $currentSpace.embedding_models.length === 0 || (!selectedSite && !selectedItem)}
        onclick={importKnowledge}
      >
        {importKnowledge.isLoading ? m.importing() : m.import()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
