<!--
  A required written reason: shown to other people and kept in the audit log.
  Validation is the form's job: pass `error` on submit and focus `ref`.
-->
<script lang="ts">
  import type { Snippet } from "svelte";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { m } from "$lib/paraglide/messages";
  import { REASON_MAX_LENGTH } from "./reason";

  type Props = {
    id: string;
    label: string;
    /** Who sees the reason, shown under the field. */
    help: string;
    value?: string;
    /** Shown under the field and marks it invalid; set it on submit, not while typing. */
    error?: string | null;
    ref?: HTMLTextAreaElement | null;
    /** Rendered at the end of the help text, e.g. a link to the docs. */
    helpLink?: Snippet;
    rows?: number;
  };

  let {
    id,
    label,
    help,
    value = $bindable(""),
    error = null,
    ref = $bindable(null),
    helpLink,
    rows = 3
  }: Props = $props();

  const describedBy = $derived(
    [`${id}-help`, `${id}-counter`, error ? `${id}-error` : null].filter(Boolean).join(" ")
  );
</script>

<Field.Field>
  <Field.Label for={id}>
    {label}
    <span class="text-secondary font-normal">{m.oversight_reason_required()}</span>
  </Field.Label>
  <Textarea
    {id}
    bind:ref
    bind:value
    {rows}
    maxlength={REASON_MAX_LENGTH}
    aria-required="true"
    aria-invalid={error ? true : undefined}
    aria-describedby={describedBy}
  />
  {#if error}
    <!-- Not an alert: the form moves focus here, which reads the error with the field. -->
    <p id={`${id}-error`} class="text-negative-stronger text-sm font-medium">{error}</p>
  {/if}
  <div class="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
    <Field.Description id={`${id}-help`}>
      {help}
      {@render helpLink?.()}
    </Field.Description>
    <!-- Not live: announcing every keystroke drowns out the typing. -->
    <p id={`${id}-counter`} class="text-secondary shrink-0 text-sm tabular-nums">
      {m.oversight_reason_counter({ count: value.length, max: REASON_MAX_LENGTH })}
    </p>
  </div>
</Field.Field>
