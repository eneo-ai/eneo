<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { getFlowEditor } from "$lib/features/flows/FlowEditor";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import {
    flowFormFieldHasOptions,
    getFlowFormFieldVariableToken,
    getFlowFormStats,
    isFlowFormFieldNameUsableAsVariable,
    normalizeFlowFormFieldType,
    normalizeFlowFormFields,
    toPersistedFlowFormFields,
    type FlowFormField,
    type NormalizedFlowFormField,
    type NormalizedFlowFormFieldType,
  } from "$lib/features/flows/flowFormSchema";
  import { IconPlus } from "@intric/icons/plus";
  import { IconTrash } from "@intric/icons/trash";
  import { Button } from "@intric/ui";
  import { IntricError } from "@intric/intric-js";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { getChipClasses } from "$lib/features/flows/flowVariableTokens";
  import { createEventDispatcher } from "svelte";

  export let isPublished: boolean;

  const dispatch = createEventDispatcher<{
    statsChanged: { definedCount: number; requiredCount: number };
  }>();
  const userMode = getFlowUserMode();

  const flowEditor = getFlowEditor();
  const {
    state: { update }
  } = flowEditor;

  type LocalFormField = NormalizedFlowFormField & { _localId: string };

  const FIELD_TYPES: { value: NormalizedFlowFormFieldType; label: () => string }[] = [
    { value: "text", label: () => m.flow_form_field_type_text() },
    { value: "number", label: () => m.flow_form_field_type_number() },
    { value: "date", label: () => m.flow_form_field_type_date() },
    { value: "select", label: () => m.flow_form_field_type_select() },
    { value: "multiselect", label: () => m.flow_form_field_type_multiselect() },
  ];

  $: formSchema = $update.metadata_json?.form_schema as { fields: FlowFormField[] } | undefined;

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

  function normalizeForEditor(fields: FlowFormField[]): LocalFormField[] {
    return normalizeFlowFormFields(fields).map((field) => ({ ...field, _localId: uid() }));
  }

  function normalizeForPersist(fields: LocalFormField[]): FlowFormField[] {
    return toPersistedFlowFormFields(fields);
  }

  function hasCompleteFieldNames(fields: LocalFormField[]): boolean {
    return fields.every((field) => field.name.trim().length > 0);
  }

  function syncToStore(fields: LocalFormField[]) {
    $update.metadata_json = {
      ...($update.metadata_json ?? {}),
      form_schema: { fields: normalizeForPersist(fields) }
    };
  }

  function commitIfComplete(fields: LocalFormField[]) {
    if (hasCompleteFieldNames(fields)) {
      syncToStore(fields);
    }
  }

  $: formStats = getFlowFormStats(localFields);
  $: namedVariableTokens = localFields
    .map((field) => getFlowFormFieldVariableToken(field.name))
    .filter((token) => token.length > 0)
    .slice(0, 4);
  $: emptyStateExamples =
    $userMode === "power_user"
      ? [
          { label: "titel", token: "{{titel}}" },
          { label: "datum", token: "{{datum}}" },
        ]
      : [{ label: "titel", token: "{{titel}}" }];
  $: previewVariableTokens = namedVariableTokens.slice(0, $userMode === "power_user" ? 4 : 2);
  $: dispatch("statsChanged", formStats);

  function addField() {
    localDirty = true;
    localFields = [
      ...localFields,
      { name: "", type: "text", required: false, options: [], order: localFields.length + 1, _localId: uid() },
    ];
  }

  function removeField(index: number) {
    localDirty = true;
    localFields = localFields.filter((_, i) => i !== index).map((field, i) => ({ ...field, order: i + 1 }));
    commitIfComplete(localFields);
  }

  function moveField(index: number, direction: -1 | 1) {
    const nextIndex = index + direction;
    if (nextIndex < 0 || nextIndex >= localFields.length) return;
    localDirty = true;
    const updated = [...localFields];
    [updated[index], updated[nextIndex]] = [updated[nextIndex], updated[index]];
    localFields = updated.map((field, i) => ({ ...field, order: i + 1 }));
    commitIfComplete(localFields);
  }

  function updateField(index: number, patch: Partial<Omit<LocalFormField, "_localId">>) {
    localDirty = true;
    localFields[index] = { ...localFields[index], ...patch };
    localFields = localFields;
    commitIfComplete(localFields);
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
    <div class="mx-4 mt-4 rounded-xl border border-default bg-secondary/20 p-4">
      <div class="mb-3 max-w-2xl">
        <p class="text-sm font-semibold">{m.flow_form_schema_intro_title()}</p>
        <p class="mt-1 text-xs leading-relaxed text-secondary">{m.flow_form_schema_intro_desc()}</p>
      </div>
      <div class={`grid gap-3 ${$userMode === "power_user" ? "md:grid-cols-3" : "md:grid-cols-2"}`}>
        <div class="rounded-lg border border-default bg-primary px-3 py-3">
          <p class="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">
            {m.flow_form_schema_intro_fill_title()}
          </p>
          <p class="mt-1.5 text-sm text-secondary">{m.flow_form_schema_intro_fill_desc()}</p>
        </div>
        <div class="rounded-lg border border-default bg-primary px-3 py-3">
          <p class="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">
            {m.flow_form_schema_intro_variable_title()}
          </p>
          <p class="mt-1.5 text-sm text-secondary">{m.flow_form_schema_intro_variable_desc()}</p>
        </div>
        {#if $userMode === "power_user"}
          <div class="rounded-lg border border-default bg-primary px-3 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">
              {m.flow_form_schema_intro_use_title()}
            </p>
            <p class="mt-1.5 text-sm text-secondary">{m.flow_form_schema_intro_use_desc()}</p>
          </div>
        {/if}
      </div>
    </div>

    <div class="mx-auto flex max-w-xl flex-col items-center gap-3 px-4 py-8 text-center">
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
      <div class="flex flex-wrap items-center justify-center gap-2 text-xs text-muted">
        <span class="font-medium text-secondary">{m.flow_form_schema_example_label()}</span>
        {#each emptyStateExamples as example, exampleIndex (example.token)}
          <span class="rounded-full bg-primary px-2.5 py-1">{example.label}</span>
          <span>&rarr;</span>
          <span class={getChipClasses("field")}>{example.token}</span>
          {#if exampleIndex < emptyStateExamples.length - 1}
            <span class="px-1">•</span>
          {/if}
        {/each}
      </div>
      {#if !isPublished}
        <Button variant="primary" on:click={addField}>
          <IconPlus size="sm" />
          {m.flow_form_add_field()}
        </Button>
      {/if}
    </div>
  {:else}
    <div class="mx-4 mb-4 rounded-lg border border-default bg-primary px-4 py-3">
      <p class="text-sm font-medium">{m.flow_form_schema_live_hint()}</p>
      <p class="mt-1 text-xs text-secondary">
        {m.flow_form_schema_live_form_hint()} {m.flow_form_schema_required_hint()}
      </p>
      {#if previewVariableTokens.length > 0}
        <div class="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
          <span class="font-medium text-secondary">{m.flow_form_schema_example_label()}</span>
          {#each previewVariableTokens as token (token)}
            <span class={getChipClasses("field")}>{token}</span>
          {/each}
        </div>
      {/if}
    </div>
  {/if}

  {#each localFields as field, index (field._localId)}
    <div class="mx-4 mb-3 rounded-lg border border-default border-l-4 border-l-accent-default/40 p-3.5">
      <div class="flex items-start justify-between gap-3">
        <div class="flex min-w-0 flex-1 flex-col gap-2.5">
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
            <div class="flex items-center gap-1.5 text-[12px] text-muted">
              {#if isFlowFormFieldNameUsableAsVariable(field.name)}
                <span>{m.flow_form_field_variable_hint()}</span>
                <span class={getChipClasses("field")}>{getFlowFormFieldVariableToken(field.name)}</span>
              {:else}
                <span class="text-amber-700">
                  {m.flow_form_field_variable_unavailable()}
                </span>
              {/if}
            </div>
          {/if}

          <div class="grid gap-2.5 sm:grid-cols-[minmax(0,1fr)_auto]">
            <select
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 text-sm shadow focus-within:ring-2"
              disabled={isPublished}
              value={normalizeFlowFormFieldType(typeof field.type === "string" ? field.type : "text")}
              on:change={(e) => {
                const nextType = normalizeFlowFormFieldType(e.currentTarget.value);
                updateField(index, {
                  type: nextType,
                  options: flowFormFieldHasOptions(nextType) ? (field.options ?? []) : [],
                });
              }}
            >
              {#each FIELD_TYPES as type (type.value)}
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

          {#if flowFormFieldHasOptions(normalizeFlowFormFieldType(typeof field.type === "string" ? field.type : "text"))}
            <div class="border-default rounded-lg border p-2.5">
              <div class="mb-2 text-xs font-medium text-secondary">{m.flow_form_field_option()}</div>
              {#if (field.options ?? []).length === 0}
                <p class="mb-2 text-xs text-secondary">{m.flow_form_field_add_option_hint()}</p>
              {/if}
              <div class="flex flex-col gap-2">
                {#each field.options ?? [] as option, optionIndex (`${field._localId}-${optionIndex}`)}
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
