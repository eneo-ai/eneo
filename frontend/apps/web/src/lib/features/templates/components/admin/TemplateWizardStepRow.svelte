<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { m } from "$lib/paraglide/messages";
  import HelpTooltip from "$lib/components/HelpTooltip.svelte";
  import type { WizardStep, WizardStepKind } from "./templateForm";

  let { kind, step = $bindable() }: { kind: WizardStepKind; step: WizardStep } = $props();

  const uid = $props.id();
  const id = (part: string) => `${uid}-${kind}-${part}`;

  const text = $derived(
    kind === "attachments"
      ? {
          title: m.wizard_attachments_section(),
          description: m.wizard_attachments_description(),
          help: m.wizard_attachments_help(),
          required: m.wizard_attachments_required_description(),
          titlePlaceholder: m.wizard_attachments_title_placeholder(),
          descriptionPlaceholder: m.wizard_attachments_description_placeholder()
        }
      : {
          title: m.wizard_collections_section(),
          description: m.wizard_collections_description(),
          help: m.wizard_collections_help(),
          required: m.wizard_collections_required_description(),
          titlePlaceholder: m.wizard_collections_title_placeholder(),
          descriptionPlaceholder: m.wizard_collections_description_placeholder()
        }
  );
</script>

<Settings.Row title={text.title} description={text.description} fullWidth let:aria>
  <HelpTooltip slot="title" text={text.help} />
  <div class="flex flex-col gap-4">
    <RadioGroup.Root
      value={step.enabled ? "on" : "off"}
      onValueChange={(v) => (step.enabled = v === "on")}
      class="grid w-full grid-cols-2 gap-2"
      {...aria}
    >
      <Field.Label for={id("on")} class="font-normal">
        <Field.Field orientation="horizontal">
          <RadioGroup.Item value="on" id={id("on")} />
          <span>{m.enabled()}</span>
        </Field.Field>
      </Field.Label>
      <Field.Label for={id("off")} class="font-normal">
        <Field.Field orientation="horizontal">
          <RadioGroup.Item value="off" id={id("off")} />
          <span>{m.disabled()}</span>
        </Field.Field>
      </Field.Label>
    </RadioGroup.Root>

    {#if step.enabled}
      <div class="border-default bg-hover-default flex flex-col gap-4 rounded-lg border p-4">
        <Field.Field orientation="horizontal">
          <Checkbox id={id("required")} bind:checked={step.required} />
          <Field.Label for={id("required")} class="text-default font-normal">
            {text.required}
          </Field.Label>
        </Field.Field>

        <Field.Field>
          <Field.Label for={id("title")}>{m.title()}</Field.Label>
          <Input id={id("title")} bind:value={step.title} placeholder={text.titlePlaceholder} />
        </Field.Field>

        <Field.Field>
          <Field.Label for={id("description")}>{m.description()}</Field.Label>
          <Textarea
            id={id("description")}
            bind:value={step.description}
            placeholder={text.descriptionPlaceholder}
            class="min-h-20"
          />
        </Field.Field>
      </div>
    {/if}
  </div>
</Settings.Row>
