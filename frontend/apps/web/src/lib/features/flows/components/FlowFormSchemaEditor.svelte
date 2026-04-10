<script lang="ts">
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
    type NormalizedFlowFormFieldType
  } from "$lib/features/flows/flowFormSchema";
  import { IconPlus } from "@intric/icons/plus";
  import { IconTrash } from "@intric/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { IntricError } from "@intric/intric-js";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { getChipClasses } from "$lib/features/flows/flowVariableTokens";
  let {
    isPublished,
    onStatsChanged
  }: {
    isPublished: boolean;
    onStatsChanged?: (detail: { definedCount: number; requiredCount: number }) => void;
  } = $props();

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
    { value: "multiselect", label: () => m.flow_form_field_type_multiselect() }
  ];

  const formSchema = $derived(
    $update.metadata_json?.form_schema as { fields: FlowFormField[] } | undefined
  );

  let localFields: LocalFormField[] = $state([]);
  let nameBeforeEditById: Record<string, string> = $state({});
  let idCounter = $state(0);
  let localDirty = $state(false);

  function uid(): string {
    return `field_${++idCounter}_${Date.now()}`;
  }

  $effect(() => {
    if (!localDirty) {
      const normalized = normalizeForEditor(formSchema?.fields ?? []);
      localFields = normalized;
    }
  });

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

  const formStats = $derived(getFlowFormStats(localFields));
  const namedVariableTokens = $derived(
    localFields
      .map((field) => getFlowFormFieldVariableToken(field.name))
      .filter((token) => token.length > 0)
      .slice(0, 4)
  );
  const emptyStateExamples = $derived(
    $userMode === "power_user"
      ? [
          { label: "ärendenummer", token: "{{ärendenummer}}" },
          { label: "verksamhet", token: "{{verksamhet}}" }
        ]
      : [{ label: "ärendenummer", token: "{{ärendenummer}}" }]
  );
  const previewVariableTokens = $derived(
    namedVariableTokens.slice(0, $userMode === "power_user" ? 4 : 2)
  );

  $effect(() => {
    onStatsChanged?.(formStats);
  });

  function addField() {
    localDirty = true;
    localFields = [
      ...localFields,
      {
        name: "",
        type: "text",
        required: false,
        options: [],
        order: localFields.length + 1,
        _localId: uid()
      }
    ];
  }

  function removeField(index: number) {
    localDirty = true;
    localFields = localFields
      .filter((_, i) => i !== index)
      .map((field, i) => ({ ...field, order: i + 1 }));
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

<div class="flex flex-col gap-5">
  {#if localFields.length === 0}
    <!-- Empty state — clean and inviting -->
    <div class="border-default bg-primary rounded-xl border px-6 py-8">
      <div class="mx-auto max-w-lg text-center">
        <p class="text-primary text-[0.9375rem] font-semibold tracking-[-0.01em]">
          {m.flow_form_schema_empty()}
        </p>
        <p class="text-secondary mt-1.5 text-sm leading-relaxed">
          {m.flow_form_schema_empty_hint()}
        </p>

        {#if previewVariableTokens.length > 0 || emptyStateExamples.length > 0}
          <div class="text-muted mt-4 flex flex-wrap items-center justify-center gap-2 text-xs">
            <span class="text-secondary font-medium">{m.flow_form_schema_example_label()}</span>
            {#each emptyStateExamples as example, exampleIndex (example.token)}
              <span class="bg-hover-dimmer rounded-md px-2 py-0.5 font-medium">{example.label}</span
              >
              <span class="text-muted">&rarr;</span>
              <span class={getChipClasses("field")}>{example.token}</span>
              {#if exampleIndex < emptyStateExamples.length - 1}
                <span class="text-muted/40">·</span>
              {/if}
            {/each}
          </div>
        {/if}

        {#if !isPublished}
          <div class="mt-5">
            <Button variant="default" onclick={addField}>
              <IconPlus class="size-4" />
              {m.flow_form_add_field()}
            </Button>
          </div>
        {/if}
      </div>
    </div>
  {:else}
    <!-- Field list -->
    <p class="text-secondary text-sm">{m.flow_form_schema_description()}</p>
    <div class="border-default bg-primary rounded-xl border">
      <div class="flex items-center justify-between px-5 py-3">
        <p class="text-sm font-medium">
          {m.flow_form_schema_live_hint()}
        </p>
        {#if previewVariableTokens.length > 0}
          <div class="flex flex-wrap items-center gap-1.5">
            {#each previewVariableTokens as token (token)}
              <span class={getChipClasses("field")}>{token}</span>
            {/each}
          </div>
        {/if}
      </div>

      <!-- Field rows -->
      <div class="border-default divide-default divide-y border-t">
        {#each localFields as field, index (field._localId)}
          <div class="group/field hover:bg-hover-dimmer/30 px-4 py-3.5 transition-colors">
            <!-- Row 1: Name + controls -->
            <div class="flex items-center gap-2">
              <div
                class="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover/field:opacity-100 focus-within:opacity-100"
              >
                <button
                  type="button"
                  class="text-muted hover:text-primary inline-flex size-6 items-center justify-center rounded transition-colors disabled:opacity-30"
                  disabled={index === 0 || isPublished}
                  onclick={() => moveField(index, -1)}
                  aria-label={m.flow_step_move_up()}
                >
                  <svg
                    class="size-3"
                    viewBox="0 0 16 16"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  >
                    <path d="M8 12V4M4 7l4-3 4 3" />
                  </svg>
                </button>
                <button
                  type="button"
                  class="text-muted hover:text-primary inline-flex size-6 items-center justify-center rounded transition-colors disabled:opacity-30"
                  disabled={index === localFields.length - 1 || isPublished}
                  onclick={() => moveField(index, 1)}
                  aria-label={m.flow_step_move_down()}
                >
                  <svg
                    class="size-3"
                    viewBox="0 0 16 16"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  >
                    <path d="M8 4v8M4 9l4 3 4-3" />
                  </svg>
                </button>
              </div>

              <input
                type="text"
                class="border-default bg-primary focus:border-accent-default focus:ring-accent-default/20 min-w-0 flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition-shadow focus:ring-2 focus:outline-none"
                placeholder={m.flow_form_field_name()}
                value={field.name}
                disabled={isPublished}
                onfocus={() => {
                  nameBeforeEditById[field._localId] = field.name;
                }}
                oninput={(e) => updateField(index, { name: e.currentTarget.value })}
                onchange={() => void rewriteVariablesOnCommittedRename(field)}
              />

              <div class="flex shrink-0 items-center gap-2">
                {#if field.required}
                  <Badge
                    variant="secondary"
                    class="bg-accent-dimmer/60 text-accent-stronger text-[11px]"
                    >{m.flow_form_field_required()}</Badge
                  >
                {/if}
                {#if !isPublished}
                  <button
                    type="button"
                    class="text-muted hover:text-negative-stronger inline-flex size-7 items-center justify-center rounded-md opacity-0 transition-all group-hover/field:opacity-100 focus:opacity-100"
                    onclick={() => removeField(index)}
                    aria-label={m.delete()}
                  >
                    <IconTrash class="size-3.5" />
                  </button>
                {/if}
              </div>
            </div>

            <!-- Row 2: Type + required + variable hint -->
            <div class="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-2 pl-[52px]">
              <select
                class="border-default bg-primary focus:border-accent-default focus:ring-accent-default/20 w-40 rounded-lg border px-2.5 py-1.5 text-sm transition-shadow focus:ring-2 focus:outline-none"
                disabled={isPublished}
                value={normalizeFlowFormFieldType(
                  typeof field.type === "string" ? field.type : "text"
                )}
                onchange={(e) => {
                  const nextType = normalizeFlowFormFieldType(e.currentTarget.value);
                  updateField(index, {
                    type: nextType,
                    options: flowFormFieldHasOptions(nextType) ? (field.options ?? []) : []
                  });
                }}
              >
                {#each FIELD_TYPES as type (type.value)}
                  <option value={type.value}>{type.label()}</option>
                {/each}
              </select>

              <label class="text-secondary inline-flex cursor-pointer items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  class="accent-accent-default size-3.5"
                  checked={field.required ?? false}
                  disabled={isPublished}
                  onchange={(e) => updateField(index, { required: e.currentTarget.checked })}
                />
                {m.flow_form_field_required()}
              </label>

              {#if field.name.trim() && isFlowFormFieldNameUsableAsVariable(field.name)}
                <span class="text-muted text-xs">
                  &rarr; <span class={getChipClasses("field")}
                    >{getFlowFormFieldVariableToken(field.name)}</span
                  >
                </span>
              {:else if field.name.trim()}
                <span class="text-warning-stronger text-xs"
                  >{m.flow_form_field_variable_unavailable()}</span
                >
              {/if}
            </div>

            <!-- Options (for select/multiselect) -->
            {#if flowFormFieldHasOptions(normalizeFlowFormFieldType(typeof field.type === "string" ? field.type : "text"))}
              <div class="mt-3 pl-[52px]">
                <div class="bg-hover-dimmer/40 rounded-lg px-3 py-2.5">
                  <span class="text-secondary text-xs font-medium"
                    >{m.flow_form_field_option()}</span
                  >
                  {#if (field.options ?? []).length === 0}
                    <p class="text-muted mt-1 text-xs">{m.flow_form_field_add_option_hint()}</p>
                  {/if}
                  <div class="mt-1.5 flex flex-col gap-1.5">
                    {#each field.options ?? [] as option, optionIndex (`${field._localId}-${optionIndex}`)}
                      <div class="flex items-center gap-2">
                        <input
                          type="text"
                          class="border-default bg-primary focus:border-accent-default focus:ring-accent-default/20 w-full rounded-md border px-2.5 py-1.5 text-sm transition-shadow focus:ring-2 focus:outline-none"
                          value={option}
                          placeholder={`${m.flow_form_field_option()} ${optionIndex + 1}`}
                          disabled={isPublished}
                          oninput={(e) => updateOption(index, optionIndex, e.currentTarget.value)}
                        />
                        <button
                          type="button"
                          class="text-muted hover:text-negative-stronger inline-flex size-6 items-center justify-center rounded"
                          onclick={() => removeOption(index, optionIndex)}
                          disabled={isPublished}
                          aria-label={m.delete()}
                        >
                          <IconTrash class="size-3" />
                        </button>
                      </div>
                    {/each}
                    {#if !isPublished}
                      <button
                        type="button"
                        class="text-accent-default hover:text-accent-stronger mt-0.5 text-left text-xs font-medium"
                        onclick={() => addOption(index)}
                      >
                        + {m.flow_form_field_add_option()}
                      </button>
                    {/if}
                  </div>
                </div>
              </div>
            {/if}
          </div>
        {/each}
      </div>
    </div>

    {#if !isPublished}
      <button
        type="button"
        class="border-default text-secondary hover:border-accent-default hover:bg-accent-dimmer hover:text-accent-default flex w-full items-center justify-center gap-2 rounded-lg border-2 border-dashed py-3 text-sm transition-colors hover:shadow-sm"
        onclick={addField}
      >
        <IconPlus class="size-4" />
        {m.flow_form_add_field()}
      </button>
    {/if}
  {/if}
</div>
