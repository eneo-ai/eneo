<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import * as Select from "$lib/components/ui/select/index.js";
  import { listHostingOptions, findHostingLabel, type HostingValue } from "./hostingOptions.js";

  let {
    value = $bindable(),
    id,
    disabled = false
  }: {
    value: HostingValue | string;
    id?: string;
    disabled?: boolean;
  } = $props();

  const options = listHostingOptions();
  const label = $derived(findHostingLabel(value));
</script>

<Select.Root type="single" bind:value {disabled}>
  <Select.Trigger {id} class="w-full">
    <span data-slot="select-value">{label}</span>
  </Select.Trigger>
  <Select.Content>
    {#each options as option (option.value)}
      <Select.Item value={option.value} label={option.label}>
        {option.label}
      </Select.Item>
    {/each}
  </Select.Content>
</Select.Root>
