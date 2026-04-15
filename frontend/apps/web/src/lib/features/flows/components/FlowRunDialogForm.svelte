<script lang="ts">
  import type { NormalizedFlowFormField } from "$lib/features/flows/flowFormSchema";
  import { getFlowFormFieldRuntimeKey } from "$lib/features/flows/flowFormSchema";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { FlowRunDialogLabels } from "./flowRunDialogLabels";

  let {
    formFields,
    formValues,
    missingRequiredFields,
    hasRequiredFormFields,
    labels,
    onFieldChange
  }: {
    formFields: NormalizedFlowFormField[];
    formValues: Record<string, unknown>;
    missingRequiredFields: NormalizedFlowFormField[];
    hasRequiredFormFields: boolean;
    labels: FlowRunDialogLabels;
    onFieldChange: (field: NormalizedFlowFormField, value: unknown) => void;
  } = $props();

  function getFieldValue(field: NormalizedFlowFormField): string {
    const value = formValues[getFlowFormFieldRuntimeKey(field.name)];
    if (Array.isArray(value)) return "";
    if (value === null || value === undefined) return "";
    return String(value);
  }

  function getFieldMultiValue(field: NormalizedFlowFormField): string[] {
    const value = formValues[getFlowFormFieldRuntimeKey(field.name)];
    if (Array.isArray(value)) return value.map((item) => String(item));
    if (typeof value === "string" && value.trim().length > 0) {
      return value
        .split(",")
        .map((item) => item.trim())
        .filter((item) => item.length > 0);
    }
    return [];
  }

  function isFieldMissing(field: NormalizedFlowFormField): boolean {
    return missingRequiredFields.includes(field);
  }

  function getRequiredErrorMessage(field: NormalizedFlowFormField): string {
    const trimmed = field.name.trim();
    return trimmed.length > 0
      ? m.flow_run_trigger_field_required({ name: trimmed })
      : m.flow_run_trigger_field_required_generic();
  }

  function fieldErrorId(fieldIndex: number): string {
    return `flow-input-error-${fieldIndex}`;
  }
</script>

<Field.Group>
  <div class="px-1">
    <p class="text-primary text-sm font-semibold">{labels.formIntroTitle}</p>
    <p class="text-secondary mt-1 text-sm leading-relaxed">{labels.formIntroDescription}</p>
    {#if hasRequiredFormFields}
      <p class="text-muted mt-1.5 text-xs">{m.flow_run_required_hint()}</p>
    {/if}
  </div>

  {#each formFields as field, fieldIndex (field.name)}
    {@const inputId = `flow-input-${fieldIndex}`}
    {@const invalid = isFieldMissing(field)}
    {@const describedBy = invalid ? fieldErrorId(fieldIndex) : undefined}
    <Field.Field data-invalid={invalid ? "true" : undefined}>
      <Field.Label for={inputId} class="flex items-center gap-1 text-sm font-medium">
        {field.name}
        {#if field.required}
          <span class="text-destructive" aria-hidden="true">*</span>
          <span class="sr-only">({labels.requiredBadge})</span>
        {/if}
      </Field.Label>

      {#if field.type === "multiselect"}
        <select
          id={inputId}
          class="border-input dark:bg-input/30 focus-visible:border-ring focus-visible:ring-ring/50 aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive min-h-[7.5rem] w-full rounded-lg border bg-transparent px-2.5 py-1.5 text-sm transition-colors outline-none focus-visible:ring-3 aria-invalid:ring-3"
          multiple
          required={field.required}
          aria-required={field.required}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          onchange={(event) => {
            const selected = Array.from(event.currentTarget.selectedOptions).map(
              (option) => option.value
            );
            onFieldChange(field, selected);
          }}
        >
          {#each field.options ?? [] as option (option)}
            <option value={option} selected={getFieldMultiValue(field).includes(option)}>
              {option}
            </option>
          {/each}
        </select>
      {:else if field.type === "select"}
        <Select.Root
          type="single"
          value={getFieldValue(field)}
          onValueChange={(value) => onFieldChange(field, value ?? "")}
        >
          <Select.Trigger
            id={inputId}
            aria-required={field.required}
            aria-invalid={invalid}
            aria-describedby={describedBy}
            class="w-full"
          >
            {getFieldValue(field) || m.flow_select_placeholder()}
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
          value={getFieldValue(field)}
          autocomplete="off"
          required={field.required}
          aria-required={field.required}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          oninput={(event) => onFieldChange(field, event.currentTarget.value)}
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
