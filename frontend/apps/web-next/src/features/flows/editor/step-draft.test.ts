import { describe, expect, it } from "vitest";
import { readRuntimeInput, withRuntimeInput } from "./step-configs";
import {
  assistantChanges,
  buildEditorUpdate,
  classificationPreviewRequest,
  draftAssistant,
  draftStep,
  stepChanges
} from "./step-draft";
import { applyOutputModeChange } from "./step-rules";
import { assistantConfigOf, stepConfigOf } from "./step-types";
import { makeAssistant, makeFlow, makeStep } from "./testing/fixtures";

describe("stepChanges", () => {
  const saved = stepConfigOf(
    makeStep({
      input_config: { text_processing: { mode: "summarize" }, future_key: { kept: true } },
      output_config: { citation_mode: "inline_inref_sidecar" }
    })
  );

  it("sends only the fields whose draft differs from the saved step", () => {
    const draft = draftStep(saved, { user_description: "Sammanfatta ärendet" });
    expect(stepChanges(saved, draft)).toEqual({ user_description: "Sammanfatta ärendet" });
  });

  it("sends nothing for an edit changed back, or for the same JSON in another key order", () => {
    expect(stepChanges(saved, draftStep(saved, { user_description: "Sammanfatta" }))).toBeNull();
    const reordered = draftStep(saved, {
      input_config: { future_key: { kept: true }, text_processing: { mode: "summarize" } }
    });
    expect(stepChanges(saved, reordered)).toBeNull();
  });

  it("keeps settings the editor does not show when it edits the object that holds them", () => {
    const draft = draftStep(saved, {
      input_config: withRuntimeInput(saved.input_config, "text", { enabled: true, required: true })
    });
    expect(stepChanges(saved, draft)).toEqual({
      input_config: {
        text_processing: { mode: "summarize" },
        future_key: { kept: true },
        runtime_input: { enabled: true, required: true }
      }
    });
  });

  it("keeps another mode's settings when the output mode changes", () => {
    const http = stepConfigOf(
      makeStep({
        step_order: 2,
        input_source: "previous_step",
        output_mode: "http_post",
        output_config: { url: "https://example.org", auth: { mode: "none" }, extra: 1 }
      })
    );
    const draft = applyOutputModeChange(http, "pass_through");
    expect(stepChanges(http, draft)).toEqual({ output_mode: "pass_through" });
  });
});

describe("assistantChanges", () => {
  const saved = assistantConfigOf(
    makeAssistant({
      groups: [{ id: "g1" }, { id: "g2" }] as never,
      completion_model_kwargs: { temperature: 0.25, reasoning_effort: "high" }
    })
  );
  const models = [
    { id: "model-1", supported_model_kwargs: { temperature: { supported: true } } },
    { id: "model-2", supported_model_kwargs: { reasoning_effort: { supported: true } } },
    {
      id: "model-3",
      supported_model_kwargs: {
        temperature: { supported: true },
        reasoning_effort: { supported: true }
      }
    }
  ] as never;

  it("sends the prompt alone when only the instruction changed, keeping its description", () => {
    const draft = draftAssistant(saved, { prompt: "Skriv ett svar." });
    expect(assistantChanges(saved, draft, { promptDescription: "v2", models })).toEqual({
      prompt: { text: "Skriv ett svar.", description: "v2" }
    });
  });

  it("compares knowledge by id, whatever the order", () => {
    const draft = draftAssistant(saved, { groups: [{ id: "g2" }, { id: "g1" }] as never });
    expect(assistantChanges(saved, draft, { models })).toBeNull();
    const fewer = draftAssistant(saved, { groups: [{ id: "g2" }] as never });
    expect(assistantChanges(saved, fewer, { models })).toEqual({ groups: [{ id: "g2" }] });
  });

  it("sends a new model with the settings that model supports", () => {
    const draft = draftAssistant(saved, { completion_model_id: "model-2" });
    expect(assistantChanges(saved, draft, { models })).toEqual({
      completion_model: { id: "model-2" },
      completion_model_kwargs: { reasoning_effort: "high" }
    });
    const keeps = draftAssistant(saved, { completion_model_id: "model-3" });
    expect(assistantChanges(saved, keeps, { models })).toEqual({
      completion_model: { id: "model-3" }
    });
  });
});

describe("buildEditorUpdate", () => {
  it("fences one step edit and one assistant edit on the read revision", () => {
    const flow = makeFlow({ draft_revision: 7 });
    const saved = stepConfigOf(flow.steps[0]!);
    const draft = draftStep(saved, { user_description: "Nytt namn" });
    expect(
      buildEditorUpdate({
        flow,
        stepId: "step-1",
        stepPatch: stepChanges(saved, draft),
        assistantId: "assistant-1",
        assistantUpdate: { prompt: { text: "Hej", description: null } },
        draft
      })
    ).toEqual({
      expected_revision: 7,
      definition: {},
      step_edits: [{ step_id: "step-1", changes: { user_description: "Nytt namn" } }],
      assistants: [
        {
          assistant_id: "assistant-1",
          step_id: "step-1",
          changes: { prompt: { text: "Hej", description: null } }
        }
      ]
    });
  });

  it("turns the flow's transcription on, keeping its other metadata, for its first audio step", () => {
    const flow = makeFlow({
      metadata_json: { form_schema: { fields: [] }, wizard: { transcription_language: "en" } }
    });
    const saved = stepConfigOf(flow.steps[0]!);
    const draft = draftStep(saved, {
      input_type: "audio",
      output_mode: "transcribe_only",
      input_config: withRuntimeInput(null, "audio", { enabled: true, required: true })
    });
    const update = buildEditorUpdate({
      flow,
      stepId: "step-1",
      stepPatch: stepChanges(saved, draft),
      assistantId: "assistant-1",
      assistantUpdate: null,
      draft
    });
    expect(readRuntimeInput(draft.input_config).inputFormat).toBe("audio");
    expect(update.definition).toEqual({
      metadata_json: {
        form_schema: { fields: [] },
        wizard: { transcription_language: "en", transcription_enabled: true }
      }
    });
    expect(update.assistants).toBeUndefined();
  });
});

describe("classificationPreviewRequest", () => {
  it("puts the draft in place of its step and leaves the other steps as saved", () => {
    const second = makeStep({
      id: "step-2",
      assistant_id: "assistant-2",
      step_order: 2,
      input_source: "previous_step"
    });
    const flow = makeFlow({ steps: [makeStep(), second] });
    const draft = draftStep(stepConfigOf(second), { output_classification_override: 3 });
    const assistant = assistantConfigOf(makeAssistant({ id: "assistant-2" }));
    const request = classificationPreviewRequest({
      flow,
      stepId: "step-2",
      draft,
      assistantId: "assistant-2",
      assistant: { ...assistant, prompt: "changed", websites: [{ id: "w1" }] as never },
      savedAssistant: assistant
    });
    const steps = request.steps as unknown as {
      id: string;
      output_classification_override: number | null;
    }[];
    expect(steps.map((step) => [step.id, step.output_classification_override])).toEqual([
      ["step-1", null],
      ["step-2", 3]
    ]);
    // Prose in the prompt plays no part in the rule; knowledge does.
    expect(request.assistants).toEqual([
      { assistant_id: "assistant-2", step_id: "step-2", update: { websites: [{ id: "w1" }] } }
    ]);
  });

  it("sends the references a drafted prompt reads, as the rule reads them", () => {
    const flow = makeFlow({ steps: [makeStep()] });
    const saved = { ...assistantConfigOf(makeAssistant()), prompt: "Läs {{step_1.output.text}}." };
    const request = (prompt: string) =>
      classificationPreviewRequest({
        flow,
        stepId: "step-1",
        draft: stepConfigOf(flow.steps[0]!),
        assistantId: "assistant-1",
        assistant: { ...saved, prompt },
        savedAssistant: saved
      }).assistants;

    expect(request("Läs noga {{ step_1.output.text }} och svara.")).toEqual([]);
    expect(request("Läs {{step_1.output.text}} och {{flow_input.diarienummer}}.")).toEqual([
      {
        assistant_id: "assistant-1",
        step_id: "step-1",
        update: {
          prompt: { text: "{{step_1.output.text}} {{flow_input.diarienummer}}", description: null }
        }
      }
    ]);
    expect(request("Svara kort.")).toEqual([
      {
        assistant_id: "assistant-1",
        step_id: "step-1",
        update: { prompt: { text: "", description: null } }
      }
    ]);
  });

  it("previews a change to one of two steps that share an assistant as the save makes it", () => {
    const second = makeStep({ id: "step-2", step_order: 2, input_source: "previous_step" });
    const flow = makeFlow({ steps: [makeStep(), second] });
    const saved = assistantConfigOf(makeAssistant());
    const drafted = { ...saved, completion_model_id: "model-2" };
    const draft = stepConfigOf(second);

    const preview = classificationPreviewRequest({
      flow,
      stepId: "step-2",
      draft,
      assistantId: "assistant-1",
      assistant: drafted,
      savedAssistant: saved
    });
    const save = buildEditorUpdate({
      flow,
      stepId: "step-2",
      stepPatch: null,
      assistantId: "assistant-1",
      assistantUpdate: assistantChanges(saved, drafted),
      draft
    });

    // Both name the edited step, so only it gets the shared assistant's copy with the change.
    expect(preview.assistants).toEqual([
      {
        assistant_id: "assistant-1",
        step_id: "step-2",
        update: { completion_model: { id: "model-2" } }
      }
    ]);
    expect(save.assistants).toEqual([
      {
        assistant_id: "assistant-1",
        step_id: "step-2",
        changes: { completion_model: { id: "model-2" } }
      }
    ]);
  });
});
