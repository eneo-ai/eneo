import { createTranslator } from "next-intl";
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
