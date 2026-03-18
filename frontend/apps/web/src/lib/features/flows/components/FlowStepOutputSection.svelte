<svelte:options runes={false} />

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep } from "@intric/intric-js";
  import { Button } from "@intric/ui";
  import { createEventDispatcher } from "svelte";
  import { getOutputHintText } from "./flowStepEditHelpers";
  import HttpConfigPanel from "./http/HttpConfigPanel.svelte";
  import type { HttpAuthoredConfig } from "./http/httpConfigTypes";
  import { createDefaultHttpConfig } from "./http/httpConfigDefaults";

  export let step: FlowStep;
  export let isPublished: boolean;
  export let isAdvancedMode: boolean;
  export let availableOutputTypes: Array<{ value: string; label: string }>;
  export let availableOutputModes: Array<{ value: string; label: string }>;
  export let flowId: string = "";
  import type { FlowOutputHintKind } from "$lib/features/flows/flowStepPresentation";

  export let outputHintKind: FlowOutputHintKind | null;

  const dispatch = createEventDispatcher<{
    outputTypeChange: { value: string };
    outputModeChange: { value: string };
    webhookUrlChange: { value: string };
    httpConfigChange: { config: HttpAuthoredConfig };
    switchToTemplateFill: void;
  }>();

  $: httpConfig = step.output_mode === "http_post" && step.output_config?.auth
    ? (step.output_config as unknown as HttpAuthoredConfig)
    : createDefaultHttpConfig("output", "POST");
</script>

<Settings.Group title={m.flow_step_output_section()}>
  <Settings.Row
    title={m.flow_step_output_type()}
    description={m.flow_step_output_format_desc()}
  >
    <div class="flex flex-col gap-2">
      <select
        class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
        value={step.output_type}
        disabled={isPublished}
        on:change={(e) => dispatch("outputTypeChange", { value: e.currentTarget.value })}
      >
        {#each availableOutputTypes as t (t.value)}
          <option value={t.value}>{t.label}</option>
        {/each}
      </select>
      {#if getOutputHintText(step.output_mode, outputHintKind)}
        <p class="text-muted text-xs leading-relaxed" aria-live="polite">
          {getOutputHintText(step.output_mode, outputHintKind)}
        </p>
      {/if}
    </div>
  </Settings.Row>

  {#if isAdvancedMode && step.output_type === "docx"}
    <div
      class="border-accent-default/20 bg-accent-dimmer/30 mb-4 rounded-xl border px-4 py-3"
    >
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div class="space-y-1">
          <p class="text-accent-stronger text-sm font-medium">
            {m.flow_template_fill_title()}
          </p>
          <p class="text-accent-stronger/80 text-xs leading-relaxed">
            {m.flow_template_fill_summary()}
          </p>
        </div>
        <Button
          variant="outlined"
          size="small"
          disabled={isPublished}
          on:click={() => dispatch("switchToTemplateFill")}
        >
          {m.flow_output_mode_template_fill()}
        </Button>
      </div>
    </div>
  {/if}

  <Settings.Row title={m.flow_step_output_mode()} description="">
    <select
      class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
      value={step.output_mode}
      disabled={isPublished}
      on:change={(e) => dispatch("outputModeChange", { value: e.currentTarget.value })}
    >
      {#each availableOutputModes as mode (mode.value)}
        <option value={mode.value}>{mode.label}</option>
      {/each}
    </select>
  </Settings.Row>

  {#if step.output_mode === "http_post"}
    <!-- Legacy URL-only fallback for configs without authored format -->
    {#if step.output_config && !step.output_config.auth}
      <Settings.Row title={m.flow_step_webhook_url()} description="">
        <input
          class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
          value={step.output_config?.url ?? ""}
          disabled={isPublished}
          on:input={(e) => dispatch("webhookUrlChange", { value: e.currentTarget.value })}
          placeholder="https://..."
        />
      </Settings.Row>
    {/if}
  {/if}
</Settings.Group>

{#if step.output_mode === "http_post" && (step.output_config?.auth || !step.output_config?.url)}
  <HttpConfigPanel
    config={httpConfig}
    direction="output"
    method="POST"
    {isPublished}
    {flowId}
    on:configChange={(e) => dispatch("httpConfigChange", { config: e.detail.config })}
  />
{/if}
