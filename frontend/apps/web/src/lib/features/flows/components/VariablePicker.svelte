<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import { Button, Dropdown } from "@intric/ui";
  import { createEventDispatcher, tick } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { isFlowFormFieldNameUsableAsVariable } from "$lib/features/flows/flowFormSchema";
  import { getChipClasses } from "$lib/features/flows/flowVariableTokens";

  export let steps: FlowStep[];
  export let currentStepOrder: number;
  export let formSchema:
    | { fields: { name: string; type: string; required?: boolean }[] }
    | undefined;
  export let isAdvancedMode: boolean = false;
  export let transcriptionEnabled: boolean = false;

  const dispatch = createEventDispatcher<{ insert: string }>();

  $: previousSteps = steps.filter((s) => s.step_order < currentStepOrder);
  $: formFields = (formSchema?.fields ?? []).filter((field) =>
    isFlowFormFieldNameUsableAsVariable(field.name ?? ""),
  );

  let searchQuery = "";
  let searchInputEl: HTMLInputElement | null = null;

  function matchesSearch(label: string): boolean {
    if (!searchQuery.trim()) return true;
    return label.toLowerCase().includes(searchQuery.trim().toLowerCase());
  }

  function handleDropdownOpen() {
    searchQuery = "";
    tick().then(() => searchInputEl?.focus());
  }

  function insert(variable: string) {
    dispatch("insert", `{{${variable}}}`);
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

<Dropdown.Root gutter={2} arrowSize={0} placement="bottom-end">
  <Dropdown.Trigger asFragment let:trigger>
    <Button
      is={trigger}
      padding="icon"
      variant="outlined"
      class="size-7 text-xs font-bold"
      title="{m.flow_variable_insert()} — @ för genväg"
    >
      &#123; &#125;
    </Button>
  </Dropdown.Trigger>
  <Dropdown.Menu let:item>
    <div class="max-h-[400px] min-w-[280px] overflow-y-auto" on:introstart={handleDropdownOpen}>
      <!-- Search -->
      <div class="border-default bg-primary sticky top-0 z-10 border-b px-3 py-2">
        <input
          bind:this={searchInputEl}
          type="text"
          class="border-default bg-secondary/50 placeholder:text-muted focus:ring-accent-default/30 w-full rounded-md border px-2.5 py-1.5 text-xs focus:ring-1 focus:outline-none"
          placeholder={m.flow_variable_search_placeholder()}
          bind:value={searchQuery}
          on:keydown|stopPropagation={() => {}}
        />
      </div>

      <!-- Flow Input Section -->
      {#if formFields.length > 0 ? formFields.some( (f) => matchesSearch(f.name) ) : isAdvancedMode && matchesSearch("flow_input.text")}
        <div class="px-3 pt-2 pb-1">
          <span class="text-secondary text-xs font-semibold">{m.flow_variable_flow_input()}</span>
        </div>
        {#if formFields.length > 0}
          {#each formFields as field (field.name)}
            {#if matchesSearch(field.name)}
              <Button
                is={item}
                on:click={() => insert(field.name)}
                class="w-full !justify-start !px-3 !py-1.5 !text-sm"
              >
                <span class="flex items-center gap-2">
                  <span class={getChipClasses("field")}>
                    {field.name}
                  </span>
                  <span class="text-muted text-xs">{field.type}</span>
                </span>
              </Button>
            {/if}
          {/each}
        {:else if isAdvancedMode && matchesSearch("flow_input.text")}
          <Button
            is={item}
            on:click={() => insert("flow_input.text")}
            class="w-full !justify-start !px-3 !py-1.5 !text-sm"
          >
            <span class="flex w-full items-center justify-between">
              <span class={getChipClasses("technical")}> text </span>
              <span class="text-muted ml-2 text-xs">{m.flow_variable_flow_input_text_desc()}</span>
            </span>
          </Button>
        {/if}
      {/if}

      {#if (transcriptionEnabled && matchesSearch("transkribering")) || (isAdvancedMode && currentStepOrder > 1 && matchesSearch("föregående_steg"))}
        <div class="border-default mx-2 my-1.5 border-t"></div>
        <div class="px-3 pt-1.5 pb-1">
          <span class="text-secondary text-xs font-semibold"
            >{m.flow_variable_system_section()}</span
          >
        </div>
        {#if transcriptionEnabled && matchesSearch("transkribering")}
          <Button
            is={item}
            on:click={() => insert("transkribering")}
            class="w-full !justify-start !px-3 !py-1.5 !text-sm"
          >
            <span class={getChipClasses("system")}> transkribering </span>
          </Button>
        {/if}
        {#if isAdvancedMode && currentStepOrder > 1 && matchesSearch("föregående_steg")}
          <Button
            is={item}
            on:click={() => insert("föregående_steg")}
            class="w-full !justify-start !px-3 !py-1.5 !text-sm"
          >
            <span class={getChipClasses("system")}> föregående_steg </span>
          </Button>
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
            <div class="border-default mx-2 my-1.5 border-t"></div>

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
              <Button
                is={item}
                on:click={() => insert(prevStep.user_description ?? "")}
                class="w-full !justify-start !px-3 !py-1.5 !text-sm"
              >
                <span class="flex w-full items-center justify-between">
                  <span class={getChipClasses("step")}>
                    {prevStep.user_description}
                  </span>
                  <span class="text-muted ml-2 text-xs">{m.flow_variable_alias_desc()}</span>
                </span>
              </Button>
            {/if}

            <!-- Output text -->
            {#if isAdvancedMode && (matchesSearch("text") || matchesSearch(`step_${prevStep.step_order}`))}
              <Button
                is={item}
                on:click={() => insert(`step_${prevStep.step_order}.output.text`)}
                class="w-full !justify-start !px-3 !py-1.5 !text-sm"
              >
                <span class="flex w-full items-center justify-between">
                  <span class={getChipClasses("step")}>
                    {m.flow_variable_output_text_label()}
                  </span>
                  <span class="text-muted ml-2 text-xs">{getOutputTextDescription(prevStep)}</span>
                </span>
              </Button>
            {/if}

            <!-- Full output -->
            {#if isAdvancedMode && (matchesSearch("output") || matchesSearch(`step_${prevStep.step_order}`))}
              <Button
                is={item}
                on:click={() => insert(`step_${prevStep.step_order}.output`)}
                class="w-full !justify-start !px-3 !py-1.5 !text-sm"
              >
                <span class="flex w-full items-center justify-between">
                  <span class={getChipClasses("step")}>
                    {m.flow_variable_full_output_label()}
                  </span>
                  <span class="text-muted ml-2 text-xs">{getFullOutputDescription(prevStep)}</span>
                </span>
              </Button>
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
                    <Button
                      is={item}
                      on:click={() =>
                        insert(`step_${prevStep.step_order}.output.structured.${prop}`)}
                      class="w-full !justify-start !px-3 !py-1.5 !text-sm"
                    >
                      <span class="flex w-full items-center justify-between">
                        <span class={getChipClasses("structured")}>
                          {prop}
                        </span>
                        {#if propType}
                          <span class="text-muted ml-2 font-mono text-xs">{propType}</span>
                        {/if}
                      </span>
                    </Button>
                  {/if}
                {/each}
              {:else if matchesSearch("structured")}
                <Button
                  is={item}
                  on:click={() => insert(`step_${prevStep.step_order}.output.structured`)}
                  class="w-full !justify-start !px-3 !py-1.5 !text-sm"
                >
                  <span class="flex w-full items-center justify-between">
                    <span class={getChipClasses("structured")}>
                      {m.flow_variable_structured_label()}
                    </span>
                    <span class="text-muted ml-2 text-xs">{m.flow_variable_structured_desc()}</span>
                  </span>
                </Button>
                <p class="text-muted px-3 pb-1 text-xs">
                  {m.flow_variable_json_no_contract_hint()}
                </p>
              {/if}
            {/if}
          {/if}
        {/each}
      {/if}
    </div>
  </Dropdown.Menu>
</Dropdown.Root>
