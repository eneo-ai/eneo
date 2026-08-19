import { describe, expect, it } from "vitest";

import {
  parseAIBuilderStreamEvent,
  type AIBuilderPublicErrorPayload,
  type AIBuilderStreamEvent
} from "./protocol";

const validPublicError: AIBuilderPublicErrorPayload = {
  schema_version: 2,
  code: "planner_stream_failed",
  category: "internal",
  message: "Planning failed.",
  phase: "router",
  eneo_error_code: 9007,
  request_id: "request-1"
};

const validEvents: AIBuilderStreamEvent[] = [
  { event: "text", data: JSON.stringify({ text: "Building" }) },
  { event: "status", data: JSON.stringify({ status: "architecture_committed" }) },
  {
    event: "question",
    data: JSON.stringify({
      question_id: "output_format",
      question: "Which output do you need?",
      options: [{ id: "docx", label: "Word", value: "docx" }],
      selection_mode: "single",
      allow_custom: false
    })
  },
  {
    event: "requirements_summary",
    data: JSON.stringify({
      requirements_version: "a".repeat(64),
      summary: "Create a report",
      key_decisions: [{ topic: "Output", decision: "Word" }],
      input_description: "Uploaded documents",
      output_description: "One Word report",
      resolved_requirements: [
        {
          requirement_id: "terminal_output",
          selected_value: "docx_document"
        }
      ]
    })
  },
  {
    event: "plan",
    data: JSON.stringify({
      plan_id: "00000000-0000-4000-8000-000000000001",
      proposal: {
        spec: {
          flow_name: "Create a report",
          steps: []
        },
        execution_shape: {
          completion_model_step_count: 0,
          transcription_model_step_count: 0,
          deterministic_step_count: 0,
          schema_constrained_step_count: 0
        }
      }
    })
  },
  {
    event: "usage",
    data: JSON.stringify({
      planner_request_count: 1,
      token_usage_estimated: false,
      last_request_id: null
    })
  },
  {
    event: "error",
    data: JSON.stringify(validPublicError)
  },
  { event: "done", data: "" }
];

const invalidPayloads: AIBuilderStreamEvent[] = [
  { event: "text", data: "{}" },
  { event: "status", data: JSON.stringify({ status: "unknown" }) },
  {
    event: "question",
    data: JSON.stringify({
      question_id: "output_format",
      question: "Which output do you need?",
      selection_mode: "one",
      allow_custom: false
    })
  },
  {
    event: "requirements_summary",
    data: JSON.stringify({
      requirements_version: "a".repeat(64),
      summary: "Create a report",
      key_decisions: "Word",
      input_description: "Uploaded documents",
      output_description: "One Word report"
    })
  },
  {
    // A summary the client cannot name is one the user cannot confirm.
    event: "requirements_summary",
    data: JSON.stringify({
      summary: "Create a report",
      key_decisions: [{ topic: "Output", decision: "Word" }],
      input_description: "Uploaded documents",
      output_description: "One Word report"
    })
  },
  {
    event: "plan",
    data: JSON.stringify({
      plan_id: "not-a-uuid",
      proposal: {
        spec: {
          flow_name: "Create a report",
          steps: []
        },
        execution_shape: {
          completion_model_step_count: 0,
          transcription_model_step_count: 0,
          deterministic_step_count: 0,
          schema_constrained_step_count: 0
        }
      }
    })
  },
  {
    event: "usage",
    data: JSON.stringify({ planner_request_count: "one" })
  },
  {
    event: "usage",
    data: JSON.stringify({ planner_request_count: 1.5 })
  },
  {
    event: "error",
    data: JSON.stringify({
      ...validPublicError,
      category: undefined
    })
  },
  {
    event: "error",
    data: JSON.stringify({
      ...validPublicError,
      code: "not_a_real_code"
    })
  },
  {
    event: "error",
    data: JSON.stringify({
      ...validPublicError,
      eneo_error_code: 9007.5
    })
  },
  {
    event: "error",
    data: JSON.stringify({
      ...validPublicError,
      diagnostic_context: {
        request_id: "request-1",
        unexpected: "value"
      }
    })
  },
  {
    event: "error",
    data: JSON.stringify({
      ...validPublicError,
      unexpected: true
    })
  }
];

function planEventWithStep(step: unknown): AIBuilderStreamEvent {
  const planEvent = structuredClone(validEvents.find((event) => event.event === "plan"));
  if (!planEvent) throw new Error("Plan event fixture is missing.");
  const data = JSON.parse(planEvent.data) as {
    proposal: { spec: { steps: unknown[] } };
  };
  data.proposal.spec.steps.push(step);
  return { event: "plan", data: JSON.stringify(data) };
}

describe("AI Builder stream protocol", () => {
  it.each(validEvents)("accepts a valid $event event", (rawEvent) => {
    expect(parseAIBuilderStreamEvent(rawEvent).event).toBe(rawEvent.event);
  });

  it("preserves typed resolved requirements in confirmation events", () => {
    const rawEvent = validEvents.find((event) => event.event === "requirements_summary");
    if (!rawEvent) throw new Error("Requirements summary fixture is missing.");

    const parsed = parseAIBuilderStreamEvent(rawEvent);

    expect(parsed.event).toBe("requirements_summary");
    if (parsed.event !== "requirements_summary") return;
    expect(parsed.data.resolved_requirements).toEqual([
      {
        requirement_id: "terminal_output",
        selected_value: "docx_document"
      }
    ]);
  });

  it("preserves the unsupported PDF template error as a typed Builder error", () => {
    const rawEvent: AIBuilderStreamEvent = {
      event: "error",
      data: JSON.stringify({
        schema_version: 2,
        code: "pdf_template_unsupported",
        category: "bad_request",
        message: "Filling a fixed PDF template is not supported.",
        phase: "planner",
        eneo_error_code: 9007,
        request_id: "request-pdf-template"
      })
    };

    expect(parseAIBuilderStreamEvent(rawEvent)).toEqual({
      event: "error",
      data: {
        schema_version: 2,
        code: "pdf_template_unsupported",
        category: "bad_request",
        message: "Filling a fixed PDF template is not supported.",
        phase: "planner",
        eneo_error_code: 9007,
        request_id: "request-pdf-template"
      }
    });
  });

  // The backend model refuses a disclosure whose input or output is blank or
  // whitespace-only. A parser that accepted them would render a contract row
  // with nothing in it.
  it.each(["", "   "])("rejects a requirements summary with a blank input (%j)", (blank) => {
    const rawEvent = validEvents.find((event) => event.event === "requirements_summary");
    if (!rawEvent) throw new Error("Requirements summary fixture is missing.");
    const data = { ...JSON.parse(rawEvent.data as string), input_description: blank };

    expect(() =>
      parseAIBuilderStreamEvent({ event: "requirements_summary", data: JSON.stringify(data) })
    ).toThrow(/Invalid AI Builder requirements_summary event payload/);
  });

  it.each(["", "   "])("rejects a requirements summary with a blank output (%j)", (blank) => {
    const rawEvent = validEvents.find((event) => event.event === "requirements_summary");
    if (!rawEvent) throw new Error("Requirements summary fixture is missing.");
    const data = { ...JSON.parse(rawEvent.data as string), output_description: blank };

    expect(() =>
      parseAIBuilderStreamEvent({ event: "requirements_summary", data: JSON.stringify(data) })
    ).toThrow(/Invalid AI Builder requirements_summary event payload/);
  });

  it.each(invalidPayloads)("rejects an invalid $event payload", (rawEvent) => {
    expect(() => parseAIBuilderStreamEvent(rawEvent)).toThrow(
      new RegExp(`Invalid AI Builder ${rawEvent.event} event payload`)
    );
  });

  it("rejects a syntactically valid non-object payload", () => {
    expect(() =>
      parseAIBuilderStreamEvent({ event: "text", data: JSON.stringify("text") })
    ).toThrow(/Invalid AI Builder text event payload/);
  });

  it("rejects an invalid nested plan step", () => {
    expect(() =>
      parseAIBuilderStreamEvent(
        planEventWithStep({
          plan_step_ref: "step_a",
          name: "Write report",
          assistant_spec: { instructions: "Write the report" },
          input_source: "unsupported"
        })
      )
    ).toThrow(/Invalid AI Builder plan event payload at proposal.spec.steps.0.input_source/);
  });

  it.each([59, 7_776_001])("rejects review expiry %i outside the backend contract", (expiry) => {
    expect(() =>
      parseAIBuilderStreamEvent(
        planEventWithStep({
          plan_step_ref: "step_a",
          name: "Write report",
          assistant_spec: { instructions: "Write the report" },
          input_source: "flow_input",
          review_policy: { mode: "view", expires_after_seconds: expiry }
        })
      )
    ).toThrow(
      /Invalid AI Builder plan event payload at proposal.spec.steps.0.review_policy.expires_after_seconds/
    );
  });

  it.each([60, 7_776_000])("accepts review expiry %i at the backend boundary", (expiry) => {
    expect(() =>
      parseAIBuilderStreamEvent(
        planEventWithStep({
          plan_step_ref: "step_a",
          name: "Write report",
          assistant_spec: { instructions: "Write the report" },
          input_source: "flow_input",
          review_policy: { mode: "view", expires_after_seconds: expiry }
        })
      )
    ).not.toThrow();
  });
});
