<script lang="ts">
  import type { FlowStep } from "@eneo/eneo-js";
  import { Handle, Position } from "@xyflow/svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import { m } from "$lib/paraglide/messages";
  import { getDownstreamKindForOutput } from "$lib/features/flows/flowStepPresentation";
  import type { FlowStepMcpSummary } from "$lib/features/flows/flowStepMcpConfig";

  let {
    data
  }: {
    data: {
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
      direction?: "LR" | "TB";
      runStatus?: string;
      numTokensInput?: number;
      numTokensOutput?: number;
      modelName?: string;
      classLevel?: number | null;
      assistantClassLevel?: number | null;
      mcpSummary?: FlowStepMcpSummary | null;
    };
  } = $props();

  const isPowerUser = $derived(data.mode === "power_user");
  const isAssembly = $derived(data.step.output_mode === "template_fill");
  const nextChannelLabel = $derived(
    isAssembly
      ? m.flow_template_fill_card_badge()
      : getDownstreamKindForOutput(data.step.output_type as FlowStep["output_type"]) ===
          "text_and_structured"
        ? m.flow_step_summary_next_channel_text_and_structured_short()
        : m.flow_step_summary_next_channel_text_short()
  );
  const inputTypeLabel = $derived.by(() => {
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
  });
  const outputTypeLabel = $derived.by(() => {
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
  });

  const borderColor = $derived(
    data.runStatus
      ? data.runStatus === "completed"
        ? "border-positive-default"
        : data.runStatus === "failed"
          ? "border-negative-default"
          : data.runStatus === "running"
            ? "border-accent-default"
            : "border-default"
      : data.isActive
        ? "border-accent-default"
        : "border-default"
  );
  const surfaceClass = $derived(isAssembly ? "bg-warning-dimmer/25" : "bg-primary");
  const headerClass = $derived(isAssembly ? "bg-warning-dimmer/50" : "bg-hover-dimmer");
</script>

{#if isPowerUser}
  <!-- Power User: Technical card -->
  <Card.Root
    class="{surfaceClass} border-2 py-0 shadow-sm transition-colors {borderColor}"
    style="width: 300px;"
  >
    <Card.Header class="{headerClass} flex-row items-center justify-between gap-2 px-3 py-1.5">
      <div class="flex min-w-0 items-center gap-2">
        <span
          class="bg-hover-default flex size-5 shrink-0 items-center justify-center rounded text-xs font-bold"
        >
          {data.step.step_order}
        </span>
        <span class="truncate text-sm font-semibold">{data.label}</span>
        {#if isAssembly}
          <Badge
            variant="secondary"
            class="bg-warning-dimmer text-warning-stronger text-xs font-bold"
          >
            {m.flow_node_assembly_format_badge()}
          </Badge>
        {/if}
      </div>
      <div class="flex items-center gap-1">
        {#if data.assistantClassLevel != null}
          <Badge
            variant="secondary"
            class="bg-accent-dimmer text-accent-stronger text-xs font-bold"
          >
            {m.flow_node_model_class_badge({ level: String(data.assistantClassLevel) })}
          </Badge>
        {/if}
        {#if data.classLevel != null && data.classLevel !== data.assistantClassLevel}
          <Badge
            variant="secondary"
            class="text-xs font-bold
            {data.classLevel >= 3
              ? 'bg-negative-dimmer text-negative-stronger'
              : data.classLevel >= 2
                ? 'bg-warning-dimmer text-warning-stronger'
                : 'bg-positive-dimmer text-positive-stronger'}"
          >
            {m.flow_node_output_class_badge({ level: String(data.classLevel) })}
          </Badge>
        {/if}
      </div>
    </Card.Header>
    <Card.Content class="space-y-1 px-3 py-2 text-xs">
      {#if data.modelName}
        <div class="text-secondary">{data.modelName}</div>
      {/if}
      <div class="flex flex-wrap items-center gap-1">
        <Badge variant="secondary" class="bg-hover-dimmer text-primary text-xs">
          {m.flow_step_card_input_short()}: {inputTypeLabel}
        </Badge>
        <Badge variant="secondary" class="bg-positive-dimmer text-positive-stronger text-xs">
          {m.flow_step_card_output_short()}: {outputTypeLabel}
        </Badge>
        <Badge
          variant="secondary"
          class="text-xs {isAssembly
            ? 'bg-warning-dimmer text-warning-stronger'
            : 'bg-accent-dimmer text-accent-stronger'}"
        >
          {m.flow_step_card_chain_short()}: {nextChannelLabel}
        </Badge>
      </div>
      {#if data.mcpSummary?.hasActiveMcp}
        <div class="text-warning-stronger flex items-center gap-1">
          {m.flow_step_mcp_tools_badge({ count: String(data.mcpSummary.enabledToolCount) })}
        </div>
      {/if}
      {#if data.runStatus && (data.numTokensInput || data.numTokensOutput)}
        <div class="text-secondary">
          {m.flow_node_token_usage({
            input: String(data.numTokensInput ?? 0),
            output: String(data.numTokensOutput ?? 0)
          })}
        </div>
      {/if}
    </Card.Content>
  </Card.Root>
{:else}
  <!-- User Mode: Compact pill -->
  <Card.Root
    class="bg-primary flex-row items-center gap-2 border-2 px-3 py-1.5 shadow-sm transition-colors {borderColor}"
    style="min-width: 120px; max-width: {data.direction === 'TB' ? '260px' : '160px'};"
  >
    <span
      class="bg-hover-default flex size-5 shrink-0 items-center justify-center rounded text-xs font-bold"
    >
      {data.step.step_order}
    </span>
    <span class="truncate text-xs font-medium">{data.label}</span>
  </Card.Root>
{/if}

<Handle type="target" position={data.direction === "TB" ? Position.Top : Position.Left} />
<Handle type="source" position={data.direction === "TB" ? Position.Bottom : Position.Right} />
