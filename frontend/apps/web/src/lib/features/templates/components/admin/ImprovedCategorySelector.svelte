<script lang="ts">
  import { untrack } from "svelte";
  import { createSelect } from "@melt-ui/svelte";
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import { IconCheck } from "@eneo/icons/check";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import { m } from "$lib/paraglide/messages";
  import { assistantTemplateCategories, appTemplateCategories } from "../../TemplateCategories";

  interface Props {
    value?: string;
    type: "assistant" | "app";
  }

  let { value = $bindable(""), type }: Props = $props();
  const uid = $props.id();

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
  <!-- Note: Label and description come from Settings.Row parent -->
  <RadioGroup.Root
    value={isPredefined ? "on" : "off"}
    onValueChange={(v) => (isPredefined = v === "on")}
    class="grid w-full grid-cols-2 gap-2"
    aria-label={m.category()}
  >
    <Field.Label for={`${uid}-on`} class="font-normal">
      <Field.Field orientation="horizontal">
        <RadioGroup.Item value="on" id={`${uid}-on`} />
        <span>{m.predefined()}</span>
      </Field.Field>
    </Field.Label>
    <Field.Label for={`${uid}-off`} class="font-normal">
      <Field.Field orientation="horizontal">
        <RadioGroup.Item value="off" id={`${uid}-off`} />
        <span>{m.custom()}</span>
      </Field.Field>
    </Field.Label>
  </RadioGroup.Root>

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
      <Input
        bind:value={customValue}
        placeholder={m.category_name_placeholder()}
        required
        aria-label={m.category()}
        aria-describedby={`${uid}-custom-help`}
      />
      <p id={`${uid}-custom-help`} class="text-secondary text-sm">
        {m.custom_category_help()}
      </p>
    {/if}
  </div>
</div>

<style lang="postcss">
  @reference '@eneo/ui/styles';

  div[data-highlighted] {
    @apply bg-hover-dimmer;
  }

  div[data-disabled] {
    @apply opacity-30 hover:bg-transparent;
  }
</style>
