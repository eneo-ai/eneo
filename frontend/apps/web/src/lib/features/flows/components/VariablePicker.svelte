<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import { Button, Dropdown } from "@intric/ui";
  import { createEventDispatcher, tick } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { getChipClasses } from "$lib/features/flows/flowVariableTokens";

  export let steps: FlowStep[];
  export let currentStepOrder: number;
  export let formSchema: { fields: { name: string; type: string; required?: boolean }[] } | undefined;
  export let isAdvancedMode: boolean = false;
  export let transcriptionEnabled: boolean = false;

  const dispatch = createEventDispatcher<{ insert: string }>();

  $: previousSteps = steps.filter((s) => s.step_order < currentStepOrder);
  $: formFields = formSchema?.fields ?? [];

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
    <Button is={trigger} padding="icon" variant="outlined" class="size-7 text-xs font-bold" title={m.flow_variable_insert()}>
      &#123; &#125;
    </Button>
  </Dropdown.Trigger>
  <Dropdown.Menu let:item>
    <div class="min-w-[280px] max-h-[400px] overflow-y-auto" on:introstart={handleDropdownOpen}>
      <!-- Search -->
      <div class="sticky top-0 z-10 border-b border-default bg-primary px-3 py-2">
        <input
          bind:this={searchInputEl}
          type="text"
          class="w-full rounded-md border border-default bg-secondary/50 px-2.5 py-1.5 text-xs placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-accent-default/30"
          placeholder={m.flow_variable_search_placeholder()}
          bind:value={searchQuery}
          on:keydown|stopPropagation={() => {}}
        />
      </div>

      <!-- Flow Input Section -->
      {#if formFields.length > 0 ? formFields.some(f => matchesSearch(f.name)) : (isAdvancedMode && matchesSearch("flow_input.text"))}
      <div class="px-3 pt-2 pb-1">
        <span class="text-xs font-semibold text-secondary">{m.flow_variable_flow_input()}</span>
      </div>
      {#if formFields.length > 0}
        {#each formFields as field (field.name)}
          {#if matchesSearch(field.name)}
          <Button is={item} onclick={() => insert(field.name)} class="!text-sm w-full !justify-start !px-3 !py-1.5">
            <span class="flex items-center gap-2">
              <span class="{getChipClasses('field')}">
                {field.name}
              </span>
              <span class="text-xs text-muted">{field.type}</span>
            </span>
          </Button>
          {/if}
        {/each}
      {:else}
        {#if isAdvancedMode && matchesSearch("flow_input.text")}
        <Button is={item} onclick={() => insert("flow_input.text")} class="!text-sm w-full !justify-start !px-3 !py-1.5">
          <span class="flex items-center justify-between w-full">
            <span class="{getChipClasses('technical')}">
              text
            </span>
            <span class="text-xs text-muted ml-2">{m.flow_variable_flow_input_text_desc()}</span>
          </span>
        </Button>
        {/if}
      {/if}
      {/if}

      {#if (transcriptionEnabled && matchesSearch("transkribering")) || (isAdvancedMode && currentStepOrder > 1 && matchesSearch("föregående_steg"))}
      <div class="border-default mx-2 my-1.5 border-t"></div>
      <div class="px-3 pt-1.5 pb-1">
        <span class="text-xs font-semibold text-secondary">System</span>
      </div>
      {#if transcriptionEnabled && matchesSearch("transkribering")}
      <Button is={item} onclick={() => insert("transkribering")} class="!text-sm w-full !justify-start !px-3 !py-1.5">
        <span class="{getChipClasses('system')}">
          transkribering
        </span>
      </Button>
      {/if}
      {#if isAdvancedMode && currentStepOrder > 1 && matchesSearch("föregående_steg")}
        <Button is={item} onclick={() => insert("föregående_steg")} class="!text-sm w-full !justify-start !px-3 !py-1.5">
          <span class="{getChipClasses('system')}">
            föregående_steg
          </span>
        </Button>
      {/if}
      {/if}

      <!-- Previous Steps Sections -->
      {#if previousSteps.length > 0}
        {#each previousSteps as prevStep (prevStep.step_order)}
          {@const stepName = prevStep.user_description ?? `Step ${prevStep.step_order}`}
          {@const hasStepMatches = matchesSearch(stepName) || (isAdvancedMode && (matchesSearch("text") || matchesSearch("output") || matchesSearch(`step_${prevStep.step_order}`)))}
          {#if hasStepMatches}
          <div class="border-default mx-2 my-1.5 border-t"></div>

          <!-- Step header -->
          <div class="px-3 pt-1.5 pb-1">
            <span class="text-xs font-semibold text-secondary">
              {m.flow_variable_step_output({ order: String(prevStep.step_order), name: stepName })}
            </span>
          </div>

          <!-- Step name alias -->
          {#if prevStep.user_description?.trim() && matchesSearch(prevStep.user_description)}
            <Button is={item} onclick={() => insert(prevStep.user_description ?? "")} class="!text-sm w-full !justify-start !px-3 !py-1.5">
              <span class="flex items-center justify-between w-full">
                <span class="{getChipClasses('step')}">
                  {prevStep.user_description}
                </span>
                <span class="text-xs text-muted ml-2">alias</span>
              </span>
            </Button>
          {/if}

          <!-- Output text -->
          {#if isAdvancedMode && (matchesSearch("text") || matchesSearch(`step_${prevStep.step_order}`))}
          <Button is={item} onclick={() => insert(`step_${prevStep.step_order}.output.text`)} class="!text-sm w-full !justify-start !px-3 !py-1.5">
            <span class="flex items-center justify-between w-full">
              <span class="{getChipClasses('step')}">
                text
              </span>
              <span class="text-xs text-muted ml-2">{getOutputTextDescription(prevStep)}</span>
            </span>
          </Button>
          {/if}

          <!-- Full output -->
          {#if isAdvancedMode && (matchesSearch("output") || matchesSearch(`step_${prevStep.step_order}`))}
          <Button is={item} onclick={() => insert(`step_${prevStep.step_order}.output`)} class="!text-sm w-full !justify-start !px-3 !py-1.5">
            <span class="flex items-center justify-between w-full">
              <span class="{getChipClasses('step')}">
                full output
              </span>
              <span class="text-xs text-muted ml-2">{getFullOutputDescription(prevStep)}</span>
            </span>
          </Button>
          {/if}

          <!-- JSON fields sub-section -->
          {#if isAdvancedMode && prevStep.output_type === "json"}
            <div class="mx-3 mt-1.5 mb-1 flex items-center gap-2">
              <div class="border-default h-px flex-1 border-t"></div>
              <span class="text-xs font-medium uppercase tracking-wider text-muted">{m.flow_variable_json_fields()}</span>
              <div class="border-default h-px flex-1 border-t"></div>
            </div>
            {#if prevStep.output_contract?.properties}
              {#each Object.keys(prevStep.output_contract.properties) as prop (prop)}
                {#if matchesSearch(prop)}
                {@const propType = getSchemaType(prevStep, prop)}
                <Button is={item} onclick={() => insert(`step_${prevStep.step_order}.output.structured.${prop}`)} class="!text-sm w-full !justify-start !px-3 !py-1.5">
                  <span class="flex items-center justify-between w-full">
                    <span class="{getChipClasses('structured')}">
                      {prop}
                    </span>
                    {#if propType}
                      <span class="text-xs font-mono text-muted ml-2">{propType}</span>
                    {/if}
                  </span>
                </Button>
                {/if}
              {/each}
            {:else}
              {#if matchesSearch("structured")}
              <Button is={item} onclick={() => insert(`step_${prevStep.step_order}.output.structured`)} class="!text-sm w-full !justify-start !px-3 !py-1.5">
                <span class="flex items-center justify-between w-full">
                  <span class="{getChipClasses('structured')}">
                    structured
                  </span>
                  <span class="text-xs text-muted ml-2">{m.flow_variable_structured_desc()}</span>
                </span>
              </Button>
              <p class="px-3 pb-1 text-xs text-muted">{m.flow_variable_json_no_contract_hint()}</p>
              {/if}
            {/if}
          {/if}
          {/if}
        {/each}
      {/if}
    </div>
  </Dropdown.Menu>
</Dropdown.Root>
