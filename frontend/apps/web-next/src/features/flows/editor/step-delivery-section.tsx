import { Button } from "@astryxdesign/core/Button";
import { HStack } from "@astryxdesign/core/HStack";
import { Switch } from "@astryxdesign/core/Switch";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { ArrowRight, Send } from "lucide-react";
import { useFormatter, useTranslations } from "use-intl";
import { useId, useState } from "react";
import { flushSync } from "react-dom";
import { TextInput } from "@/components/astryx/text-input";
import { StatusLabel } from "@/components/composites/status-label";
import { flowDeliverables, type RunDeliverables } from "../flow-deliverables";
import { formFieldsOf as formFieldDrafts } from "../flow-form-fields";
import { stepReadersByNameOrPlace } from "../flow-steps";
import { useStepPromptsState } from "./editor-api";
import { Anchor, EditorSection, focusAnchor, problemStatus, VariablePicker } from "./editor-fields";
import type { FieldProblems } from "./field-problems";
import {
  oneLineStart,
  readDeliverable,
  runResultHost,
  sendsRunResult,
  stepDeliversArtifact,
  withDeliverable,
  withTidyDeliverable
} from "./step-configs";
import { stepLabel } from "./step-labels";
import type { FlowPublic, FlowStep, StepConfig, StepDeliverable } from "./step-types";
import { insertToken, type VariableGroup } from "./step-variables";

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
  run,
  draft,
  groups,
  onChange,
  problems
}: {
  formId: string;
  flow: FlowPublic;
  stepId: string;
  /** The run's deliverables with this step's draft in place. */
  run: RunDeliverables<FlowStep>;
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
  /**
   * Marks the step, under a name typed already or else the step's; focus goes
   * to the button that takes the mark away.
   */
  const keep = () => {
    flushSync(() => {
      setCustomising(false);
      set(deliverable ?? { label: stepName });
    });
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
      {/* Below the field: the first letter typed marks the step, and the row
          goes then without moving the field under the cursor. */}
      {fields}
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
            variant="secondary"
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

/**
 * Where a text or document step's result goes: which later steps read it,
 * whether it is one of the run's results (and under which names), and
 * whether the step that sends the run's result sends it. Readers come from
 * the saved flow; whether it is included is read with the step's draft in
 * place.
 */
export function StepDeliverySection({
  formId,
  sectionId,
  flow,
  stepId,
  draft,
  groups,
  onChange,
  problems,
  dirty,
  onGoStep
}: {
  formId: string;
  sectionId: string;
  flow: FlowPublic;
  stepId: string;
  draft: StepConfig;
  groups: VariableGroup[];
  onChange: (next: StepConfig) => void;
  problems: FieldProblems;
  /** The step has unsaved changes, which the step that sends does not show yet. */
  dirty: boolean;
  /** Opens another step of the flow; absent, the step that sends is not offered. */
  onGoStep?: (stepId: string) => void;
}) {
  const t = useTranslations();
  const format = useFormatter();
  const run = flowDeliverables(
    flow.steps.map((step) => (step.id === stepId ? { ...step, ...draft } : step))
  );
  const included = run.deliverables.some((step) => step.id === stepId);
  // Readers come from the saved flow: a later prompt names this step as saved,
  // and the core rewrites it when a new name is saved.
  const self = flow.steps.find((step) => step.id === stepId);
  const order = self?.step_order ?? 0;
  // A later AI step can read this one through its prompt, which lives on its
  // assistant. Only a current prompt counts: one read before a change may name
  // this step when the saved one no longer does.
  const later = flow.steps.filter((step) => step.step_order > order && !sendsRunResult(step));
  const { prompts, current } = useStepPromptsState(flow.id, later, true);
  const readers = self ? stepReadersByNameOrPlace(self, flow.steps, prompts) : [];
  const name = (step: FlowStep) => stepLabel(step.step_order, step.user_description, t);
  // The last working step has no later step to name. "Read by no step" waits
  // for every prompt to be current: one not read, or read before a change, may name this step.
  const readLine =
    later.length === 0
      ? null
      : readers.length === 1 && readers[0]!.step_order === order + 1
        ? t("flow_step_editor_delivery_read_next", { step: name(readers[0]!) })
        : readers.length > 0
          ? t("flow_step_editor_delivery_read_by", { steps: format.list(readers.map(name)) })
          : current
            ? t(
                included
                  ? "flow_step_editor_delivery_unread_included"
                  : "flow_step_editor_delivery_unread_off"
              )
            : null;

  const sender = run.sender;
  const host = sender ? runResultHost(sender) : null;
  const sendLine = !sender
    ? t("flow_step_editor_delivery_no_sender")
    : !host
      ? t("flow_step_editor_delivery_no_address")
      : included
        ? t("flow_step_editor_delivery_sent_to", { host })
        : t("flow_step_editor_delivery_not_sent_to", { host });
  const senderId = sender?.id;

  return (
    <EditorSection
      id={sectionId}
      title={t("flow_step_editor_delivery_title")}
      description={t("flow_step_editor_delivery_description")}
    >
      {readLine && (
        <HStack gap={2} align="center">
          <ArrowRight className="text-ax-text-secondary size-4 shrink-0" aria-hidden="true" />
          <Text type="supporting" size="sm" as="p" display="block" className="m-0 max-w-prose">
            {readLine}
          </Text>
        </HStack>
      )}
      <DeliverableFields
        formId={formId}
        flow={flow}
        stepId={stepId}
        run={run}
        draft={draft}
        groups={groups}
        onChange={onChange}
        problems={problems}
      />
      <HStack gap={3} align="center" justify="between" wrap="wrap">
        <HStack gap={2} align="center">
          <Send className="text-ax-text-secondary size-4 shrink-0" aria-hidden="true" />
          <Text type="supporting" size="sm" as="p" display="block" className="m-0 max-w-prose">
            {sendLine}
          </Text>
        </HStack>
        {senderId && onGoStep && (
          <Button
            label={t("flow_step_editor_delivery_open_sender")}
            size="sm"
            variant="secondary"
            onClick={() => onGoStep(senderId)}
          />
        )}
      </HStack>
      {senderId && onGoStep && dirty && (
        // It opens the saved flow; leaving asks first, as every other way out does.
        <Text type="supporting" size="sm" as="p" display="block" className="m-0 max-w-prose">
          {t("flow_step_editor_delivery_save_first")}
        </Text>
      )}
    </EditorSection>
  );
}
