import { describe, expect, test, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({
  m: {
    disabled: () => "Disabled",
    embedding_model_disabled_by_admin: () => "Disabled by administrator",
    embedding_model_not_in_space: () => "Not enabled in this space"
  }
}));

import {
  embeddingModelGroupTitle,
  embeddingModelLabel,
  modelDisplayName,
  modelProviderLabel
} from "./modelLabels";

describe("modelDisplayName", () => {
  test("prefers the nickname over the model id", () => {
    expect(modelDisplayName({ name: "multilingual-e5-large", nickname: "E5 Large" })).toBe(
      "E5 Large"
    );
  });

  test("falls back to the model id when the nickname is missing or blank", () => {
    expect(modelDisplayName({ name: "multilingual-e5-large" })).toBe("multilingual-e5-large");
    expect(modelDisplayName({ name: "multilingual-e5-large", nickname: "  " })).toBe(
      "multilingual-e5-large"
    );
  });
});

describe("modelProviderLabel", () => {
  test("uses the provider name when set", () => {
    expect(
      modelProviderLabel({ name: "x", provider_name: "Berget", provider_type: "openai" })
    ).toBe("Berget");
  });

  test("prettifies the provider type when there is no provider name", () => {
    expect(modelProviderLabel({ name: "x", provider_type: "azure_openai" })).toBe("Azure Openai");
  });

  test("is null for globally seeded models without a provider", () => {
    expect(modelProviderLabel({ name: "x" })).toBeNull();
  });
});

describe("embeddingModelLabel", () => {
  test("appends the provider so same-named models stay distinguishable", () => {
    const shared = { name: "multilingual-e5-large" };
    expect(embeddingModelLabel({ ...shared, provider_name: "Berget" })).toBe(
      "multilingual-e5-large (Berget)"
    );
    expect(embeddingModelLabel({ ...shared, provider_name: "Azure Sundsvall" })).toBe(
      "multilingual-e5-large (Azure Sundsvall)"
    );
  });

  test("shows only the name when no provider is known", () => {
    expect(embeddingModelLabel({ name: "multilingual-e5-large" })).toBe("multilingual-e5-large");
  });
});

describe("embeddingModelGroupTitle", () => {
  const model = { name: "multilingual-e5-large", provider_name: "Berget" };

  test("has no status suffix when the model is in the space", () => {
    expect(embeddingModelGroupTitle({ ...model, is_org_enabled: true }, true)).toBe(
      "multilingual-e5-large (Berget)"
    );
  });

  test("names an org-wide disable separately from a model not selected for the space", () => {
    expect(embeddingModelGroupTitle({ ...model, is_org_enabled: false }, false)).toBe(
      "multilingual-e5-large (Berget) (Disabled by administrator)"
    );
    expect(embeddingModelGroupTitle({ ...model, is_org_enabled: true }, false)).toBe(
      "multilingual-e5-large (Berget) (Not enabled in this space)"
    );
  });

  test("falls back to a plain disabled label when the org state is unknown", () => {
    expect(embeddingModelGroupTitle(model, false)).toBe(
      "multilingual-e5-large (Berget) (Disabled)"
    );
  });
});
