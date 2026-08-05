<script lang="ts">
  import { uid } from "uid";
  import CircleOff from "lucide-svelte/icons/circle-off";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import Row from "./Row.svelte";
  import InfoTip from "./InfoTip.svelte";
  import type { ToggleNumberField } from "./form.svelte";

  let {
    title,
    description = "",
    toggleLabel,
    field,
    valueLabel,
    unit = undefined,
    offStatus,
    hint = undefined,
    info = undefined
  }: {
    title: string;
    description?: string;
    /** Visible label next to the switch. */
    toggleLabel: string;
    field: ToggleNumberField;
    /** Inline prefix inside the number input (e.g. "Gallra efter"). */
    valueLabel: string;
    unit?: string;
    /** Status line shown when the switch is off, stating the consequence. */
    offStatus: string;
    hint?: string;
    info?: string;
  } = $props();

  const switchId = uid(8);
  const hintId = uid(8);
  const errorId = uid(8);

  $effect(() => {
    if (field.enabled) field.applySuggestion();
  });

  function describedBy(descriptionId: string): string {
    const ids = [
      description ? descriptionId : null,
      hint ? hintId : null,
      field.error ? errorId : null
    ];
    return ids.filter(Boolean).join(" ");
  }
</script>

<Row
  {title}
  {description}
  hasChanges={field.dirty}
  revertFn={() => field.reset()}
  let:descriptionId
>
  <svelte:fragment slot="title">
    {#if info}<InfoTip {title} text={info} />{/if}
  </svelte:fragment>
  <div class="flex w-full flex-col gap-3">
    <div class="flex items-center gap-3 pt-1">
      <Switch id={switchId} bind:checked={field.enabled} aria-describedby={descriptionId} />
      <Label for={switchId} class="text-primary font-normal">{toggleLabel}</Label>
    </div>
    {#if field.enabled}
      <div class="flex w-full max-w-72 flex-col gap-1.5">
        <InputGroup.Root>
          <InputGroup.Addon align="inline-start">
            <InputGroup.Text>{valueLabel}</InputGroup.Text>
          </InputGroup.Addon>
          <InputGroup.Input
            type="text"
            inputmode="numeric"
            autocomplete="off"
            class="text-right"
            bind:value={field.raw}
            aria-label="{title}: {valueLabel}"
            aria-describedby={describedBy(descriptionId) || undefined}
            aria-invalid={field.error ? true : undefined}
          />
          {#if unit}
            <InputGroup.Addon align="inline-end">
              <InputGroup.Text>{unit}</InputGroup.Text>
            </InputGroup.Addon>
          {/if}
        </InputGroup.Root>
        {#if hint}
          <p id={hintId} class="text-secondary text-xs">{hint}</p>
        {/if}
        {#if field.error}
          <Field.Error id={errorId} class="text-xs">{field.error}</Field.Error>
        {/if}
      </div>
    {:else}
      <Alert.Root class="max-w-xl">
        <CircleOff aria-hidden="true" />
        <Alert.Description>{offStatus}</Alert.Description>
      </Alert.Root>
    {/if}
  </div>
</Row>
