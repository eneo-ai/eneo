import { describe, expect, it } from "vitest";

import { describeBuilderToolStep } from "./builderToolStep";
import type { AIBuilderSessionTool } from "./protocol";

const SERVER = "11111111-1111-4111-8111-111111111111";
const TOOL = "22222222-2222-4222-8222-222222222221";

const LISTED: AIBuilderSessionTool[] = [
  {
    ref: "tool_a",
    mcp_server_id: SERVER,
    mcp_server_name: "Records",
    mcp_server_security_level: null,
    tool_id: TOOL,
    tool_name: "lookup",
    tool_description: null,
    refusal: null
  }
];

const context = {
  tools: LISTED,
  formFields: [{ name: "from_date", label: "Från datum", type: "date" }],
  stepNumberOf: (ref: string) => (ref === "step_a" ? 1 : null)
};

function toolStep(toolId: string, args: Record<string, unknown>) {
  return {
    input_source: "tool" as const,
    input_config: { tool: { mcp_server_id: SERVER, tool_id: toolId, arguments: args } }
  };
}

describe("describeBuilderToolStep", () => {
  // Kills: an argument's source misread (a run-form field shown by its name
  // or as text, an earlier step's field without its step, a fixed value
  // that merely looks like a reference read as one), and a tool the list
  // does not name given another tool's names.
  it("says where each argument comes from and names the tool from the session's list", () => {
    const described = describeBuilderToolStep(
      toolStep(TOOL, {
        limit: 5,
        from: "{{ flow_input.from_date }}",
        days: "{{ step_a.output.structured.anomaly_days }}",
        whole: "{{ step_a.output.text }}",
        note: "see {{ step_a.output.text }} too",
        later: "{{ step_x.output.text }}"
      }),
      context
    );

    expect(described).toEqual({
      tool: { serverName: "Records", toolName: "lookup" },
      arguments: [
        { name: "limit", kind: "fixed", text: "5" },
        { name: "from", kind: "run_input", label: "Från datum" },
        { name: "days", kind: "earlier_step", stepNumber: 1, field: "anomaly_days" },
        { name: "whole", kind: "earlier_step", stepNumber: 1, field: null },
        { name: "note", kind: "reference", text: "see {{ step_a.output.text }} too" },
        { name: "later", kind: "reference", text: "{{ step_x.output.text }}" }
      ]
    });
    expect(describeBuilderToolStep(toolStep("gone", {}), context)?.tool).toBeNull();
  });

  // Kills: a step without a readable tool choice drawn as a tool step.
  it.each([
    { input_source: "flow_input" as const, input_config: null },
    { input_source: "tool" as const, input_config: { tool: { tool_id: TOOL } } },
    { input_source: "tool" as const, input_config: null }
  ])("describes no tool for a step that names none (%#)", (step) => {
    expect(describeBuilderToolStep(step, context)).toBeNull();
  });
});
