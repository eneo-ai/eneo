<script lang="ts">
  import { IconCancel } from "@intric/icons/cancel";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { IconFolder } from "@intric/icons/folder";
  import { IconFile } from "@intric/icons/file";
  import { IconTrash } from "@intric/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { m } from "$lib/paraglide/messages";
  import IntegrationVendorIcon from "$lib/features/integrations/components/IntegrationVendorIcon.svelte";
  import {
    getSortedWrapperItems,
    isWrapperFolderItem,
    type IntegrationEntry
  } from "./knowledgeIntegration";
  import WrapperBadges from "./WrapperBadges.svelte";

  type Props = {
    entry: IntegrationEntry;
    enabledModels: string[];
    /** Remove the given integration-knowledge ids from the selection. */
    onRemove: (ids: string[]) => void;
  };

  let { entry, enabledModels, onRemove }: Props = $props();

  const modelEnabled = $derived(
    entry.type === "wrapper"
      ? enabledModels.includes(entry.wrapper.items[0]?.embedding_model.id)
      : enabledModels.includes(entry.knowledge.embedding_model.id)
  );

  let expanded = $state(false);
</script>

{#if entry.type === "wrapper"}
  {@const wrapper = entry.wrapper}
  <Collapsible.Root bind:open={expanded} class="w-full">
    <div
      class="border-default hover:bg-hover-dimmer flex h-16 w-full items-center gap-2 border-b px-4"
    >
      <Collapsible.Trigger
        class="flex size-6 cursor-pointer items-center justify-center transition-opacity hover:opacity-70"
        aria-label={expanded ? m.aria_collapse() : m.aria_expand()}
      >
        {#if expanded}<IconChevronDown />{:else}<IconChevronRight />{/if}
      </Collapsible.Trigger>

      {#if modelEnabled}
        <IntegrationVendorIcon size="sm" type={wrapper.integration_type} />
      {:else}
        <IconCancel />
      {/if}

      <span class="truncate px-2">{wrapper.name}</span>
      <WrapperBadges items={wrapper.items} />
      {#if !modelEnabled}<span>({m.model_disabled()})</span>{/if}
      <div class="flex-grow"></div>

      <Button
        variant="destructive"
        size="icon"
        aria-label={m.remove()}
        onclick={() => onRemove(wrapper.items.map((item) => item.id))}
      >
        <IconTrash />
      </Button>
    </div>

    <Collapsible.Content>
      <div class="border-default bg-secondary flex flex-col border-t px-4 py-2">
        {#each getSortedWrapperItems(wrapper.items) as wrapperItem (wrapperItem.id)}
          <div class="flex items-center justify-between gap-2 py-2 text-sm">
            <span class="flex min-w-0 flex-1 items-center gap-2">
              {#if isWrapperFolderItem(wrapperItem)}
                <IconFolder class="text-secondary h-4 w-4 flex-shrink-0" />
              {:else}
                <IconFile class="text-secondary h-4 w-4 flex-shrink-0" />
              {/if}
              <span class="truncate">{wrapperItem.name}</span>
            </span>
            {#if wrapperItem.folder_path}
              <span class="text-muted max-w-[50%] flex-shrink-0 truncate text-xs">
                {wrapperItem.folder_path}
              </span>
            {/if}
          </div>
        {/each}
      </div>
    </Collapsible.Content>
  </Collapsible.Root>
{:else}
  {@const knowledge = entry.knowledge}
  <div
    class="border-default hover:bg-hover-dimmer flex h-16 w-full items-center gap-2 border-b px-4"
  >
    <div class="size-6"></div>
    {#if modelEnabled}
      <IntegrationVendorIcon size="sm" type={knowledge.integration_type} />
    {:else}
      <IconCancel />
    {/if}
    <span class="flex-grow truncate px-2">{knowledge.name}</span>
    {#if !modelEnabled}<span>({m.model_disabled()})</span>{/if}

    <Button
      variant="destructive"
      size="icon"
      aria-label={m.remove()}
      onclick={() => onRemove([knowledge.id])}
    >
      <IconTrash />
    </Button>
  </div>
{/if}
