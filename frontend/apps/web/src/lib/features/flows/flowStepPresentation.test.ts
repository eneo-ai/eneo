import { describe, expect, it } from "vitest";
import {
  buildFlowGraphTopology,
  type FlowGraphTopologyStepLike,
  getDownstreamKindForOutput,
  getEdgePayloadKind,
  getRecommendedDisplayedInputType,
  getRuntimeFileOriginKind,
  getSourceHintKind,
  getStepSummaryModel,
  sortSelectableInputTypeOptionsForDisplay
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

describe("getStepSummaryModel", () => {
  it("summarizes source, output, downstream channel, and context badges", () => {
    const summary = getStepSummaryModel({
      step: {
        step_order: 2,
        input_source: "previous_step",
        input_type: "json",
        output_type: "pdf",
        output_mode: "pass_through",
        user_description: "Render"
      },
      previousStep: {
        step_order: 1,
        input_source: "flow_input",
        input_type: "text",
        output_type: "json",
        output_mode: "pass_through",
        user_description: "Extract"
      },
      hasInputTemplateOverride: true,
      hasKnowledge: true,
      hasAttachments: false
    });

    expect(summary).toMatchObject({
      sourceKind: "previous_step_json",
      sourceStepOrder: 1,
      inputFormat: "json",
      outputFormat: "pdf",
      downstreamKind: "text",
      usesInputTemplate: true,
      hasKnowledge: true,
      hasAttachments: false
    });
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
    output_mode: outputMode
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
