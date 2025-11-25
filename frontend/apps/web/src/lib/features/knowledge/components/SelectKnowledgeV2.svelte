<script lang="ts">
  import { createCombobox } from "@melt-ui/svelte";
  import { IconCancel } from "@intric/icons/cancel";
  import { IconCollections } from "@intric/icons/collections";
  import { IconPlus } from "@intric/icons/plus";
  import { IconTrash } from "@intric/icons/trash";
  import { IconWeb } from "@intric/icons/web";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { Button } from "@intric/ui";
  import type { GroupSparse, IntegrationKnowledge, WebsiteSparse, InfoBlob } from "@intric/intric-js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getAvailableKnowledge } from "../getAvailableKnowledge";
  import { tick } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { formatWebsiteName } from "$lib/core/formatting/formatWebsiteName";
  import IntegrationVendorIcon from "$lib/features/integrations/components/IntegrationVendorIcon.svelte";
  import { getIntric } from "$lib/core/Intric";
  import BlobPreview from "./BlobPreview.svelte";

  /** Bind this variable if you want to be able to select websites */
  export let selectedWebsites: WebsiteSparse[] | undefined = undefined;
  /** Bind this variable if you want to be able to select collections aka groups */
  export let selectedCollections: GroupSparse[] | undefined = undefined;
  /** Bind this variable if you want to be able to select integration knowledge */
  export let selectedIntegrationKnowledge:
    | Omit<IntegrationKnowledge[], "tenant_id" | "user_integration_id" | "space_id">
    | undefined = undefined;

  export let aria: AriaProps = { "aria-label": "Select knowledge" };
  /**
   * Set this to true if you're rendering the selector inside a dialog. Will portal it to the body element
   * and set a z-index of 5000, so it is always on top. Helps to prevent clipping to scroll parent inside a dialog.
   */
  export let inDialog = false;
  export let originMode: "personal" | "organization" | "both" = "both";

  const {
    elements: {
      input: inputPersonal,
      menu: menuPersonal,
      group: groupPersonal,
      groupLabel: groupLabelPersonal,
      option: optionPersonal
    },
    states: { open: openPersonal, inputValue: inputValuePersonal }
  } = createCombobox<
    | { website: WebsiteSparse }
    | { collection: GroupSparse }
    | { integrationKnowledge: IntegrationKnowledge }
  >({
    forceVisible: false,
    loop: true,
    positioning: {
      sameWidth: true,
      fitViewport: true,
      flip: false,
      placement: "bottom"
    },
    onSelectedChange({ next }) {
      if (next) addItem(next.value);
      inputPersonalEl?.blur();
      $inputValuePersonal = "";
      setTimeout(() => personalTriggerBtn?.focus(), 1);
      return undefined;
    },
    portal: inDialog ? "body" : null
  });

  const {
    elements: {
      input: inputOrg,
      menu: menuOrg,
      group: groupOrg,
      groupLabel: groupLabelOrg,
      option: optionOrg
    },
    states: { open: openOrg, inputValue: inputValueOrg }
  } = createCombobox<
    | { website: WebsiteSparse }
    | { collection: GroupSparse }
    | { integrationKnowledge: IntegrationKnowledge }
  >({
    forceVisible: false,
    loop: true,
    positioning: {
      sameWidth: true,
      fitViewport: true,
      flip: false,
      placement: "bottom"
    },
    onSelectedChange({ next }) {
      if (next) addItem(next.value);
      inputOrgEl?.blur();
      $inputValueOrg = "";
      setTimeout(() => orgTriggerBtn?.focus(), 1);
      return undefined;
    },
    portal: inDialog ? "body" : null
  });

  const {
    state: { currentSpace, nonOrgSpaces, organizationSpaceId }
  } = getSpacesManager();

  const intric = getIntric();

  let expandedItems = new Set<string>();
  let blobCache = new Map<string, InfoBlob[]>();
  let loadingBlobs = new Set<string>();
  let currentPages = new Map<string, number>(); 
  const ITEMS_PER_PAGE = 10;

  async function toggleExpanded(id: string, type: "collection" | "website" | "integration", item: GroupSparse | WebsiteSparse | IntegrationKnowledge) {
    if (expandedItems.has(id)) {
      expandedItems.delete(id);
      expandedItems = expandedItems;
    } else {
      expandedItems.add(id);
      expandedItems = expandedItems;

      // Initialize pagination for all types
      if (!currentPages.has(id)) {
        currentPages.set(id, 1);
        currentPages = currentPages;
      }

      if (!blobCache.has(id)) {
        loadingBlobs.add(id);
        loadingBlobs = loadingBlobs;

        try {
          let blobs: InfoBlob[];
          if (type === "collection") {
            blobs = await intric.groups.listInfoBlobs(item as GroupSparse);
          } else if (type === "website") {
            blobs = await intric.websites.indexedBlobs.list(item as WebsiteSparse);
          } else {
            // Integration knowledge - not yet supported
            blobs = [];
          }
          console.log(`Fetched ${blobs.length} blobs for ${type} ${id}`);
          blobCache.set(id, blobs);
          blobCache = blobCache;
        } catch (error) {
          console.error(`Failed to fetch blobs for ${type} ${id}:`, error);
        } finally {
          loadingBlobs.delete(id);
          loadingBlobs = loadingBlobs;
        }
      }
    }
  }

  function getPaginatedBlobs(id: string, blobs: InfoBlob[] | undefined) {
    if (!blobs) return [];

    // Always use pagination for all types
    const page = currentPages.get(id) || 1;
    const start = (page - 1) * ITEMS_PER_PAGE;
    const end = start + ITEMS_PER_PAGE;
    return blobs.slice(start, end);
  }

  function getTotalPages(blobs: InfoBlob[] | undefined) {
    if (!blobs) return 0;
    return Math.ceil(blobs.length / ITEMS_PER_PAGE);
  }

  function changePage(id: string, newPage: number) {
    currentPages.set(id, newPage);
    currentPages = currentPages;
  }

  function formatBlobSize(bytes: number | undefined): string {
    if (!bytes) return "";
    const kb = bytes / 1024;
    if (kb < 1024) return `${kb.toFixed(1)} KB`;
    const mb = kb / 1024;
    return `${mb.toFixed(1)} MB`;
  }

  function ownerSpaceId(item: any): string | undefined {
    return (
      item?.space_id ??
      item?.spaceId ??
      item?.space?.id ??
      item?.metadata?.space_id ??
      item?.metadata?.spaceId
    );
  }

  function isPersonalItem(item: any) {
    const sid = ownerSpaceId(item);
    if (!sid) return true; 
    return sid === $currentSpace?.id;
  }
  function isOrgItem(item: any) {
    const sid = ownerSpaceId(item);
    if ($organizationSpaceId) {
      return sid === $organizationSpaceId;
    }
    if (!$currentSpace?.id) {
      return false;
    }
    return Boolean(sid) && sid !== $currentSpace.id;
  }

  function addItem(
    item:
      | { website: WebsiteSparse }
      | { collection: GroupSparse }
      | { integrationKnowledge: IntegrationKnowledge }
  ) {
    if ("collection" in item && selectedCollections) {
      if (!selectedCollections.some(c => c.id === item.collection.id)) {
        selectedCollections = [...selectedCollections, item.collection];
      }
    }
    if ("website" in item && selectedWebsites) {
      if (!selectedWebsites.some(w => w.id === item.website.id)) {
        selectedWebsites = [...selectedWebsites, item.website];
      }
    }
    if ("integrationKnowledge" in item && selectedIntegrationKnowledge) {
      if (!selectedIntegrationKnowledge.some(k => k.id === item.integrationKnowledge.id)) {
        selectedIntegrationKnowledge = [...selectedIntegrationKnowledge, item.integrationKnowledge];
      }
    }
  }

  let inputPersonalEl: HTMLInputElement;
  let personalTriggerBtn: HTMLButtonElement;
  let inputOrgEl: HTMLInputElement;
  let orgTriggerBtn: HTMLButtonElement;

  $: activeFilter =
    originMode === "organization"
      ? $inputValueOrg
      : originMode === "personal"
      ? $inputValuePersonal
      : ($openPersonal ? $inputValuePersonal : $inputValueOrg);

    $: availableKnowledge = getAvailableKnowledge(
      $currentSpace,
      selectedWebsites,
      selectedCollections,
      selectedIntegrationKnowledge,
      activeFilter
  );

  $: sectionEntries = Object.entries(availableKnowledge.sections).map(([modelId, section]) => {
    const dedupe = <T extends { id: string }>(arr: T[] = []) => {
      const seen = new Set<string>();
      return arr.filter(x => (seen.has(x.id) ? false : (seen.add(x.id), true)));
    };
    return [
      modelId,
      {
        ...section,
        groups: dedupe(section.groups),
        websites: dedupe(section.websites),
        integrationKnowledge: dedupe(section.integrationKnowledge)
      }
    ] as const;
  });

  $: enabledModels = $currentSpace.embedding_models.map((model) => model.id);

  $: partitionedSections = sectionEntries.flatMap(([modelId, section]) => {
    const split = (arr: any[] = []) => {
      const personal: any[] = [];
      const org: any[] = [];
      for (const item of arr) {
        const sid = ownerSpaceId(item);
        if (!sid || sid === $currentSpace?.id) personal.push(item);
        else {
          org.push(item);
        }
      }
      return { personal, org };
    };

    const g = split(section.groups);
    const w = split(section.websites);
    const k = split(section.integrationKnowledge);

    const mk = (
      origin: "Personal" | "Organization",
      groups: any[],
      websites: any[],
      integrationKnowledge: any[]
    ) => ({
      ...section,
      origin,
      groups,
      websites,
      integrationKnowledge,
      availableItemsCount:
        (groups?.length ?? 0) + (websites?.length ?? 0) + (integrationKnowledge?.length ?? 0)
    });

    const out: Array<[string, any]> = [];
    if (g.personal.length || w.personal.length || k.personal.length)
      out.push([`${modelId}::personal`, mk("Personal", g.personal, w.personal, k.personal)]);
    if (g.org.length || w.org.length || k.org.length)
      out.push([`${modelId}::org`, mk("Organization", g.org, w.org, k.org)]);

    return out;
  });

  $: partitionedSectionsPersonal = partitionedSections.filter(([, s]) => s.origin === "Personal");
  $: partitionedSectionsOrg = partitionedSections.filter(([, s]) => s.origin === "Organization");

  $: selectedCollectionsPersonal = (selectedCollections ?? []).filter(isPersonalItem);
  $: selectedCollectionsOrg = (selectedCollections ?? []).filter(isOrgItem);

  $: selectedWebsitesPersonal = (selectedWebsites ?? []).filter(isPersonalItem);
  $: selectedWebsitesOrg = (selectedWebsites ?? []).filter(isOrgItem);
  
  $: selectedIntegrationKnowledgePersonal = (selectedIntegrationKnowledge ?? []).filter(isPersonalItem);
  $: selectedIntegrationKnowledgeOrg = (selectedIntegrationKnowledge ?? []).filter(isOrgItem);

  $: hasOrgSelections =
    selectedCollectionsOrg.length > 0 ||
    selectedWebsitesOrg.length > 0 ||
    selectedIntegrationKnowledgeOrg.length > 0;

  $: shouldRenderOrgSelectedSection =
    Boolean($organizationSpaceId) || hasOrgSelections || partitionedSectionsOrg.length > 0;

</script>
{#if originMode !== "organization"}
  <section class="knowledge-selected">

    {#each selectedCollectionsPersonal as collection (`group:${collection.id}`)}
      {@const isItemModelEnabled = enabledModels.includes(collection.embedding_model.id)}
      {@const isExpanded = expandedItems.has(collection.id)}
      {@const isLoading = loadingBlobs.has(collection.id)}
      {@const allBlobs = blobCache.get(collection.id)}
      {@const blobs = getPaginatedBlobs(collection.id, allBlobs)}
      {@const totalPages = getTotalPages(allBlobs)}
      {@const currentPage = currentPages.get(collection.id) || 1}
      <div class="knowledge-item-container">
        <div class="knowledge-item" class:text-negative-default={!isItemModelEnabled}>
          {#if collection.metadata.num_info_blobs > 0}
            <button
              class="expand-button"
              on:click={() => toggleExpanded(collection.id, "collection", collection)}
              aria-label={isExpanded ? "Collapse" : "Expand"}
            >
              {#if isExpanded}
                <IconChevronDown />
              {:else}
                <IconChevronRight />
              {/if}
            </button>
          {:else}
            <div class="expand-button-placeholder"></div>
          {/if}
          {#if isItemModelEnabled}
            <IconCollections />
          {:else}
            <IconCancel />
          {/if}
          <span class="truncate px-2">{collection.name}</span>
          {#if !isItemModelEnabled}<span>(model disabled)</span>{/if}
          <div class="flex-grow"></div>
          {#if collection.metadata.num_info_blobs > 0}
            <span class="label-blue border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-sm">
              {collection.metadata.num_info_blobs} {m.resource_files()}
            </span>
          {:else}
            <span class="label-neutral border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-sm">
              {m.empty()}
            </span>
          {/if}
          <Button variant="destructive" padding="icon" on:click={() => {
            selectedCollections = selectedCollections?.filter((item) => item.id !== collection.id);
            if ($openPersonal) inputPersonalEl?.focus();
            if ($openOrg)      inputOrgEl?.focus();
          }}><IconTrash /></Button>
        </div>
        {#if isExpanded}
          <div class="blob-list">
            {#if isLoading}
              <div class="blob-item text-muted">Loading...</div>
            {:else if blobs && blobs.length > 0}
              {#each blobs as blob (blob.id)}
                <BlobPreview {blob} let:showBlob>
                  <button class="blob-item blob-item-clickable" on:click={showBlob}>
                    <span class="blob-title truncate">{blob.metadata?.title || blob.metadata?.url || "Untitled"}</span>
                    {#if blob.metadata?.size}
                      <span class="blob-size text-muted">{formatBlobSize(blob.metadata.size)}</span>
                    {/if}
                  </button>
                </BlobPreview>
              {/each}
              {#if totalPages > 1}
                <div class="pagination">
                  <Button
                    variant="simple"
                    padding="text"
                    disabled={currentPage === 1}
                    on:click={() => changePage(collection.id, currentPage - 1)}
                  >
                    {m.previous()}
                  </Button>
                  <span class="text-muted text-sm">{m.page_x_of_y({ x: currentPage, y: totalPages })}</span>
                  <Button
                    variant="simple"
                    padding="text"
                    disabled={currentPage === totalPages}
                    on:click={() => changePage(collection.id, currentPage + 1)}
                  >
                    {m.next()}
                  </Button>
                </div>
              {/if}
            {:else}
              <div class="blob-item text-muted">No files found</div>
            {/if}
          </div>
        {/if}
      </div>
    {/each}

    {#each selectedWebsitesPersonal as website (`website:${website.id}`)}
      {@const isItemModelEnabled = enabledModels.includes(website.embedding_model.id)}
      {@const isExpanded = expandedItems.has(website.id)}
      {@const isLoading = loadingBlobs.has(website.id)}
      {@const allBlobs = blobCache.get(website.id)}
      {@const blobs = getPaginatedBlobs(website.id, allBlobs)}
      {@const totalPages = getTotalPages(allBlobs)}
      {@const currentPage = currentPages.get(website.id) || 1}
      {@const pagesCrawled = website.latest_crawl?.pages_crawled}
      <div class="knowledge-item-container">
        <div class="knowledge-item">
          {#if pagesCrawled && pagesCrawled > 0}
            <button
              class="expand-button"
              on:click={() => toggleExpanded(website.id, "website", website)}
              aria-label={isExpanded ? "Collapse" : "Expand"}
            >
              {#if isExpanded}
                <IconChevronDown />
              {:else}
                <IconChevronRight />
              {/if}
            </button>
          {:else}
            <div class="expand-button-placeholder"></div>
          {/if}
          {#if isItemModelEnabled}<IconWeb />{:else}<IconCancel />{/if}
          <span class="truncate px-2">{formatWebsiteName(website)}</span>
          {#if !isItemModelEnabled}<span>(model disabled)</span>{/if}
          <div class="flex-grow"></div>
          {#if pagesCrawled && pagesCrawled > 0}
            <span class="label-blue border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-sm">
              {pagesCrawled} {pagesCrawled === 1 ? 'page' : 'pages'}
            </span>
          {/if}
          <Button variant="destructive" padding="icon" on:click={() => {
            selectedWebsites = selectedWebsites?.filter((item) => item.id !== website.id);
            if ($openPersonal) inputPersonalEl?.focus();
            if ($openOrg)      inputOrgEl?.focus();
          }}><IconTrash /></Button>
        </div>
        {#if isExpanded}
          <div class="blob-list">
            {#if isLoading}
              <div class="blob-item text-muted">Loading...</div>
            {:else if blobs && blobs.length > 0}
              {#each blobs as blob (blob.id)}
                <BlobPreview {blob} let:showBlob>
                  <button class="blob-item blob-item-clickable" on:click={showBlob}>
                    <span class="blob-title truncate">{blob.metadata?.title || blob.metadata?.url || "Untitled"}</span>
                    {#if blob.metadata?.size}
                      <span class="blob-size text-muted">{formatBlobSize(blob.metadata.size)}</span>
                    {/if}
                  </button>
                </BlobPreview>
              {/each}
              {#if totalPages > 1}
                <div class="pagination">
                  <Button
                    variant="simple"
                    padding="text"
                    disabled={currentPage === 1}
                    on:click={() => changePage(website.id, currentPage - 1)}
                  >
                    {m.previous()}
                  </Button>
                  <span class="text-muted text-sm">{m.page_x_of_y({ x: currentPage, y: totalPages })}</span>
                  <Button
                    variant="simple"
                    padding="text"
                    disabled={currentPage === totalPages}
                    on:click={() => changePage(website.id, currentPage + 1)}
                  >
                    {m.next()}
                  </Button>
                </div>
              {/if}
            {:else}
              <div class="blob-item text-muted">No pages found</div>
            {/if}
          </div>
        {/if}
      </div>
    {/each}

    {#each selectedIntegrationKnowledgePersonal as knowledge (`integration:${knowledge.id}`)}
      {@const isItemModelEnabled = enabledModels.includes(knowledge.embedding_model.id)}
      <div class="knowledge-item">
        {#if isItemModelEnabled}
          <IntegrationVendorIcon size="sm" type={knowledge.integration_type}/>
        {:else}
          <IconCancel />
        {/if}
        <span class="truncate px-2">{knowledge.name}</span>
        {#if !isItemModelEnabled}<span>(model disabled)</span>{/if}
        <div class="flex-grow"></div>
        <Button variant="destructive" padding="icon" on:click={() => {
          selectedIntegrationKnowledge = selectedIntegrationKnowledge?.filter((item) => item.id !== knowledge.id);
          if ($openPersonal) inputPersonalEl?.focus();
          if ($openOrg)      inputOrgEl?.focus();
        }}><IconTrash /></Button>
      </div>
    {/each}
  </section>
{/if}

{#if originMode !== "personal"}
  {#if shouldRenderOrgSelectedSection}
  <section class="knowledge-selected">
    {#each selectedCollectionsOrg as collection (`group:${collection.id}`)}
      {@const isItemModelEnabled = enabledModels.includes(collection.embedding_model.id)}
      {@const isExpanded = expandedItems.has(collection.id)}
      {@const isLoading = loadingBlobs.has(collection.id)}
      {@const allBlobs = blobCache.get(collection.id)}
      {@const blobs = getPaginatedBlobs(collection.id, allBlobs)}
      {@const totalPages = getTotalPages(allBlobs)}
      {@const currentPage = currentPages.get(collection.id) || 1}
      <div class="knowledge-item-container">
        <div class="knowledge-item" class:text-negative-default={!isItemModelEnabled}>
          {#if collection.metadata.num_info_blobs > 0}
            <button
              class="expand-button"
              on:click={() => toggleExpanded(collection.id, "collection", collection)}
              aria-label={isExpanded ? "Collapse" : "Expand"}
            >
              {#if isExpanded}
                <IconChevronDown />
              {:else}
                <IconChevronRight />
              {/if}
            </button>
          {:else}
            <div class="expand-button-placeholder"></div>
          {/if}
          {#if isItemModelEnabled}<IconCollections />{:else}<IconCancel />{/if}
          <span class="truncate px-2">{collection.name}</span>
          {#if !isItemModelEnabled}<span>(model disabled)</span>{/if}
          <div class="flex-grow"></div>
          {#if collection.metadata.num_info_blobs > 0}
            <span class="label-blue border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-sm">
              {collection.metadata.num_info_blobs} {m.resource_files()}
            </span>
          {:else}
            <span class="label-neutral border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-sm">
              Empty
            </span>
          {/if}
          <Button variant="destructive" padding="icon" on:click={() => {
            selectedCollections = selectedCollections?.filter((item) => item.id !== collection.id);
            if ($openPersonal) inputPersonalEl?.focus();
            if ($openOrg)      inputOrgEl?.focus();
          }}><IconTrash /></Button>
        </div>
        {#if isExpanded}
          <div class="blob-list">
            {#if isLoading}
              <div class="blob-item text-muted">Loading...</div>
            {:else if blobs && blobs.length > 0}
              {#each blobs as blob (blob.id)}
                <BlobPreview {blob} let:showBlob>
                  <button class="blob-item blob-item-clickable" on:click={showBlob}>
                    <span class="blob-title truncate">{blob.metadata?.title || blob.metadata?.url || "Untitled"}</span>
                    {#if blob.metadata?.size}
                      <span class="blob-size text-muted">{formatBlobSize(blob.metadata.size)}</span>
                    {/if}
                  </button>
                </BlobPreview>
              {/each}
              {#if totalPages > 1}
                <div class="pagination">
                  <Button
                    variant="simple"
                    padding="text"
                    disabled={currentPage === 1}
                    on:click={() => changePage(collection.id, currentPage - 1)}
                  >
                    {m.previous()}
                  </Button>
                  <span class="text-muted text-sm">{m.page_x_of_y({ x: currentPage, y: totalPages })}</span>
                  <Button
                    variant="simple"
                    padding="text"
                    disabled={currentPage === totalPages}
                    on:click={() => changePage(collection.id, currentPage + 1)}
                  >
                    {m.next()}
                  </Button>
                </div>
              {/if}
            {:else}
              <div class="blob-item text-muted">No files found</div>
            {/if}
          </div>
        {/if}
      </div>
    {/each}

    {#each selectedWebsitesOrg as website (`website:${website.id}`)}
      {@const isItemModelEnabled = enabledModels.includes(website.embedding_model.id)}
      {@const isExpanded = expandedItems.has(website.id)}
      {@const isLoading = loadingBlobs.has(website.id)}
      {@const allBlobs = blobCache.get(website.id)}
      {@const blobs = getPaginatedBlobs(website.id, allBlobs)}
      {@const totalPages = getTotalPages(allBlobs)}
      {@const currentPage = currentPages.get(website.id) || 1}
      {@const pagesCrawled = website.latest_crawl?.pages_crawled}
      <div class="knowledge-item-container">
        <div class="knowledge-item">
          {#if pagesCrawled && pagesCrawled > 0}
            <button
              class="expand-button"
              on:click={() => toggleExpanded(website.id, "website", website)}
              aria-label={isExpanded ? "Collapse" : "Expand"}
            >
              {#if isExpanded}
                <IconChevronDown />
              {:else}
                <IconChevronRight />
              {/if}
            </button>
          {:else}
            <div class="expand-button-placeholder"></div>
          {/if}
          {#if isItemModelEnabled}<IconWeb />{:else}<IconCancel />{/if}
          <span class="truncate px-2">{formatWebsiteName(website)}</span>
          {#if !isItemModelEnabled}<span>(model disabled)</span>{/if}
          <div class="flex-grow"></div>
          {#if pagesCrawled && pagesCrawled > 0}
            <span class="label-blue border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-sm">
              {pagesCrawled} {pagesCrawled === 1 ? 'page' : 'pages'}
            </span>
          {/if}
          <Button variant="destructive" padding="icon" on:click={() => {
            selectedWebsites = selectedWebsites?.filter((item) => item.id !== website.id);
            if ($openPersonal) inputPersonalEl?.focus();
            if ($openOrg)      inputOrgEl?.focus();
          }}><IconTrash /></Button>
        </div>
        {#if isExpanded}
          <div class="blob-list">
            {#if isLoading}
              <div class="blob-item text-muted">Loading...</div>
            {:else if blobs && blobs.length > 0}
              {#each blobs as blob (blob.id)}
                <BlobPreview {blob} let:showBlob>
                  <button class="blob-item blob-item-clickable" on:click={showBlob}>
                    <span class="blob-title truncate">{blob.metadata?.title || blob.metadata?.url || "Untitled"}</span>
                    {#if blob.metadata?.size}
                      <span class="blob-size text-muted">{formatBlobSize(blob.metadata.size)}</span>
                    {/if}
                  </button>
                </BlobPreview>
              {/each}
              {#if totalPages > 1}
                <div class="pagination">
                  <Button
                    variant="simple"
                    padding="text"
                    disabled={currentPage === 1}
                    on:click={() => changePage(website.id, currentPage - 1)}
                  >
                    {m.previous()}
                  </Button>
                  <span class="text-muted text-sm">{m.page_x_of_y({ x: currentPage, y: totalPages })}</span>
                  <Button
                    variant="simple"
                    padding="text"
                    disabled={currentPage === totalPages}
                    on:click={() => changePage(website.id, currentPage + 1)}
                  >
                    {m.next()}
                  </Button>
                </div>
              {/if}
            {:else}
              <div class="blob-item text-muted">No pages found</div>
            {/if}
          </div>
        {/if}
      </div>
    {/each}

    {#each selectedIntegrationKnowledgeOrg as knowledge (`integration:${knowledge.id}`)}
      {@const isItemModelEnabled = enabledModels.includes(knowledge.embedding_model.id)}
      <div class="knowledge-item">
        {#if isItemModelEnabled}
          <IntegrationVendorIcon size="sm" type={knowledge.integration_type}/>
        {:else}
          <IconCancel />
        {/if}
        <span class="truncate px-2">{knowledge.name}</span>
        {#if !isItemModelEnabled}<span>(model disabled)</span>{/if}
        <div class="flex-grow"></div>
        <Button variant="destructive" padding="icon" on:click={() => {
          selectedIntegrationKnowledge = selectedIntegrationKnowledge?.filter((item) => item.id !== knowledge.id);
          if ($openPersonal) inputPersonalEl?.focus();
          if ($openOrg)      inputOrgEl?.focus();
        }}><IconTrash /></Button>
      </div>
    {/each}
  </section>
  {/if}
{/if}

{#if originMode !== "organization"}
  <section class="knowledge-section">
    {#if $openPersonal}
      <div class="border-default relative mt-2 h-12 w-full overflow-clip rounded-lg border">
        <input
          bind:this={inputPersonalEl}
          name="knowledgeFilterPersonal"
          class="absolute inset-0 rounded-lg pl-[4.2rem] text-lg"
          {...$inputPersonal}
          use:inputPersonal
        />
        <label for="knowledgeFilterPersonal" class="text-muted pointer-events-none absolute top-0 bottom-0 left-3 flex items-center text-lg">
          Filter:
        </label>
      </div>
    {:else}
      <button
        bind:this={personalTriggerBtn}
        {...aria}
        class="border-default hover:bg-hover-default relative mt-2 flex h-12 w-full items-center justify-center gap-1 overflow-clip rounded-lg border"
        on:click={async () => {
          $openPersonal = true;
          await tick();
          inputPersonalEl?.focus();
          $openOrg = false;
        }}
      >
        <IconPlus class="min-w-7" />{m.add_knowledge_personal()}
      </button>
    {/if}

    <div class="border-default bg-primary z-20 flex flex-col overflow-hidden overflow-y-auto rounded-lg border shadow-xl"
        class:inDialog
        {...$menuPersonal}
        use:menuPersonal>
      {#if partitionedSectionsPersonal.length > 0}
        {#each partitionedSectionsPersonal as [key, section] (key)}
          <div {...$groupPersonal(section.name + '-Personal')} use:groupPersonal class="flex w-full flex-col">
            <div class="bg-frosted-glass-secondary border-default sticky top-0 flex items-center gap-3 border-b px-4 py-2 font-mono text-sm"
                {...$groupLabelPersonal(section.name + '-Personal')}
                use:groupLabelPersonal>
              <span>
                {#if availableKnowledge.showHeaders}{section.name}{:else}Select a knowledge source{/if}
              </span>
              <span class="flex-grow"></span>
              <span class="rounded-full border px-2 py-0.5 text-xs border-label-default bg-label-dimmer text-label-stronger label-blue">
                Personal
              </span>
            </div>

            {#if !section.isEnabled}
              <p class="knowledge-message">{section.name} is currently not enabled in this space.</p>
            {:else if !section.isCompatible}
              <p class="knowledge-message">The sources embedded by this model are not compatible with the currently selected knowledge.</p>
            {:else if section.availableItemsCount === 0}
              <p class="knowledge-message">No more sources available.</p>
            {:else}
              {#each section.groups as collection (`group:${collection.id}`)}
                <div class="knowledge-item cursor-pointer" {...$optionPersonal({ value: { collection } })} use:optionPersonal>
                  <div class="flex max-w-full flex-grow items-center gap-3">
                    <IconCollections />
                    <span class="truncate">{collection.name}</span>
                  </div>
                  <div class="flex-grow"></div>
                  {#if collection.metadata.num_info_blobs > 0}
                    <span class="label-blue border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-sm">
                      {collection.metadata.num_info_blobs} {m.resource_files()}
                    </span>
                  {:else}
                    <span class="label-neutral border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-sm">
                      Empty
                    </span>
                  {/if}
                </div>
              {/each}

              {#each section.websites as website (`website:${website.id}`)}
                <div class="knowledge-item cursor-pointer" {...$optionPersonal({ value: { website } })} use:optionPersonal>
                  <div class="flex max-w-full flex-grow items-center gap-3">
                    <IconWeb />
                    <span class="truncate">{formatWebsiteName(website)}</span>
                  </div>
                </div>
              {/each}

              {#each section.integrationKnowledge as integrationKnowledge (`integration:${integrationKnowledge.id}`)}
                <div class="knowledge-item cursor-pointer" {...$optionPersonal({ value: { integrationKnowledge } })} use:optionPersonal>
                  <div class="flex max-w-full flex-grow items-center gap-3">
                    <IntegrationVendorIcon size="sm" type={integrationKnowledge.integration_type} />
                    <span class="truncate">{integrationKnowledge.name}</span>
                  </div>
                </div>
              {/each}
            {/if}
          </div>
        {/each}
      {:else}
        <p class="knowledge-message">{m.no_personal_sources()}</p>
      {/if}
    </div>
  </section>
{/if}

{#if originMode !== "personal"}
  <section class="knowledge-section">
    {#if $openOrg}
      <div class="border-default relative mt-2 h-12 w-full overflow-clip rounded-lg border">
        <input
          bind:this={inputOrgEl}
          name="knowledgeFilterOrg"
          class="absolute inset-0 rounded-lg pl-[4.2rem] text-lg"
          {...$inputOrg}
          use:inputOrg
        />
        <label for="knowledgeFilterOrg" class="text-muted pointer-events-none absolute top-0 bottom-0 left-3 flex items-center text-lg">
          Filter:
        </label>
      </div>
    {:else}
      <button
        bind:this={orgTriggerBtn}
        {...aria}
        class="border-default hover:bg-hover-default relative mt-2 flex h-12 w-full items-center justify-center gap-1 overflow-clip rounded-lg border"
        on:click={async () => {
          $openOrg = true;
          await tick();
          inputOrgEl?.focus();
          $openPersonal = false;
        }}
      >
        <IconPlus class="min-w-7" />{m.add_knowledge_organization()}
      </button>
    {/if}

    <div class="border-default bg-primary z-20 flex flex-col overflow-hidden overflow-y-auto rounded-lg border shadow-xl"
        class:inDialog
        {...$menuOrg}
        use:menuOrg>
      {#if partitionedSectionsOrg.length > 0}
        {#each partitionedSectionsOrg as [key, section] (key)}
          <div {...$groupOrg(section.name + '-Organization')} use:groupOrg class="flex w-full flex-col">
            <div class="bg-frosted-glass-secondary border-default sticky top-0 flex items-center gap-3 border-b px-4 py-2 font-mono text-sm"
                {...$groupLabelOrg(section.name + '-Organization')}
                use:groupLabelOrg>
              <span>
                {#if availableKnowledge.showHeaders}{section.name}{:else}Select a knowledge source{/if}
              </span>
              <span class="flex-grow"></span>
              <span class="rounded-full border px-2 py-0.5 text-xs border-label-default bg-label-dimmer text-label-stronger label-warning">
                {m.organization()}
              </span>
            </div>

            {#if !section.isEnabled}
              <p class="knowledge-message">{section.name} is currently not enabled in this space.</p>
            {:else if !section.isCompatible}
              <p class="knowledge-message">The sources embedded by this model are not compatible with the currently selected knowledge.</p>
            {:else if section.availableItemsCount === 0}
              <p class="knowledge-message">No more sources available.</p>
            {:else}
              {#each section.groups as collection (`group:${collection.id}`)}
                <div class="knowledge-item cursor-pointer" {...$optionOrg({ value: { collection } })} use:optionOrg>
                  <div class="flex max-w-full flex-grow items-center gap-3">
                    <IconCollections />
                    <span class="truncate">{collection.name}</span>
                  </div>
                  <div class="flex-grow"></div>
                  {#if collection.metadata.num_info_blobs > 0}
                    <span class="label-blue border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-sm">
                      {collection.metadata.num_info_blobs} {m.resource_files()}
                    </span>
                  {:else}
                    <span class="label-neutral border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-sm">
                      Empty
                    </span>
                  {/if}
                </div>
              {/each}

              {#each section.websites as website (`website:${website.id}`)}
                <div class="knowledge-item cursor-pointer" {...$optionOrg({ value: { website } })} use:optionOrg>
                  <div class="flex max-w-full flex-grow items-center gap-3">
                    <IconWeb />
                    <span class="truncate">{formatWebsiteName(website)}</span>
                  </div>
                </div>
              {/each}

              {#each section.integrationKnowledge as integrationKnowledge (`integration:${integrationKnowledge.id}`)}
                <div class="knowledge-item cursor-pointer" {...$optionOrg({ value: { integrationKnowledge } })} use:optionOrg>
                  <div class="flex max-w-full flex-grow items-center gap-3">
                    <IntegrationVendorIcon size="sm" type={integrationKnowledge.integration_type} />
                    <span class="truncate">{integrationKnowledge.name}</span>
                  </div>
                </div>
              {/each}
            {/if}
          </div>
        {/each}
      {:else}
        <p class="knowledge-message">{m.no_organization_sources()}</p>
      {/if}
    </div>
  </section>
 {/if}

<style lang="postcss">
  @reference "@intric/ui/styles";
  p.knowledge-message {
    @apply text-muted flex min-h-16 items-center justify-center px-4 text-center;
  }

  .knowledge-help {
    @apply text-muted mb-2;
  }

  .knowledge-item {
    @apply border-default bg-primary hover:bg-hover-dimmer flex h-16 w-full items-center gap-2 border-b px-4;
  }

  div[data-highlighted] {
    @apply bg-hover-default;
  }

  /* div[data-selected] { } */

  div[data-disabled] {
    @apply opacity-30 hover:bg-transparent;
  }

  .knowledge-section, .knowledge-selected {
    @apply mt-6;
  }

  .section-title {
    @apply text-base font-semibold;
  }

  div.inDialog {
    z-index: 5000;
  }

  .knowledge-item-container {
    @apply w-full;
  }

  .expand-button {
    @apply flex items-center justify-center p-0 bg-transparent border-none cursor-pointer hover:opacity-70 transition-opacity;
    width: 24px;
    height: 24px;
  }

  .expand-button-placeholder {
    width: 24px;
    height: 24px;
  }

  .blob-list {
    @apply border-default bg-secondary flex flex-col border-t px-4 py-2;
  }

  .blob-item {
    @apply flex items-center justify-between gap-2 py-2 text-sm;
  }

  .blob-item-clickable {
    @apply w-full text-left cursor-pointer hover:bg-hover-dimmer transition-colors;
  }

  .blob-title {
    @apply flex-grow truncate;
  }

  .blob-size {
    @apply flex-shrink-0 text-xs;
  }

  .pagination {
    @apply flex items-center justify-center gap-3 py-3 border-t border-default;
  }
</style>
