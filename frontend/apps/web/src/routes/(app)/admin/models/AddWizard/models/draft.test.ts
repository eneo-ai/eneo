import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy({}, { get: (_target, key) => () => String(key) })
}));

import type { ImageModel } from "@eneo/eneo-js";
import {
  applyCatalogModelToDraft,
  createEmptyDraft,
  draftToWizardModel,
  findDraftCostOverflow,
  isDraftComplete,
  modelToDraft
} from "./draft";

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
