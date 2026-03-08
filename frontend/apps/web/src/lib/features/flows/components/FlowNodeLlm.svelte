<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import { Handle, Position } from "@xyflow/svelte";
  import { m } from "$lib/paraglide/messages";
  import { getDownstreamKindForOutput } from "$lib/features/flows/flowStepPresentation";

  export let data: {
    label: string;
    step: Pick<
      FlowStep,
      | "step_order"
      | "input_type"
      | "output_type"
      | "output_mode"
      | "mcp_policy"
      | "output_classification_override"
    >;
    isActive: boolean;
    mode: "user" | "power_user";
    runStatus?: string;
    numTokensInput?: number;
    numTokensOutput?: number;
    modelName?: string;
    classLevel?: number | null;
    assistantClassLevel?: number | null;
  };

  $: isPowerUser = data.mode === "power_user";
  $: isAssembly = data.step.output_mode === "template_fill";
  $: nextChannelLabel = isAssembly
    ? m.flow_template_fill_card_badge()
    : getDownstreamKindForOutput(data.step.output_type as FlowStep["output_type"]) ===
        "text_and_structured"
      ? m.flow_step_summary_next_channel_text_and_structured_short()
      : m.flow_step_summary_next_channel_text_short();
  $: inputTypeLabel = (() => {
    switch (data.step.input_type) {
      case "json":
        return m.flow_type_json();
      case "document":
        return m.flow_type_document();
      case "file":
        return m.flow_type_file();
      case "audio":
        return m.flow_type_audio();
      case "any":
        return m.flow_type_any();
      case "text":
      default:
        return m.flow_type_text();
    }
  })();
  $: outputTypeLabel = (() => {
    switch (data.step.output_type) {
      case "json":
        return m.flow_output_type_json();
      case "pdf":
        return m.flow_output_type_pdf();
      case "docx":
        return m.flow_output_type_docx();
      case "text":
      default:
        return m.flow_output_type_text();
    }
  })();

  $: borderColor = data.runStatus
    ? data.runStatus === "completed"
      ? "border-positive-default"
      : data.runStatus === "failed"
        ? "border-negative-default"
        : data.runStatus === "running"
          ? "border-accent-default"
          : "border-default"
    : data.isActive
      ? "border-accent-default"
      : "border-default";
  $: surfaceClass = isAssembly ? "bg-warning-dimmer/25" : "bg-primary";
  $: headerClass = isAssembly ? "bg-warning-dimmer/50" : "bg-hover-dimmer";
</script>

{#if isPowerUser}
  <!-- Power User: Technical card -->
  <div
    class="{surfaceClass} rounded-lg border-2 shadow-sm transition-colors {borderColor}"
    style="width: 300px;"
  >
    <div class="{headerClass} flex items-center justify-between px-3 py-1.5">
      <div class="min-w-0 flex items-center gap-2">
        <span
          class="bg-hover-default flex size-5 shrink-0 items-center justify-center rounded text-xs font-bold"
        >
          {data.step.step_order}
        </span>
        <span class="truncate text-sm font-semibold">{data.label}</span>
        {#if isAssembly}
          <span
            class="bg-warning-dimmer text-warning-stronger rounded px-1.5 text-[10px] font-bold"
          >
            DOCX
          </span>
        {/if}
      </div>
      <div class="flex items-center gap-1">
        {#if data.assistantClassLevel != null}
          <span class="bg-accent-dimmer text-accent-stronger rounded px-1.5 text-[10px] font-bold">
            Model K{data.assistantClassLevel}
          </span>
        {/if}
        {#if data.classLevel != null && data.classLevel !== data.assistantClassLevel}
          <span
            class="rounded px-1.5 text-[10px] font-bold
            {data.classLevel >= 3
              ? 'bg-negative-dimmer text-negative-stronger'
              : data.classLevel >= 2
                ? 'bg-warning-dimmer text-warning-stronger'
                : 'bg-positive-dimmer text-positive-stronger'}"
          >
            Output K{data.classLevel}
          </span>
        {/if}
      </div>
    </div>
    <div class="space-y-1 px-3 py-2 text-xs">
      {#if data.modelName}
        <div class="text-secondary">{data.modelName}</div>
      {/if}
      <div class="flex flex-wrap items-center gap-1">
        <span class="bg-hover-dimmer rounded px-1.5">
          {m.flow_step_card_input_short()}: {inputTypeLabel}
        </span>
        <span class="bg-positive-dimmer text-positive-stronger rounded px-1.5">
          {m.flow_step_card_output_short()}: {outputTypeLabel}
        </span>
        <span
          class="{isAssembly
            ? 'bg-warning-dimmer text-warning-stronger'
            : 'bg-accent-dimmer text-accent-stronger'} rounded px-1.5"
        >
          {m.flow_step_card_chain_short()}: {nextChannelLabel}
        </span>
      </div>
      {#if data.step.mcp_policy === "restricted"}
        <div class="text-warning-stronger flex items-center gap-1">
          {m.flow_step_mcp_policy()}: {m.flow_mcp_policy_restricted()}
        </div>
      {/if}
      {#if data.runStatus && (data.numTokensInput || data.numTokensOutput)}
        <div class="text-secondary">
          {data.numTokensInput ?? 0} / {data.numTokensOutput ?? 0} tokens
        </div>
      {/if}
    </div>
  </div>
{:else}
  <!-- User Mode: Compact pill -->
  <div
    class="bg-primary flex items-center gap-2 rounded-lg border-2 px-3 py-1.5 shadow-sm transition-colors {borderColor}"
    style="min-width: 120px; max-width: 160px;"
  >
    <span
      class="bg-hover-default flex size-5 shrink-0 items-center justify-center rounded text-xs font-bold"
    >
      {data.step.step_order}
    </span>
    <span class="truncate text-xs font-medium">{data.label}</span>
  </div>
{/if}

<Handle type="target" position={Position.Left} />
<Handle type="source" position={Position.Right} />
