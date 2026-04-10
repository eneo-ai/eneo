import { describe, expect, it } from "vitest";
import { IntricError } from "@intric/intric-js";

import { getTemplateFillErrorMessage } from "./templateFillErrors";

describe("templateFillErrors", () => {
  it("maps backend template error code to Swedish copy", () => {
    const error = new IntricError(
      "raw backend",
      "RESPONSE",
      400,
      0,
      { code: "flow_template_invalid_archive" },
      { endpoint: "GET@test" }
    );

    expect(getTemplateFillErrorMessage(error, "fallback")).toBe(
      "Den uppladdade filen är inte en giltig Word-mall (.docx). Välj en .docx-fil och försök igen."
    );
  });

  it("maps missing file content errors to localized message fallback", () => {
    const error = new IntricError(
      "Selected template file has no binary content.",
      "RESPONSE",
      400,
      0,
      {},
      { endpoint: "GET@test" }
    );

    expect(getTemplateFillErrorMessage(error, "fallback")).toBe(
      "Den valda DOCX-mallen kunde inte läsas eftersom filinnehållet saknas."
    );
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

    expect(getTemplateFillErrorMessage(error, "fallback")).toBe("Some other template error");
  });

  it("falls back for unknown errors", () => {
    expect(getTemplateFillErrorMessage(new Error("boom"), "fallback")).toBe("fallback");
  });
});
