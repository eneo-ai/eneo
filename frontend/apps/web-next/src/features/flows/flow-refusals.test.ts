import { createTranslator } from "use-intl";
import { describe, expect, it } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import en from "@/lib/i18n/messages/en.json";
import sv from "@/lib/i18n/messages/sv.json";
import { makeStep } from "./flow-fixtures";
import { flowRefusalMessage } from "./flow-refusals";

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
    ).toContain("flyttar det steget efter Steg 2: Skriv svar");
    expect(
      flowRefusalMessage(
        refusal("flow_step_read_lost_producer", {
          ...read,
          reason: "reader_moved_before_producer"
        }),
        steps,
        tEn
      )
    ).toContain("the change moves Step 2: Skriv svar before that step");
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
      "eller få Steg 2: Skriv svar att läsa ett annat steg"
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

  it("falls back to the core's message for a code without a sentence", () => {
    expect(flowRefusalMessage(refusal("something_new", {}, "Nope."), steps, t)).toBe("Nope.");
    expect(flowRefusalMessage(new Error("network"), steps, t)).toBe(t("request_failed"));
  });
});
