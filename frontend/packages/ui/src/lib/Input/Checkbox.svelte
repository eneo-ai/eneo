<script lang="ts">
  import { createCheckbox } from "@melt-ui/svelte";
  import { writable } from "svelte/store";

  export let checked = false;
  export let indeterminate = false;
  export let disabled = false;
  export let onCheckedChange: ((checked: boolean | "indeterminate") => void) | undefined = undefined;
  export let ariaLabel: string | undefined = undefined;

  // Create controlled checked store
  const checkedStore = writable<boolean | "indeterminate">(
    indeterminate ? "indeterminate" : checked
  );

  const {
    elements: { root, input },
    helpers: { isChecked, isIndeterminate }
  } = createCheckbox({
    checked: checkedStore,
    onCheckedChange: ({ next }) => {
      checked = next === true;
      indeterminate = next === "indeterminate";
      onCheckedChange?.(next);
      return next;
    },
    disabled
  });

  // Sync external prop changes to controlled store
  $: checkedStore.set(indeterminate ? "indeterminate" : checked);
</script>

<button
  {...$root}
  use:root
  class="flex h-4 w-4 items-center justify-center rounded border-2 transition-colors
         border-gray-400 bg-white hover:border-gray-600
         data-[state=checked]:border-blue-600 data-[state=checked]:bg-blue-600
         data-[state=indeterminate]:border-blue-600 data-[state=indeterminate]:bg-blue-600
         data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50"
  type="button"
  aria-label={ariaLabel}
>
  {#if $isIndeterminate}
    <!-- Indeterminate dash -->
    <svg
      class="h-3 w-3 text-white"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      stroke-width="3"
    >
      <path stroke-linecap="round" d="M6 12h12" />
    </svg>
  {:else if $isChecked}
    <!-- Check icon -->
    <svg
      class="h-3 w-3 text-white"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      stroke-width="3"
    >
      <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  {/if}
  <input {...$input} use:input />
</button>