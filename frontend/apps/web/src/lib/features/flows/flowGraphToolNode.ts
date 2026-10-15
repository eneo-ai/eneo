import type { FlowStep } from "@eneo/eneo-js";
import {
  argumentReads,
  boundVariableToken,
  findToolOption,
  holdsVariable,
  readToolInputConfig,
  type ToolOptionsLoad
} from "./components/tool/toolInputConfig";
import type { UnattendedToolRefusal } from "./flowToolRefusal";
import {
  referencedStepOrder,
  structuredOutputField,
  type VariableClassificationContext
} from "./flowVariableTokens";

/** Arguments a tool node lists before it sums up the rest. */
export const TOOL_NODE_SHOWN_ARGUMENTS = 3;

export type FlowGraphToolArgument =
  | { name: string; kind: "fixed"; text: string }
  /** One whole reference to an earlier step: the step and, when it names one, the field. */
  | { name: string; kind: "step"; stepOrder: number; field: string | null }
  /** Any other value that reads an earlier step or the run's input, shown as written. */
  | { name: string; kind: "reference"; text: string }
  /** A value that holds a reference which reads nothing: a later, missing or unknown name. */
  | { name: string; kind: "unresolved"; text: string };

/** True for an argument that an edge into the tool node stands for. */
export function argumentHasEdge(row: FlowGraphToolArgument): boolean {
  return row.kind === "step" || row.kind === "reference";
}

export type FlowGraphToolProblem =
  | { kind: "unchosen" }
  /** The loaded list has no such tool for this flow. */
  | { kind: "not_listed" }
  | { kind: "refused"; refusal: UnattendedToolRefusal };

export type FlowGraphToolNode = {
  /** Whether the editor's tool list, which names the tool, is there yet. */
  listState: ToolOptionsLoad["status"];
  /** Null until the tool list is loaded and has the tool. */
  toolName: string | null;
  serverName: string | null;
  problem: FlowGraphToolProblem | null;
  rows: FlowGraphToolArgument[];
  hiddenCount: number;
};

/** Handle on the node that an edge into one argument ends at. */
export function toolArgumentHandleId(node: FlowGraphToolNode, argument: string): string {
  const shown = node.rows.some((row) => row.name === argument && argumentHasEdge(row));
  return shown ? `arg:${argument}` : TOOL_NODE_MORE_HANDLE;
}
export const TOOL_NODE_MORE_HANDLE = "more";

/**
 * The binding edges as drawn: one per argument the node lists, ending at its
 * row, and one per source step for the arguments it does not list, ending at
 * the node's summary row with the names it carries. The full list belongs to
 * the step editor; a dozen edges into one point would only be a smudge.
 */
export function drawToolBindings<
  E extends { source: string; target: string; kind: string; argument?: string }
>(
  edges: E[],
  tools: ReadonlyMap<string, FlowGraphToolNode>,
  detailed: boolean
): Array<E & { targetHandle?: string; arguments?: string[] }> {
  const drawn: Array<E & { targetHandle?: string; arguments?: string[] }> = [];
  const summarised = new Map<string, string[]>();
  for (const edge of edges) {
    const tool = tools.get(edge.target);
    if (edge.kind !== "tool_argument" || edge.argument === undefined || tool === undefined) {
      drawn.push(edge);
      continue;
    }
    const handle = detailed ? toolArgumentHandleId(tool, edge.argument) : TOOL_NODE_MORE_HANDLE;
    const key = `${edge.source}\u0000${edge.target}`;
    const carried = handle === TOOL_NODE_MORE_HANDLE ? summarised.get(key) : undefined;
    if (carried !== undefined) {
      carried.push(edge.argument);
      continue;
    }
    const names = [edge.argument];
    if (handle === TOOL_NODE_MORE_HANDLE) summarised.set(key, names);
    drawn.push({ ...edge, targetHandle: handle, arguments: names });
  }
  return drawn;
}

// What a value reads comes from the one resolver the edges use, so a row is
// drawn as bound exactly when an edge reaches it.
function argumentRow(
  name: string,
  value: unknown,
  context: VariableClassificationContext
): FlowGraphToolArgument {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  if (!holdsVariable(value)) return { name, kind: "fixed", text };
  const reads = argumentReads(value, context);
  if (reads.stepOrders.length === 0 && !reads.readsFlowInput) {
    return { name, kind: "unresolved", text };
  }
  const token = boundVariableToken(value);
  const stepOrder = token === null ? null : referencedStepOrder(token, context);
  return stepOrder !== null && token !== null
    ? { name, kind: "step", stepOrder, field: structuredOutputField(token) }
    : { name, kind: "reference", text };
}

/**
 * What a tool step's node shows: the tool and its server as far as the
 * editor's tool list knows them, why a run could not call it now, and the
 * arguments, those that read other data first.
 */
export function describeFlowGraphToolNode(
  step: Pick<FlowStep, "input_config">,
  load: ToolOptionsLoad,
  /** The step's own reference context, as the step editor builds it. */
  context: VariableClassificationContext
): FlowGraphToolNode {
  const config = readToolInputConfig(step.input_config);
  const listState = load.status;
  if (config === null) {
    return {
      listState,
      toolName: null,
      serverName: null,
      problem: { kind: "unchosen" },
      rows: [],
      hiddenCount: 0
    };
  }
  const rows = Object.entries(config.arguments).map(([name, value]) =>
    argumentRow(name, value, context)
  );
  const ordered = [...rows.filter(argumentHasEdge), ...rows.filter((row) => !argumentHasEdge(row))];
  const shown = ordered.slice(0, TOOL_NODE_SHOWN_ARGUMENTS);
  const base = { listState, rows: shown, hiddenCount: ordered.length - shown.length };
  if (load.status !== "loaded") {
    return { ...base, toolName: null, serverName: null, problem: null };
  }
  const option = findToolOption(load.options, config);
  if (option === null) {
    return { ...base, toolName: null, serverName: null, problem: { kind: "not_listed" } };
  }
  return {
    ...base,
    toolName: option.tool_name,
    serverName: option.mcp_server_name,
    problem: option.refusal === null ? null : { kind: "refused", refusal: option.refusal }
  };
}

const HEADER = 32;
const PADDING = 8;
const NAME = 22;
const ROW = 20;
const NOTE = 20;
/** Width of a tool node in the detailed graph; the compact pill matches a step. */
export const TOOL_NODE_WIDTH = 280;
export const TOOL_NODE_COMPACT_HEIGHT = 48;

/**
 * Height of a detailed tool node and where each row's centre sits, so the
 * layout, the node and its argument handles agree on one geometry.
 */
export function toolNodeGeometry(node: FlowGraphToolNode): {
  height: number;
  rowCenterY: (index: number) => number;
  moreCenterY: number;
  rowHeight: number;
} {
  const firstRow = HEADER + PADDING + NAME;
  const rowsHeight = (node.rows.length + (node.hiddenCount > 0 ? 1 : 0)) * ROW;
  const note = node.problem === null ? 0 : NOTE;
  return {
    height: firstRow + rowsHeight + note + PADDING,
    rowCenterY: (index) => firstRow + index * ROW + ROW / 2,
    moreCenterY: firstRow + node.rows.length * ROW + ROW / 2,
    rowHeight: ROW
  };
}
