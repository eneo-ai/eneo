import { describe, expect, it } from "vitest";
import type { FlowToolOption, ToolOptionsLoad } from "./components/tool/toolInputConfig";
import { flowGraphEdgePoints, roundedOrthogonalPath, type FlowGraphPoint } from "./flowGraphLayout";
import { planFlowGraph, type FlowGraphDrawnEdge, type FlowGraphPlan } from "./flowGraphPlan";
import { TOOL_NODE_MORE_HANDLE, toolNodeGeometry } from "./flowGraphToolNode";
import type { FlowGraphTopologyStepLike } from "./flowStepPresentation";

const step = (
  order: number,
  input_source: FlowGraphTopologyStepLike["input_source"],
  input_config: FlowGraphTopologyStepLike["input_config"] = null
): FlowGraphTopologyStepLike => ({
  id: `s${order}`,
  step_order: order,
  input_source,
  output_mode: "pass_through",
  output_type: "text",
  input_config
});
const tool = (order: number, args: Record<string, unknown> = {}) =>
  step(order, "tool", { tool: { mcp_server_id: "srv", tool_id: `t${order}`, arguments: args } });
const fromStep = (order: number) => `{{step_${order}.output.text}}`;

// Every tool step of every flow below names a listed tool, so the nodes are
// as tall as they are in the editor.
const toolLoad: ToolOptionsLoad = {
  status: "loaded",
  classificationsEnabled: false,
  refreshing: false,
  options: Array.from({ length: 20 }, (_, index): FlowToolOption => ({
    mcp_server_id: "srv",
    mcp_server_name: "Server",
    mcp_server_security_level: null,
    tool_id: `t${index + 1}`,
    tool_name: `tool_${index + 1}`,
    tool_description: null,
    input_schema: null,
    refusal: null
  }))
};

const ownersFlow = [
  step(1, "flow_input"),
  tool(2, { from_date: "2026-09-01" }),
  step(3, "previous_step"),
  step(4, "previous_step")
];

/** mulberry32: a small seeded generator with full 32-bit state. */
function random(seed: number): (n: number) => number {
  let state = seed >>> 0;
  return (n) => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return Math.floor((((t ^ (t >>> 14)) >>> 0) / 4294967296) * n);
  };
}

/** Flow shapes over every source kind, tool arguments of every kind, underlag and deliveries. */
function generatedFlows(count: number): FlowGraphTopologyStepLike[][] {
  const next = random(20261015);
  const sources = [
    "flow_input",
    "previous_step",
    "all_previous_steps",
    "http_get",
    "tool"
  ] as const;
  return Array.from({ length: count }, () => {
    const size = 1 + next(7);
    return Array.from({ length: size }, (_, index) => {
      const order = index + 1;
      const earlier = () => fromStep(1 + next(order - 1 || 1));
      const source = sources[next(sources.length)];
      if (source === "tool") {
        const reads = [
          "fixed",
          "{{flow_input.text}}",
          ...(order > 1 ? [earlier(), earlier()] : [])
        ];
        const args = Object.fromEntries(
          Array.from({ length: next(6) }, (_, a) => [`a${a}`, reads[next(reads.length)]])
        );
        return tool(order, args);
      }
      const base = step(order, source);
      const withUnderlag =
        order > 2 && next(3) === 0 ? { ...base, input_bindings: { question: earlier() } } : base;
      return next(5) === 0 ? { ...withUnderlag, output_mode: "http_post" as const } : withUnderlag;
    });
  });
}
const generated = generatedFlows(80);
const generatedWithBindings = generated.filter((flow) =>
  planFlowGraph({ steps: flow, toolLoad, detailed: true }).edges.some(
    (edge) => edge.kind === "tool_argument"
  )
).length;

const flows: Array<[string, FlowGraphTopologyStepLike[]]> = [
  ["owner", ownersFlow],
  // A tool step is the first reader of the run's input, and a later tool is
  // the only one: the input node once landed on the tool node.
  ["tool reads the run input", [tool(1, { q: "{{flow_input.text}}" }), step(2, "previous_step")]],
  [
    "later tool reads the run input",
    [step(1, "flow_input"), step(2, "previous_step"), tool(3, { q: "{{flow_input.text}}" })]
  ],
  // s1->s3 and s2->s4 meet in one gap and once read as s1->s4 and s2->s3.
  [
    "lanes meeting in a gap",
    [
      step(1, "flow_input"),
      step(2, "previous_step"),
      { ...step(3, "all_previous_steps"), input_bindings: { question: fromStep(1) } },
      { ...step(4, "all_previous_steps"), input_bindings: { question: fromStep(2) } }
    ]
  ],
  // Four bindings over the steps need four heights between the rows; a fixed
  // row gap once clamped two of them onto one line.
  [
    "four bindings over the steps",
    [
      step(1, "flow_input"),
      step(2, "previous_step"),
      step(3, "previous_step"),
      step(4, "previous_step"),
      ...[1, 2, 3, 4].map((source) => tool(source + 4, { q: fromStep(source) }))
    ]
  ],
  // Shown and summarised arguments from several sources at once.
  [
    "several bindings, shown and hidden",
    [
      step(1, "flow_input"),
      step(2, "previous_step"),
      tool(3, {
        a: fromStep(1),
        b: fromStep(2),
        c: "{{flow_input.text}}",
        d: fromStep(1),
        e: fromStep(2),
        f: "fixed"
      })
    ]
  ],
  [
    "fifteen arguments",
    [
      step(1, "flow_input"),
      tool(
        2,
        Object.fromEntries(
          Array.from({ length: 15 }, (_, i) => [`a${i}`, i < 12 ? fromStep(1) : "fixed"])
        )
      )
    ]
  ],
  ...generated.map((flow, index): [string, FlowGraphTopologyStepLike[]] => [
    `generated ${index}`,
    flow
  ])
];

type Rect = { x: number; y: number; width: number; height: number; kind: string };

function rectOf(plan: FlowGraphPlan, id: string): Rect {
  const node = plan.nodes.find((candidate) => candidate.id === id)!;
  return { ...plan.layout.positions.get(id)!, ...plan.boxOf(node), kind: node.kind };
}

const inSourceRow = (rect: Rect) => rect.kind !== "step" && rect.kind !== "output";

/**
 * Where the handles an edge uses sit, as FlowNodeLlm, FlowNodeIO and
 * FlowNodeTool place them, with the handle FlowGraph gives the edge.
 */
function endpoints(
  plan: FlowGraphPlan,
  edge: FlowGraphDrawnEdge,
  detailed: boolean
): [FlowGraphPoint, FlowGraphPoint, "top" | "left"] {
  const from = rectOf(plan, edge.source);
  const to = rectOf(plan, edge.target);
  const source = inSourceRow(from)
    ? { x: from.x + from.width / 2, y: from.y + from.height }
    : { x: from.x + from.width, y: from.y + plan.metrics.spineHandleY };
  const handle = edge.targetHandle ?? (inSourceRow(from) ? "top" : "left");
  if (handle === "top") return [source, { x: to.x + to.width / 2, y: to.y }, "top"];
  const tool = plan.tools.get(edge.target);
  let handleY = to.kind === "step" ? plan.metrics.spineHandleY : to.height / 2;
  if (tool && detailed) {
    const geometry = toolNodeGeometry(tool);
    const row = tool.rows.findIndex((candidate) => `arg:${candidate.name}` === handle);
    handleY = handle === TOOL_NODE_MORE_HANDLE ? geometry.moreCenterY : geometry.rowCenterY(row);
    expect(handle === TOOL_NODE_MORE_HANDLE || row >= 0).toBe(true);
  }
  return [source, { x: to.x, y: to.y + handleY }, "left"];
}

function overlaps(
  a: { x: number; y: number; width: number; height: number },
  b: { x: number; y: number; width: number; height: number }
) {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

describe("layoutFlowGraph", () => {
  // Kills a layout ranked by edges (it put step 1 top right in the
  // owner's flow) and a source placed away from the step it feeds.
  it("puts steps in step order on one line and each source above the step it feeds", () => {
    const plan = planFlowGraph({ steps: ownersFlow, toolLoad, detailed: true });
    const rect = (id: string) => rectOf(plan, id);
    const steps = ["s1", "s2", "s3", "s4"].map(rect);
    expect(steps.map((s) => s.y)).toEqual([steps[0].y, steps[0].y, steps[0].y, steps[0].y]);
    expect(steps.map((s) => s.x)).toEqual([...steps.map((s) => s.x)].sort((a, b) => a - b));
    expect(new Set(steps.map((s) => s.x)).size).toBe(4);
    for (const [source, target] of [
      ["input", "s1"],
      ["tool-s2", "s2"]
    ]) {
      const above = rect(source);
      const below = rect(target);
      expect(above.x + above.width / 2).toBe(below.x + below.width / 2);
      expect(above.y + above.height).toBeLessThan(below.y);
    }
    const output = rect("output");
    expect(output.x).toBeGreaterThan(steps[3].x + steps[3].width);
    expect(output.y + output.height / 2).toBe(steps[0].y + plan.metrics.spineHandleY);
  });

  // A generator that never binds an argument would leave the tool routes untested.
  it(`binds tool arguments in ${generatedWithBindings} of 80 generated flows`, () => {
    expect(generatedWithBindings).toBeGreaterThanOrEqual(20);
  });

  // The invariants every flow keeps in both modes, through the production
  // plan (bindings summarised, argument handles as drawn). Kills two nodes on
  // one place (the result under the tool node, the input on a tool node), a
  // route through a node, a run into a handle along the node's border, and
  // two edges with different ends drawn on one line (lanes meeting in a gap,
  // lanes clamped onto one height).
  describe.each([
    ["Avancerad", true],
    ["Enkel", false]
  ])("in %s", (_mode, detailed) => {
    it.each(flows)("draws %s without overlap, crossing or merged edges", (_name, steps) => {
      const plan = planFlowGraph({ steps, toolLoad, detailed });
      const { layout } = plan;
      const rects = plan.nodes.map((node) => rectOf(plan, node.id));
      for (const [index, a] of rects.entries()) {
        for (const b of rects.slice(index + 1)) expect(overlaps(a, b)).toBe(false);
      }
      const segments = plan.edges.map((edge, index) => {
        const [source, target, handle] = endpoints(plan, edge, detailed);
        const points = flowGraphEdgePoints(layout.routes[index], source, target);
        const last = points[points.length - 2];
        if (handle === "top") {
          expect([last.x, last.y < target.y]).toEqual([target.x, true]);
        } else {
          expect([last.y, last.x < target.x]).toEqual([target.y, true]);
        }
        // Kills an extent that leaves out the lanes, which cut them from the image.
        for (const point of points) {
          expect(point.x >= 0 && point.x <= layout.size.width).toBe(true);
          expect(point.y >= 0 && point.y <= layout.size.height).toBe(true);
        }
        // A run of no length is not drawn (roundedOrthogonalPath drops it).
        const runs = points
          .slice(0, -1)
          .map((a, i) => [a, points[i + 1]] as const)
          .filter(([a, b]) => a.x !== b.x || a.y !== b.y);
        for (const [a, b] of runs) {
          expect(a.x === b.x || a.y === b.y).toBe(true);
          const segment = {
            x: Math.min(a.x, b.x),
            y: Math.min(a.y, b.y),
            width: Math.abs(a.x - b.x) || 0.01,
            height: Math.abs(a.y - b.y) || 0.01
          };
          for (const node of plan.nodes) {
            if (node.id === edge.source || node.id === edge.target) continue;
            const r = rectOf(plan, node.id);
            const inner = { x: r.x + 1, y: r.y + 1, width: r.width - 2, height: r.height - 2 };
            expect(overlaps(segment, inner)).toBe(false);
          }
        }
        return { edge, runs };
      });
      for (const [i, a] of segments.entries()) {
        for (const b of segments.slice(i + 1)) {
          if (a.edge.source === b.edge.source || a.edge.target === b.edge.target) continue;
          for (const [p, q] of a.runs) {
            for (const [r, t] of b.runs) {
              const vertical = p.x === q.x && r.x === t.x && p.x === r.x;
              const horizontal = p.y === q.y && r.y === t.y && p.y === r.y;
              const [lo1, hi1, lo2, hi2] = vertical
                ? [Math.min(p.y, q.y), Math.max(p.y, q.y), Math.min(r.y, t.y), Math.max(r.y, t.y)]
                : [Math.min(p.x, q.x), Math.max(p.x, q.x), Math.min(r.x, t.x), Math.max(r.x, t.x)];
              const shared =
                (vertical || horizontal) && Math.min(hi1, hi2) - Math.max(lo1, lo2) >= 0;
              expect(shared).toBe(false);
            }
          }
        }
      }
    });
  });
});

describe("roundedOrthogonalPath", () => {
  // Kills a path that leaves its corners square or places the label off the
  // line.
  it("rounds each turn and labels the middle of the longest run", () => {
    const { path, labelX, labelY } = roundedOrthogonalPath(
      [
        { x: 0, y: 0 },
        { x: 10, y: 0 },
        { x: 10, y: 100 },
        { x: 40, y: 100 }
      ],
      8
    );
    expect(path).toBe("M 0 0 L 5 0 Q 10 0 10 5 L 10 92 Q 10 100 18 100 L 40 100");
    expect([labelX, labelY]).toEqual([10, 50]);
  });
});
