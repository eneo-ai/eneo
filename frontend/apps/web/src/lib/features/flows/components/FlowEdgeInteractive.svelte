<script lang="ts">
  import {
    BaseEdge,
    EdgeLabel,
    getSmoothStepPath,
    type Position
  } from "@xyflow/svelte";
  import { IconPlus } from "@intric/icons/plus";
  import { m } from "$lib/paraglide/messages";

  export let id: string;
  export let sourceX: number;
  export let sourceY: number;
  export let targetX: number;
  export let targetY: number;
  export let sourcePosition: Position;
  export let targetPosition: Position;
  export let markerStart: string | undefined;
  export let markerEnd: string | undefined;
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
    | undefined;

  $: [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 8
  });
  $: isPowerUser = data?.mode === "power_user";
  $: isEscalation = Boolean(data?.classificationEscalation);
  $: isViolation = Boolean(data?.classificationViolation);
  $: labelOffsetY = data?.labelOffsetY ?? 0;
  $: edgeColor = isViolation
    ? "var(--color-error, #dc2626)"
    : isEscalation
      ? "var(--color-warning, #d97706)"
      : undefined;
  $: edgeKind = data?.edgeKind ?? "previous_step";
  $: edgeStyle = [
    edgeColor ? `stroke: ${edgeColor}` : null,
    edgeKind === "all_previous_steps" ? "stroke-dasharray: 4 4; opacity: 0.6" : null,
    data?.animate ? "stroke-dasharray: 6 6; animation: flow-edge-dash 1.1s linear infinite" : null
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
</script>

<BaseEdge
  {id}
  path={edgePath}
  {markerStart}
  {markerEnd}
  style={edgeStyle || undefined}
/>

{#if isPowerUser}
  <EdgeLabel x={labelX} y={labelY + labelOffsetY}>
    <div class="edge-actions group nodrag nopan flex items-center gap-1 rounded-full bg-white/70 px-1.5 py-0.5 text-secondary backdrop-blur-sm dark:bg-gray-900/70">
      {#if isEscalation || isViolation}
        <span class="text-[11px]" title={isViolation ? m.flow_graph_classification_violation() : m.flow_graph_classification_escalation()}>
          {#if isViolation}⛔{:else}🔒{/if}
        </span>
      {/if}

      {#if data?.dataType}
        <button
          class="rounded px-1.5 py-0.5 text-[10px] font-medium hover:bg-black/5 dark:hover:bg-white/10"
          on:click|stopPropagation={inspectEdge}
          aria-label={m.flow_graph_inspect_edge()}
        >
          {data.dataType}
        </button>
      {/if}

      {#if !data?.readOnly && data?.allowInsert !== false}
        <button
          class="rounded p-0.5 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-black/5 dark:hover:bg-white/10"
          on:click|stopPropagation={insertStep}
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

  @keyframes flow-edge-dash {
    to {
      stroke-dashoffset: -12;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    :global(.edge-actions *) {
      animation: none !important;
      transition: none !important;
    }
  }
</style>
