<script lang="ts">
  import { createCombobox } from "@melt-ui/svelte";
  import { IconCancel } from "@intric/icons/cancel";
  import { IconCollections } from "@intric/icons/collections";
  import { IconPlus } from "@intric/icons/plus";
  import { IconTrash } from "@intric/icons/trash";
  import { IconWeb } from "@intric/icons/web";
  import { Button } from "@intric/ui";
  import type { GroupSparse, IntegrationKnowledge, WebsiteSparse } from "@intric/intric-js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getAvailableKnowledge } from "../getAvailableKnowledge";
  import { tick } from "svelte";
  import { formatWebsiteName } from "$lib/core/formatting/formatWebsiteName";
  import IntegrationVendorIcon from "$lib/features/integrations/components/IntegrationVendorIcon.svelte";

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
      console.log("3",{ personal, org })
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
      <div class="knowledge-item" class:text-negative-default={!isItemModelEnabled}>
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
            {collection.metadata.num_info_blobs} files
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
    {/each}

    {#each selectedWebsitesPersonal as website (`website:${website.id}`)}
      {@const isItemModelEnabled = enabledModels.includes(website.embedding_model.id)}
      <div class="knowledge-item">
        {#if isItemModelEnabled}<IconWeb />{:else}<IconCancel />{/if}
        <span class="truncate px-2">{formatWebsiteName(website)}</span>
        {#if !isItemModelEnabled}<span>(model disabled)</span>{/if}
        <div class="flex-grow"></div>
        <Button variant="destructive" padding="icon" on:click={() => {
          selectedWebsites = selectedWebsites?.filter((item) => item.id !== website.id);
          if ($openPersonal) inputPersonalEl?.focus();
          if ($openOrg)      inputOrgEl?.focus();
        }}><IconTrash /></Button>
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
      <div class="knowledge-item" class:text-negative-default={!isItemModelEnabled}>
        {#if isItemModelEnabled}<IconCollections />{:else}<IconCancel />{/if}
        <span class="truncate px-2">{collection.name}</span>
        {#if !isItemModelEnabled}<span>(model disabled)</span>{/if}
        <div class="flex-grow"></div>
        {#if collection.metadata.num_info_blobs > 0}
          <span class="label-blue border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-sm">
            {collection.metadata.num_info_blobs} files
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
    {/each}

    {#each selectedWebsitesOrg as website (`website:${website.id}`)}
      {@const isItemModelEnabled = enabledModels.includes(website.embedding_model.id)}
      <div class="knowledge-item">
        {#if isItemModelEnabled}<IconWeb />{:else}<IconCancel />{/if}
        <span class="truncate px-2">{formatWebsiteName(website)}</span>
        {#if !isItemModelEnabled}<span>(model disabled)</span>{/if}
        <div class="flex-grow"></div>
        <Button variant="destructive" padding="icon" on:click={() => {
          selectedWebsites = selectedWebsites?.filter((item) => item.id !== website.id);
          if ($openPersonal) inputPersonalEl?.focus();
          if ($openOrg)      inputOrgEl?.focus();
        }}><IconTrash /></Button>
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
        <IconPlus class="min-w-7" />Add knowledge (Personal)
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
                      {collection.metadata.num_info_blobs} files
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
        <p class="knowledge-message">No Personal sources available.</p>
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
        <IconPlus class="min-w-7" />Add knowledge (Organization)
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
                Organization
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
                      {collection.metadata.num_info_blobs} files
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
        <p class="knowledge-message">No Organization sources available.</p>
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
</style>
