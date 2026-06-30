<script lang="ts">
  import { IconCancel } from "@eneo/icons/cancel";
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import { IconChevronRight } from "@eneo/icons/chevron-right";
  import { IconFolder } from "@eneo/icons/folder";
  import { IconFile } from "@eneo/icons/file";
  import { IconTrash } from "@eneo/icons/trash";
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
  <Collapsible.Root
    bind:open={expanded}
    class="border-default bg-primary w-full overflow-hidden rounded-xl border transition-shadow duration-150 hover:shadow-sm"
  >
    <div class="flex h-14 w-full items-center gap-2 px-3">
      <Collapsible.Trigger
        class="text-secondary hover:bg-hover-dimmer hover:text-primary focus-visible:ring-stronger flex size-7 cursor-pointer items-center justify-center rounded-lg transition-colors focus-visible:ring-2 focus-visible:outline-none"
        aria-label={expanded ? m.aria_collapse() : m.aria_expand()}
      >
        {#if expanded}<IconChevronDown />{:else}<IconChevronRight />{/if}
      </Collapsible.Trigger>

      {#if modelEnabled}
        <IntegrationVendorIcon size="sm" type={wrapper.integration_type} />
      {:else}
        <IconCancel />
      {/if}

      <Collapsible.Trigger
        class="focus-visible:ring-stronger hover:text-primary flex-grow cursor-pointer truncate rounded-md px-1 text-left text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none"
      >
        {wrapper.name}
      </Collapsible.Trigger>
      <WrapperBadges items={wrapper.items} />
      {#if !modelEnabled}<span class="text-negative-default text-sm">({m.model_disabled()})</span
        >{/if}

      <Button
        variant="ghost"
        size="icon"
        class="text-muted hover:text-negative-default hover:bg-negative-dimmer shrink-0"
        aria-label={m.remove()}
        onclick={() => onRemove(wrapper.items.map((item) => item.id))}
      >
        <IconTrash />
      </Button>
    </div>

    <Collapsible.Content>
      <div class="border-default flex flex-col gap-0.5 border-t px-2 py-1.5">
        {#each getSortedWrapperItems(wrapper.items) as wrapperItem (wrapperItem.id)}
          <div class="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-sm">
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
    class="border-default bg-primary flex h-14 w-full items-center gap-2 overflow-hidden rounded-xl border px-3 transition-shadow duration-150 hover:shadow-sm"
  >
    <div class="size-7"></div>
    {#if modelEnabled}
      <IntegrationVendorIcon size="sm" type={knowledge.integration_type} />
    {:else}
      <IconCancel />
    {/if}
    <span class="flex-grow truncate px-1 text-sm font-medium">{knowledge.name}</span>
    {#if !modelEnabled}<span class="text-negative-default text-sm">({m.model_disabled()})</span
      >{/if}

    <Button
      variant="ghost"
      size="icon"
      class="text-muted hover:text-negative-default hover:bg-negative-dimmer shrink-0"
      aria-label={m.remove()}
      onclick={() => onRemove([knowledge.id])}
    >
      <IconTrash />
    </Button>
  </div>
{/if}
