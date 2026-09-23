<script module lang="ts">
  import type { FlowStep } from "@eneo/eneo-js";
  import type { FlowFormSchemaMetadata } from "$lib/features/flows/flowFormSchema";

  /** Everything a caller needs to offer flow variables through the picker. */
  export type VariablePickerContext = {
    steps: FlowStep[];
    currentStepOrder: number;
    formSchema: FlowFormSchemaMetadata | undefined;
    isAdvancedMode: boolean;
    transcriptionEnabled: boolean;
  };
</script>

<script lang="ts">
  import * as Popover from "$lib/components/ui/popover/index.js";
  import * as Command from "$lib/components/ui/command/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import Braces from "@lucide/svelte/icons/braces";
  import { m } from "$lib/paraglide/messages";
  import {
    getFlowFormFieldVariableExpression,
    isFlowFormFieldNameUsableAsVariable
  } from "$lib/features/flows/flowFormSchema";
  import {
    getChipClasses,
    VARIABLE_CATEGORY_CLASSES,
    type VariableCategory
  } from "$lib/features/flows/flowVariableTokens";
  import { fieldTypeLabel } from "$lib/features/flows/ai-builder/aiBuilderSummaryText";

  let {
    steps,
    currentStepOrder,
    formSchema,
    isAdvancedMode = false,
    transcriptionEnabled = false,
    sectionVariablesAvailable = false,
    uploadVariableAvailable = false,
    onInsert
  }: {
    steps: VariablePickerContext["steps"];
    currentStepOrder: VariablePickerContext["currentStepOrder"];
    formSchema: VariablePickerContext["formSchema"];
    isAdvancedMode?: boolean;
    transcriptionEnabled?: boolean;
    /** The editor holds the AI instruction of a step that reads section by section. */
    sectionVariablesAvailable?: boolean;
    /** Offer the text of the file uploaded when the flow runs (custom text of an upload step). */
    uploadVariableAvailable?: boolean;
    onInsert?: (variable: string) => void;
  } = $props();

  type Entry = { token: string; label: string; description?: string };
  // Each group carries the colour its variables get in the editor, so a
  // form field, a result from the run and an earlier step's answer read the
  // same in the list as in the text.
  type Group = { key: string; heading: string; category: VariableCategory; entries: Entry[] };

  let open = $state(false);

  function stepName(step: FlowStep): string {
    return step.user_description?.trim() || m.flow_step_unnamed();
  }

  function outputTextDescription(step: FlowStep): string {
    if (step.output_type === "json") return m.flow_variable_output_text_desc_json();
    if (step.output_type === "pdf" || step.output_type === "docx") {
      return m.flow_variable_output_text_desc_prerender();
    }
    return m.flow_variable_output_text_desc();
  }

  function fullOutputDescription(step: FlowStep): string {
    return step.output_type === "pdf" || step.output_type === "docx"
      ? m.flow_variable_full_output_desc_artifacts()
      : m.flow_variable_full_output_desc();
  }

  function schemaFields(step: FlowStep): Array<{ name: string; type: string }> {
    const properties = (step.output_contract as { properties?: Record<string, { type?: unknown }> })
      ?.properties;
    if (!properties || typeof properties !== "object") return [];
    return Object.entries(properties).map(([name, schema]) => ({
      name,
      type: typeof schema?.type === "string" ? schema.type : ""
    }));
  }

  // The same variables the editor's autocomplete accepts, grouped the way an
  // author thinks about them: what the person filled in, what the run itself
  // provides, and what each earlier step answered. Technical paths only in
  // Avancerad.
  const groups = $derived.by<Group[]>(() => {
    const result: Group[] = [];

    const fields = (formSchema?.fields ?? []).filter((field) =>
      isFlowFormFieldNameUsableAsVariable(field.name ?? "")
    );
    const fieldEntries: Entry[] = fields.map((field) => ({
      token: getFlowFormFieldVariableExpression(field.name),
      label: field.label?.trim() || field.name,
      description: isAdvancedMode ? fieldTypeLabel(field.type) : undefined
    }));
    if (fieldEntries.length === 0 && isAdvancedMode) {
      fieldEntries.push({
        token: "flow_input.text",
        label: m.flow_variable_flow_input_text_label(),
        description: m.flow_variable_flow_input_text_desc()
      });
    }
    if (fieldEntries.length > 0) {
      result.push({
        key: "fields",
        heading: m.flow_variable_form_field(),
        category: "field",
        entries: fieldEntries
      });
    }

    const runEntries: Entry[] = [];
    if (uploadVariableAvailable) {
      runEntries.push({
        token: "step_input.text",
        label: m.flow_variable_upload_label(),
        description: m.flow_variable_upload_desc()
      });
    }
    if (sectionVariablesAvailable) {
      runEntries.push({
        token: "section_index",
        label: m.flow_variable_section_index_label(),
        description: m.flow_variable_section_index()
      });
    }
    if (transcriptionEnabled) {
      runEntries.push({
        token: "transkribering",
        label: m.flow_variable_transcription(),
        description: m.flow_variable_transcription_desc()
      });
    }
    if (isAdvancedMode && currentStepOrder > 1) {
      runEntries.push({
        token: "föregående_steg",
        label: m.flow_variable_previous_step(),
        description: m.flow_variable_previous_step_desc()
      });
    }
    if (runEntries.length > 0) {
      result.push({
        key: "run",
        heading: m.flow_variable_run_section(),
        category: "system",
        entries: runEntries
      });
    }

    for (const step of steps.filter((s) => s.step_order < currentStepOrder)) {
      const entries: Entry[] = [];
      if (step.user_description?.trim()) {
        entries.push({
          token: step.user_description.trim(),
          label: m.flow_variable_step_answer_label(),
          description: m.flow_variable_alias_desc()
        });
      }
      if (isAdvancedMode) {
        entries.push(
          {
            token: `step_${step.step_order}.output.text`,
            label: m.flow_variable_output_text_label(),
            description: outputTextDescription(step)
          },
          {
            token: `step_${step.step_order}.output`,
            label: m.flow_variable_full_output_label(),
            description: fullOutputDescription(step)
          }
        );
        if (step.output_type === "json") {
          const fieldsOfStep = schemaFields(step);
          if (fieldsOfStep.length > 0) {
            for (const field of fieldsOfStep) {
              entries.push({
                token: `step_${step.step_order}.output.structured.${field.name}`,
                label: field.name,
                description: field.type || undefined
              });
            }
          } else {
            entries.push({
              token: `step_${step.step_order}.output.structured`,
              label: m.flow_variable_structured_label(),
              description: m.flow_variable_structured_desc()
            });
          }
        }
      }
      if (entries.length > 0) {
        result.push({
          key: `step-${step.step_order}`,
          category: "step",
          heading: m.flow_variable_step_output({
            order: String(step.step_order),
            name: stepName(step)
          }),
          entries
        });
      }
    }
    return result;
  });

  function insert(token: string) {
    open = false;
    onInsert?.(`{{${token}}}`);
  }
</script>

<Popover.Root bind:open>
  <Popover.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="outline" size="sm" title={m.flow_variable_insert_hint()}>
        <Braces data-icon="inline-start" aria-hidden="true" />
        {m.flow_variable_insert()}
      </Button>
    {/snippet}
  </Popover.Trigger>
  <Popover.Content align="start" class="w-[min(30rem,calc(100vw-2rem))] p-0">
    <Command.Root>
      <Command.Input placeholder={m.flow_variable_search_placeholder()} />
      <Command.List class="max-h-[min(24rem,60vh)]">
        <Command.Empty>{m.flow_variable_search_empty()}</Command.Empty>
        {#each groups as group (group.key)}
          <Command.Group heading={group.heading}>
            {#each group.entries as entry (entry.token)}
              <Command.Item
                value={`${group.key}:${entry.token}`}
                keywords={[entry.label, entry.token, group.heading, entry.description ?? ""]}
                onSelect={() => insert(entry.token)}
                class="items-start gap-2.5 py-2"
              >
                <span
                  class="{VARIABLE_CATEGORY_CLASSES[group.category]
                    .scopeClass} bg-label-default mt-1.5 size-2 shrink-0 rounded-full"
                  aria-hidden="true"
                ></span>
                <span class="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span class="text-primary text-sm font-medium">{entry.label}</span>
                  {#if entry.description}
                    <span class="text-secondary text-xs leading-relaxed">{entry.description}</span>
                  {/if}
                  {#if isAdvancedMode}
                    <code
                      translate="no"
                      class="{getChipClasses(group.category)} mt-0.5 max-w-full self-start truncate"
                      >{`{{${entry.token}}}`}</code
                    >
                  {/if}
                </span>
              </Command.Item>
            {/each}
          </Command.Group>
        {/each}
      </Command.List>
    </Command.Root>
  </Popover.Content>
</Popover.Root>
