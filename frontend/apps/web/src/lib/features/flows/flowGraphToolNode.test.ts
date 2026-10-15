import { describe, expect, it } from "vitest";
import type { FlowToolOption, ToolOptionsLoad } from "./components/tool/toolInputConfig";
import { buildContext } from "./components/flowPromptVariables";
import {
  describeFlowGraphToolNode,
  drawToolBindings,
  toolArgumentHandleId,
  TOOL_NODE_MORE_HANDLE
} from "./flowGraphToolNode";

const option: FlowToolOption = {
  mcp_server_id: "srv",
  mcp_server_name: "SEAB SQL",
  mcp_server_security_level: null,
  tool_id: "t2",
  tool_name: "query_detail_view",
  tool_description: null,
  input_schema: null,
  refusal: null
};
const loaded = (options: FlowToolOption[]): ToolOptionsLoad => ({
  status: "loaded",
  options,
  classificationsEnabled: false,
  refreshing: false
});
const step = (args: Record<string, unknown>) => ({
  input_config: { tool: { mcp_server_id: "srv", tool_id: "t2", arguments: args } }
});
const seabStep = step({
  site: "Sundsvall",
  limit: 50,
  days: "{{step_1.output.structured.anomaly_days}}",
  note: "Dagar: {{ step_1.output.text }}",
  named: "{{Hämta}}",
  later: "{{step_9.output.text}}"
});
// Step 2 of a flow whose step 1 is called "Hämta" and returns JSON.
const context = buildContext(
  [
    { step_order: 1, user_description: "Hämta", output_type: "json", input_config: null },
    { step_order: 2, user_description: "Detaljer", output_type: "text", input_config: null }
  ],
  undefined,
  false,
  2
);

describe("describeFlowGraphToolNode", () => {
  // Kills a node that names no tool or server once the list has them, lists
  // fixed values before the arguments that read other data, drops the count
  // of arguments it does not show, or reads a reference otherwise than the
  // edges do (a later step drawn as bound, a step name drawn as text).
  it("names the tool and its server and lists bound arguments first", () => {
    const node = describeFlowGraphToolNode(seabStep, loaded([option]), context);
    expect([node.toolName, node.serverName, node.problem]).toEqual([
      "query_detail_view",
      "SEAB SQL",
      null
    ]);
    expect(node.rows).toEqual([
      { name: "days", kind: "step", stepOrder: 1, field: "anomaly_days" },
      { name: "note", kind: "reference", text: "Dagar: {{ step_1.output.text }}" },
      { name: "named", kind: "step", stepOrder: 1, field: null }
    ]);
    expect(node.hiddenCount).toBe(3);
    expect(toolArgumentHandleId(node, "days")).toBe("arg:days");
    expect(toolArgumentHandleId(node, "site")).toBe(TOOL_NODE_MORE_HANDLE);
    const later = describeFlowGraphToolNode(
      step({ later: "{{step_9.output.text}}" }),
      loaded([option]),
      context
    );
    expect(later.rows).toEqual([
      { name: "later", kind: "unresolved", text: "{{step_9.output.text}}" }
    ]);
  });

  // Kills a node that claims a name before the list is there, and one that
  // hides why a run could not call the tool.
  it.each([
    [{ status: "loading" } as ToolOptionsLoad, null],
    [loaded([]), { kind: "not_listed" }],
    [
      loaded([{ ...option, refusal: "tool_switched_off_in_space" }]),
      { kind: "refused", refusal: "tool_switched_off_in_space" }
    ]
  ])("says what it knows about an unnamed or unavailable tool", (load, problem) => {
    const node = describeFlowGraphToolNode(step({ days: "x" }), load, context);
    expect(node.problem).toEqual(problem);
    expect(node.rows).toEqual([{ name: "days", kind: "fixed", text: "x" }]);
    if (problem?.kind !== "refused") expect(node.toolName).toBeNull();
  });

  it("marks a tool step that names no tool yet", () => {
    expect(
      describeFlowGraphToolNode({ input_config: null }, loaded([option]), context).problem
    ).toEqual({
      kind: "unchosen"
    });
  });
});

// Kills one edge per hidden argument (a tool with fifteen bound arguments drew
// twelve edges into one point) and a summary edge that forgets which source
// it stands for.
it("draws one counted edge per source for the arguments the node does not list", () => {
  const bound = (order: number) => `{{step_${order}.output.text}}`;
  const tool = describeFlowGraphToolNode(
    step({ a: bound(1), b: bound(1), c: bound(1), d: bound(1), e: bound(1), f: bound(2) }),
    loaded([option]),
    buildContext(
      [1, 2, 3].map((order) => ({
        step_order: order,
        user_description: null,
        output_type: "text" as const,
        input_config: null
      })),
      undefined,
      false,
      3
    )
  );
  const edges = ["a", "b", "c", "d", "e", "f"].map((argument) => ({
    source: argument === "f" ? "s2" : "s1",
    target: "tool-s3",
    kind: "tool_argument",
    argument
  }));
  const tools = new Map([["tool-s3", tool]]);
  const shape = (detailed: boolean) =>
    drawToolBindings(edges, tools, detailed).map((e) => [e.source, e.targetHandle, e.arguments]);
  expect(shape(true)).toEqual([
    ["s1", "arg:a", ["a"]],
    ["s1", "arg:b", ["b"]],
    ["s1", "arg:c", ["c"]],
    ["s1", TOOL_NODE_MORE_HANDLE, ["d", "e"]],
    ["s2", TOOL_NODE_MORE_HANDLE, ["f"]]
  ]);
  expect(shape(false)).toEqual([
    ["s1", TOOL_NODE_MORE_HANDLE, ["a", "b", "c", "d", "e"]],
    ["s2", TOOL_NODE_MORE_HANDLE, ["f"]]
  ]);
});
