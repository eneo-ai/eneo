<script lang="ts">
  import type { FlowStep } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils.js";
  import type { FlowFormSchemaMetadata } from "../flowFormSchema";
  import {
    describeAnswerFields,
    describeTemplateSegments,
    type TemplateSegment
  } from "../flowStepRequestPreview";
  import { getChipClasses } from "../flowVariableTokens";
  import { buildContext } from "./flowPromptVariables";
  import {
    boundVariableToken,
    readToolInputConfig,
    type FlowToolOption
  } from "./tool/toolInputConfig";

  let {
    open = $bindable(false),
    step,
    steps,
    formSchema,
    instructionText,
    ownText,
    materialSentence,
    hasAttachments,
    hasKnowledge,
    isAdvancedMode,
    transcriptionEnabled,
    tool = null
  }: {
    open?: boolean;
    step: FlowStep;
    steps: FlowStep[];
    formSchema: FlowFormSchemaMetadata | undefined;
    instructionText: string;
    ownText: string;
    /** The material block's sentence; with an own text it points at the text shown below it. */
    materialSentence: string | null;
    hasAttachments: boolean;
    hasKnowledge: boolean;
    isAdvancedMode: boolean;
    transcriptionEnabled: boolean;
    /** The listed tool a tool step reads its material from; null for any other step. */
    tool?: Pick<FlowToolOption, "mcp_server_name" | "tool_name"> | null;
  } = $props();

  const uid = $props.id();

  // Only the instruction is rendered per section, so only it may use section variables.
  const instruction = $derived(
    describeTemplateSegments(
      instructionText,
      buildContext(steps, formSchema, transcriptionEnabled, step.step_order, true),
      formSchema
    )
  );
  const material = $derived(
    ownText.trim()
      ? describeTemplateSegments(
          ownText,
          buildContext(steps, formSchema, transcriptionEnabled, step.step_order),
          formSchema
        )
      : null
  );
  const answer = $derived(describeAnswerFields(step));
  // Where each argument of the tool call gets its value: one whole variable,
  // named as the instruction names it, or a fixed value as written.
  const toolArguments = $derived(
    Object.entries(readToolInputConfig(step.input_config)?.arguments ?? {}).map(([name, value]) =>
      typeof value === "string" && boundVariableToken(value) !== null
        ? {
            name,
            kind: "variable" as const,
            segments: describeTemplateSegments(
              value,
              buildContext(steps, formSchema, transcriptionEnabled, step.step_order),
              formSchema
            )
          }
        : { name, kind: "fixed" as const, value: JSON.stringify(value) }
    )
  );
  // A long instruction would push the material and the answer out of view;
  // it opens in full on request.
  const LONG_INSTRUCTION = 900;
  const instructionIsLong = $derived(instructionText.length > LONG_INSTRUCTION);
  let instructionExpanded = $state(false);
</script>

<!-- The author's own words sit in a quiet inset, apart from the sentences that explain them. -->
{#snippet chips(segments: TemplateSegment[])}
  {#each segments as segment, index (index)}
    {#if segment.kind === "text"}
      {segment.value}
    {:else}
      <span class={cn(getChipClasses(segment.category), "box-decoration-clone font-sans")}
        >{segment.label}</span
      >
    {/if}
  {/each}
{/snippet}

{#snippet template(segments: TemplateSegment[], clamped = false)}
  <!-- The clamp sits on the paragraph, not the padded box, or the padding shows part of the next line. -->
  <div class="bg-secondary rounded-lg px-4 py-3">
    <p
      class={cn(
        "text-primary text-sm leading-relaxed whitespace-pre-wrap",
        clamped && "line-clamp-10"
      )}
    >
      {@render chips(segments)}
    </p>
  </div>
{/snippet}

<Dialog.Root bind:open>
  <!-- sm:max-w-2xl beats the primitive's sm:max-w-sm from the breakpoint up. -->
  <Dialog.Content
    class="grid max-h-[85vh] grid-rows-[auto_minmax(0,1fr)] gap-5 sm:max-w-2xl sm:p-6"
    closeLabel={m.close()}
  >
    <Dialog.Header class="gap-1 pr-8 text-left">
      <Dialog.Title>{m.flow_request_preview_title()}</Dialog.Title>
      <Dialog.Description>{m.flow_request_preview_description()}</Dialog.Description>
    </Dialog.Header>

    <div class="-mx-4 flex flex-col gap-6 overflow-y-auto px-4 sm:-mx-6 sm:px-6">
      {#if tool}
        <section class="flex flex-col gap-2" aria-labelledby="{uid}-tool">
          <h3 id="{uid}-tool" class="text-primary text-sm font-semibold">
            {m.flow_request_preview_tool_call()}
          </h3>
          <p class="text-primary text-sm">
            {m.flow_tool_picker_server({ name: tool.mcp_server_name })}
          </p>
          <code translate="no" class="text-primary self-start font-mono text-sm break-all"
            >{tool.tool_name}</code
          >
          {#if toolArguments.length > 0}
            <ul class="flex flex-col gap-1.5">
              {#each toolArguments as argument (argument.name)}
                <li class="text-primary text-sm leading-relaxed">
                  <code translate="no" class="font-mono text-xs">{argument.name}</code>
                  {#if argument.kind === "variable"}
                    <span class="text-secondary">{m.flow_request_preview_tool_variable()}</span>
                    {@render chips(argument.segments)}
                  {:else}
                    <span class="text-secondary">{m.flow_request_preview_tool_fixed()}</span>
                    <code translate="no" class="font-mono text-xs break-all">{argument.value}</code>
                  {/if}
                </li>
              {/each}
            </ul>
          {:else}
            <p class="text-secondary text-sm">{m.flow_request_preview_tool_no_arguments()}</p>
          {/if}
          {#if step.input_type === "json"}
            <p class="text-primary text-sm">{m.flow_request_preview_tool_format_json()}</p>
          {:else if step.input_type === "text"}
            <p class="text-primary text-sm">{m.flow_request_preview_tool_format_text()}</p>
          {/if}
        </section>
      {/if}
      <section class="flex flex-col gap-2">
        <h3 class="text-primary text-sm font-semibold">{m.flow_request_preview_instruction()}</h3>
        {#if instructionText.trim()}
          {@render template(instruction, instructionIsLong && !instructionExpanded)}
          {#if instructionIsLong}
            <Button
              variant="link"
              size="sm"
              class="text-accent-stronger h-auto self-start px-0"
              aria-expanded={instructionExpanded}
              onclick={() => (instructionExpanded = !instructionExpanded)}
            >
              {instructionExpanded
                ? m.flow_request_preview_instruction_less()
                : m.flow_request_preview_instruction_more()}
            </Button>
          {/if}
        {:else}
          <p class="text-secondary text-sm">{m.flow_request_preview_instruction_empty()}</p>
        {/if}
      </section>

      <section class="flex flex-col gap-2">
        <h3 class="text-primary text-sm font-semibold">{m.flow_request_preview_material()}</h3>
        {#if materialSentence}
          <p class="text-primary text-sm">{materialSentence}</p>
        {:else if !material}
          <p class="text-secondary text-sm">{m.flow_request_preview_material_empty()}</p>
        {/if}
        {#if material}
          {@render template(material)}
        {/if}
        {#if hasAttachments}
          <p class="text-primary text-sm">{m.flow_request_preview_material_files()}</p>
        {/if}
        {#if hasKnowledge}
          <p class="text-primary text-sm">{m.flow_request_preview_material_knowledge()}</p>
        {/if}
      </section>

      <section class="flex flex-col gap-2">
        <h3 class="text-primary text-sm font-semibold">{m.flow_request_preview_answer()}</h3>
        {#if answer.kind === "free_text"}
          <p class="text-primary text-sm">{m.flow_request_preview_answer_free_text()}</p>
        {:else if answer.kind === "document"}
          <p class="text-primary text-sm">
            {m.flow_request_preview_answer_document({
              document:
                answer.format === "pdf" ? m.flow_output_type_pdf() : m.flow_output_type_docx()
            })}
          </p>
        {:else if answer.fields.length === 0}
          <p class="text-primary text-sm">{m.flow_typed_io_contract_info_simple()}</p>
        {:else}
          {#if answer.perSection}
            <p class="text-primary text-sm">{m.flow_request_preview_answer_per_section()}</p>
          {/if}
          <ul class="marker:text-secondary flex list-disc flex-col gap-2 pl-5">
            {#each answer.fields as field (field.name)}
              <li class="text-primary text-sm">
                <span class="font-medium">{field.label}</span>
                {#if isAdvancedMode}
                  <span class="text-secondary ml-1 font-mono text-xs">{field.name}</span>
                {/if}
                {#if field.description}
                  <span class="text-secondary block text-xs">{field.description}</span>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
      </section>
    </div>
  </Dialog.Content>
</Dialog.Root>
