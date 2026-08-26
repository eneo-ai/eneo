<script lang="ts">
  import { page } from "$app/state";
  import { onMount, untrack } from "svelte";
  import { SvelteMap, SvelteSet } from "svelte/reactivity";
  import type { EmbeddingModel, IntegrationKnowledgePreview } from "@eneo/eneo-js";
  import {
    CheckCircle2,
    ChevronDown,
    Cloud,
    FileText,
    FlaskConical,
    Globe2,
    LoaderCircle,
    RefreshCw,
    Trash2,
    Users
  } from "lucide-svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import * as Command from "$lib/components/ui/command/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { getEneo } from "$lib/core/Eneo";
  import { getJobManager } from "$lib/features/jobs/JobManager";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import type { IntegrationImportDialogProps } from "../IntegrationData";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { toastError } from "$lib/core/errors";
  import SharePointFolderTree from "./SharePointFolderTree.svelte";
  import { buildSharePointSelectionKey, normalizeSharePointPath } from "./selectionKey";
  import {
    fetchSharePointFixturePreview,
    isSharePointFixtureModeRequested,
    parseSharePointFixtureScenario,
    type SharePointFixtureScenario
  } from "./fixtureMode";
  import { isSharePointDescendantPath } from "./treeState";

  type PreviewCategory = "my_teams" | "other_sites" | "onedrive";
  type ImportStep = "source" | "content" | "review" | "complete";

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

  type SharePointImportDialogProps = IntegrationImportDialogProps & {
    fixtureScenario?: SharePointFixtureScenario;
  };

  let {
    goBack,
    openController,
    integration,
    fixtureScenario: fixtureScenarioOverride
  }: SharePointImportDialogProps = $props();

  const eneo = getEneo();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();
  const { addJob, startFastUpdatePolling } = getJobManager();
  const CATEGORY_ORDER: PreviewCategory[] = ["my_teams", "other_sites", "onedrive"];
  const steps = [
    { number: 1, label: m.sharepoint_step_source },
    { number: 2, label: m.sharepoint_step_content },
    { number: 3, label: m.sharepoint_step_review }
  ] as const;

  let dialogOpen = $state(false);
  let activeStep = $state<ImportStep>("source");
  let fixtureScenario = $state<SharePointFixtureScenario | null>(
    untrack(() => fixtureScenarioOverride ?? parseSharePointFixtureScenario(page.url.searchParams))
  );
  let fixtureModeRequested = $derived(
    fixtureScenarioOverride !== undefined || isSharePointFixtureModeRequested(page.url.searchParams)
  );
  let availableResources = $state<PreviewOption[] | null>(null);
  let previewLoadFailed = $state(false);
  let loadedPreviewSource = $state<"fixture" | "real" | null>(null);
  let loadedFixtureScenario = $state<SharePointFixtureScenario | null>(null);
  let loadedPreviewSourceKey = $state<string | null>(null);
  let requestedPreviewSourceKey = $derived(
    fixtureModeRequested
      ? `fixture:${fixtureScenario ?? "invalid"}`
      : `real:${integration.id ?? "missing"}`
  );
  let isFixtureSession = $derived(fixtureModeRequested || loadedPreviewSource === "fixture");
  let fixtureTreeScenario = $derived(fixtureScenario ?? loadedFixtureScenario);
  let currentStepNumber = $derived(activeStep === "source" ? 1 : activeStep === "content" ? 2 : 3);

  let sourceFilter = $state("");
  let selectedSite = $state<CategorizedIntegrationKnowledgePreview | null>(null);
  let selectedEmbeddingModel = $state<{ id: string } | null>(null);
  let selectedItems = $state<SelectedImportItem[]>([]);
  let wrapperName = $state("");
  let fixtureDetailsOpen = $state(false);

  onMount(() => openController.subscribe((value) => (dialogOpen = value)));
  $effect(() => {
    openController.set(dialogOpen);
  });

  function getPreviewCategory(site: CategorizedIntegrationKnowledgePreview): PreviewCategory {
    if (site.type === "onedrive") return "onedrive";
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

  function getCategoryIcon(category: PreviewCategory) {
    switch (category) {
      case "my_teams":
        return Users;
      case "other_sites":
        return Globe2;
      case "onedrive":
        return Cloud;
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

  function isFixtureScenario(value: string): value is SharePointFixtureScenario {
    return value === "representative" || value === "large_tenant" || value === "empty";
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
    const search = sourceFilter.trim().toLowerCase();
    if (!search) return availableResources ?? [];
    return (availableResources ?? []).filter((resource) =>
      resource.value.name.toLowerCase().includes(search)
    );
  });

  let groupedFilteredResources = $derived.by(() => {
    const grouped = new SvelteMap<PreviewCategory, PreviewOption[]>();
    for (const resource of filteredResources) {
      const category = getPreviewCategory(resource.value);
      const existing = grouped.get(category);
      if (existing) existing.push(resource);
      else grouped.set(category, [resource]);
    }

    return CATEGORY_ORDER.map((category) => ({
      category,
      items: grouped.get(category) ?? []
    })).filter((group) => group.items.length > 0);
  });

  const loadPreview = createAsyncState(async () => {
    const { id } = integration;
    const activeFixtureScenario = fixtureScenario;
    const fixtureModeWasRequested = fixtureModeRequested;
    loadedPreviewSourceKey = requestedPreviewSourceKey;
    loadedPreviewSource = null;
    loadedFixtureScenario = null;
    availableResources = null;
    previewLoadFailed = false;
    resetSelection();

    if (fixtureModeWasRequested && !activeFixtureScenario) {
      availableResources = [];
      return;
    }

    if (!fixtureModeWasRequested && !id) {
      toast.warning(m.you_need_to_configure_this_integration_before_using_it());
      dialogOpen = false;
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
        preview = (await eneo.integrations.knowledge.preview({ id })).map(normalizePreviewSite);
        loadedPreviewSource = "real";
      }

      availableResources = preview
        .map((site) => ({ label: site.name, value: site }))
        .sort((a, b) => {
          const categoryDiff =
            getCategoryRank(getPreviewCategory(a.value)) -
            getCategoryRank(getPreviewCategory(b.value));
          if (categoryDiff !== 0) return categoryDiff;
          return a.label.localeCompare(b.label);
        });
    } catch (error) {
      previewLoadFailed = true;
      availableResources = [];
      toastError(error);
    }
  });

  function retryPreview() {
    loadedPreviewSourceKey = null;
    loadPreview();
  }

  function resetSelection() {
    activeStep = "source";
    sourceFilter = "";
    selectedSite = null;
    selectedItems = [];
    wrapperName = "";
  }

  function resetFlow() {
    resetSelection();
    fixtureDetailsOpen = false;
    fixtureScenario =
      fixtureScenarioOverride ?? parseSharePointFixtureScenario(page.url.searchParams);
  }

  function handleDialogOpenChange(open: boolean) {
    dialogOpen = open;
    if (!open) resetFlow();
  }

  function returnToIntegrationPicker() {
    resetFlow();
    dialogOpen = false;
    goBack();
  }

  function handleBack() {
    if (activeStep === "review") {
      activeStep = "content";
      return;
    }
    if (activeStep === "content") {
      resetSelection();
      return;
    }
    returnToIntegrationPicker();
  }

  function changeFixtureScenario(value: string) {
    if (!isFixtureScenario(value) || value === fixtureScenario) return;
    fixtureScenario = value;
    loadedPreviewSourceKey = null;
    resetSelection();
  }

  function handleSiteSelect(site: CategorizedIntegrationKnowledgePreview) {
    selectedSite = site;
    selectedItems = [];
    wrapperName = "";
    sourceFilter = "";
    activeStep = "content";
  }

  function getSelectionKey(item: SelectedTreeItem): string {
    return buildSharePointSelectionKey(item);
  }

  function updateSelectionName(selectionKey: string, nextName: string) {
    selectedItems = selectedItems.map((entry) =>
      entry.selectionKey === selectionKey ? { ...entry, importName: nextName } : entry
    );
  }

  function removeSelectedItem(selectionKey: string) {
    selectedItems = selectedItems.filter((entry) => entry.selectionKey !== selectionKey);
  }

  function toggleSelectedItem(item: SelectedTreeItem) {
    const selectionKey = getSelectionKey(item);
    if (selectedItems.some((entry) => entry.selectionKey === selectionKey)) {
      removeSelectedItem(selectionKey);
      return;
    }

    const remainingItems =
      item.type === "folder" || item.type === "site_root"
        ? selectedItems.filter((entry) => !isSharePointDescendantPath(entry.item.path, item.path))
        : selectedItems;
    selectedItems = [...remainingItems, { selectionKey, item, importName: item.name }];
  }

  let selectedItemKeys = $derived(selectedItems.map((entry) => entry.selectionKey));
  let selectedPaths = $derived(selectedItems.map((entry) => entry.item.path));
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
        if (existing.item.type !== "folder" && existing.item.type !== "site_root") return false;
        return isSharePointDescendantPath(entry.item.path, existing.item.path);
      });
      if (blockedByParent) excludedKeys.add(entry.selectionKey);
      else effectiveEntries.push(entry);
    }

    return { effectiveEntries, excludedKeys, skippedCount: excludedKeys.size };
  });

  let requiresWrapperName = $derived(dedupedSelection.effectiveEntries.length > 1);
  let wrapperNameMissing = $derived(requiresWrapperName && wrapperName.trim().length === 0);
  let reviewReady = $derived(
    selectedSite !== null &&
      dedupedSelection.effectiveEntries.length > 0 &&
      !wrapperNameMissing &&
      (isFixtureSession || selectedEmbeddingModel !== null)
  );

  let embeddingModels = $derived($currentSpace.embedding_models);
  let stableEmbeddingModels = $derived(
    embeddingModels.filter((model: EmbeddingModel) => model.stability === "stable")
  );
  let experimentalEmbeddingModels = $derived(
    embeddingModels.filter((model: EmbeddingModel) => model.stability === "experimental")
  );

  $effect(() => {
    if (embeddingModels.length === 0) {
      selectedEmbeddingModel = null;
      return;
    }
    if (
      !selectedEmbeddingModel ||
      !embeddingModels.some((model) => model.id === selectedEmbeddingModel?.id)
    ) {
      selectedEmbeddingModel = { id: embeddingModels[0].id };
    }
  });

  function getModelDisplayName(model: EmbeddingModel): string {
    return model.open_source ? `${model.name} (${m.model_label_open_source()})` : model.name;
  }

  function selectEmbeddingModel(id: string) {
    if (embeddingModels.some((model) => model.id === id)) selectedEmbeddingModel = { id };
  }

  function formatSize(bytes?: number): string {
    if (bytes == null) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function simulateImport() {
    if (!reviewReady) return;
    activeStep = "complete";
  }

  const importKnowledge = createAsyncState(async () => {
    if (isFixtureSession || loadedPreviewSource !== "real") return;
    if (!selectedSite || !selectedEmbeddingModel || !reviewReady) return;
    const { id } = integration;
    if (!id) return;

    try {
      const site = selectedSite;
      const resourceType = site.type === "onedrive" ? "onedrive" : "site";
      const batchItems = dedupedSelection.effectiveEntries.map((entry) => ({
        key: site.key,
        name: entry.importName.trim() || entry.item.name,
        url: entry.item.type === "site_root" ? (site.url ?? "") : (entry.item.web_url ?? ""),
        folder_id: entry.item.type === "site_root" ? undefined : entry.item.id,
        folder_path: entry.item.type === "site_root" ? undefined : entry.item.path,
        type: entry.item.type,
        resource_type: resourceType
      }));

      const response = await eneo.integrations.knowledge.importBatch({
        integration: { id },
        items: batchItems,
        wrapper_name: requiresWrapperName ? wrapperName.trim() : undefined,
        embedding_model: selectedEmbeddingModel,
        space: $currentSpace
      });
      const createdItems = response.items.filter((item) => item.status === "created");
      const failedItems = response.items.filter((item) => item.status === "failed");

      createdItems.forEach((item) => {
        if (item.job) addJob(item.job);
      });
      refreshCurrentSpace();
      startFastUpdatePolling();

      if (createdItems.length === 0) {
        toast.error(m.sharepoint_batch_import_all_failed({ failed: failedItems.length }));
        return;
      }
      if (failedItems.length > 0) {
        toast.warning(
          m.sharepoint_batch_import_partial({
            created: createdItems.length,
            total: response.items.length,
            failed: failedItems.length
          })
        );
      } else {
        toast.success(m.sharepoint_batch_import_success({ count: createdItems.length }));
      }

      dialogOpen = false;
      resetFlow();
    } catch (error) {
      toastError(error);
    }
  });

  $effect(() => {
    if (dialogOpen && loadedPreviewSourceKey !== requestedPreviewSourceKey) loadPreview();
  });
</script>

<Dialog.Root bind:open={dialogOpen} onOpenChange={handleDialogOpenChange}>
  <Dialog.Content
    class="flex h-[calc(100dvh-1rem)] max-h-[calc(100dvh-1rem)] w-[calc(100vw-1rem)] max-w-none flex-col gap-0 overflow-hidden p-0 sm:h-[min(92dvh,56rem)] sm:max-h-[92dvh] sm:max-w-5xl"
    closeLabel={m.close()}
  >
    <Dialog.Header class="shrink-0 border-b px-4 py-4 pr-12 sm:px-6">
      <Dialog.Title>
        {isFixtureSession
          ? m.sharepoint_fixture_dialog_title()
          : m.import_knowledge_from_sharepoint()}
      </Dialog.Title>
      <Dialog.Description>
        {isFixtureSession
          ? m.sharepoint_fixture_dialog_description()
          : m.sharepoint_import_dialog_description()}
      </Dialog.Description>
    </Dialog.Header>

    {#if isFixtureSession}
      <Alert.Root class="border-caution/35 bg-caution/8 mx-4 mt-3 w-auto shrink-0 sm:mx-6">
        <FlaskConical class="text-caution" aria-hidden="true" />
        <Collapsible.Root bind:open={fixtureDetailsOpen} class="col-start-2 min-w-0">
          <div class="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
            <div class="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2">
              <Alert.Title class="text-caution">
                {m.sharepoint_fixture_compact_title()}
              </Alert.Title>
              <span class="text-muted-foreground text-xs">
                {m.sharepoint_fixture_compact_status()}
              </span>
            </div>

            <div class="flex min-w-0 items-center gap-1.5">
              <span id="sharepoint-fixture-scenario-label" class="sr-only">
                {m.sharepoint_fixture_scenario_label()}
              </span>
              <Select.Root
                type="single"
                value={fixtureScenario ?? ""}
                onValueChange={changeFixtureScenario}
              >
                <Select.Trigger
                  class="h-8 min-w-0 flex-1 sm:w-56 sm:flex-none"
                  aria-labelledby="sharepoint-fixture-scenario-label"
                >
                  {fixtureScenario
                    ? getFixtureScenarioLabel(fixtureScenario)
                    : m.sharepoint_fixture_scenario_invalid()}
                </Select.Trigger>
                <Select.Content>
                  <Select.Item
                    value="representative"
                    label={m.sharepoint_fixture_scenario_representative()}
                  />
                  <Select.Item
                    value="large_tenant"
                    label={m.sharepoint_fixture_scenario_large_tenant()}
                  />
                  <Select.Item value="empty" label={m.sharepoint_fixture_scenario_empty()} />
                </Select.Content>
              </Select.Root>

              <Collapsible.Trigger
                class="hover:bg-muted inline-flex h-8 shrink-0 items-center gap-1 rounded-md px-2 text-xs font-medium"
              >
                {m.details()}
                <ChevronDown
                  class="size-3.5 transition-transform {fixtureDetailsOpen ? 'rotate-180' : ''}"
                  aria-hidden="true"
                />
              </Collapsible.Trigger>
            </div>
          </div>

          <Collapsible.Content>
            <Alert.Description class="border-caution/25 text-muted-foreground mt-2 border-t pt-2">
              {m.sharepoint_fixture_banner_description()}
            </Alert.Description>
          </Collapsible.Content>
        </Collapsible.Root>
      </Alert.Root>
    {/if}

    <ol
      class="border-border mx-4 grid shrink-0 grid-cols-3 border-b py-3 sm:mx-6"
      aria-label={m.sharepoint_import_progress()}
    >
      {#each steps as step (step.number)}
        <li
          class="text-muted-foreground flex min-w-0 items-center gap-2 text-xs sm:text-sm"
          class:text-foreground={currentStepNumber >= step.number}
          aria-current={currentStepNumber === step.number ? "step" : undefined}
        >
          <span
            class="border-border flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold"
            class:bg-accent-default={currentStepNumber >= step.number}
            class:border-accent-default={currentStepNumber >= step.number}
            class:text-on-fill={currentStepNumber >= step.number}
          >
            {step.number}
          </span>
          <span class="truncate">{step.label()}</span>
        </li>
      {/each}
    </ol>

    <div class="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
      {#if activeStep === "source"}
        <section class="flex min-h-full flex-col gap-3" aria-labelledby="sharepoint-source-heading">
          <div>
            <h3 id="sharepoint-source-heading" class="font-semibold">
              {m.sharepoint_choose_source_title()}
            </h3>
            <p class="text-muted-foreground mt-1 text-sm">
              {m.sharepoint_choose_source_description()}
            </p>
          </div>

          <Command.Root
            label={m.find_sharepoint_site()}
            shouldFilter={false}
            class="border-border flex min-h-72 flex-1 flex-col rounded-xl border p-0"
          >
            <Command.Input
              bind:value={sourceFilter}
              placeholder={m.find_sharepoint_site()}
              aria-label={m.find_sharepoint_site()}
            />
            <Command.List
              class="min-h-0 flex-1 border-t"
              aria-busy={loadPreview.isLoading}
              aria-label={m.sharepoint_available_sources()}
            >
              {#if loadPreview.isLoading}
                <div
                  class="text-muted-foreground flex items-center justify-center gap-2 px-4 py-10"
                  role="status"
                >
                  <LoaderCircle class="size-4 animate-spin" aria-hidden="true" />
                  {m.loading_available_sites()}
                </div>
              {:else if previewLoadFailed}
                <div class="flex flex-col items-center gap-3 px-4 py-10 text-center" role="alert">
                  <p class="text-destructive text-sm">{m.sharepoint_preview_load_error()}</p>
                  <Button variant="outline" size="sm" onclick={retryPreview}>
                    <RefreshCw aria-hidden="true" />
                    {m.retry()}
                  </Button>
                </div>
              {:else if groupedFilteredResources.length === 0}
                <Command.Empty>{m.no_matching_sites_found()}</Command.Empty>
              {:else}
                {#each groupedFilteredResources as group (group.category)}
                  {@const CategoryIcon = getCategoryIcon(group.category)}
                  <Command.Group heading={getCategoryLabel(group.category)}>
                    {#each group.items as previewItem (previewItem.value.key)}
                      <Command.Item
                        value={`${group.category}:${previewItem.value.type}:${previewItem.value.key}:${previewItem.label}`}
                        class="min-h-11 px-3 [&_.cn-command-item-indicator]:hidden"
                        onSelect={() => handleSiteSelect(previewItem.value)}
                      >
                        <CategoryIcon class="text-muted-foreground size-4" aria-hidden="true" />
                        <span class="min-w-0 flex-1 truncate">{previewItem.label}</span>
                      </Command.Item>
                    {/each}
                  </Command.Group>
                {/each}
              {/if}
            </Command.List>
          </Command.Root>
        </section>
      {:else if activeStep === "content" && selectedSite}
        <section
          class="flex h-full min-h-[20rem] flex-col gap-3"
          aria-labelledby="sharepoint-content-heading"
        >
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="min-w-0">
              <h3
                id="sharepoint-content-heading"
                class="truncate font-semibold"
                title={selectedSite.name}
              >
                {selectedSite.name}
              </h3>
            </div>
            <Badge variant="secondary">
              {m.sharepoint_selected_items_count({ count: selectedItems.length })}
            </Badge>
          </div>

          <SharePointFolderTree
            userIntegrationId={integration.id || ""}
            spaceId={$currentSpace.id}
            siteId={selectedSite.type === "onedrive" ? undefined : selectedSite.key}
            driveId={selectedSite.type === "onedrive" ? selectedSite.key : undefined}
            siteName={selectedSite.name}
            isOneDrive={selectedSite.type === "onedrive"}
            fixtureScenario={fixtureTreeScenario ?? undefined}
            {selectedItemKeys}
            {selectedPaths}
            onToggleSelect={toggleSelectedItem}
          />

          {#if dedupedSelection.skippedCount > 0}
            <p class="text-muted-foreground text-sm" role="status">
              {m.sharepoint_nested_selection_notice({ count: dedupedSelection.skippedCount })}
            </p>
          {/if}
        </section>
      {:else if activeStep === "review" && selectedSite}
        <section class="flex flex-col gap-5" aria-labelledby="sharepoint-review-heading">
          <div>
            <h3 id="sharepoint-review-heading" class="font-semibold">
              {m.sharepoint_review_title()}
            </h3>
            <p class="text-muted-foreground mt-1 text-sm">
              {m.sharepoint_review_description({
                count: dedupedSelection.effectiveEntries.length,
                source: selectedSite.name
              })}
            </p>
          </div>

          {#if dedupedSelection.skippedCount > 0}
            <Alert.Root>
              <FileText aria-hidden="true" />
              <Alert.Title>{m.sharepoint_nested_selection_review_title()}</Alert.Title>
              <Alert.Description>
                {m.sharepoint_nested_selection_notice({ count: dedupedSelection.skippedCount })}
              </Alert.Description>
            </Alert.Root>
          {/if}

          {#if requiresWrapperName}
            <Field.Field data-invalid={wrapperNameMissing || undefined}>
              <Field.Label for="sharepoint-wrapper-name">
                {m.sharepoint_wrapper_name_label()}
              </Field.Label>
              <Input
                id="sharepoint-wrapper-name"
                bind:value={wrapperName}
                placeholder={m.sharepoint_wrapper_name_placeholder()}
                aria-invalid={wrapperNameMissing}
                aria-describedby="sharepoint-wrapper-description"
              />
              {#if wrapperNameMissing}
                <Field.Error id="sharepoint-wrapper-description">
                  {m.sharepoint_wrapper_name_missing_hint()}
                </Field.Error>
              {:else}
                <Field.Description id="sharepoint-wrapper-description">
                  {m.sharepoint_wrapper_name_required_hint()}
                </Field.Description>
              {/if}
            </Field.Field>
          {/if}

          {#if !isFixtureSession}
            {#if embeddingModels.length === 0}
              <Alert.Root variant="destructive">
                <Alert.Title>{m.warning()}</Alert.Title>
                <Alert.Description>{m.warning_no_embedding_models()}</Alert.Description>
              </Alert.Root>
            {:else if embeddingModels.length > 1}
              <Field.Field>
                <Field.Label id="sharepoint-embedding-model-label">
                  {m.embedding_model()}
                </Field.Label>
                <Select.Root
                  type="single"
                  value={selectedEmbeddingModel?.id ?? ""}
                  onValueChange={selectEmbeddingModel}
                >
                  <Select.Trigger class="w-full" aria-labelledby="sharepoint-embedding-model-label">
                    {#if selectedEmbeddingModel}
                      {getModelDisplayName(
                        embeddingModels.find((model) => model.id === selectedEmbeddingModel?.id) ??
                          embeddingModels[0]
                      )}
                    {:else}
                      {m.no_model_selected()}
                    {/if}
                  </Select.Trigger>
                  <Select.Content>
                    {#if stableEmbeddingModels.length > 0}
                      <Select.Group>
                        <Select.GroupHeading>{m.stable_embedding_models()}</Select.GroupHeading>
                        {#each stableEmbeddingModels as model (model.id)}
                          <Select.Item value={model.id} label={getModelDisplayName(model)} />
                        {/each}
                      </Select.Group>
                    {/if}
                    {#if experimentalEmbeddingModels.length > 0}
                      <Select.Group>
                        <Select.GroupHeading>
                          {m.experimental_embedding_models()}
                        </Select.GroupHeading>
                        {#each experimentalEmbeddingModels as model (model.id)}
                          <Select.Item value={model.id} label={getModelDisplayName(model)} />
                        {/each}
                      </Select.Group>
                    {/if}
                  </Select.Content>
                </Select.Root>
              </Field.Field>
            {/if}
          {/if}

          <div class="flex flex-col gap-3">
            {#each dedupedSelection.effectiveEntries as selection, index (selection.selectionKey)}
              <article class="border-border bg-card rounded-xl border p-3">
                <div class="flex items-start gap-2">
                  <Field.Field class="min-w-0 flex-1">
                    <Field.Label for={`sharepoint-import-name-${index}`}>
                      {m.sharepoint_import_name_for({ name: selection.item.name })}
                    </Field.Label>
                    <Input
                      id={`sharepoint-import-name-${index}`}
                      value={selection.importName}
                      oninput={(event) =>
                        updateSelectionName(selection.selectionKey, event.currentTarget.value)}
                    />
                  </Field.Field>
                  <Button
                    variant="ghost"
                    size="icon"
                    class="mt-6 shrink-0"
                    aria-label={m.sharepoint_remove_item({ name: selection.item.name })}
                    onclick={() => removeSelectedItem(selection.selectionKey)}
                  >
                    <Trash2 aria-hidden="true" />
                  </Button>
                </div>
                <div class="text-muted-foreground mt-2 flex min-w-0 items-center gap-2 text-xs">
                  <span class="min-w-0 flex-1 truncate" title={selection.item.path}>
                    {selection.item.path}
                  </span>
                  {#if selection.item.size != null}
                    <span class="shrink-0">{formatSize(selection.item.size)}</span>
                  {/if}
                </div>
              </article>
            {/each}
          </div>
        </section>
      {:else if activeStep === "complete"}
        <section
          class="flex min-h-72 flex-col items-center justify-center gap-4 text-center"
          aria-labelledby="sharepoint-simulation-complete-heading"
          role="status"
        >
          <span
            class="bg-positive-default/10 flex size-14 items-center justify-center rounded-full"
          >
            <CheckCircle2 class="text-positive-stronger size-8" aria-hidden="true" />
          </span>
          <div>
            <h3 id="sharepoint-simulation-complete-heading" class="text-lg font-semibold">
              {m.sharepoint_fixture_simulation_complete_title()}
            </h3>
            <p class="text-muted-foreground mt-1 max-w-md text-sm">
              {m.sharepoint_fixture_simulation_complete_description({
                count: dedupedSelection.effectiveEntries.length
              })}
            </p>
          </div>
        </section>
      {/if}
    </div>

    <Dialog.Footer class="mx-0 mb-0 shrink-0 rounded-none border-t px-4 py-4 sm:px-6">
      {#if activeStep === "complete"}
        <Button class="w-full sm:w-auto" onclick={() => (dialogOpen = false)}>
          {m.close()}
        </Button>
      {:else}
        <Button variant="outline" class="w-full sm:w-auto" onclick={handleBack}>
          {m.back()}
        </Button>
        {#if activeStep === "content"}
          <Button
            class="w-full sm:w-auto"
            disabled={dedupedSelection.effectiveEntries.length === 0}
            onclick={() => (activeStep = "review")}
          >
            {m.continue()}
          </Button>
        {:else if activeStep === "review"}
          <Button
            class="w-full sm:w-auto"
            disabled={!reviewReady || importKnowledge.isLoading}
            onclick={isFixtureSession ? simulateImport : importKnowledge}
          >
            {#if importKnowledge.isLoading}
              <LoaderCircle class="animate-spin" aria-hidden="true" />
              {m.importing()}
            {:else if isFixtureSession}
              <FlaskConical aria-hidden="true" />
              {m.sharepoint_fixture_simulate_import()}
            {:else}
              {m.import()}
            {/if}
          </Button>
        {/if}
      {/if}
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
