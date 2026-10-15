import { buildContext } from "./components/flowPromptVariables";
import type { ToolOptionsLoad } from "./components/tool/toolInputConfig";
import {
  layoutFlowGraph,
  type FlowGraphBox,
  type FlowGraphLayout,
  type FlowGraphMetrics
} from "./flowGraphLayout";
import {
  describeFlowGraphToolNode,
  drawToolBindings,
  TOOL_NODE_COMPACT_HEIGHT,
  TOOL_NODE_WIDTH,
  toolNodeGeometry,
  type FlowGraphToolNode
} from "./flowGraphToolNode";
import {
  buildFlowGraphTopology,
  type FlowGraphTopologyEdge,
  type FlowGraphTopologyNode,
  type FlowGraphTopologyStepLike
} from "./flowStepPresentation";

/** Every length the layout and the nodes have to agree on, per mode. */
export const FLOW_GRAPH_METRICS: Record<"detailed" | "compact", FlowGraphMetrics> = {
  detailed: {
    columnGap: 96,
    rowGap: 72,
    laneGap: 28,
    laneSpacing: 12,
    margin: 20,
    spineHandleY: 18
  },
  compact: { columnGap: 64, rowGap: 56, laneGap: 20, laneSpacing: 10, margin: 16, spineHandleY: 24 }
};

export type FlowGraphDrawnEdge = FlowGraphTopologyEdge & {
  targetHandle?: string;
  arguments?: string[];
};

export type FlowGraphPlan = {
  nodes: FlowGraphTopologyNode[];
  /** The edges as drawn, tool bindings summarised; `layout.routes` follows this order. */
  edges: FlowGraphDrawnEdge[];
  tools: Map<string, FlowGraphToolNode>;
  /** Tool node id -> the id of the step it belongs to. */
  ownerOf: Record<string, string>;
  boxOf: (node: FlowGraphTopologyNode) => FlowGraphBox;
  metrics: FlowGraphMetrics;
  layout: FlowGraphLayout;
};

/**
 * Everything Flödesvy draws, before xyflow: the nodes and edges, what each
 * tool node shows, the size of every node and where it all goes. The
 * component only turns this into xyflow nodes and edges.
 */
export function planFlowGraph(params: {
  steps: FlowGraphTopologyStepLike[];
  formSchema?: Parameters<typeof buildContext>[1];
  toolLoad: ToolOptionsLoad;
  detailed: boolean;
}): FlowGraphPlan {
  const { formSchema, toolLoad, detailed } = params;
  const steps = [...params.steps].sort((a, b) => a.step_order - b.step_order);
  const metrics = FLOW_GRAPH_METRICS[detailed ? "detailed" : "compact"];
  const topology = buildFlowGraphTopology(steps, formSchema);
  const byOrder = new Map(steps.map((step) => [step.step_order, step]));
  const tools = new Map<string, FlowGraphToolNode>();
  const ownerOf: Record<string, string> = {};
  for (const node of topology.nodes) {
    if (node.kind !== "tool_source") continue;
    const step = byOrder.get(node.stepOrder);
    if (!step) continue;
    const context = buildContext(steps, formSchema, false, step.step_order);
    tools.set(node.id, describeFlowGraphToolNode(step, toolLoad, context));
    ownerOf[node.id] = step.id ?? `step-${step.step_order}`;
  }

  // The step box is what the lanes under the steps keep clear of; a card
  // with a two-line name and wrapped badges stays inside it.
  const stepBox = detailed ? { width: 300, height: 140 } : { width: 200, height: 48 };
  const placeBox = detailed ? { width: 170, height: 44 } : { width: 150, height: 40 };
  const boxOf = (node: FlowGraphTopologyNode): FlowGraphBox => {
    if (node.kind === "step") return stepBox;
    if (node.kind === "tool_source") {
      const tool = tools.get(node.id);
      return detailed && tool
        ? { width: TOOL_NODE_WIDTH, height: toolNodeGeometry(tool).height }
        : { width: 200, height: TOOL_NODE_COMPACT_HEIGHT };
    }
    return placeBox;
  };
  const edges = drawToolBindings(topology.edges, tools, detailed);
  const layout = layoutFlowGraph({ nodes: topology.nodes, edges, boxOf, metrics });
  return { nodes: topology.nodes, edges, tools, ownerOf, boxOf, metrics, layout };
}
