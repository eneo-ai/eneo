"use client";

import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { useTranslations } from "use-intl";
import { Switch } from "@astryxdesign/core/Switch";
import { ContractFromExampleDialog } from "./contract-from-example-dialog";
import { Anchor, EditorSection, problemStatus } from "./editor-fields";
import type { FieldProblems } from "./field-problems";
import {
  readCitationsOn,
  readHttpConfig,
  readSpeakerMapping,
  supportsCitations,
  withCitations,
  withHttpConfig,
  withSpeakerMapping,
  type SpeakerMapping
} from "./step-configs";
import { HttpFields } from "./step-http-fields";
import {
  invalidOptionLabel,
  outputModeIssueText,
  outputModeLabel,
  outputTypeLabel
} from "./step-labels";
import {
  applyOutputModeChange,
  applyOutputTypeChange,
  outputModeIssue,
  outputModeOptions,
  outputTypeOptions
} from "./step-rules";
import { TemplateFillFields } from "./step-template-fields";
import {
  objectOf,
  type FlowPublic,
  type JsonObject,
  type OutputMode,
  type OutputType,
  type StepConfig
} from "./step-types";
import { formFieldsOf, type VariableGroup } from "./step-variables";

const NONE = "__none";

function SpeakerMappingFields({
  flow,
  mapping,
  onChange,
  problem
}: {
  flow: FlowPublic;
  mapping: SpeakerMapping;
  onChange: (mapping: SpeakerMapping) => void;
  problem?: string;
}) {
  const t = useTranslations();
  const fields = formFieldsOf(flow);
  const participantFields = fields.filter((field) =>
    ["text", "multiselect", "list"].includes(field.type)
  );
  const countFields = fields.filter((field) => field.type === "number");
  const fieldOptions = (list: typeof fields, current: string | null) => [
    { value: NONE, label: t("flow_step_editor_speakers_no_field") },
    ...list.map((field) => ({ value: field.name, label: field.label })),
    ...(current && !list.some((field) => field.name === current)
      ? [{ value: current, label: invalidOptionLabel(current, t) }]
      : [])
  ];
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Selector
          label={t("flow_step_editor_speakers_participants")}
          description={t("flow_step_editor_speakers_participants_description")}
          options={fieldOptions(participantFields, mapping.participantsField)}
          value={mapping.participantsField ?? NONE}
          onChange={(value) =>
            onChange({ ...mapping, participantsField: value === NONE ? null : value })
          }
          status={problemStatus(problem)}
          width="100%"
        />
        <Selector
          label={t("flow_step_editor_speakers_count")}
          description={t("flow_step_editor_speakers_count_description")}
          options={fieldOptions(countFields, mapping.speakerCountField)}
          value={mapping.speakerCountField ?? NONE}
          onChange={(value) =>
            onChange({ ...mapping, speakerCountField: value === NONE ? null : value })
          }
          width="100%"
        />
      </div>
      <Switch
        label={t("flow_step_editor_speakers_infer_names")}
        description={t("flow_step_editor_speakers_infer_names_description")}
        value={mapping.inferNames}
        onChange={(inferNames) => onChange({ ...mapping, inferNames })}
      />
      {participantFields.length === 0 && (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {t("flow_step_editor_speakers_no_fields")}
        </Text>
      )}
    </div>
  );
}

/** What the step does with what it reads, what it hands on, and where. */
export function StepOutputSection({
  formId,
  sectionId,
  flow,
  stepId,
  draft,
  isLast,
  onChange,
  problems,
  groups,
  wholeValueGroups,
  onContractProposed
}: {
  formId: string;
  sectionId: string;
  flow: FlowPublic;
  stepId: string;
  draft: StepConfig;
  isLast: boolean;
  onChange: (next: StepConfig) => void;
  problems: FieldProblems;
  groups: VariableGroup[];
  wholeValueGroups: VariableGroup[];
  /** An output contract the author accepted from an example answer. */
  onContractProposed: (contract: JsonObject) => void;
}) {
  const t = useTranslations();
  const modes = outputModeOptions(draft, isLast);
  const types = outputTypeOptions(draft);
  const issue = outputModeIssue(draft, isLast);

  return (
    <EditorSection
      id={sectionId}
      title={t("flow_step_editor_output_title")}
      description={t("flow_step_editor_output_description")}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Anchor formId={formId} anchor="output_mode">
          <Selector
            label={t("flow_step_output_mode")}
            options={modes.map((option) => ({
              value: option.value,
              label: option.invalid
                ? invalidOptionLabel(outputModeLabel(option.value, t), t)
                : outputModeLabel(option.value, t)
            }))}
            value={draft.output_mode}
            onChange={(value) => onChange(applyOutputModeChange(draft, value as OutputMode))}
            status={problemStatus(
              problems.output_mode ?? (issue ? outputModeIssueText(issue, t) : null)
            )}
            width="100%"
          />
        </Anchor>
        <Anchor formId={formId} anchor="output_type">
          <Selector
            label={t("flow_step_output_type")}
            options={types.map((option) => ({
              value: option.value,
              label: option.invalid
                ? invalidOptionLabel(outputTypeLabel(option.value, t), t)
                : outputTypeLabel(option.value, t)
            }))}
            value={draft.output_type}
            onChange={(value) => onChange(applyOutputTypeChange(draft, value as OutputType))}
            isReadOnly={types.length === 1 && !types[0]?.invalid}
            status={problemStatus(problems.output_type)}
            width="100%"
          />
        </Anchor>
      </div>

      <Text type="supporting" size="sm" as="p" display="block" className="m-0">
        {t(`flow_step_editor_output_mode_help_${draft.output_mode}`)}
      </Text>

      {draft.output_type === "json" && draft.output_mode !== "speaker_mapping" && (
        <div className="flex flex-col gap-1">
          <Text type="supporting" size="sm" as="p" display="block" className="m-0">
            {draft.output_contract
              ? t("flow_editor_tools_contract_example_has_contract", {
                  count: Object.keys(objectOf(draft.output_contract.properties)).length
                })
              : t("flow_editor_tools_contract_example_hint")}
          </Text>
          <ContractFromExampleDialog
            current={draft.output_contract}
            onAccept={onContractProposed}
          />
        </div>
      )}

      {draft.output_mode === "http_post" && (
        <Anchor formId={formId} anchor="output_config.http">
          <HttpFields
            flowId={flow.id}
            stepId={stepId}
            direction="output"
            config={readHttpConfig(draft.output_config, "output")}
            onChange={(http) =>
              onChange({ ...draft, output_config: withHttpConfig(draft.output_config, http) })
            }
            groups={groups}
            problem={problems["output_config.http"]}
          />
        </Anchor>
      )}

      {draft.output_mode === "template_fill" && (
        <Anchor formId={formId} anchor="output_config.template">
          <TemplateFillFields
            flowId={flow.id}
            draft={draft}
            onChange={(output_config) => onChange({ ...draft, output_config })}
            groups={wholeValueGroups}
            problem={problems["output_config.template"]}
          />
        </Anchor>
      )}

      {draft.output_mode === "speaker_mapping" && (
        <Anchor formId={formId} anchor="output_config.speaker_mapping">
          <SpeakerMappingFields
            flow={flow}
            mapping={readSpeakerMapping(draft.output_config)}
            onChange={(mapping) =>
              onChange({
                ...draft,
                output_config: withSpeakerMapping(draft.output_config, mapping)
              })
            }
            problem={problems["output_config.speaker_mapping"]}
          />
        </Anchor>
      )}

      {(supportsCitations(draft) || readCitationsOn(draft.output_config)) && (
        <Anchor formId={formId} anchor="output_config.citation_mode">
          <Switch
            label={t("flow_step_citation_mode")}
            description={t("flow_step_citation_mode_desc")}
            value={readCitationsOn(draft.output_config)}
            isDisabled={!supportsCitations(draft) && !readCitationsOn(draft.output_config)}
            onChange={(on) =>
              onChange({ ...draft, output_config: withCitations(draft.output_config, on) })
            }
            status={problemStatus(problems["output_config.citation_mode"])}
          />
        </Anchor>
      )}
    </EditorSection>
  );
}
