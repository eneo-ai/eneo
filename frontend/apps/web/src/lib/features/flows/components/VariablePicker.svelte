<script lang="ts">
  import { tick } from "svelte";
  import type { FlowStep } from "@intric/intric-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    getFlowFormFieldVariableExpression,
    isFlowFormFieldNameUsableAsVariable
  } from "$lib/features/flows/flowFormSchema";
  import { getChipClasses } from "$lib/features/flows/flowVariableTokens";

  let {
    steps,
    currentStepOrder,
    formSchema,
    isAdvancedMode = false,
    transcriptionEnabled = false,
    onInsert
  }: {
    steps: FlowStep[];
    currentStepOrder: number;
    formSchema:
      | { fields: { name: string; label?: string | null; type: string; required?: boolean }[] }
      | undefined;
    isAdvancedMode?: boolean;
    transcriptionEnabled?: boolean;
    onInsert?: (variable: string) => void;
  } = $props();

  const previousSteps = $derived(steps.filter((s) => s.step_order < currentStepOrder));
  const formFields = $derived(
    (formSchema?.fields ?? []).filter((field) =>
      isFlowFormFieldNameUsableAsVariable(field.name ?? "")
    )
  );

  let searchQuery = $state("");
  let searchInputEl: HTMLInputElement | null = $state(null);

  function matchesSearch(label: string): boolean {
    if (!searchQuery.trim()) return true;
    return label.toLowerCase().includes(searchQuery.trim().toLowerCase());
  }

  function getFieldLabel(field: { name: string; label?: string | null }): string {
    const label = field.label?.trim();
    return label || field.name;
  }

  function handleDropdownOpen(open: boolean) {
    if (open) {
      searchQuery = "";
      tick().then(() => searchInputEl?.focus());
    }
  }

  function insert(variable: string) {
    onInsert?.(`{{${variable}}}`);
  }

  function getSchemaType(step: FlowStep, prop: string): string {
    const schema = step.output_contract as Record<string, unknown> | null | undefined;
    if (!schema || typeof schema !== "object") return "";
    const properties = schema.properties as Record<string, Record<string, unknown>> | undefined;
    if (!properties || !properties[prop]) return "";
    const propType = properties[prop].type;
    if (typeof propType === "string") return propType;
    return "";
  }

  function getOutputTextDescription(step: FlowStep): string {
    if (step.output_type === "json") return m.flow_variable_output_text_desc_json();
    if (step.output_type === "pdf" || step.output_type === "docx") {
      return m.flow_variable_output_text_desc_prerender();
    }
    return m.flow_variable_output_text_desc();
  }

  function getFullOutputDescription(step: FlowStep): string {
    if (step.output_type === "pdf" || step.output_type === "docx") {
      return m.flow_variable_full_output_desc_artifacts();
    }
    return m.flow_variable_full_output_desc();
  }
</script>

<DropdownMenu.Root onOpenChange={handleDropdownOpen}>
  <DropdownMenu.Trigger>
    {#snippet child({ props })}
      <Button
        {...props}
        size="icon"
        variant="outline"
        class="size-7 text-xs font-bold"
        title="{m.flow_variable_insert()} — @ för genväg"
      >
        &#123; &#125;
      </Button>
    {/snippet}
  </DropdownMenu.Trigger>
  <DropdownMenu.Content align="end" class="max-h-[400px] min-w-[280px] overflow-y-auto p-0">
    <!-- Search -->
    <div class="border-default bg-primary sticky top-0 z-10 border-b px-3 py-2">
      <input
        bind:this={searchInputEl}
        type="text"
        class="border-default bg-secondary/50 placeholder:text-muted focus:ring-accent-default/30 w-full rounded-md border px-2.5 py-1.5 text-xs focus:ring-1 focus:outline-none"
        placeholder={m.flow_variable_search_placeholder()}
        bind:value={searchQuery}
        onkeydown={(e) => e.stopPropagation()}
      />
    </div>

    <!-- Flow Input Section -->
    {#if formFields.length > 0 ? formFields.some((f) => matchesSearch(getFieldLabel(f)) || matchesSearch(f.name)) : isAdvancedMode && matchesSearch("flow_input.text")}
      <div class="px-3 pt-2 pb-1">
        <span class="text-secondary text-xs font-semibold">{m.flow_variable_flow_input()}</span>
      </div>
      {#if formFields.length > 0}
        {#each formFields as field (field.name)}
          {#if matchesSearch(getFieldLabel(field)) || matchesSearch(field.name)}
            <DropdownMenu.Item
              class="!justify-start !px-3 !py-1.5 !text-sm"
              onclick={() => insert(getFlowFormFieldVariableExpression(field.name))}
            >
              <span class="flex items-center gap-2">
                <span class={getChipClasses("field")}>
                  {getFieldLabel(field)}
                </span>
                {#if getFieldLabel(field) !== field.name}
                  <span class="text-muted font-mono text-xs">{field.name}</span>
                {/if}
                <span class="text-muted text-xs">{field.type}</span>
              </span>
            </DropdownMenu.Item>
          {/if}
        {/each}
      {:else if isAdvancedMode && matchesSearch("flow_input.text")}
        <DropdownMenu.Item
          class="!justify-start !px-3 !py-1.5 !text-sm"
          onclick={() => insert("flow_input.text")}
        >
          <span class="flex w-full items-center justify-between">
            <span class={getChipClasses("technical")}> text </span>
            <span class="text-muted ml-2 text-xs">{m.flow_variable_flow_input_text_desc()}</span>
          </span>
        </DropdownMenu.Item>
      {/if}
    {/if}

    {#if (transcriptionEnabled && matchesSearch("transkribering")) || (isAdvancedMode && currentStepOrder > 1 && matchesSearch("föregående_steg"))}
      <DropdownMenu.Separator class="mx-2 my-1.5" />
      <div class="px-3 pt-1.5 pb-1">
        <span class="text-secondary text-xs font-semibold">{m.flow_variable_system_section()}</span>
      </div>
      {#if transcriptionEnabled && matchesSearch("transkribering")}
        <DropdownMenu.Item
          class="!justify-start !px-3 !py-1.5 !text-sm"
          onclick={() => insert("transkribering")}
        >
          <span class={getChipClasses("system")}> transkribering </span>
        </DropdownMenu.Item>
      {/if}
      {#if isAdvancedMode && currentStepOrder > 1 && matchesSearch("föregående_steg")}
        <DropdownMenu.Item
          class="!justify-start !px-3 !py-1.5 !text-sm"
          onclick={() => insert("föregående_steg")}
        >
          <span class={getChipClasses("system")}> föregående_steg </span>
        </DropdownMenu.Item>
      {/if}
    {/if}

    <!-- Previous Steps Sections -->
    {#if previousSteps.length > 0}
      {#each previousSteps as prevStep (prevStep.step_order)}
        {@const stepName = prevStep.user_description ?? `Step ${prevStep.step_order}`}
        {@const hasStepMatches =
          matchesSearch(stepName) ||
          (isAdvancedMode &&
            (matchesSearch("text") ||
              matchesSearch("output") ||
              matchesSearch(`step_${prevStep.step_order}`)))}
        {#if hasStepMatches}
          <DropdownMenu.Separator class="mx-2 my-1.5" />

          <!-- Step header -->
          <div class="px-3 pt-1.5 pb-1">
            <span class="text-secondary text-xs font-semibold">
              {m.flow_variable_step_output({
                order: String(prevStep.step_order),
                name: stepName
              })}
            </span>
          </div>

          <!-- Step name alias -->
          {#if prevStep.user_description?.trim() && matchesSearch(prevStep.user_description)}
            <DropdownMenu.Item
              class="!justify-start !px-3 !py-1.5 !text-sm"
              onclick={() => insert(prevStep.user_description ?? "")}
            >
              <span class="flex w-full items-center justify-between">
                <span class={getChipClasses("step")}>
                  {prevStep.user_description}
                </span>
                <span class="text-muted ml-2 text-xs">{m.flow_variable_alias_desc()}</span>
              </span>
            </DropdownMenu.Item>
          {/if}

          <!-- Output text -->
          {#if isAdvancedMode && (matchesSearch("text") || matchesSearch(`step_${prevStep.step_order}`))}
            <DropdownMenu.Item
              class="!justify-start !px-3 !py-1.5 !text-sm"
              onclick={() => insert(`step_${prevStep.step_order}.output.text`)}
            >
              <span class="flex w-full items-center justify-between">
                <span class={getChipClasses("step")}>
                  {m.flow_variable_output_text_label()}
                </span>
                <span class="text-muted ml-2 text-xs">{getOutputTextDescription(prevStep)}</span>
              </span>
            </DropdownMenu.Item>
          {/if}

          <!-- Full output -->
          {#if isAdvancedMode && (matchesSearch("output") || matchesSearch(`step_${prevStep.step_order}`))}
            <DropdownMenu.Item
              class="!justify-start !px-3 !py-1.5 !text-sm"
              onclick={() => insert(`step_${prevStep.step_order}.output`)}
            >
              <span class="flex w-full items-center justify-between">
                <span class={getChipClasses("step")}>
                  {m.flow_variable_full_output_label()}
                </span>
                <span class="text-muted ml-2 text-xs">{getFullOutputDescription(prevStep)}</span>
              </span>
            </DropdownMenu.Item>
          {/if}

          <!-- JSON fields sub-section -->
          {#if isAdvancedMode && prevStep.output_type === "json"}
            <div class="mx-3 mt-1.5 mb-1 flex items-center gap-2">
              <div class="border-default h-px flex-1 border-t"></div>
              <span class="text-muted text-xs font-medium tracking-wider uppercase"
                >{m.flow_variable_json_fields()}</span
              >
              <div class="border-default h-px flex-1 border-t"></div>
            </div>
            {#if prevStep.output_contract?.properties}
              {#each Object.keys(prevStep.output_contract.properties) as prop (prop)}
                {#if matchesSearch(prop)}
                  {@const propType = getSchemaType(prevStep, prop)}
                  <DropdownMenu.Item
                    class="!justify-start !px-3 !py-1.5 !text-sm"
                    onclick={() => insert(`step_${prevStep.step_order}.output.structured.${prop}`)}
                  >
                    <span class="flex w-full items-center justify-between">
                      <span class={getChipClasses("structured")}>
                        {prop}
                      </span>
                      {#if propType}
                        <span class="text-muted ml-2 font-mono text-xs">{propType}</span>
                      {/if}
                    </span>
                  </DropdownMenu.Item>
                {/if}
              {/each}
            {:else if matchesSearch("structured")}
              <DropdownMenu.Item
                class="!justify-start !px-3 !py-1.5 !text-sm"
                onclick={() => insert(`step_${prevStep.step_order}.output.structured`)}
              >
                <span class="flex w-full items-center justify-between">
                  <span class={getChipClasses("structured")}>
                    {m.flow_variable_structured_label()}
                  </span>
                  <span class="text-muted ml-2 text-xs">{m.flow_variable_structured_desc()}</span>
                </span>
              </DropdownMenu.Item>
              <p class="text-muted px-3 pb-1 text-xs">
                {m.flow_variable_json_no_contract_hint()}
              </p>
            {/if}
          {/if}
        {/if}
      {/each}
    {/if}
  </DropdownMenu.Content>
</DropdownMenu.Root>
