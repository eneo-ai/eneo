<script lang="ts">
  import FlowStepSection from "$lib/features/flows/components/FlowStepSection.svelte";
  import { untrack } from "svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep } from "@eneo/eneo-js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { IconQuestionMark } from "@eneo/icons/question-mark";
  import { slide } from "svelte/transition";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import type {
    AdvancedJsonDrafts,
    AdvancedJsonErrors,
    AdvancedJsonField
  } from "./advancedJsonDrafts";
  import FlowStepAdvancedJsonField from "./FlowStepAdvancedJsonField.svelte";

  let {
    step,
    isPublished,
    advancedJsonDrafts,
    advancedJsonErrors,
    embedded = false,
    onJsonFieldUpdate,
    onJsonFieldFormat
  }: {
    step: FlowStep;
    isPublished: boolean;
    advancedJsonDrafts: AdvancedJsonDrafts;
    advancedJsonErrors: AdvancedJsonErrors;
    embedded?: boolean;
    onJsonFieldUpdate?: (detail: { field: AdvancedJsonField; value: string }) => void;
    onJsonFieldFormat?: (detail: { field: AdvancedJsonField }) => void;
  } = $props();

  // Keep the raw JSON editor out of sight until there is a custom schema or the
  // user explicitly opts to edit — Avancerat shouldn't open onto a wall of JSON.
  let editInputContract = $state(false);
  let editOutputContract = $state(false);
  const hasCustomJson = (value: string) => {
    const trimmed = value.trim();
    return trimmed.length > 0 && trimmed !== "{}";
  };
  const showInputContractField = $derived(
    editInputContract || hasCustomJson(advancedJsonDrafts.input_contract)
  );
  const showOutputContractField = $derived(
    editOutputContract || hasCustomJson(advancedJsonDrafts.output_contract)
  );
  // Re-hide the editors when the edited step changes so a manual reveal on one
  // step doesn't carry into the next.
  let lastStepOrder = $state(untrack(() => step.step_order));
  $effect(() => {
    if (step.step_order !== lastStepOrder) {
      lastStepOrder = step.step_order;
      editInputContract = false;
      editOutputContract = false;
    }
  });
</script>

<div transition:slide={{ duration: 200 }}>
  <FlowStepSection title={embedded ? undefined : m.flow_step_advanced()}>
    <Settings.Row
      title={m.flow_step_input_contract()}
      description={m.flow_step_input_contract_desc()}
    >
      <svelte:fragment slot="title">
        <Tooltip.Provider delayDuration={150}>
          <Tooltip.Root>
            <Tooltip.Trigger>
              <IconQuestionMark class="text-muted hover:text-primary ml-1.5" />
            </Tooltip.Trigger>
            <Tooltip.Content>{m.flow_step_input_contract_tooltip()}</Tooltip.Content>
          </Tooltip.Root>
        </Tooltip.Provider>
      </svelte:fragment>
      {#if step.input_type !== "json" && step.input_type !== "text"}
        <Alert.Root
          class="bg-warning-dimmer/50 text-warning-stronger mb-2 rounded-lg"
          role="status"
        >
          <Alert.Description class="text-warning-stronger text-xs leading-relaxed">
            {m.flow_step_input_contract_inactive()}
          </Alert.Description>
        </Alert.Root>
      {:else}
        <Alert.Root
          class="bg-positive-dimmer/50 text-positive-stronger mb-2 rounded-lg"
          role="status"
        >
          <Alert.Description class="text-positive-stronger text-xs leading-relaxed">
            {m.flow_step_input_contract_active()}
          </Alert.Description>
        </Alert.Root>
      {/if}
      {#if showInputContractField}
        <FlowStepAdvancedJsonField
          field="input_contract"
          stepOrder={step.step_order}
          value={advancedJsonDrafts.input_contract}
          error={advancedJsonErrors.input_contract}
          {isPublished}
          placeholder={'{"type": "object", "properties": {...}}'}
          onUpdate={onJsonFieldUpdate}
          onFormat={onJsonFieldFormat}
        />
      {:else}
        <Button
          variant="outline"
          size="sm"
          class="self-start"
          disabled={isPublished}
          onclick={() => (editInputContract = true)}
        >
          {m.flow_step_contract_edit_json()}
        </Button>
      {/if}
    </Settings.Row>

    <Settings.Row
      title={m.flow_step_output_contract()}
      description={m.flow_step_output_contract_desc()}
    >
      <svelte:fragment slot="title">
        <Tooltip.Provider delayDuration={150}>
          <Tooltip.Root>
            <Tooltip.Trigger>
              <IconQuestionMark class="text-muted hover:text-primary ml-1.5" />
            </Tooltip.Trigger>
            <Tooltip.Content>{m.flow_step_output_contract_tooltip()}</Tooltip.Content>
          </Tooltip.Root>
        </Tooltip.Provider>
      </svelte:fragment>
      {#if step.output_type !== "json"}
        <Alert.Root
          class="bg-warning-dimmer/50 text-warning-stronger mb-2 rounded-lg"
          role="status"
        >
          <Alert.Description class="text-warning-stronger text-xs leading-relaxed">
            {m.flow_step_output_contract_inactive()}
          </Alert.Description>
        </Alert.Root>
      {:else}
        <Alert.Root
          class="bg-positive-dimmer/50 text-positive-stronger mb-2 rounded-lg"
          role="status"
        >
          <Alert.Description class="text-positive-stronger text-xs leading-relaxed">
            {m.flow_step_output_contract_active()}
          </Alert.Description>
        </Alert.Root>
      {/if}
      {#if showOutputContractField}
        <FlowStepAdvancedJsonField
          field="output_contract"
          stepOrder={step.step_order}
          value={advancedJsonDrafts.output_contract}
          error={advancedJsonErrors.output_contract}
          {isPublished}
          placeholder={'{"type": "object", "properties": {...}}'}
          onUpdate={onJsonFieldUpdate}
          onFormat={onJsonFieldFormat}
        />
      {:else}
        <Button
          variant="outline"
          size="sm"
          class="self-start"
          disabled={isPublished}
          onclick={() => (editOutputContract = true)}
        >
          {m.flow_step_contract_edit_json()}
        </Button>
      {/if}
    </Settings.Row>

    {#if step.input_source === "http_get" || step.input_source === "http_post"}
      <Settings.Row
        title={m.flow_step_input_config()}
        description={m.flow_step_input_config_desc()}
      >
        <FlowStepAdvancedJsonField
          field="input_config"
          stepOrder={step.step_order}
          value={advancedJsonDrafts.input_config}
          error={advancedJsonErrors.input_config}
          {isPublished}
          placeholder={'{"url": "https://...", "headers": {...}}'}
          onUpdate={onJsonFieldUpdate}
          onFormat={onJsonFieldFormat}
        />
      </Settings.Row>
    {/if}

    {#if step.output_mode === "http_post"}
      <Settings.Row
        title={m.flow_step_output_config()}
        description={m.flow_step_output_config_desc()}
      >
        <FlowStepAdvancedJsonField
          field="output_config"
          stepOrder={step.step_order}
          value={advancedJsonDrafts.output_config}
          error={advancedJsonErrors.output_config}
          {isPublished}
          placeholder={'{"url": "https://...", "headers": {...}}'}
          onUpdate={onJsonFieldUpdate}
          onFormat={onJsonFieldFormat}
        />
      </Settings.Row>
    {/if}
  </FlowStepSection>
</div>
