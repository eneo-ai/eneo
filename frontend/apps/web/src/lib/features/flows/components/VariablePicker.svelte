<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import { Button, Dropdown } from "@intric/ui";
  import { createEventDispatcher } from "svelte";
  import { m } from "$lib/paraglide/messages";

  export let steps: FlowStep[];
  export let currentStepOrder: number;
  export let formSchema: { fields: { name: string; type: string; required?: boolean }[] } | undefined;

  const dispatch = createEventDispatcher<{ insert: string }>();

  $: previousSteps = steps.filter((s) => s.step_order < currentStepOrder);
  $: formFields = formSchema?.fields ?? [];

  function insert(variable: string) {
    dispatch("insert", `{{ ${variable} }}`);
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
</script>

<Dropdown.Root gutter={2} arrowSize={0} placement="bottom-end">
  <Dropdown.Trigger asFragment let:trigger>
    <Button is={trigger} padding="icon" variant="outlined" class="size-7 text-xs font-bold" title={m.flow_variable_insert()}>
      &#123; &#125;
    </Button>
  </Dropdown.Trigger>
  <Dropdown.Menu let:item>
    <div class="min-w-[280px] max-h-[400px] overflow-y-auto">
      <!-- Flow Input Section -->
      <div class="px-3 pt-2 pb-1">
        <span class="text-xs font-semibold text-secondary">{m.flow_variable_flow_input()}</span>
      </div>
      {#if formFields.length > 0}
        {#each formFields as field}
          <Button is={item} onclick={() => insert(`flow_input.${field.name}`)} class="!text-sm w-full !justify-start !px-3 !py-1.5">
            <span class="flex items-center gap-2">
              <span class="bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300 rounded px-1.5 py-0.5 text-xs font-medium">
                {field.name}
              </span>
              <span class="text-[10px] text-muted">{field.type}</span>
            </span>
          </Button>
        {/each}
      {:else}
        <Button is={item} onclick={() => insert("flow_input.text")} class="!text-sm w-full !justify-start !px-3 !py-1.5">
          <span class="flex items-center justify-between w-full">
            <span class="bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300 rounded px-1.5 py-0.5 text-xs font-medium">
              text
            </span>
            <span class="text-[10px] text-muted ml-2">{m.flow_variable_flow_input_text_desc()}</span>
          </span>
        </Button>
      {/if}

      <!-- Previous Steps Sections -->
      {#if previousSteps.length > 0}
        {#each previousSteps as prevStep}
          <div class="border-default mx-2 my-1.5 border-t"></div>

          <!-- Step header -->
          <div class="px-3 pt-1.5 pb-1">
            <span class="text-xs font-semibold text-secondary">
              {m.flow_variable_step_output({ order: String(prevStep.step_order), name: prevStep.user_description ?? `Step ${prevStep.step_order}` })}
            </span>
          </div>

          <!-- Output text -->
          <Button is={item} onclick={() => insert(`step_${prevStep.step_order}.output.text`)} class="!text-sm w-full !justify-start !px-3 !py-1.5">
            <span class="flex items-center justify-between w-full">
              <span class="bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300 rounded px-1.5 py-0.5 text-xs font-medium">
                text
              </span>
              <span class="text-[10px] text-muted ml-2">{m.flow_variable_output_text_desc()}</span>
            </span>
          </Button>

          <!-- Full output -->
          <Button is={item} onclick={() => insert(`step_${prevStep.step_order}.output`)} class="!text-sm w-full !justify-start !px-3 !py-1.5">
            <span class="flex items-center justify-between w-full">
              <span class="bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300 rounded px-1.5 py-0.5 text-xs font-medium">
                full output
              </span>
              <span class="text-[10px] text-muted ml-2">{m.flow_variable_full_output_desc()}</span>
            </span>
          </Button>

          <!-- JSON fields sub-section -->
          {#if prevStep.output_type === "json"}
            <div class="mx-3 mt-1.5 mb-1 flex items-center gap-2">
              <div class="border-default h-px flex-1 border-t"></div>
              <span class="text-[10px] font-medium uppercase tracking-wider text-muted">{m.flow_variable_json_fields()}</span>
              <div class="border-default h-px flex-1 border-t"></div>
            </div>
            {#if prevStep.output_contract?.properties}
              {#each Object.keys(prevStep.output_contract.properties) as prop}
                {@const propType = getSchemaType(prevStep, prop)}
                <Button is={item} onclick={() => insert(`step_${prevStep.step_order}.output.structured.${prop}`)} class="!text-sm w-full !justify-start !px-3 !py-1.5">
                  <span class="flex items-center justify-between w-full">
                    <span class="bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300 rounded px-1.5 py-0.5 text-xs font-medium">
                      {prop}
                    </span>
                    {#if propType}
                      <span class="text-[10px] font-mono text-muted ml-2">{propType}</span>
                    {/if}
                  </span>
                </Button>
              {/each}
            {:else}
              <Button is={item} onclick={() => insert(`step_${prevStep.step_order}.output.structured`)} class="!text-sm w-full !justify-start !px-3 !py-1.5">
                <span class="flex items-center justify-between w-full">
                  <span class="bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300 rounded px-1.5 py-0.5 text-xs font-medium">
                    structured
                  </span>
                  <span class="text-[10px] text-muted ml-2">{m.flow_variable_structured_desc()}</span>
                </span>
              </Button>
              <p class="px-3 pb-1 text-[10px] text-muted">{m.flow_variable_json_no_contract_hint()}</p>
            {/if}
          {/if}
        {/each}
      {/if}
    </div>
  </Dropdown.Menu>
</Dropdown.Root>
