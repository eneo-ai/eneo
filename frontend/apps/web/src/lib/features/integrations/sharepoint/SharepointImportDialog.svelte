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
  import {
    buildSharePointSelectionKey,
    normalizeSharePointPath
  } from "./selectionKey";

  type PreviewOption = {
    label: string;
    value: IntegrationKnowledgePreview;
  };

  type SelectedTreeItem = {
    id: string;
    name: string;
    type: "file" | "folder" | "site_root";
    path: string;
    web_url?: string;
    size?: number;
  };

  type SelectedImportItem = {
    selectionKey: string;
    item: SelectedTreeItem;
    importName: string;
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
  let selectedEmbeddingModel = $state<{ id: string } | null>(null);
  let selectedItems = $state<SelectedImportItem[]>([]);
  let wrapperName = $state("");

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
    states: { open, inputValue }
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
      return undefined;
    }
  });

  function isDescendantPath(path: string, ancestorPath: string): boolean {
    const normalizedPath = normalizeSharePointPath(path);
    const normalizedAncestor = normalizeSharePointPath(ancestorPath);
    if (normalizedAncestor === "/") {
      return normalizedPath !== "/";
    }
    return normalizedPath.startsWith(`${normalizedAncestor}/`);
  }

  function getSelectionKey(item: SelectedTreeItem): string {
    return buildSharePointSelectionKey(item);
  }

  function getDefaultImportName(item: SelectedTreeItem): string {
    return item.name;
  }

  function updateSelectionName(selectionKey: string, nextName: string) {
    selectedItems = selectedItems.map((entry) => {
      if (entry.selectionKey !== selectionKey) return entry;
      return { ...entry, importName: nextName };
    });
  }

  function handleSelectionNameInput(selectionKey: string, event: Event) {
    const target = event.currentTarget as HTMLInputElement;
    updateSelectionName(selectionKey, target.value);
  }

  function removeSelectedItem(selectionKey: string) {
    selectedItems = selectedItems.filter((entry) => entry.selectionKey !== selectionKey);
  }

  function toggleSelectedItem(item: SelectedTreeItem) {
    const selectionKey = getSelectionKey(item);
    const existing = selectedItems.find((entry) => entry.selectionKey === selectionKey);
    if (existing) {
      removeSelectedItem(selectionKey);
      return;
    }

    selectedItems = [
      ...selectedItems,
      {
        selectionKey,
        item,
        importName: getDefaultImportName(item)
      }
    ];
  }

  let selectedItemKeys = $derived.by(() => selectedItems.map((entry) => entry.selectionKey));

  let dedupedSelection = $derived.by(() => {
    const sortedItems = [...selectedItems].sort(
      (a, b) =>
        normalizeSharePointPath(a.item.path).length - normalizeSharePointPath(b.item.path).length
    );

    const effectiveEntries: SelectedImportItem[] = [];
    const excludedKeys = new Set<string>();

    for (const entry of sortedItems) {
      const blockedByParent = effectiveEntries.some((existing) => {
        if (existing.selectionKey === entry.selectionKey) return false;
        if (existing.item.type !== "folder" && existing.item.type !== "site_root") {
          return false;
        }
        return isDescendantPath(entry.item.path, existing.item.path);
      });

      if (blockedByParent) {
        excludedKeys.add(entry.selectionKey);
        continue;
      }

      effectiveEntries.push(entry);
    }

    return {
      effectiveEntries,
      excludedKeys,
      skippedCount: excludedKeys.size
    };
  });

  const importKnowledge = createAsyncState(async () => {
    if (!selectedSite) return;
    if (!selectedEmbeddingModel) return;
    if (dedupedSelection.effectiveEntries.length === 0) return;

    const { id } = integration;
    if (!id) return;

    try {
      const resourceType = selectedSite.type === "onedrive" ? "onedrive" : "site";
      const batchItems = dedupedSelection.effectiveEntries.map((entry) => {
        const trimmedName = entry.importName.trim();
        const name = trimmedName.length > 0 ? trimmedName : getDefaultImportName(entry.item);

        if (entry.item.type === "site_root") {
          return {
            key: selectedSite.key,
            name,
            url: selectedSite.url ?? "",
            type: "site_root",
            resource_type: resourceType
          };
        }

        return {
          key: selectedSite.key,
          name,
          url: entry.item.web_url ?? "",
          folder_id: entry.item.id,
          folder_path: entry.item.path,
          type: entry.item.type,
          resource_type: resourceType
        };
      });

      const response = await intric.integrations.knowledge.importBatch({
        integration: { id },
        items: batchItems,
        wrapper_name: dedupedSelection.effectiveEntries.length > 1 ? wrapperName.trim() : undefined,
        embedding_model: selectedEmbeddingModel,
        space: $currentSpace
      });

      const createdItems = response.items.filter((item: any) => item.status === "created");
      const failedItems = response.items.filter((item: any) => item.status === "failed");

      createdItems.forEach((item: any) => {
        if (item.job) {
          addJob(item.job);
        }
      });

      refreshCurrentSpace();
      startFastUpdatePolling();

      if (createdItems.length === 0) {
        alert(m.sharepoint_batch_import_all_failed({ failed: failedItems.length }));
        return;
      }

      if (failedItems.length > 0) {
        console.warn("SharePoint batch import had failures", {
          created: createdItems.length,
          total: response.items.length,
          failed: failedItems.length
        });
      }

      $inputValue = "";
      selectedSite = null;
      selectedItems = [];
      wrapperName = "";
      $openController = false;
    } catch (error) {
      const errorMessage =
        error instanceof IntricError ? error.getReadableMessage() : String(error);
      alert(errorMessage);
    }
  });

  const handleSiteSelect = (site: IntegrationKnowledgePreview) => {
    selectedSite = site;
    selectedItems = [];
    wrapperName = "";
    $inputValue = site.name;
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
                  {@const previewIsOneDrive = item.value.type === "onedrive"}
                  <li
                    {...$option(item)}
                    use:option
                    class="hover:bg-hover-default flex items-center gap-2 rounded-md px-2 py-1 hover:cursor-pointer"
                  >
                    {#if previewIsOneDrive}
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
        <div class="flex flex-col gap-3">
          <SharePointFolderTree
            userIntegrationId={integration.id || ""}
            spaceId={$currentSpace.id}
            siteId={selectedSite.type === "onedrive" ? undefined : selectedSite.key}
            driveId={selectedSite.type === "onedrive" ? selectedSite.key : undefined}
            siteName={selectedSite.name}
            isOneDrive={isOneDrive ?? false}
            selectedItemKeys={selectedItemKeys}
            onToggleSelect={toggleSelectedItem}
          />

          {#if selectedItems.length > 0}
            <div class="mx-4 mb-1 px-3 py-2 bg-accent-dimmer border border-accent rounded-md">
              <div class="text-sm font-medium">
                {m.sharepoint_selected_items_count({ count: selectedItems.length })}
              </div>
              {#if dedupedSelection.skippedCount > 0}
                <div class="text-xs text-secondary mt-1">
                  {m.sharepoint_nested_selection_notice({ count: dedupedSelection.skippedCount })}
                </div>
              {/if}
            </div>

            {#if dedupedSelection.effectiveEntries.length > 1}
              <div class="mx-4 mb-1">
                <label class="text-xs text-secondary block mb-1">
                  {m.sharepoint_wrapper_name_label()}
                </label>
                <input
                  class="border border-default bg-primary rounded px-2 py-1 text-sm w-full"
                  value={wrapperName}
                  placeholder={m.sharepoint_wrapper_name_placeholder()}
                  oninput={(event) => {
                    const target = event.currentTarget as HTMLInputElement;
                    wrapperName = target.value;
                  }}
                />
              </div>
            {/if}

            <div class="mx-4 mb-2 border border-default rounded-md max-h-48 overflow-y-auto">
              {#each selectedItems as selection (selection.selectionKey)}
                <div class="px-3 py-2 border-b border-dimmer last:border-b-0">
                  <div class="flex items-center gap-2">
                    <input
                      class="border border-default bg-primary rounded px-2 py-1 text-sm flex-1 min-w-0"
                      value={selection.importName}
                      oninput={(event) => handleSelectionNameInput(selection.selectionKey, event)}
                    />
                    <button
                      type="button"
                      class="text-xs text-secondary hover:text-primary underline"
                      onclick={() => removeSelectedItem(selection.selectionKey)}
                    >
                      {m.remove()}
                    </button>
                  </div>
                  <div class="mt-1 flex items-center gap-2 text-xs text-secondary">
                    <span class="truncate">{selection.item.path}</span>
                    {#if selection.item.size != null}
                      <span class="flex-shrink-0">({formatSize(selection.item.size)})</span>
                    {/if}
                    {#if dedupedSelection.excludedKeys.has(selection.selectionKey)}
                      <span class="flex-shrink-0 text-secondary">
                        {m.sharepoint_nested_selection_skipped()}
                      </span>
                    {/if}
                  </div>
                </div>
              {/each}
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
          selectedItems = [];
          wrapperName = "";
        } else {
          goBack();
        }
      }}>{m.back()}</Button>
      <Button
        variant="primary"
        disabled={importKnowledge.isLoading || $currentSpace.embedding_models.length === 0 || !selectedSite || dedupedSelection.effectiveEntries.length === 0 || (dedupedSelection.effectiveEntries.length > 1 && wrapperName.trim().length === 0)}
        onclick={importKnowledge}
      >
        {importKnowledge.isLoading ? m.importing() : m.import()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
