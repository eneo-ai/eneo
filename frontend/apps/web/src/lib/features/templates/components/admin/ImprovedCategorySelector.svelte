<script lang="ts">
  import { untrack } from "svelte";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
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
      <Select.Root
        type="single"
        value={predefinedValue}
        onValueChange={(next) => {
          if (next) predefinedValue = next;
        }}
      >
        <Select.Trigger aria-label={m.select_category()} class="h-11 w-full">
          {predefinedCategories[predefinedValue]?.title || m.select_category()}
        </Select.Trigger>
        <Select.Content class="max-h-64">
          {#each categoryKeys as categoryKey (categoryKey)}
            <Select.Item
              value={categoryKey}
              label={predefinedCategories[categoryKey].title}
              class="flex-col items-start gap-1 py-2"
            >
              <span class="font-medium">{predefinedCategories[categoryKey].title}</span>
              <span class="text-secondary">{predefinedCategories[categoryKey].description}</span>
            </Select.Item>
          {/each}
        </Select.Content>
      </Select.Root>
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
