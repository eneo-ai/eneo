import type { FlowGraphTopologyEdge, FlowGraphTopologyNode } from "./flowStepPresentation";

export type FlowGraphPoint = { x: number; y: number };
export type FlowGraphBox = { width: number; height: number };

/** Spacing of one rendering of the graph; every length is in flow coordinates. */
export type FlowGraphMetrics = {
  columnGap: number;
  /** Between the source row and the step row. */
  rowGap: number;
  /** Between the lowest step and the first lane under the steps. */
  laneGap: number;
  laneSpacing: number;
  margin: number;
  /** Distance from a step's top to the handles its row edges use. */
  spineHandleY: number;
};

/**
 * How an edge runs between its two handles. Every route is orthogonal; its
 * vertical runs lie in its own column or in a gap between columns, and its
 * horizontal runs on a handle line, between the two rows, or in a lane under
 * the steps:
 *
 * - `direct`: a straight run between neighbours, or a source down into the
 *   step under it;
 * - `drop`: a source down to a step in another column, across the gap
 *   between the rows;
 * - `feed`: a source to a node of the source row further right (a tool
 *   argument that reads the run's input), across the gap between the rows
 *   and into the target from its left;
 * - `rise`: a step up to a node of the source row further right (a tool
 *   argument it fills, an HTTP receiver);
 * - `lane`: a step to a later step or the result past the next column, under
 *   the steps.
 *
 * In a gap, a run that leaves a column keeps to the gap's left half and a run
 * that enters one to its right half, so two edges that only meet in a gap
 * never share a line.
 */
export type FlowGraphEdgeRoute =
  | { kind: "direct" }
  | { kind: "drop"; turnY: number }
  | { kind: "feed"; turnY: number; targetGapX: number }
  | { kind: "rise"; sourceGapX: number; targetGapX: number; turnY: number }
  | { kind: "lane"; sourceGapX: number; targetGapX: number; laneY: number };

export type FlowGraphLayout = {
  /** Top-left corner of each node. */
  positions: Map<string, FlowGraphPoint>;
  /** One route per topology edge, in the same order. */
  routes: FlowGraphEdgeRoute[];
  size: FlowGraphBox;
};

/** The row a node sits in: sources above the steps, steps and the result on one line. */
function isSourceRow(node: FlowGraphTopologyNode): boolean {
  return (
    node.kind === "input" ||
    node.kind === "http_source" ||
    node.kind === "tool_source" ||
    node.kind === "http_target"
  );
}

/**
 * Places the graph on a grid the reader can trust: steps left to right in
 * step order on one line, whatever reads what, so a step's place never
 * depends on its edges. A tool node sits above its step, the result after the
 * last step and an HTTP receiver above the result. The run's input and an
 * HTTP source sit above the first step they feed, unless that place is taken
 * or they feed a tool node: then they move left until the place is free and
 * left of every tool node they feed, and the grid grows a column on the left
 * when it has to.
 */
export function layoutFlowGraph(params: {
  nodes: FlowGraphTopologyNode[];
  edges: FlowGraphTopologyEdge[];
  boxOf: (node: FlowGraphTopologyNode) => FlowGraphBox;
  metrics: FlowGraphMetrics;
}): FlowGraphLayout {
  const { nodes, edges, boxOf, metrics } = params;
  const boxes = new Map(nodes.map((node) => [node.id, boxOf(node)]));
  const box = (id: string): FlowGraphBox => boxes.get(id) ?? { width: 0, height: 0 };
  const rowById = new Map(nodes.map((node) => [node.id, isSourceRow(node)]));

  const steps = nodes
    .filter((node) => node.kind === "step")
    .sort((a, b) => a.stepOrder - b.stepOrder);
  const column = new Map<string, number>(steps.map((node, index) => [node.id, index]));
  const lastColumn = steps.length;
  const stepColumn = new Map(steps.map((node, index) => [node.stepOrder, index]));
  const sourceRowTaken = new Set<number>();
  for (const node of nodes) {
    if (node.kind === "output") column.set(node.id, lastColumn);
    if (node.kind === "http_target" || node.kind === "tool_source") {
      const at = node.kind === "tool_source" ? (stepColumn.get(node.stepOrder) ?? 0) : lastColumn;
      column.set(node.id, at);
      sourceRowTaken.add(at);
    }
  }
  for (const node of nodes) {
    if (column.has(node.id)) continue;
    // A tool node it feeds holds its own column, so the source ends up to its left.
    const columnsFed = edges
      .filter((edge) => edge.source === node.id)
      .map((edge) => column.get(edge.target))
      .filter((index): index is number => index !== undefined);
    let at = columnsFed.length > 0 ? Math.min(...columnsFed) : 0;
    while (sourceRowTaken.has(at)) at -= 1;
    column.set(node.id, at);
    sourceRowTaken.add(at);
  }

  const firstColumn = Math.min(0, ...column.values());
  const columnWidth = Math.max(0, ...nodes.map((node) => box(node.id).width));
  const columnX = (index: number) =>
    metrics.margin + (index - firstColumn) * (columnWidth + metrics.columnGap);
  const columnCentre = (index: number) => columnX(index) + columnWidth / 2;
  // The gap before a column. Runs leaving the column before it keep to its
  // left half, runs entering the column after it to its right half.
  const gapBefore = (index: number) => columnX(index) - metrics.columnGap / 2;
  const side = metrics.laneSpacing / 2;
  const leaving = (from: number) => gapBefore(from + 1) - side;
  const entering = (to: number) => gapBefore(to) + side;

  // Lanes first: they depend only on columns, and how many the band between
  // the rows needs decides how tall that band is, so no two lanes ever share
  // a height.
  const upperLanes = new LaneAllocator();
  const lowerLanes = new LaneAllocator();
  type Planned =
    | { kind: "direct" }
    | { kind: "drop"; lane: number }
    | { kind: "feed"; lane: number; targetGapX: number }
    | { kind: "rise"; lane: number; sourceGapX: number; targetGapX: number }
    | { kind: "lane"; lane: number; sourceGapX: number; targetGapX: number };
  const planned = edges.map((edge): Planned => {
    const from = column.get(edge.source) ?? 0;
    const to = column.get(edge.target) ?? 0;
    const fromSourceRow = rowById.get(edge.source) === true;
    const toSourceRow = rowById.get(edge.target) === true;
    if (fromSourceRow && toSourceRow) {
      const targetGapX = entering(to);
      return { kind: "feed", lane: upperLanes.take(columnCentre(from), targetGapX), targetGapX };
    }
    if (fromSourceRow) {
      if (from === to) return { kind: "direct" };
      return { kind: "drop", lane: upperLanes.take(columnCentre(from), columnCentre(to)) };
    }
    if (toSourceRow) {
      // Into the next column the climb is one straight run up the gap.
      const adjacent = to === from + 1;
      const sourceGapX = adjacent ? gapBefore(to) : leaving(from);
      const targetGapX = adjacent ? gapBefore(to) : entering(to);
      return {
        kind: "rise",
        lane: upperLanes.take(sourceGapX, targetGapX),
        sourceGapX,
        targetGapX
      };
    }
    if (to === from + 1) return { kind: "direct" };
    const sourceGapX = leaving(from);
    const targetGapX = entering(to);
    return { kind: "lane", lane: lowerLanes.take(sourceGapX, targetGapX), sourceGapX, targetGapX };
  });

  const sourceRow = nodes.filter(isSourceRow);
  const sourceRowHeight = Math.max(0, ...sourceRow.map((node) => box(node.id).height));
  // Lane 0 runs half the row gap above the steps and each further lane one
  // spacing higher; the band grows until its highest lane clears the sources.
  const rowGap = Math.max(
    metrics.rowGap,
    metrics.rowGap / 2 + (upperLanes.count + 1) * metrics.laneSpacing
  );
  const spineTop = metrics.margin + (sourceRowHeight > 0 ? sourceRowHeight + rowGap : 0);
  const spineNodes = nodes.filter((node) => !isSourceRow(node));
  const spineBottom = Math.max(
    spineTop,
    ...spineNodes.map((node) => spineTop + box(node.id).height)
  );

  const positions = new Map<string, FlowGraphPoint>();
  for (const node of nodes) {
    const { width, height } = box(node.id);
    const x = columnX(column.get(node.id) ?? 0) + (columnWidth - width) / 2;
    if (isSourceRow(node)) {
      // Bottom-aligned, so the run down to a step is as short as the row gap.
      positions.set(node.id, { x, y: metrics.margin + sourceRowHeight - height });
    } else if (node.kind === "output") {
      // Centred on the handle line of the steps, so the last edge is straight.
      positions.set(node.id, { x, y: spineTop + metrics.spineHandleY - height / 2 });
    } else {
      positions.set(node.id, { x, y: spineTop });
    }
  }

  const turnY = (lane: number) => spineTop - metrics.rowGap / 2 - lane * metrics.laneSpacing;
  const laneY = (lane: number) => spineBottom + metrics.laneGap + lane * metrics.laneSpacing;
  const routes = planned.map((route): FlowGraphEdgeRoute => {
    switch (route.kind) {
      case "direct":
        return route;
      case "drop":
        return { kind: "drop", turnY: turnY(route.lane) };
      case "feed":
        return { kind: "feed", turnY: turnY(route.lane), targetGapX: route.targetGapX };
      case "rise":
        return {
          kind: "rise",
          sourceGapX: route.sourceGapX,
          targetGapX: route.targetGapX,
          turnY: turnY(route.lane)
        };
      case "lane":
        return {
          kind: "lane",
          sourceGapX: route.sourceGapX,
          targetGapX: route.targetGapX,
          laneY: laneY(route.lane)
        };
    }
  });

  const lowestLane =
    lowerLanes.count > 0
      ? spineBottom + metrics.laneGap + (lowerLanes.count - 1) * metrics.laneSpacing
      : spineBottom;
  return {
    positions,
    routes,
    size: {
      width: columnX(lastColumn) + columnWidth + metrics.margin,
      height: lowestLane + metrics.margin
    }
  };
}

/**
 * Gives each horizontal run the first lane no other run reaches, touching
 * included: two runs that met end to end would read as one edge.
 */
class LaneAllocator {
  private lanes: Array<Array<[number, number]>> = [];

  get count(): number {
    return this.lanes.length;
  }

  take(a: number, b: number): number {
    const start = Math.min(a, b);
    const end = Math.max(a, b);
    // A run of no length has nothing to keep apart.
    if (end - start < 0.5) return 0;
    let index = this.lanes.findIndex((runs) =>
      runs.every(([from, to]) => end < from || start > to)
    );
    if (index === -1) {
      index = this.lanes.length;
      this.lanes.push([]);
    }
    this.lanes[index].push([start, end]);
    return index;
  }
}

/** The corners of an edge from its source handle to its target handle. */
export function flowGraphEdgePoints(
  route: FlowGraphEdgeRoute,
  source: FlowGraphPoint,
  target: FlowGraphPoint
): FlowGraphPoint[] {
  switch (route.kind) {
    case "direct": {
      if (source.y === target.y || source.x === target.x) return [source, target];
      // A source above its step drops vertically; a row edge turns midway.
      if (target.y > source.y + 1 && Math.abs(target.x - source.x) < 1) {
        return [source, target];
      }
      const midX = (source.x + target.x) / 2;
      return [source, { x: midX, y: source.y }, { x: midX, y: target.y }, target];
    }
    case "feed":
      return [
        source,
        { x: source.x, y: route.turnY },
        { x: route.targetGapX, y: route.turnY },
        { x: route.targetGapX, y: target.y },
        target
      ];
    case "drop":
      return [source, { x: source.x, y: route.turnY }, { x: target.x, y: route.turnY }, target];
    case "rise":
      return [
        source,
        { x: route.sourceGapX, y: source.y },
        { x: route.sourceGapX, y: route.turnY },
        { x: route.targetGapX, y: route.turnY },
        { x: route.targetGapX, y: target.y },
        target
      ];
    case "lane":
      return [
        source,
        { x: route.sourceGapX, y: source.y },
        { x: route.sourceGapX, y: route.laneY },
        { x: route.targetGapX, y: route.laneY },
        { x: route.targetGapX, y: target.y },
        target
      ];
  }
}

/** Drops repeated corners and corners on a straight run. */
function simplify(points: FlowGraphPoint[]): FlowGraphPoint[] {
  const distinct = points.filter(
    (point, index) =>
      index === 0 ||
      Math.abs(point.x - points[index - 1].x) > 0.5 ||
      Math.abs(point.y - points[index - 1].y) > 0.5
  );
  return distinct.filter((point, index) => {
    if (index === 0 || index === distinct.length - 1) return true;
    const before = distinct[index - 1];
    const after = distinct[index + 1];
    const vertical = Math.abs(before.x - point.x) < 0.5 && Math.abs(point.x - after.x) < 0.5;
    const horizontal = Math.abs(before.y - point.y) < 0.5 && Math.abs(point.y - after.y) < 0.5;
    return !vertical && !horizontal;
  });
}

/**
 * An SVG path through orthogonal corners with rounded turns, and where its
 * label goes: the middle of its longest run, where it is easiest to tell
 * which line it names.
 */
export function roundedOrthogonalPath(
  points: FlowGraphPoint[],
  radius: number
): { path: string; labelX: number; labelY: number } {
  const corners = simplify(points);
  const first = corners[0] ?? { x: 0, y: 0 };
  let path = `M ${first.x} ${first.y}`;
  let label = first;
  let longest = -1;
  for (let index = 1; index < corners.length; index += 1) {
    const from = corners[index - 1];
    const to = corners[index];
    const length = Math.abs(to.x - from.x) + Math.abs(to.y - from.y);
    if (length > longest) {
      longest = length;
      label = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
    }
    const next = corners[index + 1];
    if (!next) {
      path += ` L ${to.x} ${to.y}`;
      continue;
    }
    const lengthOut = Math.abs(next.x - to.x) + Math.abs(next.y - to.y);
    const r = Math.min(radius, length / 2, lengthOut / 2);
    const inX = to.x - Math.sign(to.x - from.x) * r;
    const inY = to.y - Math.sign(to.y - from.y) * r;
    const outX = to.x + Math.sign(next.x - to.x) * r;
    const outY = to.y + Math.sign(next.y - to.y) * r;
    path += ` L ${inX} ${inY} Q ${to.x} ${to.y} ${outX} ${outY}`;
  }
  return { path, labelX: label.x, labelY: label.y };
}
