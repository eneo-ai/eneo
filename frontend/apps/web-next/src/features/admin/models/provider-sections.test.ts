import { describe, expect, it } from "vitest";
import type { ModelProvider } from "./model-providers";
import type { AdminModel, ModelsPresentation } from "./models";
import {
  buildProviderSections,
  countByKind,
  filterSections,
  modelLifecycle,
  modelPrice,
  modelsAttention,
  providerStatus,
  UNCLASSIFIED
} from "./provider-sections";

const TODAY = "2026-09-25";

const provider = (overrides: Partial<ModelProvider>): ModelProvider => ({
  id: "p",
  tenant_id: "t",
  name: "Provider",
  provider_type: "openai",
  config: {},
  is_active: true,
  masked_api_key: "...abcd",
  created_at: "",
  updated_at: "",
  ...overrides
});

const model = (overrides: Record<string, unknown>) =>
  ({
    id: "m",
    name: "model-id",
    nickname: "Model",
    is_deprecated: false,
    is_org_enabled: true,
    provider_id: "p1",
    security_classification: null,
    ...overrides
  }) as unknown as AdminModel;

const presentation = {
  completion_models: [
    model({ id: "c1", name: "gpt-4o", nickname: "GPT-4o", provider_id: "p1" }),
    model({
      id: "c2",
      name: "gpt-4",
      nickname: "GPT-4",
      provider_id: "p1",
      deprecation_date: "2025-01-01",
      security_classification: { id: "s1", name: "Klass 1" }
    }),
    // Legacy global model without a provider: not shown.
    model({ id: "c3", name: "legacy", provider_id: null })
  ],
  embedding_models: [model({ id: "e1", name: "e5-large", nickname: "E5", provider_id: "p2" })],
  transcription_models: [
    model({ id: "t1", name: "whisper-1", nickname: "Whisper", provider_id: "p1" })
  ]
} as unknown as ModelsPresentation;

const providers = [
  provider({ id: "p1", name: "OpenAI" }),
  provider({ id: "p2", name: "vLLM", provider_type: "hosted_vllm", masked_api_key: null }),
  provider({ id: "p3", name: "Mistral", provider_type: "mistral", masked_api_key: null })
];

const sections = buildProviderSections(presentation, providers);
const all = { search: "", kind: "all" as const, security: "all" };

describe("provider status", () => {
  it("reads inactive, missing key and ready from the provider data", () => {
    expect(providerStatus(provider({ is_active: false }))).toBe("inactive");
    expect(providerStatus(provider({ masked_api_key: null }))).toBe("missing_key");
    // Self-hosted vLLM has an optional key (backend provider_field_config).
    expect(providerStatus(provider({ provider_type: "hosted_vllm", masked_api_key: null }))).toBe(
      "ready"
    );
    expect(providerStatus(provider({}))).toBe("ready");
  });

  it("groups provider-backed models and lists providers that need a key first", () => {
    expect(sections.map((section) => section.name)).toEqual(["Mistral", "OpenAI", "vLLM"]);
    const openai = sections.find((section) => section.name === "OpenAI")!;
    expect(openai.models.map(({ model }) => model.id)).toEqual(["c1", "c2", "t1"]);
    expect(openai.status).toBe("ready");
    expect(sections[0]!.needsKey).toBe(true);
  });
});

describe("filters", () => {
  it("filters by type and drops providers left without models", () => {
    const result = filterSections(sections, { ...all, kind: "embedding" });
    expect(result.map(({ section }) => section.name)).toEqual(["vLLM"]);
  });

  it("filters by security class, including unclassified models", () => {
    const classified = filterSections(sections, { ...all, security: "s1" });
    expect(classified.flatMap(({ models }) => models.map(({ model }) => model.id))).toEqual(["c2"]);
    const unclassified = filterSections(sections, { ...all, security: UNCLASSIFIED });
    expect(unclassified.flatMap(({ models }) => models.map(({ model }) => model.id))).toEqual([
      "c1",
      "t1",
      "e1"
    ]);
  });

  it("searches display names, technical ids and provider names", () => {
    const ids = (search: string) =>
      filterSections(sections, { ...all, search }).flatMap(({ models }) =>
        models.map(({ model }) => model.id)
      );
    expect(ids("gpt-4o")).toEqual(["c1"]);
    expect(ids("whisper")).toEqual(["t1"]);
    expect(ids("vllm")).toEqual(["e1"]);
    expect(ids("  ")).toHaveLength(4);
  });

  it("counts models per type with the other filters applied", () => {
    expect(countByKind(sections, { search: "", security: "all" })).toEqual({
      all: 4,
      completion: 2,
      embedding: 1,
      transcription: 1
    });
    expect(countByKind(sections, { search: "gpt", security: "all" })).toEqual({
      all: 2,
      completion: 2,
      embedding: 0,
      transcription: 0
    });
  });
});

describe("lifecycle and attention", () => {
  it("derives deprecation from the date or the manual flag", () => {
    expect(modelLifecycle(model({ deprecation_date: "2025-01-01" }), TODAY)).toEqual({
      kind: "deprecated",
      date: "2025-01-01"
    });
    expect(modelLifecycle(model({ is_deprecated: true }), TODAY)).toEqual({
      kind: "deprecated",
      date: null
    });
    expect(modelLifecycle(model({ deprecation_date: "2027-01-01" }), TODAY)).toEqual({
      kind: "retiring",
      date: "2027-01-01"
    });
    expect(modelLifecycle(model({}), TODAY)).toEqual({ kind: "active" });
  });

  it("reports active providers without a required key and deprecated models still in use", () => {
    const attention = modelsAttention(sections, TODAY);
    expect(attention.missingKey.map((section) => section.name)).toEqual(["Mistral"]);
    expect(attention.deprecated.map(({ model }) => model.id)).toEqual(["c2"]);

    const quiet = buildProviderSections(
      {
        ...presentation,
        completion_models: [
          model({ id: "c2", deprecation_date: "2025-01-01", is_org_enabled: false }),
          model({ id: "c4", deprecation_date: "2025-01-01", migrated_to_model_id: "c1" })
        ]
      } as unknown as ModelsPresentation,
      [provider({ id: "p1" }), provider({ id: "p3", is_active: false, masked_api_key: null })]
    );
    expect(modelsAttention(quiet, TODAY)).toEqual({ missingKey: [], deprecated: [] });
  });
});

describe("prices", () => {
  it("formats per 1M tokens, per minute or unknown", () => {
    expect(
      modelPrice(
        model({ input_cost_per_token: "0.000003", output_cost_per_token: "0.000015" }),
        "completion"
      )
    ).toEqual({ kind: "tokens", input: "$3.00", output: "$15.00" });
    expect(modelPrice(model({ cost_per_minute: "0.006" }), "transcription")).toEqual({
      kind: "minute",
      value: "$0.006"
    });
    expect(modelPrice(model({}), "embedding")).toEqual({ kind: "unknown" });
  });
});
