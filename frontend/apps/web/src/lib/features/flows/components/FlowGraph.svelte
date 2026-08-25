<script lang="ts">
  import {
    SvelteFlow,
    Controls,
    Background,
    BackgroundVariant,
    MiniMap,
    MarkerType,
    Panel,
    Position,
    type Node,
    type Edge,
    type NodeEventWithPointer
  } from "@xyflow/svelte";
  import "@xyflow/svelte/dist/style.css";
  import dagre from "dagre";
  import type { Flow, FlowStep } from "@eneo/eneo-js";
  import FlowNodeLlm from "./FlowNodeLlm.svelte";
  import FlowNodeIO from "./FlowNodeIO.svelte";
  import FlowEdgeInteractive from "./FlowEdgeInteractive.svelte";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { getFlowEditor } from "$lib/features/flows/FlowEditor";
  import {
    buildFlowGraphTopology,
    getEdgePayloadKind
  } from "$lib/features/flows/flowStepPresentation";
  import { IconDownload } from "@eneo/icons/download";
  import { onMount, tick } from "svelte";
  import { SvelteMap, SvelteSet } from "svelte/reactivity";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    flow: Flow;
    activeStepId: string | null;
    onnodeclick?: (id: string) => void;
  }
  let { flow, activeStepId, onnodeclick }: Props = $props();

  const mode = getFlowUserMode();
  const flowEditor = getFlowEditor();
  const assistantRevision = flowEditor.assistantRevision;

  let doFitView = $state(false);

  type AssistantFlowMeta = {
    modelName: string | null;
    assistantClassificationLevel: number | null;
  };

  const nodeTypes = {
    llm: FlowNodeLlm,
    assembly: FlowNodeLlm,
    input: FlowNodeIO,
    output: FlowNodeIO,
    http_source: FlowNodeIO,
    http_target: FlowNodeIO
  };
  const edgeTypes = {
    interactive: FlowEdgeInteractive
  };

  let nodes = $state.raw<Node[]>([]);
  let edges = $state.raw<Edge[]>([]);
  let assistantMetaById = new SvelteMap<string, AssistantFlowMeta>();
  let lastLoadedRevisionByAssistant = new SvelteMap<string, number>();
  const loadingAssistantIds = new SvelteSet<string>();
  let inspectedEdge = $state<{
    title: string;
    payload: Record<string, unknown> | null;
  } | null>(null);

  $effect(() => {
    const revision = $assistantRevision;
    const assistantIds = (flow?.steps ?? [])
      .map((step) => step.assistant_id)
      .filter(
        (assistantId): assistantId is string =>
          typeof assistantId === "string" && assistantId.length > 0
      );
    for (const assistantId of assistantIds) {
      if (
        lastLoadedRevisionByAssistant.get(assistantId) === revision ||
        loadingAssistantIds.has(assistantId)
      ) {
        continue;
      }
      void loadAssistantMeta(assistantId);
    }
  });

  // Memoize layout — only rebuild when step structure or mode changes, not on activeStepId alone
  let lastStepsJson = "";
  let lastMode = "";
  let lastMetaJson = "";
  let cachedLayout: { nodes: Node[]; edges: Edge[] } = { nodes: [], edges: [] };

  $effect(() => {
    const orderedSteps = flow?.steps ?? [];
    const stepsJson = JSON.stringify(
      orderedSteps.map((s) => ({
        id: s.id,
        step_order: s.step_order,
        user_description: s.user_description,
        input_source: s.input_source,
        input_type: s.input_type,
        output_type: s.output_type,
        output_mode: s.output_mode,
        assistant_id: s.assistant_id
      }))
    );
    const metaJson = JSON.stringify(
      orderedSteps.map((s) => ({
        assistant_id: s.assistant_id,
        meta: s.assistant_id ? (assistantMetaById.get(s.assistant_id) ?? null) : null
      }))
    );
    const currentMode = $mode;

    if (stepsJson !== lastStepsJson || currentMode !== lastMode || metaJson !== lastMetaJson) {
      lastStepsJson = stepsJson;
      lastMode = currentMode;
      lastMetaJson = metaJson;
      cachedLayout = buildLayout(flow?.steps ?? [], activeStepId, currentMode);
      nodes = cachedLayout.nodes;
      edges = cachedLayout.edges;
    } else {
      // Only activeStepId changed — update isActive in-place
      nodes = cachedLayout.nodes.map((n) => ({
        ...n,
        data: { ...n.data, isActive: n.id === activeStepId }
      }));
    }
  });

  onMount(async () => {
    await tick();
    requestAnimationFrame(() => {
      doFitView = true;
    });
  });

  function parseAssistantMeta(assistant: unknown): AssistantFlowMeta {
    if (assistant === null || typeof assistant !== "object") {
      return {
        modelName: null,
        assistantClassificationLevel: null
      };
    }
    const completionModel = (assistant as { completion_model?: unknown }).completion_model;
    if (completionModel === null || typeof completionModel !== "object") {
      return {
        modelName: null,
        assistantClassificationLevel: null
      };
    }
    const modelName =
      typeof (completionModel as { name?: unknown }).name === "string"
        ? (completionModel as { name: string }).name
        : null;
    const securityClassification = (completionModel as { security_classification?: unknown })
      .security_classification;
    const assistantClassificationLevel =
      securityClassification &&
      typeof securityClassification === "object" &&
      typeof (securityClassification as { security_level?: unknown }).security_level === "number"
        ? (securityClassification as { security_level: number }).security_level
        : null;
    return {
      modelName,
      assistantClassificationLevel
    };
  }

  async function loadAssistantMeta(assistantId: string): Promise<void> {
    const revision = $assistantRevision;
    loadingAssistantIds.add(assistantId);
    try {
      const assistant = await flowEditor.loadAssistant(assistantId);
      const parsed = parseAssistantMeta(assistant);
      assistantMetaById.set(assistantId, parsed);
      lastLoadedRevisionByAssistant.set(assistantId, revision);
    } catch {
      assistantMetaById.set(assistantId, {
        modelName: null,
        assistantClassificationLevel: null
      });
      lastLoadedRevisionByAssistant.set(assistantId, revision);
    } finally {
      loadingAssistantIds.delete(assistantId);
    }
  }

  function getClassificationLevel(step: FlowStep | undefined): number | null {
    if (!step) return null;
    const value = step.output_classification_override;
    if (typeof value === "number") return value;
    const assistantId = typeof step.assistant_id === "string" ? step.assistant_id : null;
    if (assistantId === null) return null;
    return assistantMetaById.get(assistantId)?.assistantClassificationLevel ?? null;
  }

  function buildPayloadPreview(
    sourceStep: FlowStep | undefined,
    targetStep: FlowStep | undefined,
    sourceClassification: number | null,
    targetClassification: number | null
  ): Record<string, unknown> {
    return {
      source_step_order: sourceStep?.step_order ?? 0,
      source_output_type: sourceStep?.output_type ?? "flow_input",
      source_output_contract: sourceStep?.output_contract ?? null,
      target_step_order: targetStep?.step_order ?? null,
      target_input_source: targetStep?.input_source ?? null,
      target_input_type: targetStep?.input_type ?? null,
      target_input_contract: targetStep?.input_contract ?? null,
      target_input_bindings: targetStep?.input_bindings ?? null,
      source_classification: sourceClassification,
      target_classification: targetClassification
    };
  }

  async function handleEdgeInsert(sourceStepOrder: number): Promise<void> {
    if ($mode !== "power_user") return;
    if (flow.published_version != null) return;
    await flowEditor.insertStepAfter(sourceStepOrder);
  }

  function handleEdgeInspect(params: {
    sourceStepOrder: number;
    sourceLabel: string;
    targetLabel: string;
    payload: Record<string, unknown> | null;
  }): void {
    if ($mode !== "power_user") return;
    inspectedEdge = {
      title: `${params.sourceLabel} -> ${params.targetLabel}`,
      payload: params.payload
    };
  }

  function buildLayout(
    steps: FlowStep[],
    activeId: string | null,
    userMode: string
  ): { nodes: Node[]; edges: Edge[] } {
    const orderedSteps = structuredClone(steps).sort((a, b) => a.step_order - b.step_order);
    const isPowerUser = userMode === "power_user";
    const nodeWidth = isPowerUser ? 300 : 160;
    const nodeHeight = isPowerUser ? 150 : 48;
    const inputNodeSize = { width: 160, height: 74 };
    const outputNodeSize = { width: 170, height: 78 };

    const g = new dagre.graphlib.Graph();
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({
      rankdir: "LR",
      ranksep: isPowerUser ? 140 : 80,
      nodesep: isPowerUser ? 50 : 30,
      marginx: 20,
      marginy: 16
    });

    // Topology (which nodes and edges exist) is owned by
    // buildFlowGraphTopology in flowStepPresentation; this component only
    // renders it.
    const topology = buildFlowGraphTopology(orderedSteps);
    const stepByOrder = new SvelteMap<number, FlowStep>();
    orderedSteps.forEach((step) => stepByOrder.set(step.step_order, step));
    const stepById = new SvelteMap<string, FlowStep>();
    orderedSteps.forEach((step) => stepById.set(step.id ?? `step-${step.step_order}`, step));

    const resultNodes: Node[] = [];
    for (const node of topology.nodes) {
      if (node.kind === "step") {
        const step = stepById.get(node.id);
        if (!step) continue;
        g.setNode(node.id, { width: nodeWidth, height: nodeHeight });
        resultNodes.push({
          id: node.id,
          type: step.output_mode === "template_fill" ? "assembly" : "llm",
          sourcePosition: Position.Right,
          targetPosition: Position.Left,
          position: { x: 0, y: 0 },
          data: {
            label: step.user_description ?? m.flow_step_fallback_label({ order: step.step_order }),
            step,
            isActive: node.id === activeId,
            mode: userMode,
            modelName: assistantMetaById.get(step.assistant_id)?.modelName ?? null,
            assistantClassLevel:
              assistantMetaById.get(step.assistant_id)?.assistantClassificationLevel ?? null,
            classLevel: getClassificationLevel(step)
          }
        });
        continue;
      }
      const ioLabel =
        node.kind === "input"
          ? m.flow_graph_node_input()
          : node.kind === "output"
            ? m.flow_graph_node_output()
            : node.kind === "http_source"
              ? m.flow_graph_node_http_source()
              : m.flow_graph_node_http_target();
      g.setNode(node.id, node.kind === "input" ? inputNodeSize : outputNodeSize);
      resultNodes.push({
        id: node.id,
        type: node.kind,
        ...(node.kind === "input" || node.kind === "http_source"
          ? { sourcePosition: Position.Right }
          : { targetPosition: Position.Left }),
        position: { x: 0, y: 0 },
        data: { label: ioLabel, nodeType: node.kind, mode: userMode }
      });
    }

    const edgeSpecs = topology.edges;
    for (const edge of edgeSpecs) {
      g.setEdge(edge.source, edge.target);
    }

    dagre.layout(g);

    for (const node of resultNodes) {
      const pos = g.node(node.id);
      if (pos) {
        node.position = {
          x: pos.x - (pos.width ?? 0) / 2,
          y: pos.y - (pos.height ?? 0) / 2
        };
      }
    }

    const incomingEdgeCounts = new SvelteMap<string, number>();
    const incomingEdgeLane = new SvelteMap<string, number>();
    for (const edge of edgeSpecs) {
      incomingEdgeCounts.set(edge.target, (incomingEdgeCounts.get(edge.target) ?? 0) + 1);
    }

    const resultEdges: Edge[] = [];
    for (const edge of edgeSpecs) {
      const sourceStep =
        edge.sourceStepOrder > 0 ? stepByOrder.get(edge.sourceStepOrder) : undefined;
      const targetStep =
        edge.targetStepOrder != null ? stepByOrder.get(edge.targetStepOrder) : undefined;
      const sourceLevel = getClassificationLevel(sourceStep);
      const targetLevel = getClassificationLevel(targetStep);
      const isEscalation = sourceLevel != null && targetLevel != null && targetLevel > sourceLevel;
      const isViolation = sourceLevel != null && targetLevel != null && targetLevel < sourceLevel;
      const laneIndex = incomingEdgeLane.get(edge.target) ?? 0;
      incomingEdgeLane.set(edge.target, laneIndex + 1);
      const laneCount = incomingEdgeCounts.get(edge.target) ?? 1;
      const labelOffsetY = (laneIndex - (laneCount - 1) / 2) * 22;
      const sourceLabel =
        edge.source === "input"
          ? m.flow_graph_node_input()
          : edge.source === "http-source"
            ? m.flow_graph_node_http_source()
            : (sourceStep?.user_description ??
              m.flow_step_fallback_label({ order: edge.sourceStepOrder }));
      const targetLabel =
        edge.target === "output"
          ? m.flow_graph_node_output()
          : edge.target === "http-target"
            ? m.flow_graph_node_http_target()
            : (targetStep?.user_description ??
              m.flow_step_fallback_label({ order: edge.targetStepOrder ?? "?" }));
      const payloadKind = getEdgePayloadKind({
        edgeKind: edge.kind,
        sourceStep,
        targetStep
      });
      const payload = buildPayloadPreview(sourceStep, targetStep, sourceLevel, targetLevel);
      const allowInsert =
        edge.kind !== "all_previous_steps" &&
        edge.kind !== "http_get" &&
        edge.kind !== "http_post" &&
        edge.target !== "output";

      const markerColor = isViolation
        ? "var(--negative-default)"
        : isEscalation
          ? "var(--warning-default)"
          : undefined;
      resultEdges.push({
        id: `e-${edge.source}-${edge.target}-${edge.kind}-${laneIndex}`,
        type: "interactive",
        source: edge.source,
        target: edge.target,
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: markerColor },
        data: {
          mode: userMode,
          readOnly: flow.published_version != null,
          dataType: payloadKind,
          edgeKind: edge.kind,
          animate: false,
          allowInsert,
          labelOffsetY,
          sourceStepOrder: edge.sourceStepOrder,
          sourceLabel,
          targetLabel,
          payload,
          classificationEscalation: isEscalation,
          classificationViolation: isViolation,
          sourceClassification: sourceLevel,
          targetClassification: targetLevel,
          onInsert: handleEdgeInsert,
          onInspect: handleEdgeInspect
        },
        style:
          edge.kind === "all_previous_steps" ? "stroke-dasharray: 4 4; opacity: 0.6" : undefined
      });
    }

    return { nodes: resultNodes, edges: resultEdges };
  }

  let isExporting = $state(false);

  async function exportPng() {
    isExporting = true;
    try {
      const { toPng } = await import("html-to-image");
      const el = document.querySelector("#flow-graph-container .svelte-flow") as HTMLElement | null;
      if (!el) return;
      doFitView = true;
      await tick();
      await new Promise((r) => requestAnimationFrame(r));
      const dataUrl = await toPng(el, {
        cacheBust: true,
        pixelRatio: 2,
        filter: (node: HTMLElement) => {
          const cls = node.classList;
          if (!cls) return true;
          return (
            !cls.contains("svelte-flow__panel") &&
            !cls.contains("svelte-flow__controls") &&
            !cls.contains("svelte-flow__minimap")
          );
        }
      });
      const link = document.createElement("a");
      link.download = `${flow.name ?? "flow"}-graph.png`;
      link.href = dataUrl;
      link.click();
    } finally {
      isExporting = false;
    }
  }

  function minimapNodeColor(node: Node): string {
    if (node.type === "input") return "var(--color-accent-default)";
    if (node.type === "output") return "var(--color-positive-default)";
    if (node.type === "assembly") return "var(--color-warning-default)";
    return "var(--background-color-secondary)";
  }

  const handleNodeClick: NodeEventWithPointer<MouseEvent | TouchEvent, Node> = ({ node }) => {
    if ((node?.type === "llm" || node?.type === "assembly") && node.data?.step) {
      onnodeclick?.(node.id);
    }
  };
</script>

<div
  class="flow-graph h-full w-full {$mode === 'power_user' ? '' : 'user-mode'}"
  id="flow-graph-container"
>
  <SvelteFlow
    {nodes}
    {edges}
    {nodeTypes}
    {edgeTypes}
    fitView={doFitView}
    fitViewOptions={{ padding: 0.3 }}
    proOptions={{ hideAttribution: true }}
    nodesDraggable={false}
    nodesConnectable={false}
    elementsSelectable={true}
    panOnDrag={true}
    zoomOnScroll={true}
    onnodeclick={handleNodeClick}
  >
    <Controls position="top-left" showLock={false} />
    {#if $mode === "power_user"}
      <Background variant={BackgroundVariant.Dots} />
      <MiniMap width={140} height={90} nodeColor={minimapNodeColor} />
      <Panel position="top-right">
        <button
          class="bg-primary/90 text-secondary hover:bg-hover-dimmer flex items-center gap-1.5 rounded px-2 py-1 text-xs backdrop-blur-sm transition-colors"
          onclick={exportPng}
          disabled={isExporting}
          aria-label={m.flow_graph_download_png()}
        >
          <IconDownload class="size-3" />
          {m.flow_graph_download_png()}
        </button>
      </Panel>
      <Panel position="bottom-left">
        <div
          class="bg-primary/90 text-secondary flex items-center gap-3 rounded px-2.5 py-1.5 text-xs backdrop-blur-sm"
        >
          <span class="flex items-center gap-1.5">
            <svg width="20" height="2"
              ><line x1="0" y1="1" x2="20" y2="1" stroke="currentColor" stroke-width="1.5" /></svg
            >
            {m.flow_graph_legend_direct()}
          </span>
          <span class="flex items-center gap-1.5">
            <svg width="20" height="2"
              ><line
                x1="0"
                y1="1"
                x2="20"
                y2="1"
                stroke="currentColor"
                stroke-width="1.5"
                stroke-dasharray="4 4"
                opacity="0.6"
              /></svg
            >
            {m.flow_graph_legend_all_previous()}
          </span>
        </div>
      </Panel>
    {:else}
      <Background variant={BackgroundVariant.Dots} size={0.5} gap={30} />
    {/if}
  </SvelteFlow>

  {#if $mode === "power_user" && inspectedEdge}
    <aside
      class="edge-inspector bg-primary border-default absolute top-3 right-3 left-3 z-20 w-auto rounded-lg border shadow-lg sm:left-auto sm:w-[320px]"
    >
      <div class="border-default flex items-center justify-between border-b px-3 py-2">
        <p class="text-sm font-semibold">{m.flow_graph_preview()} · {inspectedEdge.title}</p>
        <button
          type="button"
          class="hover:bg-hover-dimmer rounded px-2 py-1 text-xs"
          onclick={() => (inspectedEdge = null)}
        >
          {m.close()}
        </button>
      </div>
      <div class="max-h-[240px] overflow-auto p-3">
        <dl class="space-y-1.5 text-xs">
          {#each Object.entries(inspectedEdge.payload ?? {}).filter(([, v]) => v != null) as [key, value] (key)}
            <div class="flex items-baseline gap-2">
              <dt class="text-secondary shrink-0 font-mono">{key.replace(/_/g, " ")}</dt>
              <dd class="font-medium break-all">
                {typeof value === "object" ? JSON.stringify(value) : String(value)}
              </dd>
            </div>
          {/each}
        </dl>
      </div>
    </aside>
  {/if}
</div>

<style>
  .flow-graph :global(.svelte-flow) {
    --xy-node-background-color-default: var(--background-color-primary);
    --xy-node-border-default: 1px solid var(--border-color-default);
    --xy-node-border-radius-default: 8px;
    --xy-node-boxshadow-default:
      0px 3px 4px 0px var(--shadow-default), 0px 1px 2px 0px var(--shadow-stronger);
    --xy-node-boxshadow-hover-default: 0 2px 8px var(--shadow-stronger);
    --xy-node-boxshadow-selected-default: 0 0 0 2px var(--color-accent-default);
    --xy-edge-label-background-color-default: transparent;
    --xy-edge-stroke-default: var(--border-stronger);
    --xy-edge-stroke-width-default: 2;
    --xy-edge-stroke-selected-default: var(--color-accent-default);
    --xy-background-pattern-dot-color-default: var(--border-color-dimmer);
    --xy-handle-background-color-default: var(--background-color-primary);
    --xy-handle-border-color-default: var(--border-stronger);
    --xy-minimap-background-color-default: var(--background-color-secondary);
    --xy-controls-button-background-color-default: var(--background-color-primary);
    --xy-controls-button-background-color-hover-default: var(--background-color-secondary);
    --xy-controls-button-border-color-default: var(--border-color-default);
  }

  .flow-graph :global(.svelte-flow__handle) {
    width: 6px;
    height: 6px;
  }

  .flow-graph.user-mode :global(.svelte-flow__handle) {
    opacity: 0;
    pointer-events: none;
  }

  .flow-graph :global(.svelte-flow__edge-path) {
    transition:
      stroke 160ms ease-in-out,
      stroke-width 160ms ease-in-out;
  }
</style>
