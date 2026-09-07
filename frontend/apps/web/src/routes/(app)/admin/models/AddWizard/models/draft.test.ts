import type { CompletionModel } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";

import {
  applyCatalogModelToDraft,
  completionCreateCapabilities,
  completionUpdateCapabilities,
  createEmptyDraft,
  declareStrictToolSchema,
  draftToWizardModel,
  isStrictToolSchemaDeclared,
  modelToDraft
} from "./draft";

function completionModel(
  capabilities: { supports_tool_calling?: boolean; supports_strict_tool_schema?: boolean } = {}
): CompletionModel {
  return {
    id: "m1",
    name: "gpt-old",
    nickname: "GPT",
    hosting: "eu",
    description: "",
    max_input_tokens: 128000,
    max_output_tokens: 4096,
    vision: false,
    reasoning: false,
    is_deprecated: false,
    supported_model_kwargs: {},
    token_limit: 128000,
    supports_tool_calling: capabilities.supports_tool_calling ?? true,
    supports_strict_tool_schema: capabilities.supports_strict_tool_schema ?? true
  };
}

describe("the strict tool-schema declaration belongs to one route", () => {
  it("is shown for a saved model while its identifier stays, and not sent unless touched", () => {
    const draft = modelToDraft(completionModel(), "completion");
    expect(isStrictToolSchemaDeclared(draft)).toBe(true);
    // Saving an unrelated field must not re-assert a declaration the server
    // may have withdrawn since the form was opened.
    expect(completionUpdateCapabilities(draft)).toEqual({
      vision: false,
      reasoning: false,
      supports_tool_calling: true
    });
  });

  it("becomes ineffective when the identifier is edited, and returns with it", () => {
    const draft = modelToDraft(completionModel(), "completion");
    draft.name = "gpt-new";
    expect(isStrictToolSchemaDeclared(draft)).toBe(false);
    draft.name = "gpt-old";
    expect(isStrictToolSchemaDeclared(draft)).toBe(true);
    // Untouched either way: the update leaves the flag to the server.
    expect("supports_strict_tool_schema" in completionUpdateCapabilities(draft)).toBe(false);
  });

  it("compares the identifier as a request submits it, so surrounding whitespace is no move", () => {
    const draft = modelToDraft(completionModel(), "completion");
    draft.name = " gpt-old ";
    expect(isStrictToolSchemaDeclared(draft)).toBe(true);
    expect(draftToWizardModel(draft).name).toBe("gpt-old");
    draft.name = " gpt-new ";
    declareStrictToolSchema(draft, true);
    expect(draft.strictToolSchemaRoute).toBe("gpt-new");
    expect(draftToWizardModel(draft).supportsStrictToolSchema).toBe(true);
  });

  it("is withdrawn or declared again for the new route only by an explicit choice", () => {
    const draft = modelToDraft(completionModel(), "completion");
    draft.name = "gpt-new";
    declareStrictToolSchema(draft, true);
    expect(draft.strictToolSchemaRoute).toBe("gpt-new");
    expect(completionUpdateCapabilities(draft)).toEqual({
      vision: false,
      reasoning: false,
      supports_tool_calling: true,
      supports_strict_tool_schema: true
    });
    declareStrictToolSchema(draft, false);
    expect(completionUpdateCapabilities(draft).supports_strict_tool_schema).toBe(false);
  });

  it("does not survive picking a catalog model with another identifier", () => {
    const draft = modelToDraft(completionModel(), "completion");
    const next = applyCatalogModelToDraft(
      draft,
      { name: "gpt-new", supports_function_calling: true },
      "completion"
    );
    expect(next.supportsToolCalling).toBe(true);
    expect(isStrictToolSchemaDeclared(next)).toBe(false);
    expect(draftToWizardModel(next).supportsStrictToolSchema).toBe(false);
  });

  it("creates with a total capability projection", () => {
    const draft = createEmptyDraft("completion", "openai");
    draft.name = "gpt-new";
    draft.supportsToolCalling = true;
    expect(completionCreateCapabilities(draftToWizardModel(draft))).toEqual({
      vision: false,
      reasoning: false,
      supports_tool_calling: true,
      supports_strict_tool_schema: false
    });
    declareStrictToolSchema(draft, true);
    expect(
      completionCreateCapabilities(draftToWizardModel(draft)).supports_strict_tool_schema
    ).toBe(true);
  });

  it("starts undeclared for a saved model without the flag", () => {
    const saved = modelToDraft(
      completionModel({ supports_strict_tool_schema: false }),
      "completion"
    );
    expect(isStrictToolSchemaDeclared(saved)).toBe(false);
    expect("supports_strict_tool_schema" in completionUpdateCapabilities(saved)).toBe(false);
  });
});
