import { describe, expect, it } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import { testTranslator } from "@/test/i18n";
import { guidanceLength, guidanceRefusalMessage, modelRefusalMessage } from "./helper-chat-policy";

const t = testTranslator();

describe("guidanceLength", () => {
  it("counts characters as the server does, an emoji as one", () => {
    expect(guidanceLength("")).toBe(0);
    expect(guidanceLength("Tilltala med du")).toBe(15);
    // Two UTF-16 units, one code point.
    expect(guidanceLength("😀")).toBe(1);
  });
});

describe("guidanceRefusalMessage", () => {
  const tooLong = "Texten är för lång. Korta den till högst 4 000 tecken.";

  it("says a validation refusal of a too long guidance in the page's words", () => {
    // The backend's shape: the errors under details, each with a location.
    const current = new EneoApiError("Validation error", {
      status: 422,
      reason: "request_validation_error",
      details: { errors: [{ location: ["body", "guidance"], type: "string_too_long" }] }
    });
    // FastAPI's own list, with loc.
    const legacy = new EneoApiError("Validation error", {
      status: 422,
      details: [{ loc: ["body", "guidance"], type: "string_too_long", msg: "Too long" }]
    });
    expect(guidanceRefusalMessage(current, 4000, t)).toBe(tooLong);
    expect(guidanceRefusalMessage(legacy, 4000, t)).toBe(tooLong);
  });

  it("says any other failure in the catalog's words and that the text is kept", () => {
    const failure = new EneoApiError("Boom", { status: 500, errorId: "e-1" });
    expect(guidanceRefusalMessage(failure, 4000, t)).toBe(
      `${t("error_occurred")} Texten finns kvar, så du kan försöka spara igen.`
    );
    const otherField = new EneoApiError("Validation error", {
      status: 422,
      details: { errors: [{ location: ["body", "enabled"], type: "bool_type" }] }
    });
    expect(guidanceRefusalMessage(otherField, 4000, t)).toContain(
      "Texten finns kvar, så du kan försöka spara igen."
    );
  });
});

describe("modelRefusalMessage", () => {
  it.each([
    [
      "helper_chat_policy_model_unavailable",
      "Modellen är inte aktiverad i organisationen. Välj en annan modell."
    ],
    [
      "helper_chat_policy_model_without_tools",
      "Modellen kan inte använda verktyg, och det behöver hjälpassistenten. Välj en annan modell."
    ]
  ])("says the refusal %s in words with what to do", (reason, message) => {
    const error = new EneoApiError("Refused", { status: 400, reason });
    expect(modelRefusalMessage(error, t)).toBe(message);
  });

  it("says another failure in the catalog's words and what to do", () => {
    const error = new EneoApiError("Boom", { status: 500, errorId: "e-1" });
    expect(modelRefusalMessage(error, t)).toBe(
      `${t("error_occurred")} Välj modellen igen eller välj en annan.`
    );
  });
});
