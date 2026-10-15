<script lang="ts">
  import {
    SvelteFlow,
    Controls,
    Background,
    BackgroundVariant,
    MiniMap,
    MarkerType,
    Panel,
    getViewportForBounds,
    type Node,
    type Edge,
    type Rect,
    type NodeEventWithPointer,
    type FitViewOptions
  } from "@xyflow/svelte";
  import "@xyflow/svelte/dist/style.css";
  import type { Flow, FlowStep } from "@eneo/eneo-js";
  import {
    securityClassName,
    securityClassStanding,
    type NamedSecurityLevel
  } from "$lib/features/flows/flowClassificationNames";
  import FlowNodeLlm from "./FlowNodeLlm.svelte";
  import FlowNodeIO from "./FlowNodeIO.svelte";
  import FlowNodeTool from "./FlowNodeTool.svelte";
  import FlowEdgeInteractive from "./FlowEdgeInteractive.svelte";
  import FlowGraphAutoFit from "./FlowGraphAutoFit.svelte";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { getFlowEditor } from "$lib/features/flows/FlowEditor";
  import {
    computeFlowExportSize,
    computeFlowGraphEmphasis,
    planFlowExportCaption,
    emptyFlowGraphPreviewState,
    reduceFlowGraphPreview,
    resolveFlowGraphPreviewId,
    type FlowGraphPreviewEvent,
    flowGraphLayoutKey,
    getEdgePayloadKind
  } from "$lib/features/flows/flowStepPresentation";
  import { planFlowGraph } from "$lib/features/flows/flowGraphPlan";
  import { getFlowFormSchemaMetadata } from "$lib/features/flows/flowFormSchema";
  import type { ToolOptionsLoad } from "./tool/toolInputConfig";
  import { IconDownload } from "@eneo/icons/download";
  import { Button } from "$lib/components/ui/button/index.js";
  import { SvelteMap, SvelteSet } from "svelte/reactivity";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    flow: Flow;
    activeStepId: string | null;
    /** The organisation's security classes, which name the levels the nodes show. */
    classifications?: NamedSecurityLevel[];
    onnodeclick?: (id: string) => void;
    /** Laid-out size of the graph, so a host can give it a shape that fits. */
    oncontentsize?: (size: { width: number; height: number }) => void;
  }
  let { flow, activeStepId, classifications = [], onnodeclick, oncontentsize }: Props = $props();

  const mode = getFlowUserMode();
  const flowEditor = getFlowEditor();
  const assistantRevision = flowEditor.assistantRevision;
  const toolOptions = flowEditor.state.toolOptions;

  let containerEl: HTMLDivElement | undefined = $state();
  let layoutRevision = $state(0);
  let fitGraph: (() => void) | undefined = $state();
  let graphBounds: (() => Rect) | undefined = $state();
  // The step the reader is pointing at or has tabbed to. Separate from
  // activeStepId on purpose: looking at a step must not change which one
  // the editor has open.
  let previewState = $state(emptyFlowGraphPreviewState());
  const previewStepId = $derived(resolveFlowGraphPreviewId(previewState));

  function onPreview(event: FlowGraphPreviewEvent): void {
    previewState = reduceFlowGraphPreview(previewState, event);
  }

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
    tool_source: FlowNodeTool,
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
  let cachedLayout: {
    nodes: Node[];
    edges: Edge[];
    /** Tool node id -> the step it belongs to. */
    ownerOf: Record<string, string>;
    /** The laid-out extent, edges under the steps included. */
    size: { width: number; height: number };
  } = { nodes: [], edges: [], ownerOf: {}, size: { width: 0, height: 0 } };
  // The binding edge the pointer is on, which lights the argument row it fills.
  let hoveredEdgeId = $state<string | null>(null);
  // Nodes glide to a new place only right after a layout change, never while
  // someone pans or zooms.
  let gliding = $state(false);
  let glideTimer: ReturnType<typeof setTimeout> | undefined;

  $effect(() => {
    const orderedSteps = flow?.steps ?? [];
    const stepsJson = flowGraphLayoutKey(orderedSteps);
    // The class names are part of what a node shows, so renamed classes
    // rebuild the nodes too.
    // What a tool node shows decides its height, so a tool list that arrives
    // or changes rebuilds the layout too.
    const toolLoad = $toolOptions;
    const formSchema = getFlowFormSchemaMetadata(flow?.metadata_json);
    const metaJson = JSON.stringify({
      classifications,
      // A renamed run-form field changes which tool arguments read the run's input.
      formSchema,
      tools: toolLoad,
      steps: orderedSteps.map((s) => ({
        assistant_id: s.assistant_id,
        meta: s.assistant_id ? (assistantMetaById.get(s.assistant_id) ?? null) : null
      }))
    });
    const currentMode = $mode;

    if (stepsJson !== lastStepsJson || currentMode !== lastMode || metaJson !== lastMetaJson) {
      lastStepsJson = stepsJson;
      lastMode = currentMode;
      lastMetaJson = metaJson;
      cachedLayout = buildLayout(
        flow?.steps ?? [],
        activeStepId,
        currentMode,
        toolLoad,
        formSchema
      );
      // A counter, not a signature: rewiring one step's underlag changes the
      // laid-out width without changing the mode, the JSON length, or the node
      // and edge counts, and a collision leaves the old frame in place.
      layoutRevision += 1;
      if (layoutRevision > 1) glide();
    }
    applyEmphasis(activeStepId, previewStepId, hoveredEdgeId);
  });

  function glide(): void {
    gliding = true;
    clearTimeout(glideTimer);
    glideTimer = setTimeout(() => (gliding = false), 260);
  }

  function applyEmphasis(
    activeId: string | null,
    previewId: string | null,
    hoveredEdge: string | null
  ): void {
    const emphasis = computeFlowGraphEmphasis({
      edges: cachedLayout.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target
      })),
      activeId,
      previewId,
      ownerOf: cachedLayout.ownerOf
    });
    // Only pointing at a step quiets the rest: a selection persists, and a
    // graph faded around whichever step is open would stay faded.
    const previewing = emphasis.isPreview;
    const litArguments = (nodeId: string): string[] =>
      cachedLayout.edges
        .filter(
          (edge) =>
            edge.target === nodeId &&
            ((previewing && emphasis.litEdges[edge.id] === true) || edge.id === hoveredEdge)
        )
        .flatMap((edge) => (Array.isArray(edge.data?.arguments) ? edge.data.arguments : []))
        .filter((argument): argument is string => typeof argument === "string");
    nodes = cachedLayout.nodes.map((node) => ({
      ...node,
      data: {
        ...node.data,
        isActive: node.id === activeId,
        dimmed: previewing && emphasis.litNodes[node.id] !== true,
        lifted: previewing && emphasis.litNodes[node.id] === true,
        ...(node.type === "tool_source" ? { litArguments: litArguments(node.id) } : {})
      }
    }));
    edges = cachedLayout.edges.map((edge) => ({
      ...edge,
      data: {
        ...edge.data,
        // The dash runs only while someone is pointing at a step. A selection
        // persists, and a persistent selection lighting a dozen edges would
        // leave a dozen animations running at rest -- ambient motion on a
        // screen whose whole register is calm, and motion nobody started.
        onPath: emphasis.isPreview && emphasis.litEdges[edge.id] === true,
        dimmed: emphasis.hasFocus && emphasis.litEdges[edge.id] !== true
      }
    }));
  }

  /** The step a node opens and previews: a step itself, or the step a tool node belongs to. */
  function stepOfNode(id: string | undefined): string | null {
    if (!id) return null;
    const owner = cachedLayout.ownerOf[id];
    if (owner !== undefined) return owner;
    const node = cachedLayout.nodes.find((candidate) => candidate.id === id);
    return node?.type === "llm" || node?.type === "assembly" ? id : null;
  }

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

  // The levels a node shows, with the names the organisation gave them.
  function classBadges(assistantClassLevel: number | null, classLevel: number | null) {
    return {
      assistantClassLevel,
      classLevel,
      assistantClassName:
        assistantClassLevel === null
          ? null
          : securityClassName(classifications, assistantClassLevel),
      className: classLevel === null ? null : securityClassName(classifications, classLevel),
      classStanding: classLevel === null ? null : securityClassStanding(classifications, classLevel)
    };
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
    userMode: string,
    toolLoad: ToolOptionsLoad,
    formSchema: ReturnType<typeof getFlowFormSchemaMetadata>
  ): typeof cachedLayout {
    const orderedSteps = structuredClone(steps).sort((a, b) => a.step_order - b.step_order);
    const isPowerUser = userMode === "power_user";
    // What exists, what tool nodes show and where everything goes is owned by
    // planFlowGraph; this component only renders it.
    const plan = planFlowGraph({
      steps: orderedSteps,
      formSchema,
      toolLoad,
      detailed: isPowerUser
    });
    const { layout, metrics, boxOf, ownerOf } = plan;
    const topology = { nodes: plan.nodes };
    const toolById = plan.tools;
    const drawnEdges = plan.edges;
    const stepByOrder = new SvelteMap<number, FlowStep>();
    orderedSteps.forEach((step) => stepByOrder.set(step.step_order, step));
    const stepById = new SvelteMap<string, FlowStep>();
    orderedSteps.forEach((step) => stepById.set(step.id ?? `step-${step.step_order}`, step));
    oncontentsize?.(layout.size);

    const toolLabel = (nodeId: string): string =>
      toolById.get(nodeId)?.toolName ?? m.flow_graph_tool_fallback();
    const stepLabel = (step: FlowStep | undefined, order: number | string): string =>
      step?.user_description ?? m.flow_step_fallback_label({ order });

    const resultNodes: Node[] = [];
    for (const node of topology.nodes) {
      const position = layout.positions.get(node.id) ?? { x: 0, y: 0 };
      if (node.kind === "step") {
        const step = stepById.get(node.id);
        if (!step) continue;
        resultNodes.push({
          id: node.id,
          type: step.output_mode === "template_fill" ? "assembly" : "llm",
          position,
          data: {
            label: stepLabel(step, step.step_order),
            step,
            isActive: node.id === activeId,
            mode: userMode,
            handleY: metrics.spineHandleY,
            modelName: assistantMetaById.get(step.assistant_id)?.modelName ?? null,
            ...classBadges(
              assistantMetaById.get(step.assistant_id)?.assistantClassificationLevel ?? null,
              getClassificationLevel(step)
            )
          }
        });
        continue;
      }
      if (node.kind === "tool_source") {
        const tool = toolById.get(node.id);
        if (!tool) continue;
        const box = boxOf(node);
        resultNodes.push({
          id: node.id,
          type: "tool_source",
          position,
          width: box.width,
          height: box.height,
          ariaLabel:
            tool.toolName === null
              ? m.flow_graph_tool_node_label_unnamed({ order: String(node.stepOrder) })
              : m.flow_graph_tool_node_label({
                  tool: tool.toolName,
                  server: tool.serverName ?? m.flow_graph_tool_fallback(),
                  order: String(node.stepOrder)
                }),
          data: { tool, mode: userMode }
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
      resultNodes.push({
        id: node.id,
        type: node.kind,
        // These anchors say where data enters and leaves; there is nothing to
        // open on them. Leaving them focusable put tab stops in the graph
        // that answer Enter with nothing, under a description promising they
        // would open a step.
        focusable: false,
        position,
        width: boxOf(node).width,
        height: boxOf(node).height,
        data: { label: ioLabel, nodeType: node.kind, mode: userMode }
      });
    }

    const kindOf = new Map(topology.nodes.map((node) => [node.id, node.kind]));
    const fromAbove = (id: string) => {
      const kind = kindOf.get(id);
      return kind === "input" || kind === "http_source" || kind === "tool_source";
    };
    const resultEdges: Edge[] = drawnEdges.map((edge, index) => {
      const sourceStep =
        edge.sourceStepOrder > 0 ? stepByOrder.get(edge.sourceStepOrder) : undefined;
      const targetStep =
        edge.targetStepOrder != null ? stepByOrder.get(edge.targetStepOrder) : undefined;
      const isBinding = edge.kind === "tool_argument";
      // A binding sends a step's output to a tool's server, which the step's
      // own classification badge does not describe.
      const sourceLevel = isBinding ? null : getClassificationLevel(sourceStep);
      const targetLevel = isBinding ? null : getClassificationLevel(targetStep);
      const isEscalation = sourceLevel != null && targetLevel != null && targetLevel > sourceLevel;
      const isViolation = sourceLevel != null && targetLevel != null && targetLevel < sourceLevel;
      const sourceLabel =
        edge.source === "input"
          ? m.flow_graph_node_input()
          : edge.source === "http-source"
            ? m.flow_graph_node_http_source()
            : kindOf.get(edge.source) === "tool_source"
              ? toolLabel(edge.source)
              : stepLabel(sourceStep, edge.sourceStepOrder);
      const targetLabel =
        edge.target === "output"
          ? m.flow_graph_node_output()
          : edge.target === "http-target"
            ? m.flow_graph_node_http_target()
            : kindOf.get(edge.target) === "tool_source"
              ? toolLabel(edge.target)
              : stepLabel(targetStep, edge.targetStepOrder ?? "?");
      const targetHandle = edge.targetHandle ?? (fromAbove(edge.source) ? "top" : "left");
      const carried = edge.arguments ?? [];
      const allowInsert =
        edge.kind !== "all_previous_steps" &&
        edge.kind !== "http_get" &&
        edge.kind !== "tool" &&
        edge.kind !== "tool_argument" &&
        edge.kind !== "http_post" &&
        // An inserted step would not feed a consumer whose underlag names
        // its producer explicitly, so underlag edges offer no insertion.
        edge.kind !== "input_bindings" &&
        edge.target !== "output";

      const markerColor = isViolation
        ? "var(--negative-default)"
        : isEscalation
          ? "var(--warning-default)"
          : isBinding
            ? "var(--color-accent-default)"
            : // xyflow draws an arrowhead without a colour as nothing at all.
              "var(--border-strongest)";
      return {
        id: `e-${edge.source}-${edge.target}-${edge.kind}-${edge.argument ?? ""}`,
        type: "interactive",
        source: edge.source,
        target: edge.target,
        targetHandle,
        ...(isBinding
          ? {
              ariaLabel: m.flow_graph_edge_tool_argument({
                argument: carried.join(", "),
                source: sourceLabel
              })
            }
          : {}),
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: markerColor },
        data: {
          mode: userMode,
          readOnly: flow.published_version != null,
          dataType: getEdgePayloadKind({ edgeKind: edge.kind, sourceStep, targetStep }),
          edgeKind: edge.kind,
          route: layout.routes[index],
          arguments: carried,
          argumentLabel:
            carried.length === 1
              ? carried[0]
              : m.flow_graph_edge_tool_arguments_count({ count: String(carried.length) }),
          allowInsert,
          sourceStepOrder: edge.sourceStepOrder,
          sourceLabel,
          targetLabel,
          payload: buildPayloadPreview(sourceStep, targetStep, sourceLevel, targetLevel),
          classificationEscalation: isEscalation,
          classificationViolation: isViolation,
          sourceClassification: sourceLevel,
          targetClassification: targetLevel,
          onInsert: handleEdgeInsert,
          onInspect: handleEdgeInspect
        }
      };
    });

    // Tab order follows reading order: a tool node comes right before its step.
    const toolOfStep = new Map(Object.entries(ownerOf).map(([tool, step]) => [step, tool]));
    const nodeById = new Map(resultNodes.map((node) => [node.id, node]));
    const readingOrder = resultNodes
      .filter((node) => node.type !== "tool_source")
      .flatMap((node) => {
        const tool = nodeById.get(toolOfStep.get(node.id) ?? "");
        return tool ? [tool, node] : [node];
      });
    return { nodes: readingOrder, edges: resultEdges, ownerOf, size: layout.size };
  }

  let isExporting = $state(false);
  let exportFailed = $state(false);

  /**
   * Adds a caption band under the captured graph.
   *
   * The image leaves the app for a memo, an email or a printout, where none
   * of the screen around it comes along: nothing says which flow it is, and a
   * dashed edge means nothing without the convention that explains it. Both
   * are drawn in, and the dashed key only when the flow actually has one.
   *
   * Everything here is measured before it is drawn. A long flow name and a
   * narrow image -- which a tall graph scaled to the pixel ceiling produces --
   * would otherwise run text off the edge or lay the key on top of the
   * sentence, and a caption that loses its own words is worse than none.
   */
  async function addExportCaption(
    dataUrl: string,
    spec: {
      width: number;
      height: number;
      scale: number;
      hasBulkEdges: boolean;
      hasBindingEdges: boolean;
    }
  ): Promise<string> {
    const graph = new Image();
    await new Promise((resolve, reject) => {
      graph.onload = resolve;
      graph.onerror = reject;
      graph.src = dataUrl;
    });

    const style = getComputedStyle(containerEl!);
    const font = Math.max(16, Math.round(13 * spec.scale));
    const gap = Math.round(font * 0.6);
    const margin = gap * 2;
    const available = spec.width - margin * 2;

    const measure = document.createElement("canvas").getContext("2d");
    if (!measure) return dataUrl;
    const bodyFont = `${font}px ${style.fontFamily}`;
    const titleFont = `600 ${font}px ${style.fontFamily}`;

    /** Shortens to fit, or gives up when not even an ellipsis would. */
    const fitText = (text: string, maxWidth: number, withFont: string): string | null => {
      measure.font = withFont;
      if (measure.measureText(text).width <= maxWidth) return text;
      let clipped = text;
      while (clipped.length > 0 && measure.measureText(`${clipped}…`).width > maxWidth) {
        clipped = clipped.slice(0, -1);
      }
      return clipped.length === 0 ? null : `${clipped}…`;
    };

    const rawTitle = flow.name ?? "";
    const legendLabel = spec.hasBulkEdges ? m.flow_graph_legend_all_previous() : null;
    const caption = m.flow_graph_order_hint();
    const keyWidth = font * 1.6;
    measure.font = titleFont;
    const titleWidth = measure.measureText(rawTitle).width;
    measure.font = bodyFont;
    const plan = planFlowExportCaption({
      availableWidth: available,
      titleWidth,
      captionWidth: measure.measureText(caption).width,
      legendLabelWidth: legendLabel === null ? null : measure.measureText(legendLabel).width,
      keyWidth,
      gap,
      // Below roughly two characters nothing legible survives, so the row is
      // dropped instead of drawn as a lone ellipsis over the edge.
      minimumTextWidth: font * 2
    });
    if (plan.rows === 0) return dataUrl;

    // The binding key takes a row of its own under the rest, so the planned
    // rows keep their widths.
    const bindingLabel =
      spec.hasBindingEdges && plan.rows > 0
        ? fitText(m.flow_graph_legend_binding(), available - keyWidth - gap, bodyFont)
        : null;
    const rows = plan.rows + (bindingLabel !== null ? 1 : 0);
    const band = font * rows + gap * (rows + 1);
    const canvas = document.createElement("canvas");
    canvas.width = spec.width;
    canvas.height = spec.height + band;
    const ctx = canvas.getContext("2d");
    if (!ctx) return dataUrl;

    // The token, falling back to the container's own resolved background
    // rather than a literal, so the band always matches the capture.
    ctx.fillStyle =
      style.getPropertyValue("--background-color-primary").trim() || style.backgroundColor;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(graph, 0, 0);

    ctx.textBaseline = "top";
    ctx.fillStyle = style.color;
    let row = spec.height + gap;

    if (plan.showTitle) {
      const title = fitText(rawTitle, available, titleFont);
      if (title !== null) {
        ctx.font = titleFont;
        ctx.fillText(title, margin, row);
        row += font + gap;
      }
    }

    ctx.font = bodyFont;
    ctx.globalAlpha = 0.75;
    let legendRow = row;
    if (plan.showCaption) {
      const text = fitText(caption, plan.captionWidth, bodyFont);
      if (text !== null) ctx.fillText(text, margin, row);
      if (!plan.legendSharesCaptionRow) legendRow = row + font + gap;
    }

    if (plan.showLegend && legendLabel !== null) {
      const label = fitText(legendLabel, plan.legendLabelWidth, bodyFont);
      if (label !== null) {
        const labelWidth = measure.measureText(label).width;
        const right = canvas.width - margin;
        ctx.fillText(label, right - labelWidth, legendRow);
        ctx.strokeStyle = style.color;
        ctx.lineWidth = Math.max(1, Math.round(spec.scale));
        ctx.setLineDash([font / 3, font / 3]);
        ctx.beginPath();
        ctx.moveTo(right - labelWidth - gap - keyWidth, legendRow + font / 2);
        ctx.lineTo(right - labelWidth - gap, legendRow + font / 2);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }
    if (bindingLabel !== null) {
      const lastRow = plan.showLegend || plan.showCaption ? legendRow : row - font - gap;
      const bindingRow = lastRow + font + gap;
      ctx.font = bodyFont;
      const labelWidth = measure.measureText(bindingLabel).width;
      const right = canvas.width - margin;
      ctx.fillText(bindingLabel, right - labelWidth, bindingRow);
      ctx.strokeStyle = style.getPropertyValue("--color-accent-default").trim() || style.color;
      ctx.lineWidth = Math.max(1, Math.round(spec.scale));
      ctx.setLineDash([font / 3, font / 4]);
      ctx.beginPath();
      ctx.moveTo(right - labelWidth - gap - keyWidth, bindingRow + font / 2);
      ctx.lineTo(right - labelWidth - gap, bindingRow + font / 2);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    ctx.globalAlpha = 1;

    return canvas.toDataURL("image/png");
  }

  async function exportPng() {
    isExporting = true;
    try {
      const { toPng } = await import("html-to-image");
      const viewportEl = containerEl?.querySelector(".svelte-flow__viewport") as HTMLElement | null;
      const nodeBounds = graphBounds?.();
      // Node bounds leave out the lanes edges take under the steps, so the
      // image spans the laid-out extent as well.
      const bounds = nodeBounds && {
        x: Math.min(nodeBounds.x, 0),
        y: Math.min(nodeBounds.y, 0),
        width:
          Math.max(nodeBounds.x + nodeBounds.width, cachedLayout.size.width) -
          Math.min(nodeBounds.x, 0),
        height:
          Math.max(nodeBounds.y + nodeBounds.height, cachedLayout.size.height) -
          Math.min(nodeBounds.y, 0)
      };
      const size = bounds ? computeFlowExportSize(bounds) : null;
      if (!viewportEl || !bounds || !size) return;

      // The image is of the flow, not of the frame it is viewed through.
      // Rasterising the on-screen element captured only what was visible at
      // the current zoom -- a fitted 17-step flow draws its nodes at 0.17 --
      // so the viewport layer is captured with a size and transform of our
      // own instead, and comes out the same however the graph is framed.
      const viewport = getViewportForBounds(
        bounds,
        size.width,
        size.height,
        size.scale,
        size.scale,
        0
      );

      const dataUrl = await toPng(viewportEl, {
        cacheBust: true,
        // The magnification is already in the transform below. Left alone,
        // html-to-image multiplies by devicePixelRatio on top, which on a
        // retina screen doubled the export past the ceiling just computed.
        pixelRatio: 1,
        width: size.width,
        height: size.height,
        backgroundColor: getComputedStyle(containerEl!)
          .getPropertyValue("--background-color-primary")
          .trim(),
        style: {
          width: `${size.width}px`,
          height: `${size.height}px`,
          transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})`
        }
      });
      const captioned = await addExportCaption(dataUrl, {
        width: size.width,
        height: size.height,
        scale: size.scale,
        hasBulkEdges: edges.some((edge) => edge.data?.edgeKind === "all_previous_steps"),
        hasBindingEdges: edges.some((edge) => edge.data?.edgeKind === "tool_argument")
      });

      const link = document.createElement("a");
      link.download = `${flow.name ?? "flow"}-graph.png`;
      link.href = captioned;
      link.click();
      exportFailed = false;
    } catch (error) {
      // A capture can fail on its own -- a canvas the browser declines to
      // allocate, a font it will not inline. Silence left the reader pressing
      // a button that did nothing.
      console.error("[FlowGraph] flow image export failed", error);
      exportFailed = true;
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

  // Show the whole flow, whatever its size. A floor under the zoom would
  // keep labels larger but crop the graph, and a cropped graph hides that
  // there is more of it -- the worse failure of the two. Complete and small
  // is honest: the shape reads at a glance, the numbered badges survive the
  // scale, and zoom, pan and the minimap recover any detail. maxZoom 1 keeps
  // a short flow at its designed size instead of inflating it to fill.
  // Zero, because any positive floor is a promise to crop some flow and
  // nothing caps how many steps a flow may have -- 0.002 still clips a
  // 400-step Avancerad chain. The fit itself can never be degenerate: a graph
  // with nodes has positive bounds, so min(width, height) ratio is positive,
  // and xyflow returns early when there are none. The interactive floor is
  // the same value so a gesture after a deep fit is not snapped back by d3's
  // scale extent; "Visa hela flödet" is the way back from a deep zoom-out.
  const MIN_ZOOM = 0;

  // The whole graph is framed on arrival, so a minimap earns its place only
  // once someone zooms in past that -- which is Avancerad's kind of reading,
  // and only worth the clutter when there is enough graph to get lost in.
  const showMiniMap = $derived($mode === "power_user" && nodes.length > 6);
  // The key sits bottom right and the minimap bottom left, over the canvas;
  // the fitted graph keeps clear of them.
  const fitViewOptions: FitViewOptions = $derived({
    padding: { x: "4%", top: "6%", bottom: showMiniMap ? "132px" : "84px" },
    maxZoom: 1,
    minZoom: MIN_ZOOM
  });
  // The key names only what this graph draws.
  const legend = $derived({
    binding: edges.some((edge) => edge.data?.edgeKind === "tool_argument"),
    external: nodes.some(
      (node) =>
        node.type === "tool_source" || node.type === "http_source" || node.type === "http_target"
    )
  });

  const handleNodeClick: NodeEventWithPointer<MouseEvent | TouchEvent, Node> = ({ node }) => {
    const stepId = stepOfNode(node?.id);
    if (stepId === null) return;
    onPreview({ type: "activate", id: stepId });
    onnodeclick?.(stepId);
  };

  // xyflow makes every node focusable and treats Enter and Space as "select",
  // which is not what a step node is for here -- clicking one opens it in the
  // editor. Without this, the graph is reachable by keyboard but nothing in
  // it can be opened that way.
  function handleNodeKeydown(event: KeyboardEvent): void {
    if (event.key !== "Enter" && event.key !== " ") return;
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const nodeEl = target.closest<HTMLElement>(".svelte-flow__node");
    const id = nodeEl?.dataset.id;
    if (!id) return;
    const stepId = stepOfNode(id);
    if (stepId === null) return;
    event.preventDefault();
    onPreview({ type: "activate", id: stepId });
    onnodeclick?.(stepId);
  }

  // xyflow ships these in English, and its stock node description offers a
  // delete this graph does not do.
  // Tabbing to a node has to explain as much as pointing at one, so focus
  // drives the same emphasis. Both are previews: neither opens the step.
  function handleFocusIn(event: FocusEvent): void {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const id = target.closest<HTMLElement>(".svelte-flow__node")?.dataset.id;
    // Moving focus is a new gesture wherever it lands, including back where
    // it came from, so it is reported either way.
    // Only keyboard focus previews: the enlarged dialog focuses the first node
    // when it opens, and that must not fade the graph around it.
    const stepId = target.matches(":focus-visible") ? stepOfNode(id) : null;
    onPreview(stepId !== null ? { type: "focus", id: stepId } : { type: "blur" });
  }

  function handleFocusOut(event: FocusEvent): void {
    const next = event.relatedTarget;
    if (next instanceof HTMLElement && next.closest(".svelte-flow__node")) return;
    onPreview({ type: "blur" });
  }

  const ariaLabelConfig = $derived({
    "controls.ariaLabel": m.flow_graph_controls_label(),
    "controls.zoomIn.ariaLabel": m.flow_graph_zoom_in(),
    "controls.zoomOut.ariaLabel": m.flow_graph_zoom_out(),
    "controls.fitView.ariaLabel": m.flow_graph_fit_view(),
    "minimap.ariaLabel": m.flow_graph_minimap_label(),
    "node.a11yDescription.default": m.flow_graph_node_keyboard_hint(),
    "node.a11yDescription.keyboardDisabled": m.flow_graph_node_keyboard_hint(),
    "edge.a11yDescription.default": m.flow_graph_edge_keyboard_hint()
  });
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<!-- The keys are handled for the focusable nodes inside, which xyflow owns
     and renders itself; this element only carries the listener to them. -->
<div
  bind:this={containerEl}
  class={[
    "flow-graph h-full w-full",
    $mode !== "power_user" && "user-mode",
    gliding && "is-gliding"
  ]}
  onkeydown={handleNodeKeydown}
  onfocusin={handleFocusIn}
  onfocusout={handleFocusOut}
>
  <SvelteFlow
    {nodes}
    {edges}
    {nodeTypes}
    {edgeTypes}
    {fitViewOptions}
    {ariaLabelConfig}
    minZoom={MIN_ZOOM}
    proOptions={{ hideAttribution: true }}
    nodesDraggable={false}
    nodesConnectable={false}
    elementsSelectable={true}
    panOnDrag={true}
    zoomOnScroll={true}
    onnodeclick={handleNodeClick}
    onnodepointerenter={({ node }) => {
      const stepId = stepOfNode(node?.id);
      if (stepId !== null) onPreview({ type: "hover", id: stepId });
    }}
    onnodepointerleave={() => onPreview({ type: "unhover" })}
    onedgepointerenter={({ edge }) => {
      if (edge.data?.edgeKind === "tool_argument") hoveredEdgeId = edge.id;
    }}
    onedgepointerleave={() => (hoveredEdgeId = null)}
  >
    <FlowGraphAutoFit
      container={containerEl}
      options={fitViewOptions}
      revision={layoutRevision}
      bind:fit={fitGraph}
      bind:bounds={graphBounds}
    />
    <Controls position="top-left" showLock={false} />
    {#if showMiniMap}
      <MiniMap
        position="bottom-left"
        width={168}
        height={104}
        nodeColor={minimapNodeColor}
        pannable
        zoomable
      />
    {/if}
    {#if $mode === "power_user"}
      <Background variant={BackgroundVariant.Dots} />
      <Panel position="top-right">
        <Button variant="outline" size="xs" onclick={exportPng} disabled={isExporting}>
          <IconDownload class="size-3" aria-hidden="true" />
          {m.flow_graph_download_png()}
        </Button>
        {#if exportFailed}
          <p
            class="border-negative-default bg-primary text-negative-stronger mt-1 max-w-[16rem] rounded border px-2 py-1 text-xs shadow-sm"
            role="alert"
          >
            {m.flow_graph_download_failed()}
          </p>
        {/if}
      </Panel>
    {:else}
      <Background variant={BackgroundVariant.Dots} size={0.5} gap={30} />
    {/if}

    <!-- The one sentence that makes the picture readable: a numbered chain
         run in order, with arrows standing for what each step reads. It
         belongs in Enkel most of all, so it sits outside the mode branch. -->
    <Panel position="bottom-right">
      <div
        class="bg-primary text-secondary border-default flex max-w-[28rem] flex-col gap-1 rounded border px-2.5 py-1.5 text-xs shadow-sm"
      >
        <span>{m.flow_graph_order_hint()}</span>
        {#if $mode === "power_user"}
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span class="flex items-center gap-1.5">
              <svg width="20" height="2" aria-hidden="true"
                ><line x1="0" y1="1" x2="20" y2="1" stroke="currentColor" stroke-width="1.5" /></svg
              >
              {m.flow_graph_legend_direct()}
            </span>
            <span class="flex items-center gap-1.5">
              <svg width="20" height="2" aria-hidden="true"
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
            {#if legend.binding}
              <span class="flex items-center gap-1.5">
                <svg width="20" height="2" aria-hidden="true"
                  ><line
                    x1="0"
                    y1="1"
                    x2="20"
                    y2="1"
                    stroke="var(--color-accent-default)"
                    stroke-width="1.25"
                    stroke-dasharray="5 4"
                  /></svg
                >
                {m.flow_graph_legend_binding()}
              </span>
            {/if}
            {#if legend.external}
              <span class="flex items-center gap-1.5">
                <span
                  class="border-strongest h-2.5 w-5 rounded-sm border border-dashed"
                  aria-hidden="true"
                ></span>
                {m.flow_graph_legend_external()}
              </span>
            {/if}
          </div>
        {/if}
      </div>
    </Panel>
  </SvelteFlow>

  {#if $mode === "power_user" && inspectedEdge}
    <aside
      class="edge-inspector bg-primary border-default absolute top-3 right-3 left-3 z-20 w-auto rounded-lg border shadow-lg sm:left-auto sm:w-[320px]"
    >
      <div class="border-default flex items-center justify-between border-b px-3 py-2">
        <p class="text-sm font-semibold">{m.flow_graph_preview()} · {inspectedEdge.title}</p>
        <Button variant="ghost" size="xs" onclick={() => (inspectedEdge = null)}>
          {m.close()}
        </Button>
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
    --xy-edge-stroke-default: var(--border-strongest);
    --xy-edge-stroke-width-default: 2;
    --xy-edge-stroke-selected-default: var(--color-accent-default);
    --xy-background-pattern-dot-color-default: var(--border-color-dimmer);
    --xy-handle-background-color-default: var(--background-color-primary);
    --xy-handle-border-color-default: var(--border-strongest);
    --xy-minimap-background-color-default: var(--background-color-primary);
    --xy-minimap-mask-background-color-default: transparent;
    --xy-minimap-mask-stroke-color-default: var(--color-accent-default);
    --xy-minimap-mask-stroke-width-default: 3;
    --xy-minimap-node-background-color-default: var(--border-strongest);
    --xy-controls-button-background-color-default: var(--background-color-primary);
    --xy-controls-button-background-color-hover-default: var(--background-color-secondary);
    --xy-controls-button-border-color-default: var(--border-color-default);
  }

  .flow-graph :global(.svelte-flow__minimap) {
    border: 1px solid var(--border-strongest);
    border-radius: 6px;
    overflow: hidden;
  }

  /* Handles only anchor edges here -- nothing is connected by hand -- and a
     dot on every unused side reads as an edge that is missing. */
  .flow-graph :global(.svelte-flow__handle) {
    opacity: 0;
    pointer-events: none;
  }

  /* The nodes draw their own surface; xyflow's default input and output
     frame would draw a second box around them. */
  .flow-graph :global(.svelte-flow__node-input),
  .flow-graph :global(.svelte-flow__node-output) {
    padding: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
  }

  /* Pointing at a step quiets what does not feed it and lifts what does. */
  .flow-graph :global(.flow-node) {
    transition:
      opacity 150ms ease-out,
      transform 150ms ease-out,
      box-shadow 150ms ease-out,
      border-color var(--duration-fast) var(--ease-smooth-out);
  }

  /* The quieting is carried by the edges; a node fades only as far as its
     muted text keeps AA contrast (4.76:1 on white at 0.9, 2.57:1 at 0.6). */
  .flow-graph :global(.flow-node.is-dimmed) {
    opacity: 0.9;
  }

  .flow-graph :global(.flow-node.is-lifted) {
    box-shadow: 0 4px 12px var(--shadow-stronger);
  }

  @media (prefers-reduced-motion: no-preference) {
    .flow-graph :global(.flow-node.is-lifted) {
      transform: translateY(-1px);
    }

    /* A node that appears rises into place; one that moves glides there,
       but only right after the layout changed, never while panning. */
    .flow-graph :global(.flow-node) {
      animation: flow-node-enter 220ms ease-out backwards;
    }

    .flow-graph.is-gliding :global(.svelte-flow__node) {
      transition: transform 200ms ease-out;
    }
  }

  @keyframes -global-flow-node-enter {
    from {
      opacity: 0;
      transform: translateY(4px);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .flow-graph :global(.flow-node) {
      transition: none;
    }
  }
</style>
