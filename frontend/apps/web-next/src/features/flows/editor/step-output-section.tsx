import { Button } from "@astryxdesign/core/Button";
import { HStack } from "@astryxdesign/core/HStack";
import { VStack } from "@astryxdesign/core/VStack";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { useTranslations } from "use-intl";
import { Switch } from "@astryxdesign/core/Switch";
import { useId, useState } from "react";
import { flushSync } from "react-dom";
import { TextInput } from "@/components/astryx/text-input";
import { StatusLabel } from "@/components/composites/status-label";
import { flowDeliverables } from "../flow-deliverables";
import { formFieldsOf as formFieldDrafts } from "../flow-form-fields";
import { ContractFromExampleDialog } from "./contract-from-example-dialog";
import {
  Anchor,
  EditorSection,
  focusAnchor,
  problemStatus,
  TemplateScope,
  VariablePicker
} from "./editor-fields";
import type { FieldProblems } from "./field-problems";
import {
  oneLineStart,
  readCitationsOn,
  readDeliverable,
  readHttpConfig,
  readSpeakerMapping,
  stepCanBeDeliverable,
  stepDeliversArtifact,
  supportsCitations,
  withCitations,
  withDeliverable,
  withSpeakerMapping,
  withTidyDeliverable,
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
  applyHttpOutputChange,
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
  type StepConfig,
  type StepDeliverable
} from "./step-types";
import { formFieldsOf, insertToken, variableGroups, type VariableGroup } from "./step-variables";

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

/**
 * The form fields a file name can read: not the run's day, which every
 * generated name carries already. The core decides the rest (a sensitive
 * field name is refused on publishing).
 */
function fileNameGroups(flow: FlowPublic, groups: VariableGroup[]): VariableGroup[] {
  const runDate = new Set(
    formFieldDrafts(flow.metadata_json)
      .filter((field) => field.role === "run_date")
      .map((field) => `flow_input.${field.name}`)
  );
  return groups.flatMap((group) => {
    if (group.type !== "fields") return [];
    const entries = group.entries.filter((entry) => !runDate.has(entry.token));
    return entries.length > 0 ? [{ ...group, entries }] : [];
  });
}

/**
 * Whether the step's text or document is one of the run's results, under
 * which name and, for a document, which file name. The step the run delivers
 * by its place (last, or right before the step that sends the run's result)
 * is included unmarked and named after the step; "Behåll" marks it so it
 * stays when the order changes. Any other step is included when its switch
 * is on.
 */
function DeliverableFields({
  formId,
  flow,
  stepId,
  draft,
  groups,
  onChange,
  problems
}: {
  formId: string;
  flow: FlowPublic;
  stepId: string;
  draft: StepConfig;
  groups: VariableGroup[];
  onChange: (next: StepConfig) => void;
  problems: FieldProblems;
}) {
  const t = useTranslations();
  // The fields of a step included by its place, opened without a change yet: nothing is marked.
  const [customising, setCustomising] = useState(false);
  const keepId = useId();
  const resetId = useId();
  const run = flowDeliverables(
    flow.steps.map((step) => (step.id === stepId ? { ...step, ...draft } : step))
  );
  const place = run.byPlace?.step.id === stepId ? run.byPlace.place : null;
  const deliverable = readDeliverable(draft.output_config);
  const isDocument = stepDeliversArtifact(draft);
  // What the step is named in the result until the author names it.
  const stepName = oneLineStart(draft.user_description ?? "");
  const shown = deliverable ?? (place && customising ? { label: stepName } : null);
  const set = (next: StepDeliverable | null) =>
    onChange({ ...draft, output_config: withDeliverable(draft.output_config, next) });
  /** Names typed with stray spaces are made one line when the field is left. */
  const tidy = () => {
    const output_config = withTidyDeliverable(draft.output_config) as StepConfig["output_config"];
    if (output_config !== draft.output_config) onChange({ ...draft, output_config });
  };
  /** Marks the step under its name; focus goes to the button that takes the mark away. */
  const keep = () => {
    flushSync(() => set({ label: stepName }));
    document.getElementById(resetId)?.focus();
  };

  const fields = shown && (
    <>
      <Anchor formId={formId} anchor="output_config.deliverable.label">
        <TextInput
          label={t("flow_step_editor_deliverable_label")}
          description={t("flow_step_editor_deliverable_label_description")}
          value={shown.label}
          onChange={(label) => set({ ...shown, label })}
          onBlur={tidy}
          isRequired
          autoComplete="off"
          width="100%"
          status={problemStatus(problems["output_config.deliverable.label"])}
        />
      </Anchor>
      {isDocument && (
        <Anchor formId={formId} anchor="output_config.deliverable.file_name">
          <VStack gap={2} align="start">
            <TextInput
              label={t("flow_step_editor_deliverable_file_name")}
              description={t("flow_step_editor_deliverable_file_name_description")}
              value={shown.file_name ?? ""}
              onChange={(file_name) => set({ ...shown, file_name })}
              onBlur={tidy}
              isOptional
              autoComplete="off"
              width="100%"
              status={problemStatus(problems["output_config.deliverable.file_name"])}
            />
            <VariablePicker
              groups={fileNameGroups(flow, groups)}
              label={t("flow_step_editor_deliverable_insert_field")}
              onInsert={(token) =>
                set({ ...shown, file_name: insertToken(shown.file_name ?? "", token, null).text })
              }
            />
          </VStack>
        </Anchor>
      )}
    </>
  );

  if (!place) {
    return (
      <VStack gap={4}>
        <Switch
          label={t("flow_step_editor_deliverable_switch")}
          description={t("flow_step_editor_deliverable_switch_description")}
          value={deliverable !== null}
          onChange={(on) => set(on ? { label: stepName } : null)}
        />
        {fields}
      </VStack>
    );
  }

  // A marked step whose own names differ from the step's: taking the mark away resets them.
  const named = deliverable !== null && (deliverable.label !== stepName || !!deliverable.file_name);
  return (
    <VStack gap={4}>
      <VStack gap={1}>
        <StatusLabel status="success" label={t("flow_step_editor_deliverable_included")} />
        <Text type="supporting" size="sm" as="p" display="block" className="m-0 max-w-prose">
          {deliverable
            ? t("flow_step_editor_deliverable_kept")
            : t(`flow_step_editor_deliverable_place_${place}`)}
        </Text>
      </VStack>
      {!deliverable && (
        <HStack gap={2} wrap="wrap">
          <Button
            id={keepId}
            label={t("flow_step_editor_deliverable_keep")}
            size="sm"
            variant="secondary"
            onClick={keep}
          />
          {!customising && (
            <Button
              label={t(
                isDocument
                  ? "flow_step_editor_deliverable_customise"
                  : "flow_step_editor_deliverable_customise_text"
              )}
              size="sm"
              variant="ghost"
              onClick={() => {
                // The button goes; focus moves to the field it opened.
                flushSync(() => setCustomising(true));
                focusAnchor(formId, "output_config.deliverable.label");
              }}
            />
          )}
        </HStack>
      )}
      {fields}
      {deliverable && (
        <VStack gap={2} align="start">
          <Text type="supporting" size="sm" as="p" display="block" className="m-0 max-w-prose">
            {named
              ? t(
                  `flow_step_editor_deliverable_reset_named_${isDocument ? "document" : "text"}_${place}`
                )
              : t(`flow_step_editor_deliverable_reset_${place}`)}
          </Text>
          <Button
            id={resetId}
            label={t("flow_step_editor_deliverable_reset")}
            size="sm"
            variant="ghost"
            onClick={() => {
              flushSync(() => {
                setCustomising(false);
                set(null);
              });
              document.getElementById(keepId)?.focus();
            }}
          />
        </VStack>
      )}
    </VStack>
  );
}

/** What the step does with what it reads, what it hands on, and where. */
export function StepOutputSection({
  formId,
  sectionId,
  flow,
  stepId,
  stepOrder,
  draft,
  isLast,
  onChange,
  problems,
  groups,
  onContractProposed
}: {
  formId: string;
  sectionId: string;
  flow: FlowPublic;
  stepId: string;
  stepOrder: number;
  draft: StepConfig;
  isLast: boolean;
  onChange: (next: StepConfig) => void;
  problems: FieldProblems;
  groups: VariableGroup[];
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

      <Text
        type="supporting"
        size="sm"
        as="p"
        display="block"
        className="m-0 max-w-prose text-pretty"
      >
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
          {/* Sent once the step has answered: it reads as the next step would, its own answer too. */}
          <TemplateScope value={{ flow, stepOrder: stepOrder + 1 }}>
            <HttpFields
              formId={formId}
              flowId={flow.id}
              stepId={stepId}
              direction="output"
              config={readHttpConfig(draft.output_config, "output")}
              onChange={(http) => onChange(applyHttpOutputChange(draft, http))}
              groups={variableGroups({
                flow,
                stepOrder: stepOrder + 1,
                inputConfig: draft.input_config
              })}
              problems={problems}
            />
          </TemplateScope>
        </Anchor>
      )}

      {draft.output_mode === "template_fill" && (
        <Anchor formId={formId} anchor="output_config.template">
          <TemplateFillFields
            formId={formId}
            flow={flow}
            stepOrder={stepOrder}
            draft={draft}
            onChange={(output_config) => onChange({ ...draft, output_config })}
            groups={groups}
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

      {stepCanBeDeliverable(draft) && (
        <DeliverableFields
          formId={formId}
          flow={flow}
          stepId={stepId}
          draft={draft}
          groups={groups}
          onChange={onChange}
          problems={problems}
        />
      )}

      {(supportsCitations(draft) || readCitationsOn(draft.output_config)) && (
        <Anchor
          formId={formId}
          anchor="output_config.citation_mode"
          // Below the HTTP connection test, a rule keeps the switch out of the test.
          className={
            draft.output_mode === "http_post"
              ? "border-ax-border flex flex-col gap-3 border-t pt-4"
              : undefined
          }
        >
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
