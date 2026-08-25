<script lang="ts">
  import { page } from "$app/state";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { getEneo } from "$lib/core/Eneo";
  import SelectEmbeddingModel from "$lib/features/ai-models/components/SelectEmbeddingModel.svelte";
  import { getJobManager } from "$lib/features/jobs/JobManager";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { IconSearch } from "@eneo/icons/search";
  import { IconUploadCloud } from "@eneo/icons/upload-cloud";
  import { IconWeb } from "@eneo/icons/web";
  import { type IntegrationKnowledgePreview } from "@eneo/eneo-js";
  import { Button, Dialog } from "@eneo/ui";
  import { createCombobox } from "@melt-ui/svelte";
  import type { IntegrationImportDialogProps } from "../IntegrationData";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { toastError } from "$lib/core/errors";
  import { SvelteMap, SvelteSet } from "svelte/reactivity";
  import SharePointFolderTree from "./SharePointFolderTree.svelte";
  import { buildSharePointSelectionKey, normalizeSharePointPath } from "./selectionKey";
  import {
    fetchSharePointFixturePreview,
    isSharePointFixtureModeRequested,
    parseSharePointFixtureScenario,
    type SharePointFixtureScenario
  } from "./fixtureMode";

  type PreviewCategory = "my_teams" | "other_sites" | "onedrive";

  type CategorizedIntegrationKnowledgePreview = IntegrationKnowledgePreview & {
    category?: PreviewCategory;
  };

  type PreviewOption = {
    label: string;
    value: CategorizedIntegrationKnowledgePreview;
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

  const eneo = getEneo();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();
  const { addJob, startFastUpdatePolling } = getJobManager();
  const CATEGORY_ORDER: PreviewCategory[] = ["my_teams", "other_sites", "onedrive"];
  let fixtureScenario = $derived(parseSharePointFixtureScenario(page.url.searchParams));
  let isFixtureModeRequested = $derived(isSharePointFixtureModeRequested(page.url.searchParams));

  let availableResources = $state<PreviewOption[] | null>(null);
  let loadedPreviewSource = $state<"fixture" | "real" | null>(null);
  let loadedFixtureScenario = $state<SharePointFixtureScenario | null>(null);
  let loadedPreviewSourceKey = $state<string | null>(null);
  let requestedPreviewSourceKey = $derived(
    isFixtureModeRequested
      ? `fixture:${fixtureScenario ?? "invalid"}`
      : `real:${integration.id ?? "missing"}`
  );
  let isFixtureSession = $derived(isFixtureModeRequested || loadedPreviewSource === "fixture");
  let fixtureTreeScenario = $derived(fixtureScenario ?? loadedFixtureScenario);

  function getPreviewCategory(site: CategorizedIntegrationKnowledgePreview): PreviewCategory {
    if (site.type === "onedrive") return "onedrive";
    // Coerce unknown/legacy category values so no site is dropped from grouping.
    return site.category === "my_teams" ? "my_teams" : "other_sites";
  }

  function getCategoryRank(category: PreviewCategory): number {
    const idx = CATEGORY_ORDER.indexOf(category);
    return idx === -1 ? CATEGORY_ORDER.length : idx;
  }

  function getCategoryLabel(category: PreviewCategory): string {
    switch (category) {
      case "my_teams":
        return m.sharepoint_category_my_teams();
      case "other_sites":
        return m.sharepoint_category_other_sites();
      case "onedrive":
        return "OneDrive";
    }
  }

  function getFixtureScenarioLabel(scenario: SharePointFixtureScenario): string {
    switch (scenario) {
      case "representative":
        return m.sharepoint_fixture_scenario_representative();
      case "large_tenant":
        return m.sharepoint_fixture_scenario_large_tenant();
      case "empty":
        return m.sharepoint_fixture_scenario_empty();
    }
  }

  function normalizePreviewSite(
    site: IntegrationKnowledgePreview
  ): CategorizedIntegrationKnowledgePreview {
    const category = site.category;
    return {
      ...site,
      category:
        category === "my_teams" || category === "other_sites" || category === "onedrive"
          ? category
          : undefined
    };
  }

  let filteredResources = $derived.by(() => {
    const search = $inputValue.toLowerCase();
    return (availableResources ?? []).filter((resource) =>
      resource.value.name.toLowerCase().includes(search)
    );
  });

  let groupedFilteredResources = $derived.by(() => {
    const grouped = new SvelteMap<PreviewCategory, PreviewOption[]>();
    for (const resource of filteredResources) {
      const category = getPreviewCategory(resource.value);
      const existing = grouped.get(category);
      if (existing) {
        existing.push(resource);
      } else {
        grouped.set(category, [resource]);
      }
    }

    return CATEGORY_ORDER.map((category) => ({
      category,
      items: grouped.get(category) ?? []
    })).filter((group) => group.items.length > 0);
  });

  let selectedSite = $state<CategorizedIntegrationKnowledgePreview | null>(null);
  let selectedEmbeddingModel = $state<{ id: string } | null>(null);
  let selectedItems = $state<SelectedImportItem[]>([]);
  let wrapperName = $state("");

  const loadPreview = createAsyncState(async () => {
    const { id } = integration;
    const activeFixtureScenario = fixtureScenario;
    const fixtureModeWasRequested = isFixtureModeRequested;
    loadedPreviewSourceKey = requestedPreviewSourceKey;
    loadedPreviewSource = null;
    loadedFixtureScenario = null;
    availableResources = null;
    selectedSite = null;
    selectedItems = [];
    wrapperName = "";

    if (fixtureModeWasRequested && !activeFixtureScenario) {
      availableResources = [];
      return;
    }

    if (!fixtureModeWasRequested && !id) {
      toast.warning(m.you_need_to_configure_this_integration_before_using_it());
      goBack();
      return;
    }

    try {
      let preview: CategorizedIntegrationKnowledgePreview[];
      if (activeFixtureScenario) {
        preview = (
          await fetchSharePointFixturePreview(eneo.client, activeFixtureScenario)
        ).items.map(normalizePreviewSite);
        loadedPreviewSource = "fixture";
        loadedFixtureScenario = activeFixtureScenario;
      } else {
        if (!id) return;
        preview = (
          await eneo.integrations.knowledge.preview({
            id
          })
        ).map(normalizePreviewSite);
        loadedPreviewSource = "real";
      }

      availableResources = preview
        .map((site) => ({
          label: site.name,
          value: site
        }))
        .sort((a, b) => {
          const categoryDiff =
            getCategoryRank(getPreviewCategory(a.value)) -
            getCategoryRank(getPreviewCategory(b.value));
          if (categoryDiff !== 0) return categoryDiff;
          return a.label.localeCompare(b.label);
        });
    } catch (error) {
      toastError(error);
    }
  });

  const {
    elements: { menu, input, option },
    states: { open, inputValue }
  } = createCombobox<CategorizedIntegrationKnowledgePreview>({
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
    const excludedKeys = new SvelteSet<string>();

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

  let requiresWrapperName = $derived.by(() => dedupedSelection.effectiveEntries.length > 1);
  let wrapperNameMissing = $derived.by(
    () => requiresWrapperName && wrapperName.trim().length === 0
  );

  const importKnowledge = createAsyncState(async () => {
    if (isFixtureSession || loadedPreviewSource !== "real") return;
    if (!selectedSite) return;
    if (!selectedEmbeddingModel) return;
    if (dedupedSelection.effectiveEntries.length === 0) return;

    const { id } = integration;
    if (!id) return;

    const site = selectedSite;

    try {
      const resourceType = site.type === "onedrive" ? "onedrive" : "site";
      const batchItems = dedupedSelection.effectiveEntries.map((entry) => {
        const trimmedName = entry.importName.trim();
        const name = trimmedName.length > 0 ? trimmedName : getDefaultImportName(entry.item);

        if (entry.item.type === "site_root") {
          return {
            key: site.key,
            name,
            url: site.url ?? "",
            type: "site_root",
            resource_type: resourceType
          };
        }

        return {
          key: site.key,
          name,
          url: entry.item.web_url ?? "",
          folder_id: entry.item.id,
          folder_path: entry.item.path,
          type: entry.item.type,
          resource_type: resourceType
        };
      });

      const response = await eneo.integrations.knowledge.importBatch({
        integration: { id },
        items: batchItems,
        wrapper_name: requiresWrapperName ? wrapperName.trim() : undefined,
        embedding_model: selectedEmbeddingModel,
        space: $currentSpace
      });

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const createdItems = response.items.filter((item: any) => item.status === "created");
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const failedItems = response.items.filter((item: any) => item.status === "failed");

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      createdItems.forEach((item: any) => {
        if (item.job) {
          addJob(item.job);
        }
      });

      refreshCurrentSpace();
      startFastUpdatePolling();

      if (createdItems.length === 0) {
        toast.error(m.sharepoint_batch_import_all_failed({ failed: failedItems.length }));
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
      toastError(error);
    }
  });

  const handleSiteSelect = (site: CategorizedIntegrationKnowledgePreview) => {
    selectedSite = site;
    selectedItems = [];
    wrapperName = "";
    $inputValue = site.name;
  };

  $effect(() => {
    if (!$openController) {
      if (loadedPreviewSource === null) {
        loadedPreviewSourceKey = null;
      }
      return;
    }
    if (loadedPreviewSourceKey !== requestedPreviewSourceKey) {
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
      {#if isFixtureSession}
        <div
          role="alert"
          class="label-warning border-label-default bg-label-dimmer text-label-stronger m-4 rounded-md border px-3 py-2 text-sm"
        >
          <div class="font-bold">
            {m.sharepoint_fixture_banner_title({
              scenario: fixtureTreeScenario
                ? getFixtureScenarioLabel(fixtureTreeScenario)
                : m.sharepoint_fixture_scenario_invalid()
            })}
          </div>
          <div>{m.sharepoint_fixture_banner_description()}</div>
        </div>
        <div class="border-default border-t"></div>
      {/if}

      {#if !isFixtureSession && $currentSpace.embedding_models.length < 1}
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
              {:else if groupedFilteredResources.length > 0}
                {#each groupedFilteredResources as group (group.category)}
                  <div
                    class="text-secondary px-2 pt-2 pb-1 text-xs font-medium tracking-wide uppercase"
                  >
                    {getCategoryLabel(group.category)}
                  </div>
                  {#each group.items as previewItem (previewItem.value.key)}
                    {@const item = $state.snapshot(previewItem)}
                    {@const previewIsOneDrive = item.value.type === "onedrive"}
                    <li
                      {...$option(item)}
                      use:option
                      class="hover:bg-hover-default flex items-center gap-2 rounded-md px-2 py-1 hover:cursor-pointer"
                    >
                      {#if previewIsOneDrive}
                        <IconUploadCloud class="text-secondary h-4 w-4 flex-shrink-0" />
                      {:else}
                        <IconWeb class="text-secondary h-4 w-4 flex-shrink-0" />
                      {/if}
                      <span class="text-primary truncate py-1">
                        {item.value.name}
                      </span>
                    </li>
                  {/each}
                {/each}
              {:else}
                <span class="text-secondary px-2 py-1">{m.no_matching_sites_found()}</span>
              {/if}
            </div>
          </ul>
        </div>
      {:else}
        <div
          class="flex max-h-[56vh] min-h-0 flex-col gap-3 overflow-x-hidden overflow-y-auto pr-1"
        >
          <SharePointFolderTree
            userIntegrationId={integration.id || ""}
            spaceId={$currentSpace.id}
            siteId={selectedSite.type === "onedrive" ? undefined : selectedSite.key}
            driveId={selectedSite.type === "onedrive" ? selectedSite.key : undefined}
            siteName={selectedSite.name}
            isOneDrive={isOneDrive ?? false}
            fixtureScenario={fixtureTreeScenario ?? undefined}
            {selectedItemKeys}
            onToggleSelect={toggleSelectedItem}
          />

          {#if selectedItems.length > 0}
            <div class="bg-accent-dimmer border-accent mx-4 mb-1 rounded-md border px-3 py-2">
              <div class="text-sm font-medium">
                {m.sharepoint_selected_items_count({ count: selectedItems.length })}
              </div>
              {#if dedupedSelection.skippedCount > 0}
                <div class="text-secondary mt-1 text-xs">
                  {m.sharepoint_nested_selection_notice({ count: dedupedSelection.skippedCount })}
                </div>
              {/if}
            </div>

            {#if requiresWrapperName}
              <div class="mx-4 mb-1">
                <label for="sharepoint-wrapper-name" class="text-secondary mb-1 block text-xs">
                  {m.sharepoint_wrapper_name_label()} <span class="text-label-stronger">*</span>
                </label>
                <p class="text-secondary mb-1 text-xs">
                  {m.sharepoint_wrapper_name_required_hint()}
                </p>
                <input
                  id="sharepoint-wrapper-name"
                  class="border-default bg-primary w-full rounded border px-2 py-1 text-sm"
                  class:border-label-default={wrapperNameMissing}
                  value={wrapperName}
                  placeholder={m.sharepoint_wrapper_name_placeholder()}
                  oninput={(event) => {
                    const target = event.currentTarget as HTMLInputElement;
                    wrapperName = target.value;
                  }}
                />
                {#if wrapperNameMissing}
                  <p class="text-label-stronger mt-1 text-xs">
                    {m.sharepoint_wrapper_name_missing_hint()}
                  </p>
                {/if}
              </div>
            {/if}

            <div
              class="border-default mx-4 mb-2 max-h-48 overflow-x-hidden overflow-y-auto rounded-md border"
            >
              {#each selectedItems as selection (selection.selectionKey)}
                <div class="border-dimmer border-b px-3 py-2 last:border-b-0">
                  <div class="flex items-center gap-2">
                    <input
                      class="border-default bg-primary min-w-0 flex-1 rounded border px-2 py-1 text-sm"
                      value={selection.importName}
                      oninput={(event) => handleSelectionNameInput(selection.selectionKey, event)}
                    />
                    <button
                      type="button"
                      class="text-secondary hover:text-primary text-xs underline"
                      onclick={() => removeSelectedItem(selection.selectionKey)}
                    >
                      {m.remove()}
                    </button>
                  </div>
                  <div class="text-secondary mt-1 flex min-w-0 items-center gap-2 text-xs">
                    <span class="min-w-0 flex-1 truncate">{selection.item.path}</span>
                    {#if selection.item.size != null}
                      <span class="flex-shrink-0">({formatSize(selection.item.size)})</span>
                    {/if}
                    {#if dedupedSelection.excludedKeys.has(selection.selectionKey)}
                      <span class="text-secondary flex-shrink-0">
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

      {#if !isFixtureSession}
        {#if $currentSpace.embedding_models.length > 1}
          <div class="border-default w-full border-b"></div>
        {/if}

        <SelectEmbeddingModel
          hideWhenNoOptions
          bind:value={selectedEmbeddingModel}
          selectableModels={$currentSpace.embedding_models}
        ></SelectEmbeddingModel>
      {/if}
    </Dialog.Section>

    <Dialog.Controls>
      {#if wrapperNameMissing}
        <span class="text-secondary mr-auto text-xs"
          >{m.sharepoint_wrapper_name_missing_hint()}</span
        >
      {/if}
      <Button
        onclick={() => {
          if (selectedSite) {
            selectedSite = null;
            selectedItems = [];
            wrapperName = "";
          } else {
            goBack();
          }
        }}>{m.back()}</Button
      >
      {#if isFixtureSession}
        <Button variant="primary" disabled>{m.sharepoint_fixture_import_disabled()}</Button>
      {:else}
        <Button
          variant="primary"
          disabled={importKnowledge.isLoading ||
            $currentSpace.embedding_models.length === 0 ||
            !selectedSite ||
            dedupedSelection.effectiveEntries.length === 0 ||
            wrapperNameMissing}
          onclick={importKnowledge}
        >
          {importKnowledge.isLoading ? m.importing() : m.import()}
        </Button>
      {/if}
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
