<script lang="ts">
  import { getFlowEditor } from "$lib/features/flows/FlowEditor";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import {
    flowFormFieldHasOptions,
    getFlowFormFieldNameIssue,
    getFlowFormFieldVariableToken,
    getFlowFormSchemaMetadata,
    getFlowFormStats,
    isFlowFormFieldNameUsableAsVariable,
    normalizeFlowFormFieldType,
    normalizeFlowFormFields,
    type FlowFormField,
    type NormalizedFlowFormField,
    type NormalizedFlowFormFieldType
  } from "$lib/features/flows/flowFormSchema";
  import { IconPlus } from "@intric/icons/plus";
  import { IconTrash } from "@intric/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
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

  const formSchema = $derived(getFlowFormSchemaMetadata($update.metadata_json));

  let localFields: LocalFormField[] = $state([]);
  let nameBeforeEditById: Record<string, string> = $state({});
  let idCounter = 0;
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

  type FieldNameIssue = "namespace_head" | "primary_input_key" | "step_alias" | "dot" | "duplicate";

  function getFieldNameIssue(field: LocalFormField, fieldIndex: number): FieldNameIssue | null {
    const baseIssue = getFlowFormFieldNameIssue(field.name);
    if (baseIssue !== null) return baseIssue;

    const normalized = field.name.trim().toLowerCase();
    if (!normalized) return null;
    const firstMatchingIndex = localFields.findIndex(
      (candidate) => candidate.name.trim().toLowerCase() === normalized
    );
    return firstMatchingIndex !== fieldIndex ? "duplicate" : null;
  }

  function getFieldNameIssueMessage(issue: FieldNameIssue): string {
    if (issue === "namespace_head") return m.flow_form_field_name_namespace_head();
    if (issue === "primary_input_key") return m.flow_form_field_name_primary_input_key();
    if (issue === "step_alias") return m.flow_form_field_name_step_alias();
    if (issue === "dot") return m.flow_form_field_name_dot();
    return m.flow_form_field_name_duplicate();
  }

  function hasPersistableFieldNames(fields: LocalFormField[]): boolean {
    return fields.every((field, index) => {
      return field.name.trim().length > 0 && getFieldNameIssue(field, index) === null;
    });
  }

  function syncToStore(fields: LocalFormField[]) {
    flowEditor.replaceFormSchemaFields(fields);
  }

  function commitIfPersistable(fields: LocalFormField[]) {
    if (hasPersistableFieldNames(fields)) {
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
          { label: "ärendenummer", token: "{{flow_input.ärendenummer}}" },
          { label: "verksamhet", token: "{{flow_input.verksamhet}}" }
        ]
      : [{ label: "ärendenummer", token: "{{flow_input.ärendenummer}}" }]
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
    commitIfPersistable(localFields);
  }

  function moveField(index: number, direction: -1 | 1) {
    const nextIndex = index + direction;
    if (nextIndex < 0 || nextIndex >= localFields.length) return;
    localDirty = true;
    const updated = [...localFields];
    [updated[index], updated[nextIndex]] = [updated[nextIndex], updated[index]];
    localFields = updated.map((field, i) => ({ ...field, order: i + 1 }));
    commitIfPersistable(localFields);
  }

  function updateField(index: number, patch: Partial<Omit<LocalFormField, "_localId">>) {
    localDirty = true;
    localFields[index] = { ...localFields[index], ...patch };
    localFields = localFields;
    commitIfPersistable(localFields);
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

<div class="flex flex-col gap-4">
  {#if localFields.length === 0}
    <!-- Empty state — clean and inviting -->
    <Card.Root class="gap-0 py-0">
      <div class="mx-auto max-w-lg px-6 py-9 text-center">
        <p class="text-primary text-[0.9375rem] font-semibold tracking-[-0.01em]">
          {m.flow_form_schema_empty()}
        </p>
        <p class="text-secondary mt-1.5 text-[0.8125rem] leading-relaxed text-balance">
          {m.flow_form_schema_empty_hint()}
        </p>

        {#if previewVariableTokens.length > 0 || emptyStateExamples.length > 0}
          <div class="text-muted mt-5 flex flex-wrap items-center justify-center gap-2 text-xs">
            <span class="text-secondary font-medium">{m.flow_form_schema_example_label()}</span>
            {#each emptyStateExamples as example, exampleIndex (example.token)}
              <span class="bg-hover-dimmer rounded-md px-2 py-0.5 font-medium">
                {example.label}
              </span>
              <span class="text-muted" aria-hidden="true">&rarr;</span>
              <span class={getChipClasses("field")}>{example.token}</span>
              {#if exampleIndex < emptyStateExamples.length - 1}
                <span class="text-muted/40" aria-hidden="true">·</span>
              {/if}
            {/each}
          </div>
        {/if}

        {#if !isPublished}
          <div class="mt-6">
            <Button variant="default" onclick={addField}>
              <IconPlus class="size-4" />
              {m.flow_form_add_field()}
            </Button>
          </div>
        {/if}
      </div>
    </Card.Root>
  {:else}
    <!-- Field list -->
    <p class="text-secondary text-[0.8125rem] leading-relaxed">
      {m.flow_form_schema_description()}
    </p>
    <Card.Root class="gap-0 py-0">
      <div class="flex items-center justify-between gap-3 px-5 py-3">
        <p class="text-sm font-medium tracking-[-0.005em]">
          {m.flow_form_schema_live_hint()}
        </p>
        {#if previewVariableTokens.length > 0}
          <div class="flex flex-wrap items-center justify-end gap-1.5">
            {#each previewVariableTokens as token (token)}
              <span class={getChipClasses("field")}>{token}</span>
            {/each}
          </div>
        {/if}
      </div>

      <!-- Field rows -->
      <div class="border-default divide-default divide-y border-t">
        {#each localFields as field, index (field._localId)}
          {@const currentType = normalizeFlowFormFieldType(
            typeof field.type === "string" ? field.type : "text"
          )}
          {@const currentTypeLabel =
            FIELD_TYPES.find((t) => t.value === currentType)?.label() ?? FIELD_TYPES[0].label()}
          {@const hasValidVariable =
            field.name.trim() && isFlowFormFieldNameUsableAsVariable(field.name)}
          {@const fieldNameIssue = getFieldNameIssue(field, index)}
          <div class="group/field hover:bg-hover-dimmer/30 px-4 py-3.5 transition-colors">
            <!-- Row 1: Move handles + Name input + Delete -->
            <div class="flex items-center gap-2">
              <div
                class="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover/field:opacity-100 focus-within:opacity-100"
              >
                <button
                  type="button"
                  class="text-muted hover:text-primary hover:bg-hover-dimmer inline-flex size-7 items-center justify-center rounded transition-colors disabled:opacity-30"
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
                    aria-hidden="true"
                  >
                    <path d="M8 12V4M4 7l4-3 4 3" />
                  </svg>
                </button>
                <button
                  type="button"
                  class="text-muted hover:text-primary hover:bg-hover-dimmer inline-flex size-7 items-center justify-center rounded transition-colors disabled:opacity-30"
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
                    aria-hidden="true"
                  >
                    <path d="M8 4v8M4 9l4 3 4-3" />
                  </svg>
                </button>
              </div>

              <Input
                type="text"
                class="h-9 min-w-0 flex-1 font-medium"
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
                  <span
                    class="bg-accent-dimmer/60 text-accent-stronger inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium"
                  >
                    {m.flow_form_field_required()}
                  </span>
                {/if}
                {#if !isPublished}
                  <button
                    type="button"
                    class="text-muted hover:text-negative-stronger hover:bg-negative-dimmer/40 inline-flex size-8 items-center justify-center rounded-md opacity-0 transition-all group-hover/field:opacity-100 focus:opacity-100"
                    onclick={() => removeField(index)}
                    aria-label={m.delete()}
                  >
                    <IconTrash class="size-3.5" />
                  </button>
                {/if}
              </div>
            </div>

            <!-- Row 2: Type select + required + variable hint -->
            <div class="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-2 pl-[56px]">
              <Select.Root
                type="single"
                value={currentType}
                disabled={isPublished}
                onValueChange={(value) => {
                  if (!value) return;
                  const nextType = normalizeFlowFormFieldType(value);
                  updateField(index, {
                    type: nextType,
                    options: flowFormFieldHasOptions(nextType) ? (field.options ?? []) : []
                  });
                }}
              >
                <Select.Trigger class="h-8 w-44">
                  {currentTypeLabel}
                </Select.Trigger>
                <Select.Content>
                  {#each FIELD_TYPES as type (type.value)}
                    <Select.Item value={type.value} label={type.label()}>
                      {type.label()}
                    </Select.Item>
                  {/each}
                </Select.Content>
              </Select.Root>

              <label
                class="text-secondary inline-flex cursor-pointer items-center gap-2 text-sm select-none"
              >
                <Checkbox
                  checked={field.required ?? false}
                  disabled={isPublished}
                  onCheckedChange={(checked) => updateField(index, { required: checked })}
                />
                <span>{m.flow_form_field_required()}</span>
              </label>

              {#if hasValidVariable}
                <span class="text-muted inline-flex items-center gap-1.5 text-xs">
                  <span aria-hidden="true">&rarr;</span>
                  <span class={getChipClasses("field")}>
                    {getFlowFormFieldVariableToken(field.name)}
                  </span>
                </span>
              {:else if fieldNameIssue}
                <span class="text-warning-stronger text-xs">
                  {getFieldNameIssueMessage(fieldNameIssue)}
                </span>
              {/if}
            </div>

            <!-- Options (for select / multiselect) -->
            {#if flowFormFieldHasOptions(currentType)}
              <div class="mt-3 pl-[56px]">
                <div class="bg-hover-dimmer/40 rounded-lg px-3 py-2.5">
                  <span class="text-secondary text-xs font-medium">
                    {m.flow_form_field_option()}
                  </span>
                  {#if (field.options ?? []).length === 0}
                    <p class="text-muted mt-1 text-xs">
                      {m.flow_form_field_add_option_hint()}
                    </p>
                  {/if}
                  <div class="mt-1.5 flex flex-col gap-1.5">
                    {#each field.options ?? [] as option, optionIndex (`${field._localId}-${optionIndex}`)}
                      <div class="flex items-center gap-2">
                        <Input
                          type="text"
                          class="h-8 w-full"
                          value={option}
                          placeholder={`${m.flow_form_field_option()} ${optionIndex + 1}`}
                          disabled={isPublished}
                          oninput={(e) => updateOption(index, optionIndex, e.currentTarget.value)}
                        />
                        <button
                          type="button"
                          class="text-muted hover:text-negative-stronger hover:bg-negative-dimmer/40 inline-flex size-7 items-center justify-center rounded transition-colors"
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
                        class="text-accent-default hover:text-accent-stronger focus-visible:ring-ring/50 mt-0.5 self-start rounded text-left text-xs font-medium focus-visible:ring-3 focus-visible:outline-none"
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
    </Card.Root>

    {#if !isPublished}
      <button
        type="button"
        class="border-default text-secondary hover:border-accent-default hover:bg-accent-dimmer hover:text-accent-default focus-visible:border-accent-default focus-visible:ring-accent-default/20 flex w-full items-center justify-center gap-2 rounded-lg border border-dashed py-3 text-sm transition-colors focus-visible:ring-3 focus-visible:outline-none"
        onclick={addField}
      >
        <IconPlus class="size-4" />
        {m.flow_form_add_field()}
      </button>
    {/if}
  {/if}
</div>
