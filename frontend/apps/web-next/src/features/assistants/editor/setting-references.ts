import type { useFormatter, useTranslations } from "use-intl";
import {
  mentionParts,
  mentionText,
  parseBareMention,
  parseMention,
  type MentionPart
} from "@/features/references/mentions";
import type { Schema } from "@/lib/api/models";
import { editorSummaries } from "@/features/spaces/editor-summaries";
import {
  DOCUMENT_TEMPLATE_CONTROL,
  rerankerShown,
  selectableRerankModels
} from "./assistant-editor-rules";
import { settingLabel, settingText } from "./assistant-helper-cards";
import { selectedCapabilities } from "./capabilities-section";
import {
  MODEL_SPECIFIC_KWARGS,
  behaviourFromKwargs,
  modelSpecificKwargs,
  supportsBehaviorPresets,
  type ModelKwargs,
  type ModelWithKwargs
} from "./model-kwargs";
import { BEHAVIOUR_LABEL_KEYS } from "./model-kwargs-rows";
import type { Assistant } from "./use-assistant";

/**
 * References to the assistant's settings in its helper chat: a message
 * points at a setting, or at a whole section of the editor, as
 * `@[<name the editor shows>](setting:<key>)`, and the chat draws it as a
 * pill that shows the setting in the form. Pure and unit-tested.
 */

/** The editor's sections, in its order; a reference to a whole section is `section:<id>`. */
export const ASSISTANT_SECTION_IDS = [
  "general",
  "instructions",
  "knowledge",
  "skills",
  "mcp",
  "attachments",
  "ai",
  "capabilities",
  "security",
  "api-keys",
  "widget",
  "publishing"
] as const;

export type AssistantSectionId = (typeof ASSISTANT_SECTION_IDS)[number];

/**
 * Every key a reference can name. The helper's persona lists the same keys
 * (`SETTING_REFERENCES` in backend/src/eneo/helper_chats/personas/assistant.py);
 * a test on each side holds its list to the one written there, so a key
 * added on one side fails until the other has it too. A setting that is one
 * field of the assistant is named by the API's field.
 */
export const SETTING_REFERENCE_KEYS: readonly string[] = [
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
  ...MODEL_SPECIFIC_KWARGS.map((name) => `completion_model_kwargs.${name}`),
  "enabled_capabilities",
  "document_template",
  "data_retention_days",
  "published",
  "insight_enabled",
  ...ASSISTANT_SECTION_IDS.map((id) => `section:${id}`)
];

/** The scheme of a setting mention: `@[Chattmodell](setting:completion_model)`. */
export const SETTING_SCHEME = "setting";

/** One thing a message can point at: a setting the form shows, or a whole section. */
export type SettingReference = {
  key: string;
  /** The section it is in, and that section's name. */
  section: AssistantSectionId;
  sectionLabel: string;
  /** What the editor calls it. */
  label: string;
  /** What it is set to now, in a few words; for a section, that it is all of it. */
  value: string;
  /**
   * The element in the form that holds it: its control, or a container whose
   * first control is focused. A section has none: its heading takes focus.
   */
  control?: string;
};

type Translate = ReturnType<typeof useTranslations>;
type Format = ReturnType<typeof useFormatter>;

/** The section in the editor's list, as the references need it. */
type ListedSection = { id: AssistantSectionId; label: string };

type Setting = Omit<SettingReference, "section" | "sectionLabel">;

export type SettingReferenceInput = {
  /** The editor's section list: only what is in it has references. */
  sections: readonly ListedSection[];
  assistant: Assistant;
  /** The model the assistant answers with, as the form shows it. */
  model: { id: string; name: string; nickname?: string | null } | null;
  /** The model the form's model settings are for, and the settings as the form holds them. */
  kwargsModel: ModelWithKwargs | null;
  kwargs: ModelKwargs;
  /** Whether files uploaded in a chat can be read by reference (the organisation's setting). */
  fileReferences: boolean;
  /** The space's models, as the result ranking reads them; undefined while not known. */
  spaceModels?: Schema<"ModelsPresentation">;
  /** The organisation's document templates; undefined while not known. */
  documentTemplates?: readonly { id: string; name: string }[];
  t: Translate;
  format: Format;
};

/**
 * The result ranking, where the form shows its row: a space with a model
 * to choose, or a model chosen. While the space's models are not known a
 * chosen model is named by count.
 */
function rerankSetting(input: SettingReferenceInput): Setting[] {
  const { assistant, spaceModels, t } = input;
  const saved = assistant.rerank_model_id ?? null;
  const selectable = selectableRerankModels(spaceModels);
  if (!rerankerShown(selectable, saved)) return [];
  const chosen = selectable.find((model) => model.id === saved);
  const value =
    saved === null
      ? t("material_reranker_none")
      : chosen
        ? (chosen.nickname ?? chosen.name)
        : spaceModels
          ? t("material_reranker_missing")
          : editorSummaries(t).chosen(1);
  return [
    {
      key: "rerank_model_id",
      label: settingLabel("rerank_model_id", t),
      value,
      control: "reranker"
    }
  ];
}

/** The document template, where the form shows it: under "Skapa fil", while that function is on. */
function templateSetting(input: SettingReferenceInput): Setting[] {
  const { assistant, documentTemplates, t, format } = input;
  if (!selectedCapabilities(assistant).includes("file_creation")) return [];
  const choice = assistant.document_template;
  const name = documentTemplates?.find((item) => item.id === choice?.template_id)?.name ?? null;
  return [
    {
      key: "document_template",
      label: settingLabel("document_template", t),
      value: settingText("document_template", { ...choice, name }, t, format),
      control: DOCUMENT_TEMPLATE_CONTROL
    }
  ];
}

/** A section's own settings, as the form shows them to this person. */
function sectionSettings(id: AssistantSectionId, input: SettingReferenceInput): Setting[] {
  const { assistant, t, format } = input;
  const summary = editorSummaries(t);
  const text = (field: string, value: unknown) => settingText(field, value, t, format);
  switch (id) {
    case "general":
      return [
        { key: "name", label: t("name"), value: assistant.name, control: "assistant-name" },
        {
          key: "description",
          label: t("description"),
          value: summary.description(assistant.description),
          control: "assistant-description"
        }
      ];
    case "instructions": {
      const prompt = assistant.prompt?.text?.trim() ?? "";
      return [
        {
          key: "prompt",
          label: settingLabel("prompt", t),
          // The first words, as a description's are shown.
          value: prompt ? summary.description(prompt) : t("editor_summary_no_instructions"),
          control: "assistant-prompt"
        }
      ];
    }
    case "knowledge":
      return [
        {
          key: "knowledge_mode",
          label: settingLabel("knowledge_mode", t),
          value: text("knowledge_mode", assistant.knowledge_mode),
          control: "material-knowledge"
        },
        {
          key: "inline_file_text",
          label: settingLabel("inline_file_text", t),
          // Without references every upload is read directly.
          value: text("inline_file_text", input.fileReferences ? assistant.inline_file_text : true),
          control: "material-uploads"
        },
        {
          key: "knowledge",
          label: t("knowledge"),
          value: summary.sources(
            assistant.groups.length +
              assistant.websites.length +
              assistant.integration_knowledge_list.length
          ),
          control: "assistant-knowledge"
        },
        ...rerankSetting(input)
      ];
    case "mcp":
      return [
        {
          key: "mcp_servers",
          label: t("mcp_servers"),
          value: summary.chosen(assistant.mcp_servers?.length ?? 0),
          control: "mcp"
        }
      ];
    case "attachments":
      return [
        {
          key: "attachments",
          label: t("attachments"),
          value: summary.files(assistant.attachments.length),
          control: "attachments"
        }
      ];
    case "ai": {
      const { kwargsModel, kwargs } = input;
      const behaviour = supportsBehaviorPresets(kwargsModel)
        ? behaviourFromKwargs(kwargs)
        : "default";
      return [
        {
          key: "completion_model",
          label: settingLabel("completion_model", t),
          value: input.model
            ? (summary.model(input.model) ?? input.model.name)
            : t("helper_card_no_model"),
          control: "assistant-completion-model"
        },
        {
          key: "completion_model_kwargs",
          label: t("model_behaviour"),
          value: t(BEHAVIOUR_LABEL_KEYS[behaviour]),
          control: "assistant-model-behaviour"
        },
        // The model's own settings, as many as the form shows for it.
        ...modelSpecificKwargs(kwargsModel).map((name) => {
          const key = `completion_model_kwargs.${name}`;
          return {
            key,
            label: settingLabel(key, t),
            value: text(key, kwargs[name] ?? null),
            control: `assistant-kwarg-${name}`
          };
        })
      ];
    }
    case "capabilities":
      return [
        {
          key: "enabled_capabilities",
          label: t("capabilities"),
          value: summary.chosen(selectedCapabilities(assistant).length),
          control: "capabilities"
        },
        ...templateSetting(input)
      ];
    case "security":
      return [
        {
          key: "data_retention_days",
          label: t("conversation_retention_title"),
          value: summary.retention(assistant.data_retention_days),
          control: "assistant-retention-days"
        }
      ];
    case "publishing":
      return [
        // The status row is there only for someone who may publish.
        ...((assistant.permissions ?? []).includes("publish")
          ? [
              {
                key: "published",
                label: t("status"),
                value: summary.publishing(assistant.published),
                control: "assistant-publish-status"
              }
            ]
          : []),
        {
          key: "insight_enabled",
          label: t("insights"),
          value: t(assistant.insight_enabled ? "enabled" : "disabled"),
          control: "assistant-insights"
        }
      ];
    default:
      return [];
  }
}

/**
 * What a message can point at, in the editor's order: each section in its
 * list, then the settings it shows. A section the person cannot see is not
 * in the list, so nothing in it can be referred to.
 */
export function settingReferences(input: SettingReferenceInput): SettingReference[] {
  return input.sections.flatMap((section) => [
    {
      key: `section:${section.id}`,
      section: section.id,
      sectionLabel: section.label,
      label: section.label,
      value: input.t("helper_reference_whole_section")
    },
    ...sectionSettings(section.id, input).map((setting) => ({
      ...setting,
      section: section.id,
      sectionLabel: section.label
    }))
  ]);
}

/** A reference as it travels in a message, named as the editor names it. */
export function settingMention(reference: Pick<SettingReference, "key" | "label">): string {
  return mentionText(reference.label, SETTING_SCHEME, reference.key);
}

/** A text split into plain text and setting mentions. */
export function settingParts(text: string): MentionPart[] {
  return mentionParts(text, SETTING_SCHEME);
}

/**
 * A mention in an answer: the name it was written with, and the setting it
 * names. A model sometimes leaves out the scheme; `@[Namn](name)` then names
 * the setting `@[Namn](setting:name)` does, for a key in
 * SETTING_REFERENCE_KEYS as written. `key` is null for a mention of no such
 * setting; the result is null for anything that is not a mention.
 */
export function answerSettingMention(raw: string): { name: string; key: string | null } | null {
  const mention = parseMention(raw, SETTING_SCHEME) ?? parseBareMention(raw);
  if (!mention) return null;
  const key = SETTING_REFERENCE_KEYS.includes(mention.key) ? mention.key : null;
  return { name: mention.name, key };
}
