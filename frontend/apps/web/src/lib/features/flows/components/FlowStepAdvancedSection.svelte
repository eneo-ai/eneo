<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep } from "@intric/intric-js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { IconQuestionMark } from "@intric/icons/question-mark";
  import { slide } from "svelte/transition";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { MCP_POLICIES } from "./flowStepEditHelpers";
  import type { AdvancedJsonDrafts, AdvancedJsonErrors } from "./advancedJsonDrafts";

  let {
    step,
    isPublished,
    advancedJsonDrafts,
    advancedJsonErrors,
    onMcpPolicyChange,
    onJsonFieldUpdate
  }: {
    step: FlowStep;
    isPublished: boolean;
    advancedJsonDrafts: AdvancedJsonDrafts;
    advancedJsonErrors: AdvancedJsonErrors;
    onMcpPolicyChange?: (detail: { value: string }) => void;
    onJsonFieldUpdate?: (detail: { field: string; value: string }) => void;
  } = $props();
</script>

<div transition:slide={{ duration: 200 }}>
  <Settings.Group title={m.flow_step_advanced()}>
    <Settings.Row title={m.flow_step_mcp_policy()} description="">
      <svelte:fragment slot="title">
        <Tooltip.Provider delayDuration={150}>
          <Tooltip.Root>
            <Tooltip.Trigger>
              <IconQuestionMark class="text-muted hover:text-primary ml-1.5" />
            </Tooltip.Trigger>
            <Tooltip.Content>{m.flow_step_mcp_policy_tooltip()}</Tooltip.Content>
          </Tooltip.Root>
        </Tooltip.Provider>
      </svelte:fragment>
      <select
        class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
        value={step.mcp_policy}
        disabled={isPublished}
        onchange={(e) => onMcpPolicyChange?.({ value: e.currentTarget.value })}
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
      <textarea
        rows="4"
        class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 font-mono text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
        value={advancedJsonDrafts.input_contract}
        disabled={isPublished}
        oninput={(e) =>
          onJsonFieldUpdate?.({ field: "input_contract", value: e.currentTarget.value })}
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
      <textarea
        rows="4"
        class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 font-mono text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
        value={advancedJsonDrafts.output_contract}
        disabled={isPublished}
        oninput={(e) =>
          onJsonFieldUpdate?.({ field: "output_contract", value: e.currentTarget.value })}
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
          class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 font-mono text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
          value={advancedJsonDrafts.input_config}
          disabled={isPublished}
          oninput={(e) =>
            onJsonFieldUpdate?.({ field: "input_config", value: e.currentTarget.value })}
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
          class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 font-mono text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
          value={advancedJsonDrafts.output_config}
          disabled={isPublished}
          oninput={(e) =>
            onJsonFieldUpdate?.({ field: "output_config", value: e.currentTarget.value })}
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
