<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import type { SecurityClassification } from "@eneo/eneo-js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Select as SelectPrimitive } from "bits-ui";
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

  const NO_CLASSIFICATION = "none";

  let { classifications, value = $bindable(), onSelectedChange, dryrun }: Props = $props();
  const sortedClassifications = $derived(
    [...classifications].sort((a, b) => b.security_level - a.security_level)
  );

  let selectedKey = $derived(value?.id ?? NO_CLASSIFICATION);

  function select(key: string) {
    const curr = value;
    const next =
      key === NO_CLASSIFICATION
        ? null
        : (sortedClassifications.find((classification) => classification.id === key) ?? null);
    if (curr?.id === next?.id) return;
    onSelectedChange?.({ curr, next });
    if (dryrun) {
      selectedKey = curr?.id ?? NO_CLASSIFICATION;
      return;
    }
    value = next;
  }
</script>

<Select.Root type="single" bind:value={selectedKey} onValueChange={select}>
  <SelectPrimitive.Trigger>
    {#snippet child({ props })}
      <button
        {...props}
        aria-label={m.security_classification()}
        class="border-default hover:bg-hover-default flex h-16 w-full items-center justify-between border-b px-4"
      >
        <span class="truncate capitalize">{value?.name ?? m.no_classification()}</span>
        <IconChevronDown />
      </button>
    {/snippet}
  </SelectPrimitive.Trigger>
  <Select.Content>
    <Select.Group>
      <Select.GroupHeading>{m.select_security_classification()}</Select.GroupHeading>
      {#each sortedClassifications as classification (classification.id)}
        <Select.Item
          value={classification.id}
          label={classification.name}
          class="flex-col items-start gap-1 py-2"
        >
          <span class="font-bold capitalize">{classification.name}</span>
          <span class="text-secondary">{classification.description}</span>
        </Select.Item>
      {/each}
      <Select.Item value={NO_CLASSIFICATION} label={m.no_classification()} class="capitalize">
        {m.no_classification()}
      </Select.Item>
    </Select.Group>
  </Select.Content>
</Select.Root>
