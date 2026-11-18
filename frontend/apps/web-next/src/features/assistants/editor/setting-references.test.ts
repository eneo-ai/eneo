import { createFormatter } from "use-intl";
import { describe, expect, it } from "vitest";
import { testTranslator } from "@/test/i18n";
import {
  ASSISTANT_SECTION_IDS,
  SETTING_REFERENCE_KEYS,
  settingMention,
  settingParts,
  settingReferences,
  type SettingReferenceInput
} from "./setting-references";
import type { Assistant } from "./use-assistant";

const t = testTranslator();
const format = createFormatter({ locale: "sv" });

const assistant = (overrides: Record<string, unknown> = {}) =>
  ({
    id: "assistant-1",
    name: "Bygglov",
    description: "Svarar på frågor om bygglov i kommunen och hänvisar till handläggare vid behov.",
    prompt: { text: "Du är kommunens bygglovsassistent. Svara kort och sakligt." },
    completion_model: { id: "model-1", name: "nordic-large", nickname: "Nordic Large" },
    completion_model_kwargs: { temperature: 0.2 },
    knowledge_mode: "tool",
    inline_file_text: false,
    groups: [{ id: "g" }],
    websites: [{ id: "w" }],
    integration_knowledge_list: [],
    mcp_servers: [{ id: "m1" }, { id: "m2" }],
    attachments: [],
    enabled_capabilities: [],
    data_retention_days: 30,
    published: false,
    insight_enabled: true,
    permissions: ["read", "edit", "publish", "insight_toggle"],
    ...overrides
  }) as unknown as Assistant;

const ALL_SECTIONS = ASSISTANT_SECTION_IDS.map((id) => ({ id, label: id }));

const RERANKER = {
  id: "rerank-1",
  name: "multilingual-rerank",
  nickname: "Flerspråkig rankning",
  can_access: true,
  meets_security_classification: true
};

const reasoningModel = {
  supported_model_kwargs: {
    temperature: { supported: true },
    reasoning_effort: { supported: true, options: ["low", "medium", "high"] }
  }
};

function input(overrides: Partial<SettingReferenceInput> = {}): SettingReferenceInput {
  return {
    sections: ALL_SECTIONS,
    assistant: assistant(),
    model: { id: "model-1", name: "nordic-large", nickname: "Nordic Large" },
    kwargsModel: reasoningModel as SettingReferenceInput["kwargsModel"],
    kwargs: { temperature: 0.25, reasoning_effort: "medium" },
    fileReferences: true,
    t,
    format,
    ...overrides
  };
}

describe("The keys a setting reference can name", () => {
  /**
   * The same list, in the same order, as `SETTING_REFERENCES` in the
   * helper's persona (backend/src/eneo/helper_chats/personas/assistant.py),
   * whose test holds it to this one: change both together.
   */
  const PERSONA_KEYS = [
    "name",
    "description",
    "prompt",
    "knowledge_mode",
    "inline_file_text",
    "knowledge",
    "rerank_model_id",
    "mcp_servers",
    "attachments",
    "completion_model",
    "completion_model_kwargs",
    "completion_model_kwargs.reasoning_effort",
    "completion_model_kwargs.verbosity",
    "completion_model_kwargs.top_p",
    "completion_model_kwargs.presence_penalty",
    "completion_model_kwargs.frequency_penalty",
    "completion_model_kwargs.top_k",
    "enabled_capabilities",
    "document_template",
    "data_retention_days",
    "published",
    "insight_enabled",
    "section:general",
    "section:instructions",
    "section:knowledge",
    "section:skills",
    "section:mcp",
    "section:attachments",
    "section:ai",
    "section:capabilities",
    "section:security",
    "section:api-keys",
    "section:widget",
    "section:publishing"
  ];

  it("are the persona's list", () => {
    expect(SETTING_REFERENCE_KEYS).toEqual(PERSONA_KEYS);
  });

  it("cover everything the editor can list, a model with every setting included", () => {
    const everySetting = {
      supported_model_kwargs: Object.fromEntries(
        ["temperature", "reasoning_effort", "verbosity", "top_p", "presence_penalty"]
          .concat(["frequency_penalty", "top_k"])
          .map((name) => [name, { supported: true }])
      )
    };
    const keys = settingReferences(
      input({
        kwargsModel: everySetting as SettingReferenceInput["kwargsModel"],
        // The ranking row shows where the space has a model to choose, the
        // template while "Skapa fil" is on.
        assistant: assistant({ enabled_capabilities: ["file_creation"] }),
        spaceModels: { rerank_models: [RERANKER] } as SettingReferenceInput["spaceModels"]
      })
    ).map((reference) => reference.key);
    expect(new Set(keys)).toEqual(new Set(SETTING_REFERENCE_KEYS));
  });
});

describe("What the helper chat can refer to", () => {
  it("lists each section, then the settings it shows, with their values in short", () => {
    const listed = settingReferences(
      input({
        sections: [
          { id: "general", label: "Allmänt" },
          { id: "ai", label: "AI" }
        ]
      })
    ).map(({ key, sectionLabel, label, value, control }) => [
      key,
      sectionLabel,
      label,
      value,
      control
    ]);
    expect(listed).toEqual([
      ["section:general", "Allmänt", "Allmänt", "Hela avsnittet", undefined],
      ["name", "Allmänt", "Namn", "Bygglov", "assistant-name"],
      [
        "description",
        "Allmänt",
        "Beskrivning",
        "Svarar på frågor om bygglov i kommunen o…",
        "assistant-description"
      ],
      ["section:ai", "AI", "AI", "Hela avsnittet", undefined],
      ["completion_model", "AI", "Chattmodell", "Nordic Large", "assistant-completion-model"],
      [
        "completion_model_kwargs",
        "AI",
        "Modellbeteende",
        "Deterministisk",
        "assistant-model-behaviour"
      ],
      [
        "completion_model_kwargs.reasoning_effort",
        "AI",
        "Resonemangsnivå",
        "Medel",
        "assistant-kwarg-reasoning_effort"
      ]
    ]);
  });

  it("gives counts, the first words of the instructions and plain states", () => {
    const value = (key: string, overrides: Partial<SettingReferenceInput> = {}) =>
      settingReferences(input(overrides)).find((reference) => reference.key === key)?.value;
    expect(value("prompt")).toBe("Du är kommunens bygglovsassistent. Svara…");
    expect(value("prompt", { assistant: assistant({ prompt: null }) })).toBe("Inga instruktioner");
    expect(value("knowledge")).toBe("2 källor");
    expect(value("mcp_servers")).toBe("2 valda");
    expect(value("attachments")).toBe("Inga");
    expect(value("knowledge_mode")).toBe("Vid behov");
    expect(value("inline_file_text")).toBe("Öppna vid behov");
    // Without references every upload is read directly, as the form says.
    expect(value("inline_file_text", { fileReferences: false })).toBe("Läs in direkt");
    expect(value("data_retention_days")).toBe("Sparas 30 dagar");
    expect(value("published")).toBe("Utkast");
    expect(value("insight_enabled")).toBe("Aktiverad");
    expect(value("completion_model", { model: null })).toBe("Ingen modell");
  });

  it("leaves out what the form does not show this person", () => {
    const keys = (overrides: Partial<SettingReferenceInput>) =>
      settingReferences(input(overrides)).map((reference) => reference.key);

    // A section not in the editor's list: neither it nor its settings.
    const withoutPublishing = keys({
      sections: ALL_SECTIONS.filter((section) => section.id !== "publishing")
    });
    expect(withoutPublishing).not.toContain("section:publishing");
    expect(withoutPublishing).not.toContain("insight_enabled");
    // The publishing status only for someone who may publish.
    expect(
      keys({ assistant: assistant({ permissions: ["read", "edit", "insight_toggle"] }) })
    ).toEqual(expect.not.arrayContaining(["published"]));
    // The model's own settings only as far as the model has them.
    const plain = keys({ kwargsModel: null });
    expect(plain).toContain("completion_model_kwargs");
    expect(plain.filter((key) => key.startsWith("completion_model_kwargs."))).toEqual([]);
  });
});

describe("The result ranking and the document template in the '@' menu", () => {
  const find = (key: string, overrides: Partial<SettingReferenceInput> = {}) =>
    settingReferences(input(overrides)).find((reference) => reference.key === key);
  const models = (...rerank: unknown[]) =>
    ({ rerank_models: rerank }) as SettingReferenceInput["spaceModels"];

  it("lists the ranking model under Kunskap where the form shows its row, landing on the row", () => {
    expect(find("rerank_model_id", { spaceModels: models(RERANKER) })).toMatchObject({
      section: "knowledge",
      label: "Rankning av träffar",
      value: "Ingen omrankning",
      control: "reranker"
    });
    expect(
      find("rerank_model_id", {
        spaceModels: models(RERANKER),
        assistant: assistant({ rerank_model_id: "rerank-1" })
      })?.value
    ).toBe("Flerspråkig rankning");
    // A chosen model the space no longer allows stays, as the row keeps it.
    expect(
      find("rerank_model_id", {
        spaceModels: models(),
        assistant: assistant({ rerank_model_id: "rerank-gone" })
      })?.value
    ).toBe("Otillgänglig modell");
  });

  it("leaves the ranking model out where the form has no row for it", () => {
    // Nothing the space lets the assistant choose, and nothing chosen.
    expect(
      find("rerank_model_id", { spaceModels: models({ ...RERANKER, can_access: false }) })
    ).toBeUndefined();
    // The space's models not read yet: the row waits for them too.
    expect(find("rerank_model_id")).toBeUndefined();
  });

  it("lists the document template under Funktioner while Skapa fil is on, by its name", () => {
    expect(find("document_template")).toBeUndefined();
    expect(
      find("document_template", {
        assistant: assistant({
          enabled_capabilities: ["file_creation"],
          document_template: { mode: "selected", template_id: "template-1" }
        }),
        documentTemplates: [{ id: "template-1", name: "Kommunens mall" }]
      })
    ).toMatchObject({
      section: "capabilities",
      label: "Dokumentmall",
      value: "Kommunens mall",
      control: "assistant-document-template"
    });
    expect(
      find("document_template", {
        assistant: assistant({ enabled_capabilities: ["file_creation"] })
      })?.value
    ).toBe("Organisationens standard");
  });
});

describe("A setting mention", () => {
  it("names the setting as the editor does and reads back", () => {
    const raw = settingMention({ key: "section:ai", label: "AI-inställningar" });
    expect(raw).toBe("@[AI-inställningar](setting:section:ai)");
    expect(settingParts(`Om ${raw}?`)).toEqual([
      { kind: "text", text: "Om " },
      { kind: "mention", raw, name: "AI-inställningar", key: "section:ai" },
      { kind: "text", text: "?" }
    ]);
  });
});
