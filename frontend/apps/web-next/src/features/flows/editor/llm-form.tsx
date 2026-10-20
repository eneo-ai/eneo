"use client";

import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useTranslations } from "next-intl";
import { KnowledgePicker } from "@/features/knowledge/select/knowledge-picker";
import { useSpace } from "@/features/spaces/use-space";
import type { FlowDefinition, LlmStep } from "../types";
import {
  FilesFromField,
  JsonTextField,
  ModelKwargsFields,
  ModelSelector,
  NameFields,
  problemStatus,
  TemplateHint,
  type FieldProblems
} from "./step-fields";
import type { StepDraftState } from "./use-step-draft";

/**
 * The form of a model step: the instructions, what the model reads (the
 * input template, files, knowledge), the model and its settings, and the
 * output (text, or JSON against a schema edited as text).
 */
export function LlmForm({
  draft,
  definition,
  problems
}: {
  draft: StepDraftState;
  definition: FlowDefinition;
  problems: FieldProblems;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const step = draft.draft.step as LlmStep;
  const knowledge = step.knowledge ?? {};
  const collections = (knowledge.collection_ids ?? [])
    .map((id) => space.knowledge.groups.items.find((item) => item.id === id))
    .filter((item) => item !== undefined);
  const websites = (knowledge.website_ids ?? [])
    .map((id) => space.knowledge.websites.items.find((item) => item.id === id))
    .filter((item) => item !== undefined);
  return (
    <>
      <NameFields step={step} onChange={draft.update} problems={problems} />
      <div className="flex flex-col gap-1.5">
        <TextArea
          label={t("flow_section_prompt")}
          value={step.prompt}
          onChange={(prompt) => draft.update({ prompt })}
          rows={12}
          isRequired
          status={problemStatus(problems.prompt)}
          placeholder={t("flow_editor_prompt_placeholder")}
        />
        <TemplateHint definition={definition} stepKey={step.key} />
      </div>
      <TextArea
        label={t("flow_param_input")}
        description={t("flow_editor_input_hint")}
        value={step.input ?? "{{previous}}"}
        onChange={(input) => draft.update({ input })}
        rows={3}
        status={problemStatus(problems.input)}
      />
      <div className="flex flex-col gap-4">
        <ModelSelector
          value={step.model_id ?? null}
          onChange={(model_id) => draft.update({ model_id })}
          problem={problems.model_id}
        />
        <ModelKwargsFields
          modelId={step.model_id ?? null}
          value={step.model_kwargs ?? {}}
          onChange={(model_kwargs) =>
            draft.update({ model_kwargs: Object.keys(model_kwargs).length ? model_kwargs : null })
          }
        />
      </div>
      <FilesFromField
        definition={definition}
        value={step.files_from ?? []}
        onChange={(files_from) => draft.update({ files_from })}
        problem={problems.files_from}
      />
      <div className="flex flex-col gap-1.5">
        <span className="text-sm font-medium">{t("knowledge")}</span>
        <KnowledgePicker
          origin={space.personal ? "personal" : "organization"}
          selections={{ collections, websites, integrationKnowledge: [] }}
          onChange={(next) =>
            draft.update({
              knowledge: {
                collection_ids: next.collections.map((item) => item.id),
                website_ids: next.websites.map((item) => item.id)
              }
            })
          }
          resourceKinds={{ integrationKnowledge: false }}
        />
      </div>
      <RadioList
        label={t("output")}
        value={step.output?.type ?? "text"}
        onChange={(type) =>
          draft.update({
            output:
              type === "json"
                ? {
                    type: "json",
                    schema:
                      step.output?.type === "json"
                        ? step.output.schema
                        : { type: "object", properties: {} }
                  }
                : { type: "text" }
          })
        }
      >
        <RadioListItem
          value="text"
          label={t("flow_produces_text")}
          description={t("flow_produces_text_detail")}
        />
        <RadioListItem
          value="json"
          label={t("flow_produces_json")}
          description={t("flow_editor_output_json_detail")}
        />
      </RadioList>
      {step.output?.type === "json" && (
        <JsonTextField
          label={t("flow_editor_schema")}
          description={t("flow_editor_schema_hint")}
          json={draft.draft.json.output}
          onChange={(text) => draft.setJson("output", text)}
          problem={problems.output}
        />
      )}
    </>
  );
}
