<script lang="ts">
  import type { FlowEdgeKind } from "$lib/features/flows/flowStepPresentation";
  import { IconLockClosed } from "@eneo/icons/lock-closed";
  import { IconXMark } from "@eneo/icons/x-mark";
  import { BaseEdge, EdgeLabel, getBezierPath, type Position } from "@xyflow/svelte";
  import { IconPlus } from "@eneo/icons/plus";
  import { m } from "$lib/paraglide/messages";

  let {
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    markerStart = undefined,
    markerEnd = undefined,
    data = undefined
  }: {
    id: string;
    sourceX: number;
    sourceY: number;
    targetX: number;
    targetY: number;
    sourcePosition: Position;
    targetPosition: Position;
    markerStart?: string | undefined;
    markerEnd?: string | undefined;
    data?:
      | {
          mode?: "user" | "power_user";
          readOnly?: boolean;
          dataType?: string;
          edgeKind?: FlowEdgeKind;
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
  } = $props();

  const bezier = $derived(
    getBezierPath({
      sourceX,
      sourceY,
      targetX,
      targetY,
      sourcePosition,
      targetPosition
    })
  );
  const edgePath = $derived(bezier[0]);
  const labelX = $derived(bezier[1]);
  const labelY = $derived(bezier[2]);
  const isPowerUser = $derived(data?.mode === "power_user");
  const isEscalation = $derived(Boolean(data?.classificationEscalation));
  const isViolation = $derived(Boolean(data?.classificationViolation));
  const labelOffsetY = $derived(data?.labelOffsetY ?? 0);
  const edgeColor = $derived(
    isViolation
      ? "var(--color-negative-default)"
      : isEscalation
        ? "var(--color-warning-default)"
        : undefined
  );
  const edgeKind = $derived(data?.edgeKind ?? "previous_step");
  const isDirectEdge = $derived(edgeKind !== "all_previous_steps");
  const edgeStyle = $derived(
    [
      edgeColor ? `stroke: ${edgeColor}` : null,
      !isDirectEdge ? "stroke-dasharray: 4 4; opacity: 0.6" : null
    ]
      .filter(Boolean)
      .join(";")
  );

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
        class="edge-actions text-xs"
        role="img"
        aria-label={isViolation
          ? m.flow_graph_classification_violation()
          : m.flow_graph_classification_escalation()}
        title={isViolation
          ? m.flow_graph_classification_violation()
          : m.flow_graph_classification_escalation()}
      >
        {#if isViolation}
          <IconXMark class="text-negative-stronger size-3.5" />
        {:else}
          <IconLockClosed class="text-warning-stronger size-3.5" />
        {/if}
      </span>
    </EdgeLabel>
  {/if}

  <EdgeLabel x={labelX} y={labelY + labelOffsetY}>
    <div
      class="edge-label-actions nodrag nopan text-secondary flex items-center gap-1 rounded-full px-1.5 py-0.5"
    >
      {#if data?.dataType && getDataTypeLabel(data.dataType)}
        <button
          class="hover:bg-hover-dimmer rounded px-1.5 py-0.5 text-xs font-medium"
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
          class="hover:bg-hover-dimmer rounded p-0.5"
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

  /* Hidden via opacity (not visibility) so the buttons stay keyboard
     focusable; focus-within then reveals them. */
  :global(.edge-label-actions) {
    opacity: 0;
    transition: opacity 150ms ease;
    pointer-events: none;
  }

  /* EdgeLabel portals its wrapper into the shared edge-labels layer, so the
     reveal must key off the portalled wrapper itself — an edge-scoped
     descendant selector never matches the real DOM. */
  :global(.svelte-flow__edge-label:hover) :global(.edge-label-actions),
  :global(.svelte-flow__edge-label:focus-within) :global(.edge-label-actions) {
    opacity: 1;
    pointer-events: auto;
    background: var(--background-color-primary);
    backdrop-filter: blur(4px);
  }

  /* The travelling dot is feedback, not decoration: it appears only while
     the pointer or keyboard focus is on the edge, so the graph stays calm. */
  :global(.flow-dot) {
    fill: var(--border-stronger);
    opacity: 0;
    transition: opacity 150ms ease;
  }

  :global(.svelte-flow__edge:hover) :global(.flow-dot),
  :global(.svelte-flow__edge:focus-within) :global(.flow-dot) {
    opacity: 0.8;
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
