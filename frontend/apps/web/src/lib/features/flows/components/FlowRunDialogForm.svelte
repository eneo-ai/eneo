<script lang="ts">
  import {
    getFlowFormFieldLabel,
    type NormalizedFlowFormField
  } from "$lib/features/flows/flowFormSchema";
  import {
    readFlowRunFieldMultiValue,
    readFlowRunFieldValue
  } from "$lib/features/flows/flowRunContract";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { FlowRunLaunchInputState } from "./FlowRunLaunchInputState.svelte";
  import type { FlowRunDialogLabels } from "./flowRunDialogLabels";
  import FlowListInput from "./FlowListInput.svelte";
  import { SvelteSet } from "svelte/reactivity";

  let {
    formFields,
    launchInputState,
    missingRequiredFields,
    hasRequiredFormFields,
    labels
  }: {
    formFields: NormalizedFlowFormField[];
    launchInputState: FlowRunLaunchInputState;
    missingRequiredFields: NormalizedFlowFormField[];
    hasRequiredFormFields: boolean;
    labels: FlowRunDialogLabels;
  } = $props();

  const currentFormValues = $derived(launchInputState.formValuesSnapshot);

  // A form that greets a first-time user by marking three fields wrong before
  // they have typed anything reads as an accusation. The asterisk and
  // `aria-required` already say a field is needed; the error presentation
  // waits until the reader has been in the field. The footer lists whatever is
  // still missing throughout, so nothing is hidden.
  const touched = new SvelteSet<string>();
  function markTouched(field: NormalizedFlowFormField) {
    touched.add(field.name);
  }

  function isFieldMissing(field: NormalizedFlowFormField): boolean {
    return missingRequiredFields.includes(field) && touched.has(field.name);
  }

  function getRequiredErrorMessage(field: NormalizedFlowFormField): string {
    const trimmed = getFlowFormFieldLabel(field);
    return trimmed.length > 0
      ? m.flow_run_trigger_field_required({ name: trimmed })
      : m.flow_run_trigger_field_required_generic();
  }

  function fieldErrorId(fieldIndex: number): string {
    return `flow-input-error-${fieldIndex}`;
  }
</script>

<Field.Group>
  <!-- The wizard header above already says what this page is for; only the
       required-field key is added here. -->
  {#if hasRequiredFormFields}
    <p class="text-secondary text-xs">{m.flow_run_required_hint()}</p>
  {/if}

  {#each formFields as field, fieldIndex (field.name)}
    {@const inputId = `flow-input-${fieldIndex}`}
    {@const invalid = isFieldMissing(field)}
    {@const describedBy = invalid ? fieldErrorId(fieldIndex) : undefined}
    <Field.Field data-invalid={invalid ? "true" : undefined}>
      <Field.Label for={inputId} class="flex items-center gap-1 text-sm font-medium">
        {getFlowFormFieldLabel(field)}
        {#if field.required}
          <span class="text-destructive" aria-hidden="true">*</span>
          <span class="sr-only">({labels.requiredBadge})</span>
        {/if}
      </Field.Label>

      {#if field.type === "multiselect"}
        {@const selectedValues = readFlowRunFieldMultiValue(currentFormValues, field)}
        <Select.Root
          type="multiple"
          value={selectedValues}
          onValueChange={(value) => {
            markTouched(field);
            launchInputState.setFieldValue(field, value);
          }}
        >
          <Select.Trigger
            id={inputId}
            onblur={() => markTouched(field)}
            aria-required={field.required}
            aria-invalid={invalid}
            aria-describedby={describedBy}
            class="w-full"
          >
            <span class="min-w-0 truncate">
              {selectedValues.length > 0 ? selectedValues.join(", ") : m.flow_select_placeholder()}
            </span>
          </Select.Trigger>
          <Select.Content>
            {#each field.options ?? [] as option (option)}
              <Select.Item value={option}>{option}</Select.Item>
            {/each}
          </Select.Content>
        </Select.Root>
      {:else if field.type === "list"}
        <FlowListInput
          id={inputId}
          values={readFlowRunFieldMultiValue(currentFormValues, field)}
          required={field.required}
          {invalid}
          {describedBy}
          onchange={(values) => {
            markTouched(field);
            launchInputState.setFieldValue(field, values);
          }}
        />
      {:else if field.type === "select"}
        <Select.Root
          type="single"
          value={readFlowRunFieldValue(currentFormValues, field)}
          onValueChange={(value) => {
            markTouched(field);
            launchInputState.setFieldValue(field, value ?? "");
          }}
        >
          <Select.Trigger
            id={inputId}
            onblur={() => markTouched(field)}
            aria-required={field.required}
            aria-invalid={invalid}
            aria-describedby={describedBy}
            class="w-full"
          >
            {readFlowRunFieldValue(currentFormValues, field) || m.flow_select_placeholder()}
          </Select.Trigger>
          <Select.Content>
            {#each field.options ?? [] as option (option)}
              <Select.Item value={option}>{option}</Select.Item>
            {/each}
          </Select.Content>
        </Select.Root>
      {:else}
        <Input
          id={inputId}
          type={field.type === "number" ? "number" : field.type === "date" ? "date" : "text"}
          value={readFlowRunFieldValue(currentFormValues, field)}
          autocomplete="off"
          required={field.required}
          aria-required={field.required}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          onblur={() => markTouched(field)}
          oninput={(event) => launchInputState.setFieldValue(field, event.currentTarget.value)}
        />
      {/if}

      {#if invalid}
        <Field.Error id={fieldErrorId(fieldIndex)}>
          {getRequiredErrorMessage(field)}
        </Field.Error>
      {/if}
    </Field.Field>
  {/each}
</Field.Group>
