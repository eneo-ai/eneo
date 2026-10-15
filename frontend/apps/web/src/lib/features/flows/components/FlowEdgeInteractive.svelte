<script lang="ts">
  import type { FlowEdgeKind } from "$lib/features/flows/flowStepPresentation";
  import {
    flowGraphEdgePoints,
    roundedOrthogonalPath,
    type FlowGraphEdgeRoute
  } from "$lib/features/flows/flowGraphLayout";
  import { IconLockClosed } from "@eneo/icons/lock-closed";
  import { IconXMark } from "@eneo/icons/x-mark";
  import { BaseEdge, EdgeLabel } from "@xyflow/svelte";
  import { IconPlus } from "@eneo/icons/plus";
  import { cn } from "$lib/utils.js";
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";

  let {
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    markerStart = undefined,
    markerEnd = undefined,
    data = undefined
  }: {
    id: string;
    sourceX: number;
    sourceY: number;
    targetX: number;
    targetY: number;
    markerStart?: string | undefined;
    markerEnd?: string | undefined;
    data?:
      | {
          mode?: "user" | "power_user";
          readOnly?: boolean;
          dataType?: string;
          edgeKind?: FlowEdgeKind;
          route?: FlowGraphEdgeRoute;
          /** What a binding edge carries into its tool argument. */
          argumentLabel?: string;
          allowInsert?: boolean;
          sourceStepOrder?: number;
          sourceLabel?: string;
          targetLabel?: string;
          payload?: Record<string, unknown> | null;
          classificationEscalation?: boolean;
          classificationViolation?: boolean;
          onPath?: boolean;
          dimmed?: boolean;
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

  const route = $derived(data?.route ?? { kind: "direct" as const });
  const drawn = $derived.by(() => {
    const path = roundedOrthogonalPath(
      flowGraphEdgePoints(route, { x: sourceX, y: sourceY }, { x: targetX, y: targetY }),
      8
    );
    // Bindings into one tool share their climb; each is named where it turns
    // into its own argument row, so the names stack instead of overlapping.
    return (route.kind === "rise" || route.kind === "feed") && data?.edgeKind === "tool_argument"
      ? { ...path, labelX: route.targetGapX, labelY: targetY }
      : path;
  });
  const isPowerUser = $derived(data?.mode === "power_user");
  const isEscalation = $derived(Boolean(data?.classificationEscalation));
  const isViolation = $derived(Boolean(data?.classificationViolation));
  const edgeKind = $derived(data?.edgeKind ?? "previous_step");
  const isBinding = $derived(edgeKind === "tool_argument");
  const edgeColor = $derived(
    isViolation
      ? "var(--color-negative-default)"
      : isEscalation
        ? "var(--color-warning-default)"
        : isBinding
          ? "var(--color-accent-default)"
          : undefined
  );
  const edgeStyle = $derived(edgeColor ? `stroke: ${edgeColor}` : undefined);

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
      // Structured data travels as JSON, the name the step cards use for it.
      case "structured":
        return m.flow_type_json();
      case "text":
        return m.flow_graph_edge_text();
      default:
        return null;
    }
  }
  const dataTypeLabel = $derived(data?.dataType ? getDataTypeLabel(data.dataType) : null);
  const showInsert = $derived(!data?.readOnly && data?.allowInsert !== false);
</script>

<g
  class={[
    "flow-edge-group",
    isBinding && "is-binding",
    edgeKind === "all_previous_steps" && "is-bulk",
    data?.dimmed && "is-dimmed",
    data?.onPath && "is-on-path"
  ]}
>
  <BaseEdge {id} path={drawn.path} {markerStart} {markerEnd} style={edgeStyle} />
</g>

{#if isPowerUser}
  {#if isEscalation || isViolation}
    <EdgeLabel x={drawn.labelX} y={drawn.labelY - 16}>
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

  {#if isBinding || dataTypeLabel || showInsert}
    <EdgeLabel x={drawn.labelX} y={drawn.labelY}>
      <div
        class={cn(
          "flow-edge-label nodrag nopan flex items-center gap-0.5",
          data?.dimmed && "is-dimmed"
        )}
      >
        {#if isBinding}
          <span
            class="border-accent-default/40 bg-primary text-accent-stronger max-w-[5.5rem] truncate rounded-full border px-1.5 py-px font-mono text-[10px] leading-4"
            title={data?.argumentLabel}
          >
            {data?.argumentLabel}
          </span>
        {:else if dataTypeLabel}
          <Button
            variant="outline"
            size="xs"
            class={cn(
              "bg-primary text-secondary h-5 rounded-full px-1.5 text-[10px] font-normal",
              // The source node already says it is what is sent in.
              data?.dataType === "flow_input" && "edge-reveal"
            )}
            onclick={(event) => {
              event.stopPropagation();
              inspectEdge();
            }}
            aria-label="{m.flow_graph_inspect_edge()}: {dataTypeLabel}"
          >
            {dataTypeLabel}
          </Button>
        {/if}
        {#if showInsert}
          <Button
            variant="ghost"
            size="icon-xs"
            class="edge-reveal"
            onclick={(event) => {
              event.stopPropagation();
              insertStep();
            }}
            aria-label={m.flow_graph_insert_step_after({
              order: String(data?.sourceStepOrder ?? 0)
            })}
          >
            <IconPlus size="sm" />
          </Button>
        {/if}
      </div>
    </EdgeLabel>
  {/if}
{/if}

<style>
  .edge-actions {
    transform: translate(-50%, -50%);
  }

  /* Hidden via opacity (not visibility) so a button stays keyboard
     focusable; hover or focus on its label reveals it. EdgeLabel portals its
     wrapper into the shared edge-labels layer, so the reveal keys off the
     portalled wrapper itself. */
  :global(.edge-reveal) {
    opacity: 0;
    transition: opacity var(--duration-quick) var(--ease-out);
  }

  :global(.svelte-flow__edge-label:hover) :global(.edge-reveal),
  :global(.svelte-flow__edge-label:focus-within) :global(.edge-reveal) {
    opacity: 1;
  }

  :global(.flow-edge-group) :global(.svelte-flow__edge-path) {
    stroke-width: 1.5;
    transition:
      opacity 150ms ease-out,
      stroke-width 150ms ease-out;
  }

  :global(.flow-edge-group.is-binding) :global(.svelte-flow__edge-path) {
    stroke-width: 1.25;
    stroke-dasharray: 5 4;
  }

  :global(.flow-edge-group.is-bulk) :global(.svelte-flow__edge-path) {
    stroke-dasharray: 4 4;
    opacity: 0.6;
  }

  /* Quieting the rest is what makes one path traceable through a wide fan.
     It is opacity only: nothing moves and the edge stays where it was. */
  :global(.flow-edge-group.is-dimmed) {
    opacity: 0.25;
  }

  /* A label stays readable: its muted text keeps AA contrast at 0.9. */
  :global(.flow-edge-label.is-dimmed) {
    opacity: 0.9;
  }

  :global(.flow-edge-label) {
    transition: opacity 150ms ease-out;
  }

  /* Motion only explains where data goes: the edges into the step someone
     points at carry a dash in the direction the data flows, and nothing
     moves at rest. */
  @media (prefers-reduced-motion: no-preference) {
    :global(.flow-edge-group.is-on-path) :global(.svelte-flow__edge-path) {
      stroke-width: 2;
      stroke-dasharray: 6 4;
      animation: flow-edge-dash 0.9s linear infinite;
    }
  }

  @keyframes -global-flow-edge-dash {
    to {
      stroke-dashoffset: -10;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    :global(.flow-edge-group) :global(.svelte-flow__edge-path),
    :global(.flow-edge-label),
    :global(.edge-reveal) {
      transition: none;
    }
  }
</style>
