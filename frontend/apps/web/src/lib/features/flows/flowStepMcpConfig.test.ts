import { describe, expect, it } from "vitest";

import {
  buildFlowStepMcpCompatibilityMap,
  createEmptyFlowStepMcpSummary,
  hasLoadedFlowStepMcpClassificationInputs,
  shouldShowStepMcpSection,
  summarizeAssistantMcp
} from "./flowStepMcpConfig";

describe("flowStepMcpConfig", () => {
  it("hides the MCP section for non-LLM step output modes", () => {
    expect(shouldShowStepMcpSection("transcribe_only")).toBe(false);
    expect(shouldShowStepMcpSection("template_fill")).toBe(false);
    expect(shouldShowStepMcpSection("pass_through")).toBe(true);
  });

  it("summarizes MCP server and enabled tool counts from assistant config", () => {
    expect(
      summarizeAssistantMcp({
        mcp_servers: [
          {
            id: "server-1",
            name: "Weather",
            tools: [
              { id: "tool-1", name: "forecast", is_enabled: true },
              { id: "tool-2", name: "history", is_enabled: false }
            ]
          },
          {
            id: "server-2",
            name: "Maps",
            tools: [{ id: "tool-3", name: "geocode", is_enabled: true }]
          }
        ]
      })
    ).toEqual({
      enabledToolCount: 2,
      hasActiveMcp: true
    });
  });

  it("returns an empty summary when no MCP servers are configured", () => {
    expect(summarizeAssistantMcp({ mcp_servers: [] })).toEqual({
      enabledToolCount: 0,
      hasActiveMcp: false
    });
  });

  it("does not treat a server without enabled tools as active MCP", () => {
    expect(
      summarizeAssistantMcp({
        mcp_servers: [
          {
            id: "server-1",
            name: "Weather",
            tools: [
              { id: "tool-1", name: "forecast", is_enabled: false },
              { id: "tool-2", name: "history", is_enabled: false }
            ]
          }
        ]
      })
    ).toEqual({
      enabledToolCount: 0,
      hasActiveMcp: false
    });
  });

  it("provides a reusable empty MCP summary", () => {
    expect(createEmptyFlowStepMcpSummary()).toEqual({
      enabledToolCount: 0,
      hasActiveMcp: false
    });
  });

  it("computes MCP compatibility from the prior step effective output level", () => {
    const stepOneAssistant = {
      mcp_servers: [
        {
          id: "server-high",
          security_classification: { security_level: 3 }
        }
      ]
    };
    const stepTwo = {
      id: "step-2",
      assistant_id: "assistant-2",
      step_order: 2,
      input_source: "previous_step",
      output_classification_override: null
    };

    expect(
      buildFlowStepMcpCompatibilityMap({
        step: stepTwo as never,
        steps: [
          {
            id: "step-1",
            assistant_id: "assistant-1",
            step_order: 1,
            input_source: "flow_input",
            output_classification_override: null
          },
          stepTwo
        ] as never,
        assistantsById: new Map([
          ["assistant-1", stepOneAssistant],
          ["assistant-2", { mcp_servers: [] }]
        ]),
        availableServers: [
          { id: "server-low", security_classification: { security_level: 2 } },
          { id: "server-ok", security_classification: { security_level: 3 } }
        ],
        spaceSecurityClassification: { security_level: 1 }
      })
    ).toEqual({
      "server-low": { isCompatible: false, requiredLevel: 3 },
      "server-ok": { isCompatible: true, requiredLevel: 3 }
    });
  });

  it("does not let the current step output override affect same-step MCP compatibility", () => {
    const step = {
      id: "step-1",
      assistant_id: "assistant-1",
      step_order: 1,
      input_source: "flow_input",
      output_classification_override: 3
    };

    expect(
      buildFlowStepMcpCompatibilityMap({
        step: step as never,
        steps: [step] as never,
        assistantsById: new Map([["assistant-1", { mcp_servers: [] }]]),
        availableServers: [{ id: "server-low", security_classification: { security_level: 1 } }],
        spaceSecurityClassification: null
      })
    ).toEqual({
      "server-low": { isCompatible: true, requiredLevel: null }
    });
  });

  it("requires prior assistant data before step MCP compatibility is ready", () => {
    expect(
      hasLoadedFlowStepMcpClassificationInputs({
        step: {
          id: "step-2",
          assistant_id: "assistant-2",
          step_order: 2
        } as never,
        steps: [
          { id: "step-1", assistant_id: "assistant-1", step_order: 1 },
          { id: "step-2", assistant_id: "assistant-2", step_order: 2 }
        ] as never,
        assistantsById: new Map([["assistant-2", { mcp_servers: [] }]])
      })
    ).toBe(false);
  });

  it("ignores later steps when computing the current step MCP compatibility", () => {
    const stepOne = {
      id: "step-1",
      assistant_id: "assistant-1",
      step_order: 1,
      input_source: "flow_input",
      output_classification_override: null
    };
    const stepTwo = {
      id: "step-2",
      assistant_id: "assistant-2",
      step_order: 2,
      input_source: "previous_step",
      output_classification_override: null
    };
    const stepThree = {
      id: "step-3",
      assistant_id: "assistant-3",
      step_order: 3,
      input_source: "previous_step",
      output_classification_override: null
    };

    expect(
      buildFlowStepMcpCompatibilityMap({
        step: stepTwo as never,
        steps: [stepOne, stepTwo, stepThree] as never,
        assistantsById: new Map([
          [
            "assistant-1",
            {
              mcp_servers: [{ id: "server-high", security_classification: { security_level: 3 } }]
            }
          ],
          ["assistant-2", { mcp_servers: [] }]
        ]),
        availableServers: [{ id: "server-ok", security_classification: { security_level: 3 } }],
        spaceSecurityClassification: { security_level: 1 }
      })
    ).toEqual({
      "server-ok": { isCompatible: true, requiredLevel: 3 }
    });
  });
});
