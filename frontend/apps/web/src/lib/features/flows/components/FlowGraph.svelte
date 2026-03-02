<script lang="ts">
  import {
    SvelteFlow,
    Controls,
    Background,
    BackgroundVariant,
    MiniMap,
    MarkerType,
    Panel,
    type Node,
    type Edge
  } from "@xyflow/svelte";
  import "@xyflow/svelte/dist/style.css";
  import dagre from "dagre";
  import type { Flow, FlowStep } from "@intric/intric-js";
  import FlowNodeLlm from "./FlowNodeLlm.svelte";
  import FlowNodeIO from "./FlowNodeIO.svelte";
  import FlowEdgeInteractive from "./FlowEdgeInteractive.svelte";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { getFlowEditor } from "$lib/features/flows/FlowEditor";
  import { onMount, tick } from "svelte";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    flow: Flow;
    activeStepId: string | null;
    onnodeclick?: (id: string) => void;
  }
  let { flow, activeStepId, onnodeclick }: Props = $props();

  const mode = getFlowUserMode();
  const flowEditor = getFlowEditor();

  let doFitView = $state(false);

  type AssistantFlowMeta = {
    modelName: string | null;
    assistantClassificationLevel: number | null;
  };

  const nodeTypes = {
    llm: FlowNodeLlm,
    input: FlowNodeIO,
    output: FlowNodeIO
  };
  const edgeTypes = {
    interactive: FlowEdgeInteractive
  };

  let nodes = $state.raw<Node[]>([]);
  let edges = $state.raw<Edge[]>([]);
  let assistantMetaById = new Map<string, AssistantFlowMeta>();
  const loadingAssistantIds = new Set<string>();
  let inspectedEdge = $state<{
    title: string;
    payload: Record<string, unknown> | null;
  } | null>(null);

  $effect(() => {
    const assistantIds = (flow?.steps ?? [])
      .map((step) => step.assistant_id)
      .filter((assistantId): assistantId is string => typeof assistantId === "string" && assistantId.length > 0);
    for (const assistantId of assistantIds) {
      if (assistantMetaById.has(assistantId) || loadingAssistantIds.has(assistantId)) continue;
      void loadAssistantMeta(assistantId);
    }
  });

  // Memoize layout — only rebuild when step structure or mode changes, not on activeStepId alone
  let lastStepsJson = "";
  let lastMode = "";
  let cachedLayout: { nodes: Node[]; edges: Edge[] } = { nodes: [], edges: [] };

  $effect(() => {
    const stepsJson = JSON.stringify(
      (flow?.steps ?? []).map((s) => ({
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
    const currentMode = $mode;

    if (stepsJson !== lastStepsJson || currentMode !== lastMode) {
      lastStepsJson = stepsJson;
      lastMode = currentMode;
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
      return { modelName: null, assistantClassificationLevel: null };
    }
    const completionModel = (assistant as { completion_model?: unknown }).completion_model;
    if (completionModel === null || typeof completionModel !== "object") {
      return { modelName: null, assistantClassificationLevel: null };
    }
    const modelName =
      typeof (completionModel as { name?: unknown }).name === "string"
        ? (completionModel as { name: string }).name
        : null;
    const securityClassification = (completionModel as { security_classification?: unknown }).security_classification;
    const assistantClassificationLevel =
      securityClassification &&
      typeof securityClassification === "object" &&
      typeof (securityClassification as { security_level?: unknown }).security_level === "number"
        ? (securityClassification as { security_level: number }).security_level
        : null;
    return { modelName, assistantClassificationLevel };
  }

  async function loadAssistantMeta(assistantId: string): Promise<void> {
    loadingAssistantIds.add(assistantId);
    try {
      const assistant = await flowEditor.loadAssistant(assistantId);
      const parsed = parseAssistantMeta(assistant);
      assistantMetaById = new Map(assistantMetaById).set(assistantId, parsed);
    } catch {
      assistantMetaById = new Map(assistantMetaById).set(assistantId, {
        modelName: null,
        assistantClassificationLevel: null
      });
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
    const nodeWidth = isPowerUser ? 240 : 160;
    const nodeHeight = isPowerUser ? 110 : 48;
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

    g.setNode("input", inputNodeSize);
    const resultNodes: Node[] = [
      {
        id: "input",
        type: "input",
        position: { x: 0, y: 0 },
        data: { label: "Input", nodeType: "input", mode: userMode }
      }
    ];

    for (const step of orderedSteps) {
      const id = step.id ?? `step-${step.step_order}`;
      g.setNode(id, { width: nodeWidth, height: nodeHeight });
      resultNodes.push({
        id,
        type: "llm",
        position: { x: 0, y: 0 },
        data: {
          label: step.user_description ?? `Step ${step.step_order}`,
          step,
          isActive: id === activeId,
          mode: userMode,
          modelName:
            assistantMetaById.get(step.assistant_id)?.modelName ??
            null,
          assistantClassLevel:
            assistantMetaById.get(step.assistant_id)?.assistantClassificationLevel ??
            null,
          classLevel: getClassificationLevel(step)
        }
      });
    }

    g.setNode("output", outputNodeSize);
    resultNodes.push({
      id: "output",
      type: "output",
      position: { x: 0, y: 0 },
      data: { label: "Output", nodeType: "output", mode: userMode }
    });

    type EdgeSpec = {
      source: string;
      target: string;
      kind: "flow_input" | "previous_step" | "all_previous_steps" | "flow_output";
      sourceStepOrder: number;
      targetStepOrder: number | null;
    };
    const edgeSpecs: EdgeSpec[] = [];
    const stepByOrder = new Map<number, FlowStep>();
    const stepIdByOrder = new Map<number, string>();
    orderedSteps.forEach((step) => {
      stepByOrder.set(step.step_order, step);
      stepIdByOrder.set(step.step_order, step.id ?? `step-${step.step_order}`);
    });

    for (const step of orderedSteps) {
      const stepId = stepIdByOrder.get(step.step_order) ?? `step-${step.step_order}`;
      if (step.input_source === "flow_input") {
        edgeSpecs.push({
          source: "input",
          target: stepId,
          kind: "flow_input",
          sourceStepOrder: 0,
          targetStepOrder: step.step_order
        });
        continue;
      }

      if (step.input_source === "previous_step") {
        const prevStep = stepByOrder.get(step.step_order - 1);
        if (prevStep) {
          edgeSpecs.push({
            source: stepIdByOrder.get(prevStep.step_order) ?? `step-${prevStep.step_order}`,
            target: stepId,
            kind: "previous_step",
            sourceStepOrder: prevStep.step_order,
            targetStepOrder: step.step_order
          });
        } else {
          edgeSpecs.push({
            source: "input",
            target: stepId,
            kind: "flow_input",
            sourceStepOrder: 0,
            targetStepOrder: step.step_order
          });
        }
        continue;
      }

      if (step.input_source === "all_previous_steps") {
        for (const prevStep of orderedSteps) {
          if (prevStep.step_order >= step.step_order) continue;
          edgeSpecs.push({
            source: stepIdByOrder.get(prevStep.step_order) ?? `step-${prevStep.step_order}`,
            target: stepId,
            kind: "all_previous_steps",
            sourceStepOrder: prevStep.step_order,
            targetStepOrder: step.step_order
          });
        }
        edgeSpecs.push({
          source: "input",
          target: stepId,
          kind: "all_previous_steps",
          sourceStepOrder: 0,
          targetStepOrder: step.step_order
        });
      }
    }

    if (orderedSteps.length > 0) {
      const outgoingSteps = new Set<string>();
      for (const edge of edgeSpecs) {
        if (edge.source !== "input" && edge.target !== "output") {
          outgoingSteps.add(edge.source);
        }
      }
      for (const step of orderedSteps) {
        const stepId = stepIdByOrder.get(step.step_order) ?? `step-${step.step_order}`;
        if (outgoingSteps.has(stepId)) continue;
        edgeSpecs.push({
          source: stepId,
          target: "output",
          kind: "flow_output",
          sourceStepOrder: step.step_order,
          targetStepOrder: null
        });
      }
    } else {
      edgeSpecs.push({
        source: "input",
        target: "output",
        kind: "flow_output",
        sourceStepOrder: 0,
        targetStepOrder: null
      });
    }

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

    const incomingEdgeCounts = new Map<string, number>();
    const incomingEdgeLane = new Map<string, number>();
    for (const edge of edgeSpecs) {
      incomingEdgeCounts.set(edge.target, (incomingEdgeCounts.get(edge.target) ?? 0) + 1);
    }

    const resultEdges: Edge[] = [];
    for (const edge of edgeSpecs) {
      const sourceStep = edge.sourceStepOrder > 0 ? stepByOrder.get(edge.sourceStepOrder) : undefined;
      const targetStep =
        edge.targetStepOrder != null ? stepByOrder.get(edge.targetStepOrder) : undefined;
      const sourceLevel = getClassificationLevel(sourceStep);
      const targetLevel = getClassificationLevel(targetStep);
      const isEscalation =
        sourceLevel != null && targetLevel != null && targetLevel > sourceLevel;
      const isViolation =
        sourceLevel != null && targetLevel != null && targetLevel < sourceLevel;
      const laneIndex = incomingEdgeLane.get(edge.target) ?? 0;
      incomingEdgeLane.set(edge.target, laneIndex + 1);
      const laneCount = incomingEdgeCounts.get(edge.target) ?? 1;
      const labelOffsetY = (laneIndex - (laneCount - 1) / 2) * 22;
      const sourceLabel =
        edge.source === "input"
          ? "Input"
          : (sourceStep?.user_description ?? `Step ${edge.sourceStepOrder}`);
      const targetLabel =
        edge.target === "output"
          ? "Output"
          : (targetStep?.user_description ?? `Step ${edge.targetStepOrder ?? "?"}`);
      const dataType =
        edge.source === "input" ? "input" : (sourceStep?.output_type ?? "text");
      const payload = buildPayloadPreview(sourceStep, targetStep, sourceLevel, targetLevel);
      const allowInsert = edge.kind !== "all_previous_steps" && edge.target !== "output";

      const markerColor = isViolation ? "#dc2626" : isEscalation ? "#d97706" : "#9ca3af";
      resultEdges.push({
        id: `e-${edge.source}-${edge.target}-${edge.kind}-${laneIndex}`,
        type: "interactive",
        source: edge.source,
        target: edge.target,
        label: isPowerUser ? dataType : undefined,
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: markerColor },
        data: {
          mode: userMode,
          readOnly: flow.published_version != null,
          dataType,
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
        style: edge.kind === "all_previous_steps" ? "stroke-dasharray: 4 4; opacity: 0.6" : undefined
      });
    }

    return { nodes: resultNodes, edges: resultEdges };
  }

  function handleNodeClick(event: any) {
    const node = event.detail?.node ?? event.node;
    if (node?.type === "llm" && node.data?.step) {
      onnodeclick?.(node.id);
    }
  }
</script>

<div class="flow-graph h-full w-full {$mode === 'power_user' ? '' : 'user-mode'}" id="flow-graph-container">
  <SvelteFlow
    {nodes}
    {edges}
    {nodeTypes}
    {edgeTypes}
    fitView={doFitView}
    fitViewOptions={{ padding: 0.15 }}
    proOptions={{ hideAttribution: true }}
    nodesDraggable={false}
    nodesConnectable={false}
    elementsSelectable={true}
    panOnDrag={true}
    zoomOnScroll={true}
    onnodeclick={handleNodeClick}
  >
    {#if $mode === "power_user"}
      <Background variant={BackgroundVariant.Dots} />
      <MiniMap width={140} height={90} />
      <Controls position="top-left" />
      <Panel position="bottom-left">
        <div class="flex items-center gap-3 rounded bg-primary/90 px-2.5 py-1.5 text-[10px] text-secondary backdrop-blur-sm">
          <span class="flex items-center gap-1.5">
            <svg width="20" height="2"><line x1="0" y1="1" x2="20" y2="1" stroke="currentColor" stroke-width="1.5"/></svg>
            {m.flow_graph_legend_direct()}
          </span>
          <span class="flex items-center gap-1.5">
            <svg width="20" height="2"><line x1="0" y1="1" x2="20" y2="1" stroke="currentColor" stroke-width="1.5" stroke-dasharray="4 4" opacity="0.6"/></svg>
            {m.flow_graph_legend_all_previous()}
          </span>
        </div>
      </Panel>
    {/if}
  </SvelteFlow>

  {#if $mode === "power_user" && inspectedEdge}
    <aside class="edge-inspector bg-primary border-default absolute right-3 top-3 z-20 w-[320px] rounded-lg border shadow-lg">
      <div class="border-default flex items-center justify-between border-b px-3 py-2">
        <p class="text-sm font-semibold">{m.flow_graph_preview()} · {inspectedEdge.title}</p>
        <button
          class="hover:bg-hover-dimmer rounded px-2 py-1 text-xs"
          on:click={() => (inspectedEdge = null)}
        >
          {m.cancel()}
        </button>
      </div>
      <div class="max-h-[240px] overflow-auto p-3">
        <dl class="space-y-1.5 text-xs">
          {#each Object.entries(inspectedEdge.payload ?? {}).filter(([, v]) => v != null) as [key, value]}
            <div class="flex items-baseline gap-2">
              <dt class="text-secondary shrink-0 font-mono">{key.replace(/_/g, " ")}</dt>
              <dd class="break-all font-medium">
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
    --xy-node-background-color-default: var(--color-bg-primary, #fff);
    --xy-node-border-default: 1px solid var(--color-border-default, #e5e7eb);
    --xy-node-boxshadow-hover-default: 0 2px 8px rgba(0, 0, 0, 0.08);
    --xy-node-boxshadow-selected-default: 0 0 0 2px var(--color-accent, #3b82f6);
    --xy-edge-stroke-default: var(--color-border-dimmer, #d1d5db);
    --xy-edge-stroke-width-default: 1.5;
    --xy-edge-stroke-selected-default: var(--color-accent, #3b82f6);
    --xy-background-pattern-dot-color-default: var(--color-border-dimmer, #d1d5db);
    --xy-handle-background-color-default: var(--color-border-dimmer, #d1d5db);
    --xy-handle-border-color-default: transparent;
    --xy-minimap-background-color-default: var(--color-bg-secondary, #f9fafb);
    --xy-controls-button-background-color-default: var(--color-bg-primary, #fff);
    --xy-controls-button-background-color-hover-default: var(--color-bg-secondary, #f3f4f6);
    --xy-controls-button-border-color-default: var(--color-border-default, #e5e7eb);
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
    transition: stroke 160ms ease-in-out, stroke-width 160ms ease-in-out;
  }
</style>
