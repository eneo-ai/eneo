import type { FlowStep } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import {
  buildFlowGraphTopology,
  type FlowGraphTopologyStepLike,
  getDownstreamKindForOutput,
  getEdgePayloadKind,
  getRecommendedDisplayedInputType,
  getRuntimeFileOriginKind,
  getSourceHintKind,
  sortSelectableInputTypeOptionsForDisplay,
  flowGraphLayoutKey
} from "./flowStepPresentation";

describe("getSourceHintKind", () => {
  it("explains json output as dual text + structured input", () => {
    expect(getSourceHintKind({ inputSource: "previous_step", previousOutputType: "json" })).toBe(
      "previous_step_json"
    );
  });

  it("explains rendered documents as text-only for chaining", () => {
    expect(getSourceHintKind({ inputSource: "previous_step", previousOutputType: "pdf" })).toBe(
      "previous_step_document_text"
    );
    expect(getSourceHintKind({ inputSource: "previous_step", previousOutputType: "docx" })).toBe(
      "previous_step_document_text"
    );
  });

  it("treats all_previous_steps as tagged text aggregation", () => {
    expect(
      getSourceHintKind({ inputSource: "all_previous_steps", previousOutputType: "json" })
    ).toBe("all_previous_steps");
  });
});

describe("sortSelectableInputTypeOptionsForDisplay", () => {
  it("promotes json ahead of text when the previous step outputs json", () => {
    const ordered = sortSelectableInputTypeOptionsForDisplay({
      inputSource: "previous_step",
      previousOutputType: "json",
      options: [
        { value: "text", disabled: false, legacyInvalid: false },
        { value: "json", disabled: false, legacyInvalid: false },
        { value: "any", disabled: false, legacyInvalid: false }
      ]
    });

    expect(ordered.map((option) => option.value)).toEqual(["json", "text", "any"]);
  });

  it("keeps legacy invalid options pinned first", () => {
    const ordered = sortSelectableInputTypeOptionsForDisplay({
      inputSource: "previous_step",
      previousOutputType: "json",
      options: [
        { value: "file", disabled: false, legacyInvalid: true },
        { value: "text", disabled: false, legacyInvalid: false },
        { value: "json", disabled: false, legacyInvalid: false }
      ]
    });

    expect(ordered.map((option) => option.value)).toEqual(["file", "json", "text"]);
  });
});

describe("getRecommendedDisplayedInputType", () => {
  it("defaults to json for json-producing previous steps", () => {
    const value = getRecommendedDisplayedInputType({
      inputSource: "previous_step",
      previousOutputType: "json",
      options: [
        { value: "text", disabled: false, legacyInvalid: false },
        { value: "json", disabled: false, legacyInvalid: false }
      ]
    });

    expect(value).toBe("json");
  });
});

describe("getDownstreamKindForOutput", () => {
  it("keeps pdf/docx on the text channel", () => {
    expect(getDownstreamKindForOutput("pdf")).toBe("text");
    expect(getDownstreamKindForOutput("docx")).toBe("text");
  });

  it("shows json as both text and structured downstream", () => {
    expect(getDownstreamKindForOutput("json")).toBe("text_and_structured");
  });
});

describe("getEdgePayloadKind", () => {
  it("labels json-to-json edges as structured", () => {
    expect(
      getEdgePayloadKind({
        edgeKind: "previous_step",
        sourceStep: {
          step_order: 1,
          input_source: "flow_input",
          input_type: "text",
          output_type: "json",
          output_mode: "pass_through",
          user_description: "Extract"
        },
        targetStep: {
          step_order: 2,
          input_source: "previous_step",
          input_type: "json",
          output_type: "text",
          output_mode: "pass_through",
          user_description: "Use structured"
        }
      })
    ).toBe("structured");
  });

  it("labels rendered-document chains as text", () => {
    expect(
      getEdgePayloadKind({
        edgeKind: "previous_step",
        sourceStep: {
          step_order: 1,
          input_source: "flow_input",
          input_type: "text",
          output_type: "pdf",
          output_mode: "pass_through",
          user_description: "Render PDF"
        },
        targetStep: {
          step_order: 2,
          input_source: "previous_step",
          input_type: "text",
          output_type: "text",
          output_mode: "pass_through",
          user_description: "Continue"
        }
      })
    ).toBe("text");
  });

  it("hides labels for output edges", () => {
    expect(
      getEdgePayloadKind({
        edgeKind: "flow_output",
        sourceStep: undefined,
        targetStep: null
      })
    ).toBe("none");
  });
});

describe("getRuntimeFileOriginKind", () => {
  it("keeps runtime uploads attached to flow input only", () => {
    expect(getRuntimeFileOriginKind({ needsFileUpload: true, hasFlowInputStep: true })).toBe(
      "flow_input_runtime"
    );
  });

  it("flags http-only flows as having no runtime upload entry point", () => {
    expect(getRuntimeFileOriginKind({ needsFileUpload: false, hasFlowInputStep: false })).toBe(
      "no_runtime_upload"
    );
  });
});

describe("buildFlowGraphTopology", () => {
  const step = (
    order: number,
    inputSource: FlowGraphTopologyStepLike["input_source"],
    outputMode: FlowGraphTopologyStepLike["output_mode"] = "pass_through",
    id?: string
  ): FlowGraphTopologyStepLike => ({
    id: id ?? `s${order}`,
    step_order: order,
    input_source: inputSource,
    output_mode: outputMode,
    output_type: "text"
  });

  const ids = (topology: { nodes: { id: string }[] }) => topology.nodes.map((n) => n.id);

  it("renders an empty flow as input connected to output", () => {
    const t = buildFlowGraphTopology([]);
    expect(ids(t)).toEqual(["input", "output"]);
    expect(t.edges).toEqual([
      {
        source: "input",
        target: "output",
        kind: "flow_output",
        sourceStepOrder: 0,
        targetStepOrder: null
      }
    ]);
  });

  it("gives an HTTP-only flow an external source and no orphan input node", () => {
    const t = buildFlowGraphTopology([step(1, "http_get"), step(2, "previous_step")]);
    expect(ids(t)).toEqual(["s1", "s2", "output", "http-source"]);
    expect(t.edges).toEqual([
      {
        source: "http-source",
        target: "s1",
        kind: "http_get",
        sourceStepOrder: 0,
        targetStepOrder: 1
      },
      { source: "s1", target: "s2", kind: "previous_step", sourceStepOrder: 1, targetStepOrder: 2 },
      {
        source: "s2",
        target: "output",
        kind: "flow_output",
        sourceStepOrder: 2,
        targetStepOrder: null
      }
    ]);
  });

  it("keeps the input node when any step consumes flow input", () => {
    const t = buildFlowGraphTopology([step(1, "flow_input"), step(2, "http_get")]);
    expect(ids(t)).toContain("input");
    expect(ids(t)).toContain("http-source");
    expect(t.edges.filter((e) => e.source === "input").map((e) => e.target)).toEqual(["s1"]);
  });

  it("collapses several HTTP deliveries into one shared receiver node", () => {
    const t = buildFlowGraphTopology([
      step(1, "flow_input", "http_post"),
      step(2, "flow_input", "http_post")
    ]);
    expect(ids(t).filter((id) => id === "http-target")).toHaveLength(1);
    expect(
      t.edges
        .filter((e) => e.kind === "http_post")
        .map((e) => ({ source: e.source, target: e.target, kind: e.kind }))
    ).toEqual([
      { source: "s1", target: "http-target", kind: "http_post" },
      { source: "s2", target: "http-target", kind: "http_post" }
    ]);
  });

  it("collapses several HTTP endpoints into one shared source node", () => {
    const t = buildFlowGraphTopology([step(1, "http_get"), step(2, "http_get")]);
    expect(ids(t).filter((id) => id === "http-source")).toHaveLength(1);
    expect(t.edges.filter((e) => e.kind === "http_get").map((e) => e.target)).toEqual(["s1", "s2"]);
  });

  const toolStep = (order: number, args: Record<string, unknown>): FlowGraphTopologyStepLike => ({
    ...step(order, "tool"),
    input_config: { tool: { mcp_server_id: "srv", tool_id: `t${order}`, arguments: args } }
  });
  const edgeKey = (e: { source: string; target: string; kind: string; argument?: string }) =>
    [e.source, e.target, e.kind, e.argument ?? ""].join(" ");

  // The owner's four-step flow: step 2 reads a tool and none of its arguments
  // is bound. Kills a shared tool node, an edge from step 1 into step 2 or its
  // tool, a doubled edge, and any edge whose end is not a node.
  it("draws a tool step's own source node and no edge from a step it does not read", () => {
    const t = buildFlowGraphTopology([
      step(1, "flow_input", "transcribe_only"),
      toolStep(2, { from_date: "2026-09-01" }),
      step(3, "previous_step"),
      step(4, "previous_step", "render_verbatim")
    ]);
    expect(t.nodes.filter((n) => n.kind === "tool_source")).toEqual([
      { id: "tool-s2", kind: "tool_source", stepOrder: 2 }
    ]);
    expect(t.edges.map(edgeKey)).toEqual([
      "input s1 flow_input ",
      "tool-s2 s2 tool ",
      "s2 s3 previous_step ",
      "s3 s4 previous_step ",
      "s1 output flow_output ",
      "s4 output flow_output "
    ]);
    const nodeIds = new Set(ids(t));
    expect(t.edges.every((e) => nodeIds.has(e.source) && nodeIds.has(e.target))).toBe(true);
  });

  // The SEAB flow: step 2's `days` reads step 1. Kills a binding drawn into
  // the step instead of its tool, a missing binding, a binding to a later
  // step, and step 1 counted as a flow result although step 2 reads it.
  it("draws one binding edge into the tool node per argument bound to an earlier step", () => {
    const t = buildFlowGraphTopology([
      toolStep(1, { view: "features_daily" }),
      toolStep(2, {
        days: "{{step_1.output.structured.anomaly_days}}",
        site: ["{{ step_1.output.text }}", "{{step_3.output.text}}"]
      }),
      step(3, "previous_step")
    ]);
    expect(ids(t).filter((id) => id.startsWith("tool-"))).toEqual(["tool-s1", "tool-s2"]);
    expect(t.edges.filter((e) => e.kind === "tool_argument")).toEqual([
      {
        source: "s1",
        target: "tool-s2",
        kind: "tool_argument",
        argument: "days",
        sourceStepOrder: 1,
        targetStepOrder: 2
      },
      {
        source: "s1",
        target: "tool-s2",
        kind: "tool_argument",
        argument: "site",
        sourceStepOrder: 1,
        targetStepOrder: 2
      }
    ]);
    expect(t.edges.filter((e) => e.target === "output").map((e) => e.source)).toEqual(["s3"]);
    expect(new Set(t.edges.map(edgeKey)).size).toBe(t.edges.length);
  });

  // Kills a resolver that knows only `step_N`: a step named by its name or as
  // the previous step, a value nested in an object, a run-form field and a
  // flow-input alias are bindings too, and a tool that alone reads the run's
  // input still gets the input node.
  it("resolves every reference form the editor offers for a tool argument", () => {
    const t = buildFlowGraphTopology(
      [
        { ...step(1, "http_get"), user_description: "Hämta" },
        step(2, "previous_step"),
        toolStep(3, {
          a: "{{Hämta}}",
          b: "{{föregående_steg}}",
          c: "{{datum_från}}",
          d: { nested: "{{step_1.output.text}}" },
          e: "{{indata_text}}"
        })
      ],
      { fields: [{ name: "datum_från", type: "text" }] }
    );
    expect(t.edges.filter((e) => e.kind === "tool_argument").map(edgeKey)).toEqual([
      "s1 tool-s3 tool_argument a",
      "s2 tool-s3 tool_argument b",
      "input tool-s3 tool_argument c",
      "s1 tool-s3 tool_argument d",
      "input tool-s3 tool_argument e"
    ]);
    expect(ids(t)).toContain("input");
  });

  it("routes an HTTP delivery step to both the receiver and the flow output", () => {
    const t = buildFlowGraphTopology([step(1, "flow_input", "http_post")]);
    expect(ids(t)).toContain("http-target");
    const fromStep = t.edges.filter((e) => e.source === "s1").map((e) => [e.target, e.kind]);
    expect(fromStep).toEqual([
      ["http-target", "http_post"],
      ["output", "flow_output"]
    ]);
  });

  it("fans in all previous steps and still ends at the output", () => {
    const t = buildFlowGraphTopology([
      step(1, "flow_input"),
      step(2, "flow_input"),
      step(3, "all_previous_steps")
    ]);
    expect(t.edges.filter((e) => e.kind === "all_previous_steps").map((e) => e.source)).toEqual([
      "s1",
      "s2"
    ]);
    expect(t.edges.filter((e) => e.target === "output").map((e) => e.source)).toEqual(["s3"]);
  });

  it("lets underlag decide the edges of an all-previous step", () => {
    const t = buildFlowGraphTopology([
      step(1, "flow_input"),
      step(2, "previous_step"),
      step(3, "previous_step"),
      {
        ...step(4, "all_previous_steps"),
        input_bindings: { question: "Samtal: {{ step_2.output.text }}" }
      }
    ]);
    expect(t.edges.filter((e) => e.target === "s4")).toEqual([
      { source: "s2", target: "s4", kind: "input_bindings", sourceStepOrder: 2, targetStepOrder: 4 }
    ]);
    expect(t.edges.filter((e) => e.target === "output").map((e) => e.source)).toEqual(["s3", "s4"]);
  });

  it("rebuilds the layout when only the underlag changes", () => {
    const base: FlowStep = {
      id: "s2",
      assistant_id: "a2",
      step_order: 2,
      user_description: "Summary",
      input_source: "previous_step",
      input_type: "text",
      output_mode: "pass_through",
      output_type: "text"
    };
    const bound = { ...base, input_bindings: { question: "{{ step_1.output.text }}" } };
    expect(flowGraphLayoutKey([bound])).not.toEqual(flowGraphLayoutKey([base]));
    // Kills a key that misses a tool argument rebound to another step.
    const tool = (days: string): FlowStep => ({
      ...base,
      input_source: "tool",
      input_config: { tool: { mcp_server_id: "srv", tool_id: "t", arguments: { days } } }
    });
    expect(flowGraphLayoutKey([tool("{{step_1.output.text}}")])).not.toEqual(
      flowGraphLayoutKey([tool("{{step_2.output.text}}")])
    );
  });

  it("connects form-field underlag to the flow input and fixed text to nothing", () => {
    const t = buildFlowGraphTopology([
      step(1, "flow_input"),
      {
        ...step(2, "all_previous_steps"),
        input_bindings: { question: "Namn: {{ flow_input.namn }}" }
      },
      { ...step(3, "all_previous_steps"), input_bindings: { question: "Skriv en hälsning." } }
    ]);
    expect(t.edges.filter((e) => e.target === "s2")).toEqual([
      { source: "input", target: "s2", kind: "flow_input", sourceStepOrder: 0, targetStepOrder: 2 }
    ]);
    expect(t.edges.filter((e) => e.target === "s3")).toEqual([]);
  });

  it("keeps both the flow-input and the step edge for mixed underlag", () => {
    const t = buildFlowGraphTopology([
      step(1, "flow_input"),
      step(2, "previous_step"),
      {
        ...step(3, "all_previous_steps"),
        input_bindings: { question: "Namn: {{ flow_input.namn }} Samtal: {{ step_1.output.text }}" }
      }
    ]);
    expect(t.edges.filter((e) => e.target === "s3").map((e) => [e.source, e.kind])).toEqual([
      ["input", "flow_input"],
      ["s1", "input_bindings"]
    ]);
  });

  it("falls back to flow input when a previous-step reference has no predecessor", () => {
    const t = buildFlowGraphTopology([step(1, "previous_step")]);
    expect(ids(t)).toContain("input");
    expect(t.edges[0]).toEqual({
      source: "input",
      target: "s1",
      kind: "flow_input",
      sourceStepOrder: 0,
      targetStepOrder: 1
    });
  });
});
