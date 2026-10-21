import { describe, expect, it } from "vitest";
import { readRuntimeInput } from "./step-configs";
import {
  initialConfiguration,
  kindBlock,
  newStepUpdate,
  STEP_KINDS,
  uniqueStepName,
  type StepKind
} from "./step-kinds";
import { chainIssue, outputModeIssue } from "./step-rules";
import type { FlowStep, InputSource, InputType, OutputMode, OutputType } from "./step-types";
import { makeFlow, makeStep } from "./testing/fixtures";

const OPTIONS = {
  name: "Nytt steg",
  url: "https://api.example.org/arenden",
  tool: { mcp_server_id: "server-1", tool_id: "tool-1", arguments: {} }
};

const twoSteps = makeFlow({
  steps: [
    makeStep({ output_type: "json" }),
    makeStep({
      id: "step-2",
      assistant_id: "assistant-2",
      step_order: 2,
      user_description: "Skriv svar",
      input_source: "previous_step",
      input_type: "json"
    })
  ]
});

describe("the first configuration of each kind", () => {
  const places: [string, number][] = [
    ["first in an empty flow", 1],
    ["between two steps", 2],
    ["last", 3]
  ];
  for (const [place, position] of places) {
    const flow = position === 1 ? makeFlow({ steps: [] }) : twoSteps;
    for (const kind of STEP_KINDS) {
      if (kindBlock(flow, position, kind) !== null) continue;
      it(`is valid for ${kind} ${place}`, () => {
        const config = initialConfiguration(flow, position, kind, OPTIONS);
        const step = {
          input_source: config.input_source as InputSource,
          input_type: config.input_type as InputType,
          output_mode: config.output_mode as OutputMode,
          output_type: config.output_type as OutputType,
          input_bindings: null
        };
        const previous = flow.steps.find((item) => item.step_order === position - 1) ?? null;
        const isLast = position === flow.steps.length + 1;
        expect(chainIssue(step, position, previous?.output_type ?? null)).toBeNull();
        expect(outputModeIssue(step, isLast)).toBeNull();
      });
    }
  }

  it("transcribes uploaded audio", () => {
    const config = initialConfiguration(makeFlow({ steps: [] }), 1, "transcribe", OPTIONS);
    expect(config).toMatchObject({ input_type: "audio", output_mode: "transcribe_only" });
    expect(readRuntimeInput(config.input_config)).toMatchObject({
      enabled: true,
      inputFormat: "audio"
    });
  });
});

describe("where a kind fits", () => {
  const transcript = makeFlow({
    steps: [makeStep({ input_type: "audio", output_mode: "transcribe_only" })]
  });
  const blocks: [string, Parameters<typeof kindBlock>, ReturnType<typeof kindBlock>][] = [
    ["transcription after step 1", [twoSteps, 2, "transcribe"], "first_only"],
    ["speakers without a transcript before", [twoSteps, 2, "speakers"], "needs_transcript_before"],
    ["speakers after a transcript", [transcript, 2, "speakers"], null],
    ["review as the first step", [makeFlow({ steps: [] }), 1, "review"], "needs_step_before"],
    ["HTTP delivery before another step", [twoSteps, 2, "send_http"], "must_be_last"],
    [
      "a document before a step that reads JSON",
      [twoSteps, 2, "document"],
      "next_step_cannot_read"
    ],
    ["a text answer before a step that reads JSON", [twoSteps, 2, "ai"], null]
  ];
  for (const [label, args, block] of blocks) {
    it(`${label}: ${block ?? "fits"}`, () => expect(kindBlock(...args)).toBe(block));
  }

  it("nothing follows a step that sends over HTTP", () => {
    const flow = makeFlow({
      steps: [
        makeStep({
          output_mode: "http_post",
          output_config: { url: "https://x", auth: { mode: "none" } }
        })
      ]
    });
    expect(kindBlock(flow, 2, "ai")).toBe("after_outbound_step");
  });

  it("nothing goes before a first step that takes uploads", () => {
    const flow = makeFlow({ steps: [makeStep({ input_type: "document" })] });
    expect(kindBlock(flow, 1, "ai")).toBe("first_step_takes_uploads");
  });
});

describe("newStepUpdate", () => {
  it("places the new step among every saved step, fenced on the read revision", () => {
    const update = newStepUpdate(twoSteps, 2, "ai", OPTIONS);
    expect(update).toEqual({
      expected_revision: 4,
      definition: {},
      new_steps: [
        {
          name: "Nytt steg",
          configuration: {
            input_source: "previous_step",
            input_type: "json",
            output_mode: "pass_through",
            output_type: "text"
          },
          assistant: {}
        }
      ],
      step_order: [{ step_id: "step-1" }, { new_step: 0 }, { step_id: "step-2" }]
    });
  });

  it("hands the flow's input to a step added first and turns the old first step to read it", () => {
    const flow = makeFlow({ steps: [makeStep({ input_type: "json" }) as FlowStep] });
    const update = newStepUpdate(flow, 1, "document", { ...OPTIONS, format: "pdf" });
    expect(update.new_steps?.[0]?.configuration).toMatchObject({
      input_source: "flow_input",
      output_mode: "render_verbatim",
      output_type: "pdf"
    });
    expect(update.step_order).toEqual([{ new_step: 0 }, { step_id: "step-1" }]);
    expect(update.step_edits).toEqual([
      { step_id: "step-1", changes: { input_source: "previous_step", input_type: "text" } }
    ]);
  });

  it("turns transcription on for a flow's first audio step", () => {
    const update = newStepUpdate(
      makeFlow({ steps: [] }),
      1,
      "transcribe" satisfies StepKind,
      OPTIONS
    );
    expect(update.definition).toEqual({
      metadata_json: { wizard: { transcription_enabled: true } }
    });
  });
});

it("numbers a default name another step already has", () => {
  expect(uniqueStepName(twoSteps, "Sammanfatta")).toBe("Sammanfatta 2");
  expect(uniqueStepName(twoSteps, "Granskning")).toBe("Granskning");
});
