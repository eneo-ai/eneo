import { describe, expect, it } from "vitest";
import { IntricError } from "@intric/intric-js";

import { getTemplateFillErrorMessage } from "./templateFillErrors";

const messages = {
  missingFileContent:
    "Den valda DOCX-mallen kunde inte läsas. Ladda upp mallen på nytt eller välj en annan DOCX-fil.",
  fallback: "fallback"
};

describe("templateFillErrors", () => {
  it("maps missing file content errors to a clearer localized message", () => {
    const error = new IntricError(
      "Selected template file has no binary content.",
      "RESPONSE",
      400,
      0,
      {},
      { endpoint: "GET@test" }
    );

    expect(getTemplateFillErrorMessage(error, messages)).toBe(messages.missingFileContent);
  });

  it("passes through unrelated Intric errors", () => {
    const error = new IntricError(
      "Some other template error",
      "RESPONSE",
      400,
      0,
      {},
      { endpoint: "GET@test" }
    );

    expect(getTemplateFillErrorMessage(error, messages)).toBe("Some other template error");
  });

  it("falls back for unknown errors", () => {
    expect(getTemplateFillErrorMessage(new Error("boom"), messages)).toBe(messages.fallback);
  });
});
