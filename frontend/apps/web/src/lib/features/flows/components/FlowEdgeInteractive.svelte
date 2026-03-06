<script lang="ts">
  import { BaseEdge, EdgeLabel, getBezierPath, type Position } from "@xyflow/svelte";
  import { IconPlus } from "@intric/icons/plus";
  import { m } from "$lib/paraglide/messages";

  export let id: string;
  export let sourceX: number;
  export let sourceY: number;
  export let targetX: number;
  export let targetY: number;
  export let sourcePosition: Position;
  export let targetPosition: Position;
  export let markerStart: string | undefined = undefined;
  export let markerEnd: string | undefined = undefined;
  export let data:
    | {
        mode?: "user" | "power_user";
        readOnly?: boolean;
        dataType?: string;
        edgeKind?: "flow_input" | "previous_step" | "all_previous_steps" | "flow_output";
        animate?: boolean;
        allowInsert?: boolean;
        labelOffsetY?: number;
        sourceStepOrder?: number;
        sourceLabel?: string;
        targetLabel?: string;
        payload?: Record<string, unknown> | null;
        classificationEscalation?: boolean;
        classificationViolation?: boolean;
        onInsert?: (sourceStepOrder: number) => Promise<void> | void;
        onInspect?: (params: {
          sourceStepOrder: number;
          sourceLabel: string;
          targetLabel: string;
          payload: Record<string, unknown> | null;
        }) => void;
      }
    | undefined = undefined;

  $: [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition
  });
  $: isPowerUser = data?.mode === "power_user";
  $: isEscalation = Boolean(data?.classificationEscalation);
  $: isViolation = Boolean(data?.classificationViolation);
  $: labelOffsetY = data?.labelOffsetY ?? 0;
  $: edgeColor = isViolation
    ? "var(--color-negative-default)"
    : isEscalation
      ? "var(--color-warning-default)"
      : undefined;
  $: edgeKind = data?.edgeKind ?? "previous_step";
  $: isDirectEdge = edgeKind !== "all_previous_steps";
  $: edgeStyle = [
    edgeColor ? `stroke: ${edgeColor}` : null,
    !isDirectEdge ? "stroke-dasharray: 4 4; opacity: 0.6" : null
  ]
    .filter(Boolean)
    .join(";");

  function inspectEdge() {
    if (!data?.onInspect) return;
    data.onInspect({
      sourceStepOrder: data.sourceStepOrder ?? 0,
      sourceLabel: data.sourceLabel ?? "Input",
      targetLabel: data.targetLabel ?? "Output",
      payload: data.payload ?? null
    });
  }

  function insertStep() {
    if (!data?.onInsert) return;
    if (data.readOnly) return;
    void data.onInsert(data.sourceStepOrder ?? 0);
  }

  function getDataTypeLabel(dataType: string): string | null {
    switch (dataType) {
      case "flow_input":
        return m.flow_graph_edge_flow_input();
      case "structured":
        return m.flow_graph_edge_structured();
      case "text":
        return m.flow_graph_edge_text();
      default:
        return null;
    }
  }
</script>

<BaseEdge {id} path={edgePath} {markerStart} {markerEnd} style={edgeStyle || undefined} />

{#if isDirectEdge}
  <circle r="3" class="flow-dot">
    <animateMotion dur="2s" repeatCount="indefinite" path={edgePath} />
  </circle>
{/if}

{#if isPowerUser}
  {#if isEscalation || isViolation}
    <EdgeLabel x={labelX} y={labelY + labelOffsetY - 14}>
      <span
        class="edge-actions text-[11px]"
        title={isViolation
          ? m.flow_graph_classification_violation()
          : m.flow_graph_classification_escalation()}
      >
        {#if isViolation}⛔{:else}🔒{/if}
      </span>
    </EdgeLabel>
  {/if}

  <EdgeLabel x={labelX} y={labelY + labelOffsetY}>
    <div
      class="edge-label-actions nodrag nopan text-secondary flex items-center gap-1 rounded-full px-1.5 py-0.5"
    >
      {#if data?.dataType && getDataTypeLabel(data.dataType)}
        <button
          class="rounded px-1.5 py-0.5 text-[10px] font-medium hover:bg-black/5 dark:hover:bg-white/10"
          onclick={(event) => {
            event.stopPropagation();
            inspectEdge();
          }}
          aria-label={m.flow_graph_inspect_edge()}
        >
          {getDataTypeLabel(data.dataType)}
        </button>
      {/if}

      {#if !data?.readOnly && data?.allowInsert !== false}
        <button
          class="rounded p-0.5 hover:bg-black/5 dark:hover:bg-white/10"
          onclick={(event) => {
            event.stopPropagation();
            insertStep();
          }}
          aria-label={m.flow_graph_insert_step_after({ order: String(data?.sourceStepOrder ?? 0) })}
        >
          <IconPlus size="sm" />
        </button>
      {/if}
    </div>
  </EdgeLabel>
{/if}

<style>
  .edge-actions {
    transform: translate(-50%, -50%);
  }

  :global(.edge-label-actions) {
    visibility: hidden;
    opacity: 0;
    transition: opacity 150ms ease, visibility 150ms ease;
    pointer-events: none;
  }

  :global(.svelte-flow__edge:hover) :global(.edge-label-actions) {
    visibility: visible;
    opacity: 1;
    pointer-events: auto;
    background: var(--background-color-primary);
    backdrop-filter: blur(4px);
  }

  :global(.flow-dot) {
    fill: #b1b1b7;
    opacity: 0.8;
  }

  :global(.dark .flow-dot) {
    fill: #6b6b73;
  }

  @media (prefers-reduced-motion: reduce) {
    :global(.flow-dot) {
      display: none;
    }
    :global(.edge-actions *) {
      animation: none !important;
      transition: none !important;
    }
  }
</style>
