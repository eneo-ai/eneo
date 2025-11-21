<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { createSelect } from "@melt-ui/svelte";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconCheck } from "@intric/icons/check";
  import { Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import {
    assistantTemplateCategories,
    appTemplateCategories,
    formatCategoryTitle
  } from "../../TemplateCategories";

  let {
    value = $bindable(""),
    type
  }: {
    value: string;
    type: "assistant" | "app";
  } = $props();

  const predefinedCategories =
    type === "assistant" ? assistantTemplateCategories : appTemplateCategories;
  const categoryKeys = Object.keys(predefinedCategories);

  // Check if current value is a custom category
  let isCustom = $state(!categoryKeys.includes(value));
  let customValue = $state(isCustom ? value : "");

  // Create options array with predefined categories plus "custom" option
  const categoryOptions = [...categoryKeys, "custom"];

  const {
    elements: { trigger, menu, option },
    helpers: { isSelected },
    states: { selected }
  } = createSelect<string>({
    defaultSelected: { value: isCustom ? "custom" : value || categoryKeys[0] },
    positioning: {
      placement: "bottom",
      fitViewport: true,
      sameWidth: true
    },
    portal: null,
    onSelectedChange: ({ next }) => {
      if (next?.value === "custom") {
        isCustom = true;
        value = customValue || "";
      } else if (next?.value) {
        isCustom = false;
        value = next.value;
        customValue = "";
      }
      return next;
    }
  });

  // Update value when custom input changes
  function handleCustomInput() {
    if (isCustom) {
      value = customValue;
    }
  }

  // Watch for external value changes
  $effect(() => {
    const newIsCustom = !categoryKeys.includes(value);
    if (newIsCustom !== isCustom) {
      isCustom = newIsCustom;
      if (newIsCustom) {
        customValue = value;
        $selected = { value: "custom" };
      } else {
        $selected = { value };
      }
    }
  });
</script>

<div class="flex flex-col gap-2">
  <label class="text-default text-sm font-medium">{m.category()}</label>

  <button
    {...$trigger}
    use:trigger
    aria-label={m.select_category()}
    class="border-default hover:bg-hover-default flex h-10 items-center justify-between rounded-lg border px-3"
  >
    <span class="text-default">
      {#if $selected?.value === "custom"}
        {m.custom_category()}
      {:else if $selected?.value && predefinedCategories[$selected.value]}
        {predefinedCategories[$selected.value].title}
      {:else}
        {m.select_category()}
      {/if}
    </span>
    <IconChevronDown class="text-dimmer" />
  </button>

  <div
    class="border-default bg-default z-20 flex max-h-64 flex-col overflow-y-auto rounded-lg border shadow-xl"
    {...$menu}
    use:menu
  >
    <div class="bg-dimmer border-default sticky top-0 border-b px-3 py-2 text-sm font-medium">
      {m.select_category()}
    </div>
    {#each categoryOptions as categoryKey (categoryKey)}
      <div
        class="border-default hover:bg-hover-default flex min-h-10 items-center justify-between border-b px-3 hover:cursor-pointer last:border-b-0"
        {...$option({ value: categoryKey })}
        use:option
      >
        <div class="flex flex-col gap-0.5">
          <span class="text-default text-sm">
            {categoryKey === "custom"
              ? m.custom_category()
              : predefinedCategories[categoryKey].title}
          </span>
          {#if categoryKey !== "custom"}
            <span class="text-dimmer text-xs">
              {predefinedCategories[categoryKey].description}
            </span>
          {/if}
        </div>
        <div class="check {$isSelected(categoryKey) ? 'block' : 'hidden'}">
          <IconCheck class="text-positive-default" />
        </div>
      </div>
    {/each}
  </div>

  {#if isCustom}
    <Input.Text
      bind:value={customValue}
      oninput={handleCustomInput}
      label={m.custom_category_name()}
      placeholder={m.enter_custom_category()}
      required
    />
  {/if}
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";

  div[data-highlighted] {
    @apply bg-hover-dimmer;
  }

  div[data-disabled] {
    @apply opacity-30 hover:bg-transparent;
  }
</style>
