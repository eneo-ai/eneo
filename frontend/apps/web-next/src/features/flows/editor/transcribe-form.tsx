"use client";

import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Selector } from "@astryxdesign/core/Selector";
import { useTranslations } from "next-intl";
import { TextInput } from "@/components/astryx/text-input";
import { useSpace } from "@/features/spaces/use-space";
import type { FlowDefinition, TranscribeStep } from "../types";
import {
  DEFAULT_MODEL,
  FormFieldSelector,
  NameFields,
  problemStatus,
  type FieldProblems
} from "./step-fields";
import type { StepDraftState } from "./use-step-draft";

/** The form of a transcription: the audio input, the model, the language, the speakers. */
export function TranscribeForm({
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
  const step = draft.draft.step as TranscribeStep;
  const mapping = step.speaker_mapping ?? null;
  return (
    <>
      <NameFields step={step} onChange={draft.update} problems={problems} />
      <FormFieldSelector
        label={t("flow_param_source")}
        description={t("flow_editor_source_hint")}
        definition={definition}
        types={["audio", "file"]}
        value={step.source || null}
        onChange={(source) => draft.update({ source: source ?? "" })}
        problem={problems.source}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <Selector
          label={t("model")}
          options={[
            { value: DEFAULT_MODEL, label: t("flow_param_model_default") },
            ...space.transcription_models.map((model) => ({
              value: model.id,
              label: model.nickname || model.name
            }))
          ]}
          value={step.transcription_model_id ?? DEFAULT_MODEL}
          onChange={(next) => draft.update({ transcription_model_id: next || null })}
          status={problemStatus(problems.transcription_model_id)}
        />
        <TextInput
          label={t("language")}
          description={t("flow_editor_language_hint")}
          value={step.language ?? ""}
          onChange={(language) => draft.update({ language: language.trim() || null })}
          placeholder={t("flow_param_language_auto")}
          status={problemStatus(problems.language)}
        />
      </div>
      <CheckboxInput
        label={t("flow_param_speakers_on")}
        description={t("flow_editor_speakers_hint")}
        value={step.speaker_labels ?? false}
        onChange={(speaker_labels) => draft.update({ speaker_labels })}
      />
      {step.speaker_labels && (
        <div className="grid gap-4 sm:grid-cols-2">
          <NumberInput
            label={t("flow_editor_max_speakers")}
            value={step.max_speakers ?? null}
            onChange={(max_speakers) => draft.update({ max_speakers })}
            min={1}
            max={32}
            isIntegerOnly
            hasClear
            placeholder={t("flow_editor_max_speakers_any")}
            status={problemStatus(problems.max_speakers)}
          />
          <FormFieldSelector
            label={t("flow_editor_participants_field")}
            description={t("flow_editor_participants_hint")}
            definition={definition}
            types={["text"]}
            value={mapping?.participants_field ?? null}
            onChange={(participants_field) =>
              draft.update({
                speaker_mapping: {
                  ...(mapping ?? { infer_names: true }),
                  participants_field
                }
              })
            }
            optional
            problem={problems.speaker_mapping}
          />
          <CheckboxInput
            label={t("flow_editor_infer_names")}
            description={t("flow_editor_infer_names_hint")}
            value={mapping?.infer_names ?? true}
            onChange={(infer_names) =>
              draft.update({ speaker_mapping: { ...(mapping ?? {}), infer_names } })
            }
          />
        </div>
      )}
    </>
  );
}
