import type { CompletionModel, ImageModel } from "@eneo/eneo-js";
import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy({}, { get: (_target, key) => () => String(key) })
}));

import {
  applyCatalogModelToDraft,
  completionCreateCapabilities,
  completionUpdateCapabilities,
  createEmptyDraft,
  declareStrictToolSchema,
  draftToWizardModel,
  findDraftCostOverflow,
  isDraftComplete,
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

const imageModel = {
  id: "im-1",
  name: "gpt-image-1",
  nickname: "GPT Image",
  family: "openai",
  hosting: "usa",
  is_deprecated: false,
  description: null,
  cost_per_image: "0.04",
  default_size: "1536x1024",
  default_quality: "high",
  security_classification: null
} as unknown as ImageModel;

describe("image model drafts", () => {
  it("starts with auto defaults and no cost", () => {
    const draft = createEmptyDraft("image", "openai");

    expect(draft.defaultSize).toBe("auto");
    expect(draft.defaultQuality).toBe("auto");
    expect(draft.costPerImageStr).toBe("");
  });

  it("maps an existing image model into the form", () => {
    const draft = modelToDraft(imageModel, "image");

    expect(draft.name).toBe("gpt-image-1");
    expect(draft.displayName).toBe("GPT Image");
    expect(draft.costPerImageStr).toBe("0.04");
    expect(draft.defaultSize).toBe("1536x1024");
    expect(draft.defaultQuality).toBe("high");
    expect(draft.costPerMinuteStr).toBe("");
  });

  it("falls back to auto for a size or quality outside the vocabulary", () => {
    const draft = modelToDraft(
      { ...imageModel, default_size: "9x9", default_quality: "ultra" } as unknown as ImageModel,
      "image"
    );

    expect(draft.defaultSize).toBe("auto");
    expect(draft.defaultQuality).toBe("auto");
  });

  it("converts the draft into the wizard payload", () => {
    const draft = modelToDraft(imageModel, "image");

    const wizard = draftToWizardModel(draft);

    expect(wizard.costPerImage).toBe(0.04);
    expect(wizard.defaultSize).toBe("1536x1024");
    expect(wizard.defaultQuality).toBe("high");
    expect(wizard.costPerMinute).toBeNull();
  });

  it("takes the per-image price from a catalog entry and leaves token costs alone", () => {
    const draft = createEmptyDraft("image", "openai");

    const next = applyCatalogModelToDraft(
      draft,
      { name: "imagen-4.0-generate-001", cost_per_image: 0.04, input_cost_per_token: 1 },
      "image"
    );

    expect(next.name).toBe("imagen-4.0-generate-001");
    expect(next.costPerImageStr).toBe("0.04");
    expect(next.inputCostPerTokenStr).toBe("");
  });

  it("reports an oversized per-image price", () => {
    const draft = { ...createEmptyDraft("image", "openai"), costPerImageStr: "1e20" };

    expect(findDraftCostOverflow(draft)).toBe("perImage");
  });

  it("only needs a name and display name to be complete", () => {
    const draft = { ...createEmptyDraft("image", "openai"), name: "x", displayName: "X" };

    expect(isDraftComplete(draft, "image")).toBe(true);
    expect(isDraftComplete({ ...draft, displayName: "" }, "image")).toBe(false);
  });
});
