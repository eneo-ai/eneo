<script lang="ts" generics="Item extends { id: string; name: string }">
  import type { Snippet } from "svelte";
  import { fly } from "svelte/transition";
  import { quadInOut } from "svelte/easing";
  import { Select as SelectPrimitive } from "bits-ui";
  import { IconChevronUpDown } from "@eneo/icons/chevron-up-down";
  import * as Select from "$lib/components/ui/select/index.js";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";

  type Props = {
    items: Item[];
    /** The open resource, named on the trigger even when `items` does not contain it. */
    current: { id: string; name: string };
    heading: string;
    onSelect: (item: Item) => void;
    itemIcon: Snippet<[Item]>;
  };

  let { items, current, heading, onSelect, itemIcon }: Props = $props();

  function select(id: string) {
    const item = items.find((candidate) => candidate.id === id);
    if (item) onSelect(item);
  }
</script>

<Select.Root type="single" value={current.id} onValueChange={select}>
  <SelectPrimitive.Trigger>
    {#snippet child({ props })}
      <button
        {...props}
        in:fly|global={{ x: -5, duration: 300, easing: quadInOut, opacity: 0.3 }}
        class="group text-primary hover:border-dimmer hover:bg-hover-default flex max-w-[calc(100%_-_1rem)] items-center justify-between gap-2 overflow-hidden rounded-lg border border-transparent py-0.5 pr-1 pl-2 text-[1.4rem] leading-normal font-extrabold"
      >
        <span class="truncate">{current.name}</span>
        <!-- translate-y to make it look on the same line as the chevron in the space selector -->
        <IconChevronUpDown
          class="text-secondary group-hover:text-primary h-6 w-6 min-w-6 translate-y-[0.05rem]"
        />
      </button>
    {/snippet}
  </SelectPrimitive.Trigger>
  <Select.Content align="start" class="min-w-[24vw]">
    <Select.Group>
      <Select.GroupHeading>{heading}</Select.GroupHeading>
      {#each items as item (item.id)}
        <Select.Item value={item.id} label={item.name} class="min-h-12 gap-3">
          {@render itemIcon(item)}
          <span class="truncate">{formatEmojiTitle(item.name)}</span>
        </Select.Item>
      {/each}
    </Select.Group>
  </Select.Content>
</Select.Root>
