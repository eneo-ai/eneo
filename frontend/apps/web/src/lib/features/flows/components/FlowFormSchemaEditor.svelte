<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { getFlowEditor } from "$lib/features/flows/FlowEditor";
  import { IconPlus } from "@intric/icons/plus";
  import { IconTrash } from "@intric/icons/trash";
  import { Button } from "@intric/ui";
  import { IntricError } from "@intric/intric-js";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { getChipClasses } from "$lib/features/flows/flowVariableTokens";

  export let isPublished: boolean;

  const flowEditor = getFlowEditor();
  const {
    state: { update }
  } = flowEditor;

  type FormFieldType = "text" | "multiselect" | "number" | "date" | "select";
  type FormField = {
    name: string;
    type: FormFieldType | string;
    required?: boolean;
    options?: string[];
    order?: number;
  };
  type LocalFormField = FormField & { _localId: string };

  const FIELD_TYPES: { value: FormFieldType; label: () => string }[] = [
    { value: "text", label: () => m.flow_form_field_type_text() },
    { value: "number", label: () => m.flow_form_field_type_number() },
    { value: "date", label: () => m.flow_form_field_type_date() },
    { value: "select", label: () => m.flow_form_field_type_select() },
    { value: "multiselect", label: () => m.flow_form_field_type_multiselect() },
  ];
  const OPTION_FIELD_TYPES = new Set<FormFieldType>(["select", "multiselect"]);
  const LEGACY_TEXT_TYPES = new Set(["email", "textarea", "string"]);

  $: formSchema = $update.metadata_json?.form_schema as { fields: FormField[] } | undefined;

  let localFields: LocalFormField[] = [];
  let nameBeforeEditById: Record<string, string> = {};
  let idCounter = 0;
  let localDirty = false;

  function uid(): string {
    return `field_${++idCounter}_${Date.now()}`;
  }

  $: {
    if (!localDirty) {
      const normalized = normalizeForEditor(formSchema?.fields ?? []);
      localFields = normalized;
    }
  }

  function normalizeFieldType(type: string | undefined): FormFieldType {
    const normalized = (type ?? "text").trim().toLowerCase();
    if (LEGACY_TEXT_TYPES.has(normalized)) return "text";
    if (normalized === "text") return "text";
    if (normalized === "number") return "number";
    if (normalized === "date") return "date";
    if (normalized === "select") return "select";
    if (normalized === "multiselect") return "multiselect";
    return "text";
  }

  function normalizeForEditor(fields: FormField[]): LocalFormField[] {
    return [...fields]
      .map((field, index) => ({
        name: typeof field.name === "string" ? field.name : "",
        type: normalizeFieldType(typeof field.type === "string" ? field.type : "text"),
        required: Boolean(field.required),
        options: Array.isArray(field.options)
          ? field.options
              .filter((option): option is string => typeof option === "string")
              .map((option) => option.trim())
              .filter((option) => option.length > 0)
          : [],
        order: typeof field.order === "number" ? field.order : index + 1,
        _localId: uid(),
      }))
      .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
      .map((field, index) => ({ ...field, order: index + 1 }));
  }

  function normalizeForPersist(fields: LocalFormField[]): FormField[] {
    return fields.map((field, index) => {
      const type = normalizeFieldType(typeof field.type === "string" ? field.type : "text");
      const normalized: FormField = {
        name: field.name.trim(),
        type,
        required: Boolean(field.required),
        order: index + 1,
      };
      if (OPTION_FIELD_TYPES.has(type)) {
        normalized.options = (field.options ?? [])
          .map((option) => option.trim())
          .filter((option) => option.length > 0);
      }
      return normalized;
    });
  }

  function hasValidFieldNames(fields: LocalFormField[]): boolean {
    return fields.every((field) => field.name.trim().length > 0);
  }

  function syncToStore(fields: LocalFormField[]) {
    $update.metadata_json = {
      ...($update.metadata_json ?? {}),
      form_schema: { fields: normalizeForPersist(fields) }
    };
  }

  function addField() {
    localDirty = true;
    localFields = [
      ...localFields,
      { name: "", type: "text", required: false, options: [], order: localFields.length + 1, _localId: uid() },
    ];
  }

  function removeField(index: number) {
    localFields = localFields.filter((_, i) => i !== index).map((field, i) => ({ ...field, order: i + 1 }));
    syncToStore(localFields);
  }

  function moveField(index: number, direction: -1 | 1) {
    const nextIndex = index + direction;
    if (nextIndex < 0 || nextIndex >= localFields.length) return;
    const updated = [...localFields];
    [updated[index], updated[nextIndex]] = [updated[nextIndex], updated[index]];
    localFields = updated.map((field, i) => ({ ...field, order: i + 1 }));
    syncToStore(localFields);
  }

  function updateField(index: number, patch: Partial<FormField>) {
    localDirty = true;
    localFields[index] = { ...localFields[index], ...patch };
    localFields = localFields;
    if (hasValidFieldNames(localFields)) {
      syncToStore(localFields);
    }
  }

  function updateOption(index: number, optionIndex: number, value: string) {
    const current = localFields[index];
    const options = [...(current.options ?? [])];
    options[optionIndex] = value;
    updateField(index, { options });
  }

  function addOption(index: number) {
    localDirty = true;
    const current = localFields[index];
    const options = [...(current.options ?? []), ""];
    localFields[index] = { ...localFields[index], options };
    localFields = localFields;
  }

  function removeOption(index: number, optionIndex: number) {
    const current = localFields[index];
    const options = (current.options ?? []).filter((_, idx) => idx !== optionIndex);
    updateField(index, { options });
  }

  async function rewriteVariablesOnCommittedRename(field: LocalFormField) {
    const oldName = (nameBeforeEditById[field._localId] ?? "").trim();
    const newName = (field.name ?? "").trim();
    if (!oldName || !newName || oldName === newName) return;
    try {
      await flowEditor.rewriteInputFieldVariableReferences(oldName, newName);
    } catch (error) {
      const message =
        error instanceof IntricError
          ? error.getReadableMessage()
          : "Failed to rewrite variable references after field rename.";
      toast.error(message);
    }
  }
</script>

<Settings.Group title={m.flow_form_schema()}>
  <div class="flex flex-col">
  <p class="text-secondary px-4 text-sm">{m.flow_form_schema_description()}</p>

  {#if localFields.length === 0}
    <div class="flex flex-col items-center gap-3 px-4 py-8 text-center">
      <div class="rounded-xl bg-accent-dimmer p-3">
        <svg class="size-6 text-accent-stronger" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="3" width="18" height="18" rx="2"/>
          <line x1="7" y1="8" x2="10" y2="8"/>
          <line x1="13" y1="8" x2="17" y2="8"/>
          <line x1="7" y1="12" x2="10" y2="12"/>
          <line x1="13" y1="12" x2="17" y2="12"/>
          <line x1="7" y1="16" x2="10" y2="16"/>
          <line x1="13" y1="16" x2="17" y2="16"/>
        </svg>
      </div>
      <p class="text-sm text-secondary">{m.flow_form_schema_empty()}</p>
      <p class="max-w-sm text-xs text-muted">{m.flow_form_schema_empty_hint()}</p>
      {#if !isPublished}
        <Button variant="primary" on:click={addField}>
          <IconPlus size="sm" />
          {m.flow_form_add_field()}
        </Button>
      {/if}
    </div>
  {/if}

  {#each localFields as field, index (field._localId)}
    <div class="mx-4 mb-4 rounded-lg border border-default border-l-4 border-l-accent-default/40 p-4">
      <div class="flex items-start justify-between gap-3">
        <div class="flex min-w-0 flex-1 flex-col gap-3">
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="inline-flex size-7 items-center justify-center rounded text-secondary transition-colors hover:bg-hover-dimmer disabled:cursor-not-allowed disabled:opacity-40"
              disabled={index === 0 || isPublished}
              on:click={() => moveField(index, -1)}
              aria-label={m.flow_step_move_up()}
              title={m.flow_step_move_up()}
            >
              <svg class="size-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M8 12V4M4 7l4-3 4 3"/>
              </svg>
            </button>
            <button
              type="button"
              class="inline-flex size-7 items-center justify-center rounded text-secondary transition-colors hover:bg-hover-dimmer disabled:cursor-not-allowed disabled:opacity-40"
              disabled={index === localFields.length - 1 || isPublished}
              on:click={() => moveField(index, 1)}
              aria-label={m.flow_step_move_down()}
              title={m.flow_step_move_down()}
            >
              <svg class="size-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M8 4v8M4 9l4 3 4-3"/>
              </svg>
            </button>
            <input
              type="text"
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 text-sm font-medium shadow focus-within:ring-2"
              placeholder={m.flow_form_field_name()}
              value={field.name}
              disabled={isPublished}
              on:focus={() => {
                nameBeforeEditById[field._localId] = field.name;
              }}
              on:input={(e) => updateField(index, { name: e.currentTarget.value })}
              on:change={() => void rewriteVariablesOnCommittedRename(field)}
            />
            {#if field.required}
              <span class="shrink-0 rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-700">{m.flow_form_field_required()}</span>
            {/if}
            {#if !isPublished}
              <button
                type="button"
                class="shrink-0 text-secondary hover:text-red-600"
                on:click={() => removeField(index)}
                aria-label={m.delete()}
              >
                <IconTrash class="size-4" />
              </button>
            {/if}
          </div>

          <!-- Variable hint -->
          {#if field.name.trim()}
            <div class="flex items-center gap-1.5 text-xs text-muted">
              <span>&hookrightarrow;</span>
              <span>{m.flow_form_field_variable_hint()}</span>
              <span class="{getChipClasses('field')}">{`{{${field.name.trim()}}}`}</span>
            </div>
          {/if}

          <div class="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
            <select
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 text-sm shadow focus-within:ring-2"
              disabled={isPublished}
              value={normalizeFieldType(typeof field.type === "string" ? field.type : "text")}
              on:change={(e) => {
                const nextType = normalizeFieldType(e.currentTarget.value);
                updateField(index, {
                  type: nextType,
                  options: OPTION_FIELD_TYPES.has(nextType) ? (field.options ?? []) : [],
                });
              }}
            >
              {#each FIELD_TYPES as type}
                <option value={type.value}>{type.label()}</option>
              {/each}
            </select>
            <label class="inline-flex items-center gap-2 text-sm text-secondary">
              <input
                type="checkbox"
                checked={field.required ?? false}
                disabled={isPublished}
                on:change={(e) => updateField(index, { required: e.currentTarget.checked })}
              />
              {m.flow_form_field_required()}
            </label>
          </div>

          {#if OPTION_FIELD_TYPES.has(normalizeFieldType(typeof field.type === "string" ? field.type : "text"))}
            <div class="border-default rounded-lg border p-3">
              <div class="mb-2 text-xs font-medium text-secondary">{m.flow_form_field_option()}</div>
              {#if (field.options ?? []).length === 0}
                <p class="mb-2 text-xs text-secondary">{m.flow_form_field_add_option_hint()}</p>
              {/if}
              <div class="flex flex-col gap-2">
                {#each field.options ?? [] as option, optionIndex}
                  <div class="flex items-center gap-2">
                    <input
                      type="text"
                      class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 text-sm shadow focus-within:ring-2"
                      value={option}
                      placeholder={`${m.flow_form_field_option()} ${optionIndex + 1}`}
                      disabled={isPublished}
                      on:input={(e) => updateOption(index, optionIndex, e.currentTarget.value)}
                    />
                    <button
                      type="button"
                      class="inline-flex size-7 items-center justify-center rounded text-secondary hover:bg-hover-dimmer hover:text-red-600"
                      on:click={() => removeOption(index, optionIndex)}
                      disabled={isPublished}
                      aria-label={m.delete()}
                    >
                      <IconTrash class="size-3.5" />
                    </button>
                  </div>
                {/each}
              </div>
              {#if !isPublished}
                <button
                  type="button"
                  class="mt-2 rounded-md border border-default px-2.5 py-1 text-xs transition-colors hover:bg-hover-dimmer"
                  on:click={() => addOption(index)}
                >
                  {m.flow_form_field_add_option()}
                </button>
              {/if}
            </div>
          {/if}
        </div>
      </div>
    </div>
  {/each}

  {#if !isPublished && localFields.length > 0}
    <div class="px-4 pb-4">
      <button
        type="button"
        class="flex w-full items-center justify-center gap-2 rounded-lg border-2 border-dashed border-default py-3 text-sm text-secondary transition-colors hover:border-accent-default hover:bg-accent-dimmer hover:text-accent-default hover:shadow-sm"
        on:click={addField}
      >
        <IconPlus class="size-4" />
        {m.flow_form_add_field()}
      </button>
    </div>
  {/if}
  </div>
</Settings.Group>
