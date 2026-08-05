<script lang="ts">
  import { uid } from "uid";
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import Row from "./Row.svelte";
  import InfoTip from "./InfoTip.svelte";
  import type { NumberField } from "./form.svelte";

  let {
    title,
    description = "",
    field,
    unit = undefined,
    placeholder = undefined,
    hint = undefined,
    info = undefined,
    externalError = null,
    restorable = false
  }: {
    title: string;
    description?: string;
    field: NumberField;
    /** Visible unit suffix inside the input group (e.g. "MB", "dagar"). */
    unit?: string;
    placeholder?: string;
    /** Extra helper line under the input (e.g. ceiling or effective value). */
    hint?: string;
    /** Tooltip with secondary explanation, rendered next to the title. */
    info?: string;
    /** Cross-field error owned by the page (e.g. ordering between fields). */
    externalError?: string | null;
    /** Offer a one-click clear when empty means "use the default". */
    restorable?: boolean;
  } = $props();

  const shownError = $derived(field.error ?? externalError);

  const hintId = uid(8);
  const errorId = uid(8);

  function describedBy(descriptionId: string): string {
    const ids = [
      description ? descriptionId : null,
      hint ? hintId : null,
      shownError ? errorId : null
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
  <div class="flex w-full max-w-60 flex-col gap-1.5">
    <InputGroup.Root>
      <InputGroup.Input
        type="text"
        inputmode={field.scale === 1 ? "numeric" : "decimal"}
        autocomplete="off"
        bind:value={field.raw}
        {placeholder}
        aria-label={title}
        aria-describedby={describedBy(descriptionId) || undefined}
        aria-invalid={shownError ? true : undefined}
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
    {#if shownError}
      <Field.Error id={errorId} class="text-xs">{shownError}</Field.Error>
    {/if}
    {#if restorable && field.raw.trim() !== ""}
      <Button
        variant="link"
        class="h-auto w-fit px-0 text-xs"
        aria-label="{m.flow_settings_restore_field()}: {title}"
        onclick={() => (field.raw = "")}
      >
        {m.flow_settings_restore_field()}
      </Button>
    {/if}
  </div>
</Row>
