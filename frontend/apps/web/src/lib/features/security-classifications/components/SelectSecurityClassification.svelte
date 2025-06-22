<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconCheck } from "@intric/icons/check";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import type { SecurityClassification } from "@intric/intric-js";
  import { createSelect } from "@melt-ui/svelte";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    classifications: SecurityClassification[];
    value: SecurityClassification | null;
    onSelectedChange?:
      | ((args: {
          curr: SecurityClassification | null | undefined;
          next: SecurityClassification | null | undefined;
        }) => void)
      | undefined;
    dryrun?: boolean;
  };

  let { classifications, value = $bindable(), onSelectedChange, dryrun }: Props = $props();
  classifications.sort((a, b) => b.security_level - a.security_level);

  const {
    elements: { trigger, menu, option },
    helpers: { isSelected },
    states: { selected }
  } = createSelect<SecurityClassification | null>({
    defaultSelected: { value },
    positioning: {
      placement: "bottom",
      fitViewport: true,
      sameWidth: true
    },
    portal: null,
    onSelectedChange: ({ curr, next }) => {
      if (curr?.value?.id === next?.value?.id) return curr;
      onSelectedChange?.({ curr: curr?.value, next: next?.value });
      if (dryrun) {
        return curr;
      }
      value = next?.value ?? null;
      return next;
    }
  });
</script>

<button
  {...$trigger}
  use:trigger
  class="border-default hover:bg-hover-default flex h-16 items-center justify-between border-b px-4"
>
  <span class="truncate capitalize">{$selected?.value?.name ?? m.no_classification()}</span>
  <IconChevronDown />
</button>

<div
  class="border-stronger bg-primary z-20 flex flex-col overflow-y-auto rounded-lg border shadow-xl"
  {...$menu}
  use:menu
>
  <div
    class="bg-frosted-glass-secondary border-default sticky top-0 border-b px-4 py-2 font-mono text-sm"
  >
    {m.select_security_classification()}
  </div>
  {#each classifications as classification (classification.id)}
    <div
      class="border-default hover:bg-hover-stronger flex flex-col items-stretch justify-between overflow-visible border-b px-4 py-4 hover:cursor-pointer"
      {...$option({ value: classification })}
      use:option
    >
      <div class="flex w-full justify-start">
        <span class="font-bold capitalize">
          {classification.name}
        </span>
        <span class="flex-grow"></span>
        <div class="check {$isSelected(classification) ? 'block' : 'hidden'}">
          <IconCheck class="text-positive-default" />
        </div>
      </div>
      <div class="text-secondary pt-1">{classification.description}</div>
    </div>
  {/each}
  <div
    class="border-default hover:bg-hover-stronger flex min-h-16 items-center justify-between border-b px-4 hover:cursor-pointer"
    {...$option({ value: null })}
    use:option
  >
    <span class="capitalize">{m.no_classification()}</span>
    <div class="check {$selected?.value === null ? 'block' : 'hidden'}">
      <IconCheck class="text-positive-default" />
    </div>
  </div>
</div>
