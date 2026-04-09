<svelte:options runes={false} />

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep } from "@intric/intric-js";
  import { Tooltip } from "@intric/ui";
  import { IconQuestionMark } from "@intric/icons/question-mark";
  import { createEventDispatcher } from "svelte";
  import { slide } from "svelte/transition";
  import { Alert } from "@eneo/ui";
  import { MCP_POLICIES } from "./flowStepEditHelpers";
  import type { AdvancedJsonDrafts, AdvancedJsonErrors } from "./advancedJsonDrafts";

  export let step: FlowStep;
  export let isPublished: boolean;
  export let advancedJsonDrafts: AdvancedJsonDrafts;
  export let advancedJsonErrors: AdvancedJsonErrors;

  const dispatch = createEventDispatcher<{
    mcpPolicyChange: { value: string };
    jsonFieldUpdate: { field: string; value: string };
  }>();
</script>

<div transition:slide={{ duration: 200 }} class="border-l border-l-amber-300/50">
  <Settings.Group title={m.flow_step_advanced()}>
    <Settings.Row title={m.flow_step_mcp_policy()} description="">
      <svelte:fragment slot="title">
        <Tooltip text={m.flow_step_mcp_policy_tooltip()}>
          <IconQuestionMark class="text-muted hover:text-primary ml-1.5" />
        </Tooltip>
      </svelte:fragment>
      <select
        class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
        value={step.mcp_policy}
        disabled={isPublished}
        on:change={(e) => dispatch("mcpPolicyChange", { value: e.currentTarget.value })}
      >
        {#each MCP_POLICIES as policy (policy.value)}
          <option value={policy.value}>{policy.label}</option>
        {/each}
      </select>
    </Settings.Row>

    <Settings.Row
      title={m.flow_step_input_contract()}
      description={m.flow_step_input_contract_desc()}
    >
      <svelte:fragment slot="title">
        <Tooltip text={m.flow_step_input_contract_tooltip()}>
          <IconQuestionMark class="text-muted hover:text-primary ml-1.5" />
        </Tooltip>
      </svelte:fragment>
      {#if step.input_type !== "json" && step.input_type !== "text"}
        <Alert.Root class="mb-2 border-l-[3px] border-l-warning-default/40 bg-warning-dimmer/50 text-warning-stronger" role="status">
          <Alert.Description class="text-xs leading-relaxed text-warning-stronger">
            {m.flow_step_input_contract_inactive()}
          </Alert.Description>
        </Alert.Root>
      {:else}
        <Alert.Root class="mb-2 border-l-[3px] border-l-positive-default/40 bg-positive-dimmer/50 text-positive-stronger" role="status">
          <Alert.Description class="text-xs leading-relaxed text-positive-stronger">
            {m.flow_step_input_contract_active()}
          </Alert.Description>
        </Alert.Root>
      {/if}
      <textarea
        rows="4"
        class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 font-mono text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
        value={advancedJsonDrafts.input_contract}
        disabled={isPublished}
        on:input={(e) => dispatch("jsonFieldUpdate", { field: "input_contract", value: e.currentTarget.value })}
        placeholder={'{"type": "object", "properties": {...}}'}
      ></textarea>
      {#if advancedJsonErrors.input_contract}
        <p class="text-warning-stronger mt-1 text-xs" role="alert">
          {advancedJsonErrors.input_contract}
        </p>
      {/if}
    </Settings.Row>

    <Settings.Row
      title={m.flow_step_output_contract()}
      description={m.flow_step_output_contract_desc()}
    >
      <svelte:fragment slot="title">
        <Tooltip text={m.flow_step_output_contract_tooltip()}>
          <IconQuestionMark class="text-muted hover:text-primary ml-1.5" />
        </Tooltip>
      </svelte:fragment>
      {#if step.output_type !== "json"}
        <Alert.Root class="mb-2 border-l-[3px] border-l-warning-default/40 bg-warning-dimmer/50 text-warning-stronger" role="status">
          <Alert.Description class="text-xs leading-relaxed text-warning-stronger">
            {m.flow_step_output_contract_inactive()}
          </Alert.Description>
        </Alert.Root>
      {:else}
        <Alert.Root class="mb-2 border-l-[3px] border-l-positive-default/40 bg-positive-dimmer/50 text-positive-stronger" role="status">
          <Alert.Description class="text-xs leading-relaxed text-positive-stronger">
            {m.flow_step_output_contract_active()}
          </Alert.Description>
        </Alert.Root>
      {/if}
      <textarea
        rows="4"
        class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 font-mono text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
        value={advancedJsonDrafts.output_contract}
        disabled={isPublished}
        on:input={(e) =>
          dispatch("jsonFieldUpdate", { field: "output_contract", value: e.currentTarget.value })}
        placeholder={'{"type": "object", "properties": {...}}'}
      ></textarea>
      {#if advancedJsonErrors.output_contract}
        <p class="text-warning-stronger mt-1 text-xs" role="alert">
          {advancedJsonErrors.output_contract}
        </p>
      {/if}
    </Settings.Row>

    {#if step.input_source === "http_get" || step.input_source === "http_post"}
      <Settings.Row
        title={m.flow_step_input_config()}
        description={m.flow_step_input_config_desc()}
      >
        <textarea
          rows="4"
          class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 font-mono text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
          value={advancedJsonDrafts.input_config}
          disabled={isPublished}
          on:input={(e) => dispatch("jsonFieldUpdate", { field: "input_config", value: e.currentTarget.value })}
          placeholder={'{"url": "https://...", "headers": {...}}'}
        ></textarea>
        {#if advancedJsonErrors.input_config}
          <p class="text-warning-stronger mt-1 text-xs" role="alert">
            {advancedJsonErrors.input_config}
          </p>
        {/if}
      </Settings.Row>
    {/if}

    {#if step.output_mode === "http_post"}
      <Settings.Row
        title={m.flow_step_output_config()}
        description={m.flow_step_output_config_desc()}
      >
        <textarea
          rows="4"
          class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 font-mono text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
          value={advancedJsonDrafts.output_config}
          disabled={isPublished}
          on:input={(e) =>
            dispatch("jsonFieldUpdate", { field: "output_config", value: e.currentTarget.value })}
          placeholder={'{"url": "https://...", "headers": {...}}'}
        ></textarea>
        {#if advancedJsonErrors.output_config}
          <p class="text-warning-stronger mt-1 text-xs" role="alert">
            {advancedJsonErrors.output_config}
          </p>
        {/if}
      </Settings.Row>
    {/if}
  </Settings.Group>
</div>
