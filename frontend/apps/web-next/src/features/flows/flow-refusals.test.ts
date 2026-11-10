import { createTranslator } from "use-intl";
import { describe, expect, it } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import en from "@/lib/i18n/messages/en.json";
import sv from "@/lib/i18n/messages/sv.json";
import { makeStep } from "./flow-fixtures";
import { flowRefusalMessage, refusalStep } from "./flow-refusals";

/** The app's real catalog, looked up by any key as the refusals do. */
const translator = (locale: string, messages: Record<string, string>) =>
  createTranslator({ locale, messages });
const t = translator("sv", sv);
const tEn = translator("en", en);

function refusal(code: string, context?: Record<string, unknown>, message = "Refused.") {
  return new EneoApiError(message, { status: 400, code: 9007, reason: code, context });
}

const steps = [
  makeStep(1, { user_description: "Sammanfatta" }),
  makeStep(2, { user_description: "Skriv svar" })
];

describe("flowRefusalMessage", () => {
  it("names the reader, the step it reads and where, with the fix", () => {
    const error = refusal("flow_step_read_lost_producer", {
      step_id: "step-2",
      step_order: 2,
      site: "input_bindings.question",
      reads_step: 1
    });
    const message = flowRefusalMessage(error, steps, t);
    expect(message).toContain("Steg 2: Skriv svar");
    expect(message).toContain("Steg 1: Sammanfatta");
    expect(message).toContain("i sitt underlag");
    expect(flowRefusalMessage(error, steps, tEn)).toContain("Step 2: Skriv svar reads");
  });

  it("says which of the two steps the change moved, or that it removes the producer", () => {
    const read = { step_id: "step-2", step_order: 2, site: "prompt", reads_step: 1 };
    expect(
      flowRefusalMessage(
        refusal("flow_step_read_lost_producer", { ...read, reason: "producer_removed" }),
        steps,
        t
      )
    ).toBe(
      "Steg 2: Skriv svar läser Steg 1: Sammanfatta i sin instruktion, och ändringen tar bort det steget. Ändra först vad Steg 2: Skriv svar läser."
    );
    expect(
      flowRefusalMessage(
        refusal("flow_step_read_lost_producer", { ...read, reason: "producer_moved_after_reader" }),
        steps,
        t
      )
    ).toBe(
      "Steg 2: Skriv svar läser Steg 1: Sammanfatta i sin instruktion och måste ligga efter det. Behåll ordningen, eller ändra först vad Steg 2: Skriv svar läser."
    );
    expect(
      flowRefusalMessage(
        refusal("flow_step_read_lost_producer", {
          ...read,
          reason: "reader_moved_before_producer"
        }),
        steps,
        tEn
      )
    ).toContain(
      "Step 2: Skriv svar reads Step 1: Sammanfatta in its instructions and must come after it."
    );
  });

  it("names the name a renamed step was read by", () => {
    const error = refusal("flow_step_read_lost_producer", {
      step_order: 2,
      site: "input_bindings.question",
      reads_step: 1,
      reads_name: "Sammanfatta",
      reason: "producer_renamed"
    });
    expect(flowRefusalMessage(error, steps, t)).toContain(
      "med namnet ”Sammanfatta” i sitt underlag"
    );
  });

  it("keeps the general sentence for a reason it does not know", () => {
    const error = refusal("flow_step_read_lost_producer", {
      step_order: 2,
      site: "prompt",
      reads_step: 1,
      reason: "something_new"
    });
    expect(flowRefusalMessage(error, steps, t)).toContain(
      "flytta det senare eller byta vad som läses"
    );
  });

  it("names the steps that still read a form field the change removes", () => {
    const error = refusal("flow_form_field_still_read", {
      fields: ["kommun"],
      readers: [
        { field: "kommun", step_id: "step-1", step_order: 1, site: "prompt" },
        { field: "kommun", step_id: "step-2", step_order: 2, site: "input_bindings.question" }
      ]
    });
    expect(flowRefusalMessage(error, steps, t)).toBe(
      "Formulärfältet kommun läses av Steg 1: Sammanfatta, Steg 2: Skriv svar. Ändra först vad stegen läser, eller byt namn på fältet i stället för att ta bort det."
    );
    expect(flowRefusalMessage(error, steps, tEn)).toContain("The form field kommun is read by");
  });

  it("says when the flow is published, or no longer published", () => {
    expect(flowRefusalMessage(refusal("flow_unpublish_required"), steps, t)).toBe(
      t("flow_error_flow_unpublish_required")
    );
    expect(flowRefusalMessage(refusal("flow_not_published"), steps, t)).toMatch(
      /inte publicerat längre/
    );
  });

  it("falls back to the step number when the step is gone", () => {
    const error = refusal("flow_step_read_lost_producer", {
      step_order: 7,
      site: "prompt",
      reads_step: 6
    });
    expect(flowRefusalMessage(error, steps, t)).toContain("Steg 7 läser Steg 6 i sin instruktion");
  });

  it("says that a stale draft was reloaded", () => {
    expect(flowRefusalMessage(refusal("stale_revision"), steps, t)).toMatch(/hade ändrats/);
  });

  it("puts a publication refusal on the step it names, in the catalog's words", () => {
    const message = flowRefusalMessage(
      refusal("typed_io_tool_not_allowed", { step_order: 2, refusal: "space" }),
      steps,
      t
    );
    expect(message).toBe(`Steg 2: Skriv svar: ${t("flow_error_typed_io_tool_not_allowed")}`);
  });

  it("says a publication refusal in the editor's words for the issue the core names", () => {
    // The core's own message is English: "Step 2: output_config must be an object…".
    const error = refusal(
      "flow_step_invalid",
      { issue_code: "template_fill_requires_docx", step_order: 2 },
      "Step 2: output_config must be an object for output_mode 'template_fill'."
    );
    expect(flowRefusalMessage(error, steps, t)).toBe(
      `Steg 2: Skriv svar: ${t("flow_validation_msg_template_fill_requires_docx")}`
    );
  });

  it("says the draft check's sentence for a template step refused without its file", () => {
    const template = makeStep(2, {
      user_description: "Fyll i mall",
      output_mode: "template_fill",
      output_type: "docx",
      output_config: { bindings: {} }
    });
    const error = refusal(
      "flow_step_invalid",
      { step_order: 2 },
      "Step 2: output_config.template_asset_id must be a UUID."
    );
    expect(flowRefusalMessage(error, [steps[0]!, template], t)).toBe(
      `Steg 2: Fyll i mall: ${t("flow_editor_tools_check_template_missing")}`
    );
  });

  it("names the read the core refused and where it sits, by why it reads nothing", () => {
    const at = (reason: string, context: Record<string, unknown>) =>
      flowRefusalMessage(
        refusal("flow_input_binding_invalid_step_reference", {
          step_order: 2,
          issue_code: reason,
          ...context
        }),
        steps,
        t
      );
    expect(
      at("flow_input_binding_invalid_step_reference", { field: "prompt", reference: "datun" })
    ).toBe(
      "Steg 2: Skriv svar: Steget läser {{datun}} i sin instruktion, men inget i flödet heter så. Välj en variabel med Infoga variabel."
    );
    expect(
      at("flow_input_binding_future_step_reference", {
        field: "input_bindings.question",
        reference: "step_3.output.text"
      })
    ).toContain(
      "läser {{step_3.output.text}} i sitt underlag, men det steget har inget resultat än."
    );
    expect(
      at("flow_input_binding_unknown_step_order", {
        field: "output_config.url",
        reference: "step_9.output.text"
      })
    ).toContain(
      "läser {{step_9.output.text}} i sina inställningar för resultatet, men flödet har inget sådant steg."
    );
    // A path names its key; the core's code is the issue when no issue code is given.
    expect(
      flowRefusalMessage(
        refusal("flow_input_binding_unsupported_key", {
          step_order: 2,
          field: "prompt",
          key: "step_1.output.nyckel"
        }),
        steps,
        tEn
      )
    ).toBe(
      "Step 2: Skriv svar: The step reads {{step_1.output.nyckel}} in its instructions, but that value has no such part. Choose a variable with Insert variable."
    );
    // Without a named read, the general sentence.
    expect(at("flow_input_binding_invalid_step_reference", { field: "prompt" })).toBe(
      `Steg 2: Skriv svar: ${t("flow_validation_msg_input_binding_invalid_step")}`
    );
    // A step the underlag lists twice is no read in braces.
    const listed = flowRefusalMessage(
      refusal("flow_input_binding_unsupported_key", {
        step_order: 2,
        field: "input_bindings.source_refs",
        key: "step_1"
      }),
      steps,
      t
    );
    expect(listed).not.toContain("{{step_1}}");
  });

  it("gives the Word field a refusal names to the sentence it picks", () => {
    const sentence = translator("sv", {
      ...sv,
      flow_validation_msg_template_binding_not_scalar: "Fältet {placeholder} tar ett värde."
    });
    expect(
      flowRefusalMessage(
        refusal("template_binding_not_scalar", {
          step_order: 2,
          field: "output_config.bindings",
          placeholder: "Deltagare"
        }),
        steps,
        sentence
      )
    ).toBe("Steg 2: Skriv svar: Fältet Deltagare tar ett värde.");
    // The core's refusal of a list in a Word field, as the catalogs say it.
    const listInField = refusal("template_binding_not_scalar", {
      issue_code: "template_binding_not_scalar",
      step_order: 2,
      field: "output_config.bindings",
      placeholder: "Deltagare"
    });
    expect(flowRefusalMessage(listInField, steps, t)).toMatch(
      /^Steg 2: Skriv svar: Fältet ”Deltagare” i Word-mallen tar ett värde/
    );
    expect(flowRefusalMessage(listInField, steps, tEn)).toContain("“Deltagare”");
  });

  it("points at nothing the publish notice does not show", () => {
    for (const messages of [sv, en]) {
      expect(JSON.stringify(messages)).not.toMatch(/tekniska beskrivningen|technical description/i);
    }
  });

  it("never shows the core's English message: a code without a sentence gets a Swedish one", () => {
    expect(flowRefusalMessage(refusal("something_new", {}, "Nope."), steps, t)).toBe(
      t("request_failed")
    );
    expect(flowRefusalMessage(refusal("something_new", { step_order: 2 }, "Nope."), steps, t)).toBe(
      "Något i Steg 2: Skriv svar behöver ändras. Öppna steget för att se vad."
    );
    expect(flowRefusalMessage(new Error("network"), steps, t)).toBe(t("request_failed"));
  });
});

describe("refusalStep", () => {
  it("finds the step a refusal names, by id first, for the notice to open", () => {
    expect(refusalStep(refusal("x", { step_id: "step-2", step_order: 1 }), steps)?.step).toBe(
      steps[1]
    );
    expect(refusalStep(refusal("x", { step_order: 1 }), steps)?.step).toBe(steps[0]);
    expect(refusalStep(refusal("x", { step_order: 9 }), steps)).toBeNull();
    expect(refusalStep(refusal("x"), steps)).toBeNull();
    expect(refusalStep(new Error("network"), steps)).toBeNull();
  });

  it("opens the step at the field the refusal names", () => {
    const template = makeStep(2, { output_mode: "template_fill", output_type: "docx" });
    const anchor = (
      context: Record<string, unknown>,
      code = "flow_input_binding_invalid_step_reference"
    ) => refusalStep(refusal(code, { step_order: 2, ...context }), [steps[0]!, template])?.anchor;
    expect(anchor({ field: "prompt", reference: "datun" })).toBe("prompt");
    expect(anchor({ field: "output_config.bindings", placeholder: "Deltagare" })).toBe(
      "output_config.template"
    );
    // A lost read names its place as its site.
    expect(anchor({ site: "prompt", reads_step: 1 }, "flow_step_read_lost_producer")).toBe(
      "prompt"
    );
    // Without a field, the code's own field; a code without one opens the step's top.
    expect(anchor({})).toBe("input_bindings");
    expect(anchor({}, "something_new")).toBeNull();
  });
});
