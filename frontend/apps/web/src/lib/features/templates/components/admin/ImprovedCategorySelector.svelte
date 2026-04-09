<script lang="ts">
  import { untrack } from "svelte";
  import { createSelect } from "@melt-ui/svelte";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconCheck } from "@intric/icons/check";
  import { Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { assistantTemplateCategories, appTemplateCategories } from "../../TemplateCategories";

  interface Props {
    value?: string;
    type: "assistant" | "app";
  }

  let { value = $bindable(""), type }: Props = $props();

  const predefinedCategories: Record<string, { title: string; description: string }> = $derived(
    type === "assistant" ? assistantTemplateCategories : appTemplateCategories
  );
  const categoryKeys = $derived(Object.keys(predefinedCategories));

  // Mode: true = predefined, false = custom
  let isPredefined = $state(true);
  let customValue = $state("");
  let predefinedValue = $state(untrack(() => categoryKeys[0] || ""));

  // Ensure initial value is set for predefined mode
  $effect(() => {
    if (isPredefined && !value && predefinedValue) {
      value = predefinedValue;
    }
  });

  // Initialize mode and values based on incoming value
  $effect(() => {
    if (value) {
      if (categoryKeys.includes(value)) {
        isPredefined = true;
        predefinedValue = value;
      } else {
        isPredefined = false;
        customValue = value;
      }
    }
  });

  // Update external value when mode or internal values change
  $effect(() => {
    if (isPredefined) {
      value = predefinedValue;
    } else {
      value = customValue;
    }
  });

  const {
    elements: { trigger, menu, option },
    helpers: { isSelected },
    states: { open }
  } = createSelect<string>({
    defaultSelected: { value: untrack(() => predefinedValue) },
    positioning: {
      placement: "bottom",
      strategy: "fixed",
      fitViewport: true,
      sameWidth: true
    },
    portal: "body",
    onSelectedChange: ({ next }) => {
      if (next?.value) {
        predefinedValue = next.value;
      }
      return next;
    }
  });
</script>

<div class="flex flex-col gap-4">
  <!-- Mode Toggle using RadioSwitch for consistency -->
  <!-- Note: Label and description come from Settings.Row parent -->
  <Input.RadioSwitch bind:value={isPredefined} labelTrue={m.predefined()} labelFalse={m.custom()} />

  <!-- Selector or Input based on mode -->
  <div class="flex flex-col gap-2">
    {#if isPredefined}
      <button
        {...$trigger}
        use:trigger
        type="button"
        aria-label={m.select_category()}
        class="border-default hover:bg-hover-default flex h-11 items-center justify-between rounded-lg border px-4 py-2.5"
      >
        <span class="text-default text-sm font-medium">
          {predefinedCategories[predefinedValue]?.title || m.select_category()}
        </span>
        <IconChevronDown class="text-dimmer" />
      </button>

      {#if $open}
        <div
          class="border-default bg-primary z-50 flex max-h-64 flex-col overflow-y-auto rounded-lg border shadow-xl"
          {...$menu}
          use:menu
        >
          {#each categoryKeys as categoryKey (categoryKey)}
            <div
              class="border-default hover:bg-hover-default flex min-h-12 items-center justify-between border-b px-4 py-3 last:border-b-0 hover:cursor-pointer"
              {...$option({ value: categoryKey })}
              use:option
            >
              <div class="flex flex-col gap-1">
                <span class="text-default text-sm font-medium">
                  {predefinedCategories[categoryKey].title}
                </span>
                <span class="text-secondary text-sm">
                  {predefinedCategories[categoryKey].description}
                </span>
              </div>
              <div class="check {$isSelected(categoryKey) ? 'block' : 'hidden'}">
                <IconCheck class="text-positive-default" />
              </div>
            </div>
          {/each}
        </div>
      {/if}
    {:else}
      <Input.Text
        bind:value={customValue}
        placeholder={m.category_name_placeholder()}
        required
        hiddenLabel={true}
      />
      <p class="text-secondary text-sm">
        {m.custom_category_help()}
      </p>
    {/if}
  </div>
</div>

<style lang="postcss">
  @reference '@intric/ui/styles';

  div[data-highlighted] {
    @apply bg-hover-dimmer;
  }

  div[data-disabled] {
    @apply opacity-30 hover:bg-transparent;
  }
</style>
