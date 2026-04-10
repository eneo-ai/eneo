<script lang="ts">
  import type { NormalizedFlowFormField } from "$lib/features/flows/flowFormSchema";
  import { getFlowFormFieldRuntimeKey } from "$lib/features/flows/flowFormSchema";
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

  const missingRequiredFieldNames = $derived(
    missingRequiredFields.map((field) => field.name.trim()).filter((name) => name.length > 0)
  );
</script>

<div class="flex flex-col gap-5">
  <div class="px-1">
    <p class="text-sm font-semibold">{labels.formIntroTitle}</p>
    <div class="mt-1.5 space-y-1">
      <p class="text-secondary text-sm leading-relaxed">
        {labels.formIntroDescription}
      </p>
      {#if hasRequiredFormFields}
        <p class="text-muted text-sm">{m.flow_run_required_hint()}</p>
      {/if}
    </div>
  </div>

  {#if missingRequiredFields.length > 0}
    <div
      id="form-validation-banner"
      class="border-accent-default/20 bg-accent-dimmer/30 text-accent-stronger rounded-lg border px-3.5 py-2.5 text-sm"
      role="status"
      aria-live="polite"
    >
      {#if missingRequiredFieldNames.length > 0}
        {m.flow_run_missing_required_named({
          fields: missingRequiredFieldNames.join(", ")
        })}
      {:else}
        {m.flow_run_missing_required()}
      {/if}
    </div>
  {/if}

  {#each formFields as field, fieldIndex (field.name)}
    <div class="flex flex-col gap-1.5">
      <label class="text-sm font-medium" for={`flow-input-${fieldIndex}`}>
        {field.name}
        {#if field.required}
          <span class="text-negative-default" aria-hidden="true">*</span>
          <span class="sr-only">({labels.requiredBadge})</span>
        {/if}
      </label>
      {#if field.type === "multiselect"}
        <select
          id={`flow-input-${fieldIndex}`}
          class="border-default bg-primary ring-default focus-visible:ring-accent-default min-h-[120px] w-full rounded-lg border px-3 py-2 shadow focus-visible:ring-2"
          multiple
          required={field.required}
          aria-required={field.required}
          aria-describedby={missingRequiredFields.includes(field)
            ? "form-validation-banner"
            : undefined}
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
        <select
          id={`flow-input-${fieldIndex}`}
          class="border-default bg-primary ring-default focus-visible:ring-accent-default w-full rounded-lg border px-3 py-2 shadow focus-visible:ring-2"
          value={getFieldValue(field)}
          required={field.required}
          aria-required={field.required}
          aria-describedby={missingRequiredFields.includes(field)
            ? "form-validation-banner"
            : undefined}
          onchange={(event) => onFieldChange(field, event.currentTarget.value)}
        >
          <option value="">{m.flow_select_placeholder()}</option>
          {#each field.options ?? [] as option (option)}
            <option value={option}>{option}</option>
          {/each}
        </select>
      {:else}
        <input
          id={`flow-input-${fieldIndex}`}
          type={field.type === "number" ? "number" : field.type === "date" ? "date" : "text"}
          class="border-default bg-primary ring-default focus-visible:ring-accent-default w-full rounded-lg border px-3 py-2 shadow focus-visible:ring-2"
          value={getFieldValue(field)}
          autocomplete="off"
          required={field.required}
          aria-required={field.required}
          aria-describedby={missingRequiredFields.includes(field)
            ? "form-validation-banner"
            : undefined}
          oninput={(event) => onFieldChange(field, event.currentTarget.value)}
        />
      {/if}
    </div>
  {/each}
</div>
