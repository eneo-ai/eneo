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

  let {
    open = $bindable(false),
    step,
    steps,
    formSchema,
    instructionText,
    ownText,
    materialSentence,
    isAdvancedMode,
    transcriptionEnabled
  }: {
    open?: boolean;
    step: FlowStep;
    steps: FlowStep[];
    formSchema: FlowFormSchemaMetadata | undefined;
    instructionText: string;
    ownText: string;
    /** A full sentence saying what the step reads when it has no text of its own. */
    materialSentence: string | null;
    isAdvancedMode: boolean;
    transcriptionEnabled: boolean;
  } = $props();

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
  // A long instruction would push the material and the answer out of view;
  // it opens in full on request.
  const LONG_INSTRUCTION = 900;
  const instructionIsLong = $derived(instructionText.length > LONG_INSTRUCTION);
  let instructionExpanded = $state(false);
</script>

<!-- The author's own words sit in a quiet inset, apart from the sentences that explain them. -->
{#snippet template(segments: TemplateSegment[], clamped = false)}
  <!-- The clamp sits on the paragraph, not the padded box, or the padding shows part of the next line. -->
  <div class="bg-secondary rounded-lg px-4 py-3">
    <p
      class={cn(
        "text-primary text-sm leading-relaxed whitespace-pre-wrap",
        clamped && "line-clamp-10"
      )}
    >
      {#each segments as segment, index (index)}
        {#if segment.kind === "text"}
          {segment.value}
        {:else}
          <span class={cn(getChipClasses(segment.category), "box-decoration-clone font-sans")}
            >{segment.label}</span
          >
        {/if}
      {/each}
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
        {#if material}
          {@render template(material)}
        {:else if materialSentence}
          <p class="text-primary text-sm">{materialSentence}</p>
        {:else}
          <p class="text-secondary text-sm">{m.flow_request_preview_material_empty()}</p>
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
