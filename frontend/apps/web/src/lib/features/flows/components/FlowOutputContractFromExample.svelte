<script lang="ts">
  import ClipboardPaste from "@lucide/svelte/icons/clipboard-paste";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    contractFromExample,
    EXAMPLE_MAX_CHARACTERS,
    EXAMPLE_MAX_FIELDS,
    type ExampleNote,
    type ExampleProblem,
    type ExampleShape
  } from "../outputContractFromExample";
  import { formatAdvancedJson, hasCustomJson } from "./advancedJsonDrafts";

  let {
    currentContract,
    disabled,
    onCreate
  }: {
    /** The output contract draft as it stands, to ask before it is replaced. */
    currentContract: string;
    disabled: boolean;
    onCreate: (contractText: string) => void;
  } = $props();

  const PROBLEM_SENTENCES: Record<ExampleProblem, () => string> = {
    syntax: m.flow_step_json_parse_error,
    not_object: m.flow_step_json_not_object,
    no_fields: m.flow_contract_example_no_fields,
    inexact_number: m.flow_contract_example_number_too_large,
    too_large: () =>
      m.flow_contract_example_too_large({
        characters: String(EXAMPLE_MAX_CHARACTERS),
        fields: String(EXAMPLE_MAX_FIELDS)
      })
  };
  const NOTE_SENTENCES: Record<ExampleNote, () => string> = {
    empty_list: m.flow_contract_example_note_empty_list,
    null_value: m.flow_contract_example_note_null_value,
    mixed_list: m.flow_contract_example_note_mixed_list
  };

  const uid = $props.id();
  let open = $state(false);
  let confirmReplace = $state(false);
  let example = $state("");
  const reading = $derived(example.trim() ? contractFromExample(example) : null);
  const holdsNonVariable = $derived(
    reading?.ok === true && reading.fields.some((field) => !field.variable)
  );

  function shapeLabel(shape: ExampleShape): string {
    switch (shape.kind) {
      case "object":
        return shape.fields.length > 0
          ? m.flow_contract_example_type_object_fields({ fields: shape.fields.join(", ") })
          : m.flow_contract_example_type_object();
      case "list":
        return shape.item
          ? m.flow_contract_example_type_list({ item: shapeLabel(shape.item) })
          : m.flow_contract_example_type_list_any();
      case "string":
        return m.flow_contract_example_type_string();
      case "number":
        return m.flow_contract_example_type_number();
      case "boolean":
        return m.flow_contract_example_type_boolean();
      case "text_or_empty":
        return m.flow_contract_example_type_text_or_empty();
    }
  }

  function close() {
    open = false;
    example = "";
  }

  function create() {
    if (!reading?.ok) return;
    if (hasCustomJson(currentContract)) {
      confirmReplace = true;
      return;
    }
    write();
  }

  function write() {
    if (!reading?.ok) return;
    onCreate(formatAdvancedJson(reading.contract));
    confirmReplace = false;
    close();
  }
</script>

<!-- The trigger belongs to the dialog, so closing returns focus to it. -->
<Dialog.Root
  bind:open
  onOpenChange={(next) => {
    if (!next) example = "";
  }}
>
  <Dialog.Trigger {disabled}>
    {#snippet child({ props })}
      <Button variant="outline" size="sm" {...props}>
        <ClipboardPaste data-icon="inline-start" />
        {m.flow_contract_example_button()}
      </Button>
    {/snippet}
  </Dialog.Trigger>
  <Dialog.Content class="sm:max-w-lg" closeLabel={m.close()}>
    <Dialog.Header>
      <Dialog.Title>{m.flow_contract_example_title()}</Dialog.Title>
      <Dialog.Description>{m.flow_contract_example_description()}</Dialog.Description>
    </Dialog.Header>

    <Field.Field data-invalid={reading?.ok === false || undefined}>
      <Field.Label for="{uid}-example">{m.flow_contract_example_label()}</Field.Label>
      <Textarea
        id="{uid}-example"
        rows={6}
        class="max-h-[40vh] font-mono"
        spellcheck={false}
        placeholder={'{"anomaly_days": ["2026-01-02"], "total": 4}'}
        bind:value={example}
        aria-invalid={reading?.ok === false}
        aria-describedby={reading?.ok === false ? `${uid}-problem` : undefined}
      />
      {#if reading?.ok === false}
        <Field.Error id="{uid}-problem" role="alert">
          {PROBLEM_SENTENCES[reading.problem]()}
        </Field.Error>
      {/if}
    </Field.Field>

    {#if reading?.ok}
      <section class="flex flex-col gap-2">
        <h3 id="{uid}-preview" class="text-primary text-[0.8125rem] font-semibold">
          {m.flow_contract_example_preview()}
        </h3>
        <ul
          aria-labelledby="{uid}-preview"
          class="border-default flex max-h-[30vh] flex-col overflow-y-auto rounded-lg border"
        >
          {#each reading.fields as field (field.name)}
            <li
              class="border-default flex items-baseline justify-between gap-3 border-b px-3 py-1.5 last:border-b-0"
            >
              <span class="flex min-w-0 items-center gap-2">
                <code class="text-primary truncate font-mono text-xs">{field.name}</code>
                {#if !field.variable}
                  <Badge variant="destructive" aria-describedby="{uid}-not-variable">
                    {m.flow_contract_example_not_variable()}
                  </Badge>
                {/if}
              </span>
              <span class="text-secondary truncate text-xs">{shapeLabel(field.shape)}</span>
            </li>
          {/each}
        </ul>
        {#if holdsNonVariable}
          <p id="{uid}-not-variable" class="text-secondary text-xs leading-relaxed">
            {m.flow_contract_example_not_variable_reason()}
          </p>
        {/if}
        {#each reading.notes as note (note)}
          <p class="text-secondary text-xs leading-relaxed">{NOTE_SENTENCES[note]()}</p>
        {/each}
      </section>
    {/if}

    <Dialog.Footer>
      <Button variant="outline" onclick={close}>{m.cancel()}</Button>
      <Button disabled={!reading?.ok} onclick={create}>{m.flow_contract_example_create()}</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<AlertDialog.Root bind:open={confirmReplace}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.flow_contract_example_replace_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.flow_contract_example_replace_description()}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action onclick={write}>{m.flow_contract_example_replace()}</AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
