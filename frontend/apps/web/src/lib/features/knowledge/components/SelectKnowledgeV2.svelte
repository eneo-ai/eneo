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
  import { m } from "$lib/paraglide/messages";
  import { formatWebsiteName } from "$lib/core/formatting/formatWebsiteName";
  import IntegrationVendorIcon from "$lib/features/integrations/components/IntegrationVendorIcon.svelte";

  /** Bind this variable if you want to be able to select websites */
  export let selectedWebsites: WebsiteSparse[] | undefined = undefined;
  /** Bind this variable if you want to be able to select collections aka groups */
  export let selectedCollections: GroupSparse[] | undefined = undefined;
  /** Bind this variable if you want to be able to select collections aka groups */
  export let selectedIntegrationKnowledge:
    | Omit<IntegrationKnowledge[], "tenant_id" | "user_integration_id" | "space_id">
    | undefined = undefined;

  export let aria: AriaProps = { "aria-label": "Select knowledge" };
  /**
   * Set this to true if you're rendering the selector inside a dialog. Will portal it to the body element
   * and set a z-index of 5000, so it is always on top. Helps to prevent clipping to scroll parent inside a dialog.
   */
  export let inDialog = false;

  const {
    elements: { input, menu, group, groupLabel, option },
    states: { open, inputValue }
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
      if (next) {
        addItem(next.value);
      }
      inputElement.blur();
      $inputValue = "";
      setTimeout(() => {
        triggerButton.focus();
      }, 1);
      return undefined;
    },
    portal: inDialog ? "body" : null
  });

  const {
    state: { currentSpace }
  } = getSpacesManager();

  function addItem(
    item:
      | { website: WebsiteSparse }
      | { collection: GroupSparse }
      | { integrationKnowledge: IntegrationKnowledge }
  ) {
    if ("collection" in item && selectedCollections) {
      selectedCollections = [...selectedCollections, item.collection];
    }
    if ("website" in item && selectedWebsites) {
      selectedWebsites = [...selectedWebsites, item.website];
    }
    if ("integrationKnowledge" in item && selectedIntegrationKnowledge) {
      selectedIntegrationKnowledge = [...selectedIntegrationKnowledge, item.integrationKnowledge];
    }
  }

  let inputElement: HTMLInputElement;
  let triggerButton: HTMLButtonElement;

  $: availableKnowledge = getAvailableKnowledge(
    $currentSpace,
    selectedWebsites,
    selectedCollections,
    selectedIntegrationKnowledge,
    $inputValue
  );

  $: sections = Object.values(availableKnowledge.sections);

  $: enabledModels = $currentSpace.embedding_models.map((model) => model.id);
</script>

{#if selectedCollections}
  {#each selectedCollections as collection (collection.id)}
    {@const isItemModelEnabled = enabledModels.includes(collection.embedding_model.id)}
    <div class="knowledge-item" class:text-negative-default={!isItemModelEnabled}>
      {#if isItemModelEnabled}
        <IconCollections />
      {:else}
        <IconCancel />
      {/if}
      <span class="truncate px-2">{collection.name}</span>
      {#if !isItemModelEnabled}
        <span>(model disabled)</span>
      {/if}
      <div class="flex-grow"></div>
      {#if collection.metadata.num_info_blobs > 0}
        <span
          class="label-blue border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-sm"
          >{collection.metadata.num_info_blobs} files</span
        >
      {:else}
        <span
          class="label-neutral border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-sm"
          >{m.empty()}</span
        >
      {/if}
      <Button
        variant="destructive"
        padding="icon"
        on:click={() => {
          selectedCollections = selectedCollections?.filter((item) => item.id !== collection.id);
          if ($open) inputElement.focus();
        }}><IconTrash /></Button
      >
    </div>
  {/each}
{/if}

{#if selectedWebsites}
  {#each selectedWebsites as website (website.id)}
    {@const isItemModelEnabled = enabledModels.includes(website.embedding_model.id)}
    <div class="knowledge-item">
      {#if isItemModelEnabled}
        <IconWeb />
      {:else}
        <IconCancel />
      {/if}
      <span class="truncate px-2">{formatWebsiteName(website)}</span>
      {#if !isItemModelEnabled}
        <span>(model disabled)</span>
      {/if}
      <div class="flex-grow"></div>
      <Button
        variant="destructive"
        padding="icon"
        on:click={() => {
          selectedWebsites = selectedWebsites?.filter((item) => item.id !== website.id);
          if ($open) inputElement.focus();
        }}><IconTrash /></Button
      >
    </div>
  {/each}
{/if}

{#if selectedIntegrationKnowledge}
  {#each selectedIntegrationKnowledge as knowledge (knowledge.id)}
    {@const isItemModelEnabled = enabledModels.includes(knowledge.embedding_model.id)}
    <div class="knowledge-item">
      {#if isItemModelEnabled}
        <IntegrationVendorIcon size="sm" type={knowledge.integration_type}></IntegrationVendorIcon>
      {:else}
        <IconCancel />
      {/if}
      <span class="truncate px-2">{knowledge.name}</span>
      {#if !isItemModelEnabled}
        <span>(model disabled)</span>
      {/if}
      <div class="flex-grow"></div>
      <Button
        variant="destructive"
        padding="icon"
        on:click={() => {
          selectedIntegrationKnowledge = selectedIntegrationKnowledge?.filter(
            (item) => item.id !== knowledge.id
          );
          if ($open) inputElement.focus();
        }}><IconTrash /></Button
      >
    </div>
  {/each}
{/if}

{#if $open}
  <div class="border-default relative mt-2 h-12 w-full overflow-clip rounded-lg border">
    <input
      bind:this={inputElement}
      name="knowledgeFilter"
      class="absolute inset-0 rounded-lg pl-[4.2rem] text-lg"
      {...$input}
      use:input
    />

    <label
      for="knowledgeFilter"
      class="text-muted pointer-events-none absolute top-0 bottom-0 left-3 flex items-center text-lg"
      >{m.filter()}</label
    >
  </div>
{:else}
  <button
    bind:this={triggerButton}
    {...aria}
    class="border-default hover:bg-hover-default relative mt-2 flex h-12 w-full items-center justify-center gap-1 overflow-clip rounded-lg border"
    on:click={async () => {
      $open = true;
      await tick();
      inputElement.focus();
    }}
  >
    <IconPlus class="min-w-7" />Add knowledge
  </button>
{/if}

<div
  class="border-default bg-primary z-20 flex flex-col overflow-hidden overflow-y-auto rounded-lg border shadow-xl"
  class:inDialog
  {...$menu}
  use:menu
>
  {#if sections.length > 0}
    {#each sections as section (section)}
      <div {...$group(section.name)} use:group class="flex w-full flex-col">
        <div
          class="bg-frosted-glass-secondary border-default sticky top-0 flex items-center gap-3 border-b px-4 py-2 font-mono text-sm"
          {...$groupLabel(section.name)}
          use:groupLabel
        >
          {availableKnowledge.showHeaders ? section.name : m.select_knowledge_source()}
        </div>
        {#if !section.isEnabled}
          <p class="knowledge-message">{section.name} is currently not enabled in this space.</p>
        {:else if !section.isCompatible}
          <p class="knowledge-message">
            The sources embedded by this model are not compatible with the currently selected
            knowledge.
          </p>
        {:else if section.availableItemsCount === 0}
          <p class="knowledge-message">{m.no_more_sources()}</p>
        {:else}
          {#each section.groups as collection (collection.id)}
            <div
              class="knowledge-item cursor-pointer"
              {...$option({ value: { collection } })}
              use:option
            >
              <div class="flex max-w-full flex-grow items-center gap-3">
                <IconCollections />
                <span class="truncate">{collection.name}</span>
              </div>
              <div class="flex-grow"></div>

              {#if collection.metadata.num_info_blobs > 0}
                <span
                  class="label-blue border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-sm"
                  >{collection.metadata.num_info_blobs} files</span
                >
              {:else}
                <span
                  class="label-neutral border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-sm"
                  >{m.empty()}</span
                >
              {/if}
            </div>
          {/each}
          {#each section.websites as website (website.id)}
            <div
              class="knowledge-item cursor-pointer"
              {...$option({ value: { website } })}
              use:option
            >
              <div class="flex max-w-full flex-grow items-center gap-3">
                <IconWeb />
                <span class=" truncate">{formatWebsiteName(website)}</span>
              </div>
            </div>
          {/each}
          {#each section.integrationKnowledge as integrationKnowledge (integrationKnowledge.id)}
            <div
              class="knowledge-item cursor-pointer"
              {...$option({ value: { integrationKnowledge } })}
              use:option
            >
              <div class="flex max-w-full flex-grow items-center gap-3">
                <IntegrationVendorIcon size="sm" type={integrationKnowledge.integration_type}
                ></IntegrationVendorIcon>

                <span class=" truncate">{integrationKnowledge.name}</span>
              </div>
            </div>
          {/each}
        {/if}
      </div>
    {/each}
  {:else}
    <p class="knowledge-message">
      This spaces does not have any selectable knowledge sources configured.
    </p>
  {/if}
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";
  p.knowledge-message {
    @apply text-muted flex min-h-16 items-center justify-center px-4 text-center;
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

  div.inDialog {
    z-index: 5000;
  }
</style>
