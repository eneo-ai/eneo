<script lang="ts">
  import type { FlowStep } from "@eneo/eneo-js";
  import { Handle, Position } from "@xyflow/svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import { m } from "$lib/paraglide/messages";
  import { getDownstreamKindForOutput } from "$lib/features/flows/flowStepPresentation";
  import { outputModeUsesCompletionModel } from "$lib/features/flows/flowStepTypes";
  import type { SecurityClassStanding } from "$lib/features/flows/flowClassificationNames";
  import UserCheck from "@lucide/svelte/icons/user-check";
  import { cn } from "$lib/utils.js";

  let {
    data
  }: {
    data: {
      label: string;
      step: Pick<
        FlowStep,
        | "step_order"
        | "input_source"
        | "input_type"
        | "output_type"
        | "output_mode"
        | "output_classification_override"
        | "review_policy"
      >;
      isActive: boolean;
      mode: "user" | "power_user";
      /** Distance from the top of the node to its row handles, shared by every step. */
      handleY: number;
      dimmed?: boolean;
      lifted?: boolean;
      modelName?: string;
      classLevel?: number | null;
      assistantClassLevel?: number | null;
      /** The organisation's names for the two levels, and where the result's stands among its classes. */
      className?: string | null;
      assistantClassName?: string | null;
      classStanding?: SecurityClassStanding | null;
    };
  } = $props();

  // The result's class is toned by where it stands among the organisation's
  // classes, never by a fixed level.
  const CLASS_TONE: Record<SecurityClassStanding, string> = {
    highest: "bg-negative-dimmer text-negative-stronger",
    between: "bg-warning-dimmer text-warning-stronger",
    lowest: "bg-positive-dimmer text-positive-stronger"
  };

  const isPowerUser = $derived(data.mode === "power_user");
  const isAssembly = $derived(data.step.output_mode === "template_fill");
  // A step that calls no completion model has no model whose name or class to show.
  const callsModel = $derived(outputModeUsesCompletionModel(data.step.output_mode));
  const hasHumanReview = $derived(data.step.review_policy != null);
  // A step that only passes its JSON on says so where the model would be named,
  // and its input type is the output type, so no In chip.
  const copiesInput = $derived(data.step.output_mode === "copy_input");
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

  const borderColor = $derived(data.isActive ? "border-accent-default" : "border-default");
  const surfaceClass = $derived(isAssembly ? "bg-warning-dimmer/25" : "bg-primary");
  const headerClass = $derived(isAssembly ? "bg-warning-dimmer/50" : "bg-hover-dimmer");
</script>

{#if isPowerUser}
  <!-- Power User: Technical card -->
  <Card.Root
    class={cn(
      "flow-node border-2 py-0",
      surfaceClass,
      borderColor,
      data.dimmed && "is-dimmed",
      data.lifted && "is-lifted"
    )}
    style="width: 300px;"
  >
    <Card.Header class="{headerClass} flex-row items-start justify-between gap-2 px-3 py-1.5">
      <div class="flex min-w-0 items-start gap-2">
        <span
          class="bg-hover-default mt-px flex size-5 shrink-0 items-center justify-center rounded text-xs font-bold"
        >
          {data.step.step_order}
        </span>
        <span class="flow-node-name text-sm font-semibold" title={data.label}>{data.label}</span>
      </div>
      <div class="flex items-center gap-1">
        {#if callsModel && data.assistantClassLevel != null}
          <Badge
            variant="secondary"
            class="bg-accent-dimmer text-accent-stronger text-xs font-bold"
          >
            {m.flow_node_model_class_badge({ name: data.assistantClassName ?? "" })}
          </Badge>
        {/if}
        {#if data.classLevel != null && (!callsModel || data.classLevel !== data.assistantClassLevel)}
          <Badge
            variant="secondary"
            class={["text-xs font-bold", data.classStanding && CLASS_TONE[data.classStanding]]}
          >
            {m.flow_node_output_class_badge({ name: data.className ?? "" })}
          </Badge>
        {/if}
      </div>
    </Card.Header>
    <Card.Content class="space-y-1 px-3 py-2 text-xs">
      {#if copiesInput}
        <Badge variant="secondary" class="bg-positive-dimmer text-positive-stronger text-xs">
          {data.step.input_source === "tool"
            ? m.flow_graph_copy_input_tool_badge()
            : m.flow_graph_copy_input_badge()}
        </Badge>
      {:else if callsModel && data.modelName}
        <div class="text-secondary">{data.modelName}</div>
      {/if}
      <div class="flex flex-wrap items-center gap-1">
        {#if isAssembly}
          <Badge
            variant="secondary"
            class="bg-warning-dimmer text-warning-stronger text-xs font-bold"
          >
            {m.flow_node_assembly_format_badge()}
          </Badge>
        {/if}
        {#if hasHumanReview}
          <Badge variant="secondary" class="bg-hover-dimmer text-primary text-xs">
            <UserCheck aria-hidden="true" />
            {m.flow_graph_review_badge()}
          </Badge>
        {/if}
        {#if !copiesInput}
          <Badge variant="secondary" class="bg-hover-dimmer text-primary text-xs">
            {m.flow_step_card_input_short()}: {inputTypeLabel}
          </Badge>
        {/if}
        <Badge variant="secondary" class="bg-hover-dimmer text-primary text-xs">
          {m.flow_step_card_output_short()}: {outputTypeLabel}
        </Badge>
        <Badge
          variant="secondary"
          class="text-xs {isAssembly
            ? 'bg-warning-dimmer text-warning-stronger'
            : 'bg-hover-dimmer text-primary'}"
        >
          {m.flow_step_card_chain_short()}: {nextChannelLabel}
        </Badge>
      </div>
    </Card.Content>
  </Card.Root>
{:else}
  <!-- User Mode: Compact pill -->
  <Card.Root
    class={cn(
      "bg-primary flow-node flex-row items-center gap-2 border-2 px-3 py-1.5",
      borderColor,
      data.dimmed && "is-dimmed",
      data.lifted && "is-lifted"
    )}
    style="width: 200px; height: 48px;"
  >
    <span
      class="bg-hover-default flex size-5 shrink-0 items-center justify-center rounded text-xs font-bold"
    >
      {data.step.step_order}
    </span>
    <span class="flow-node-name min-w-0 text-xs font-medium" title={data.label}>{data.label}</span>
    {#if hasHumanReview}
      <span
        class="text-secondary shrink-0"
        role="img"
        aria-label={m.flow_graph_review_badge()}
        title={m.flow_graph_review_badge()}
      >
        <UserCheck class="size-3.5" />
      </span>
    {/if}
  </Card.Root>
{/if}

<!-- Steps read along one line, so every step's row handles share one height;
     a source above a step hands down into its top. -->
<Handle type="target" id="left" position={Position.Left} style="top: {data.handleY}px" />
<Handle type="target" id="top" position={Position.Top} />
<Handle type="source" position={Position.Right} style="top: {data.handleY}px" />

<style>
  /* Two lines of name before the ellipsis: a step called "11. Mellanmänskliga
     interaktioner och relationer" says nothing in fourteen characters. */
  .flow-node-name {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    overflow: hidden;
    overflow-wrap: anywhere;
  }
</style>
