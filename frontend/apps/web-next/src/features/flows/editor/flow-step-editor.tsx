"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { Suspense, useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { TextInput } from "@astryxdesign/core/TextInput";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { ListError } from "@/components/composites/query-state";
import { LoadingState } from "@/components/composites/loading-state";
import { SpaceProvider, useSpace } from "@/features/spaces/use-space";
import { useBeforeUnloadWarning } from "@/lib/hooks/use-before-unload-warning";
import {
  classificationPreviewQueryOptions,
  flowAssistantQueryOptions,
  getFlow,
  refreshFlowAssistant,
  updateFlowEditor
} from "./editor-api";
import { Anchor, focusAnchor, problemStatus } from "./editor-fields";
import { RecordUploadProvider, useEditorUploads } from "./editor-uploads";
import { TemplateScope } from "./reference-text-area";
import {
  describeSaveError,
  FIELD_ANCHORS,
  isStaleRevision,
  type FieldAnchor,
  type FieldProblems
} from "./field-problems";
import { StepAdvancedSection, parseContract, type ContractDrafts } from "./step-advanced-section";
import { StepAiSection } from "./step-ai-section";
import {
  httpUrlProblem,
  readHttpConfig,
  readTextProcessingMode,
  readToolConfig
} from "./step-configs";
import { StepControlSection } from "./step-control-section";
import {
  assistantChanges,
  buildEditorUpdate,
  classificationPreviewRequest,
  draftAssistant,
  draftStep,
  findStep,
  isLastStep,
  promptDescriptionOf,
  stepChanges,
  type AssistantEdits,
  type StepEdits
} from "./step-draft";
import { StepInputSection } from "./step-input-section";
import { stepNameTaken } from "./step-kinds";
import { inputSourceLabel, outputModeLabel, stepLabel } from "./step-labels";
import { StepOutputSection } from "./step-output-section";
import { StepReadOnly } from "./step-read-only";
import { StepRequestPreviewButton } from "./step-request-preview";
import { stepUsesModel } from "./step-rules";
import {
  assistantConfigOf,
  EDITABLE_STEP_FIELDS,
  sameJson,
  stepConfigOf,
  type AssistantConfig,
  type FlowAssistant,
  type FlowPublic,
  type StepConfig
} from "./step-types";
import { variableGroups } from "./step-variables";
import { useDebouncedValue } from "./use-debounced-value";

type EditorProps = {
  flow: FlowPublic;
  stepId: string;
  readOnly: boolean;
  onSaved: (flow: FlowPublic) => void;
  onCancel: () => void;
};

/**
 * The configuration of one flow step and its step assistant: what it reads,
 * what it does, what it hands on, who reviews it and the classification its
 * result carries. Save sends one revision-fenced editor PATCH with only the
 * fields that changed; a draft that moved on elsewhere (`stale_revision`)
 * keeps the edits and offers to put them on the latest version. Read-only
 * shows the same settings as text.
 */
export function FlowStepEditor(props: EditorProps): React.JSX.Element {
  const t = useTranslations();
  return (
    // The knowledge picker and the model list read the flow's space.
    <SpaceProvider routeId={props.flow.space_id}>
      <Suspense fallback={<LoadingState label={t("flow_step_editor_loading")} rows={6} />}>
        <StepEditorSession key={`${props.flow.id}:${props.stepId}`} {...props} />
      </Suspense>
    </SpaceProvider>
  );
}

/** The fields of the step a change of `field` may have fixed. */
function anchorsOf(field: string): FieldAnchor[] {
  return FIELD_ANCHORS.filter((anchor) => anchor === field || anchor.startsWith(`${field}.`));
}

const ASSISTANT_ANCHORS: Record<keyof AssistantConfig, FieldAnchor> = {
  prompt: "prompt",
  completion_model_id: "completion_model",
  completion_model_kwargs: "completion_model_kwargs",
  groups: "knowledge",
  websites: "knowledge",
  integration_knowledge_list: "knowledge",
  attachments: "attachments"
};

type Session = {
  flow: FlowPublic;
  saved: StepConfig;
  draft: StepConfig;
  stepOrder: number;
  assistantId: string;
  dirty: boolean;
};

function StepEditorSession({ flow: propFlow, stepId, readOnly, onSaved, onCancel }: EditorProps) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const { space } = useSpace();
  const formId = useId();
  const headingId = useId();
  const summaryRef = useRef<HTMLDivElement>(null);

  // The newest flow this editor has seen: the host's, or one it read or saved.
  const [received, setReceived] = useState<FlowPublic | null>(null);
  const latest =
    received && received.draft_revision >= propFlow.draft_revision ? received : propFlow;
  // The revision the edits were made against, held while they change something.
  const [pinned, setPinned] = useState<FlowPublic | null>(null);
  const [stepEdits, setStepEdits] = useState<StepEdits>({});
  const [assistantEdits, setAssistantEdits] = useState<AssistantEdits>({});
  const [contractDrafts, setContractDrafts] = useState<ContractDrafts>({});
  const [serverProblems, setServerProblems] = useState<FieldProblems>({});
  const [formProblems, setFormProblems] = useState<string[]>([]);
  const [checked, setChecked] = useState(false);
  const [stale, setStale] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  const latestStep = findStep(latest, stepId);
  // Files uploaded in this edit go again when it ends without saving them.
  const uploads = useEditorUploads(propFlow, latestStep?.assistant_id ?? "");
  const assistantQuery = useQuery({
    ...flowAssistantQueryOptions(latest.id, latestStep?.assistant_id ?? ""),
    enabled: latestStep !== null
  });
  const savedAssistant: FlowAssistant | null = assistantQuery.data ?? null;
  const assistantSaved = savedAssistant ? assistantConfigOf(savedAssistant) : null;
  const assistantDraft = assistantSaved ? draftAssistant(assistantSaved, assistantEdits) : null;
  const assistantUpdate =
    assistantSaved && assistantDraft
      ? assistantChanges(assistantSaved, assistantDraft, {
          promptDescription: promptDescriptionOf(savedAssistant),
          models: space.completion_models
        })
      : null;
  const invalidContract = Object.values(contractDrafts).some(
    (text) => text !== undefined && parseContract(text) === undefined
  );

  function sessionOf(flow: FlowPublic): Session | null {
    const step = findStep(flow, stepId);
    if (!step) return null;
    const saved = stepConfigOf(step);
    const draft = draftStep(saved, stepEdits);
    return {
      flow,
      saved,
      draft,
      stepOrder: step.step_order,
      assistantId: step.assistant_id,
      dirty: stepChanges(saved, draft) !== null || assistantUpdate !== null || invalidContract
    };
  }

  const pinnedSession = pinned ? sessionOf(pinned) : null;
  const session = pinnedSession?.dirty ? pinnedSession : sessionOf(latest);
  const newerElsewhere =
    session !== null && session.dirty && session.flow.draft_revision < latest.draft_revision;
  const dirty = session?.dirty ?? false;
  const effectiveReadOnly = readOnly || latest.published_version != null;
  useBeforeUnloadWarning(dirty && !effectiveReadOnly);

  const stepPatch = session ? stepChanges(session.saved, session.draft) : null;
  const previewJson = JSON.stringify(
    session && assistantDraft && assistantSaved
      ? classificationPreviewRequest({
          flow: session.flow,
          stepId,
          draft: session.draft,
          assistantId: session.assistantId,
          assistant: assistantDraft,
          savedAssistant: assistantSaved
        })
      : null
  );
  const debouncedPreview = useDebouncedValue(previewJson, 400);
  const previewRequest = JSON.parse(debouncedPreview) as
    Parameters<typeof classificationPreviewQueryOptions>[1] | null;
  const preview = useQuery({
    ...classificationPreviewQueryOptions(latest.id, previewRequest ?? {}),
    enabled: previewRequest !== null && !effectiveReadOnly,
    placeholderData: keepPreviousData
  });
  const classification =
    preview.data?.steps.find((item) => item.step_id === stepId) ??
    preview.data?.steps.find((item) => item.step_order === session?.stepOrder) ??
    null;

  const save = useMutation({
    mutationFn: async (current: Session) => {
      const update = buildEditorUpdate({
        flow: current.flow,
        stepId,
        stepPatch: stepChanges(current.saved, current.draft),
        assistantId: current.assistantId,
        assistantUpdate,
        draft: current.draft
      });
      const updated = await updateFlowEditor(current.flow.id, update);
      if (update.assistants?.length) {
        await refreshFlowAssistant(queryClient, current.flow.id, current.assistantId);
      }
      return updated;
    },
    onSuccess: (updated) => {
      uploads.keepSaved(updated);
      setReceived(updated);
      setPinned(null);
      setStepEdits({});
      setAssistantEdits({});
      setContractDrafts({});
      setServerProblems({});
      setFormProblems([]);
      setChecked(false);
      setStale(false);
      announce(t("flow_step_editor_saved"));
      onSaved(updated);
    },
    onError: (error, current) => {
      if (isStaleRevision(error)) {
        flushSync(() => setStale(true));
        summaryRef.current?.focus();
        return;
      }
      const problem = describeSaveError(
        error,
        { stepId, stepOrder: current.stepOrder, config: current.draft },
        t
      );
      const message =
        problem.otherStepOrder !== null
          ? t("flow_step_editor_other_step_problem", {
              step: stepLabel(
                problem.otherStepOrder,
                current.flow.steps.find((item) => item.step_order === problem.otherStepOrder)
                  ?.user_description,
                t
              ),
              message: problem.message
            })
          : problem.message;
      if (problem.anchor) {
        const anchor = problem.anchor;
        flushSync(() => {
          setServerProblems({ [anchor]: message });
          setFormProblems([]);
        });
        if (!focusAnchor(formId, anchor)) summaryRef.current?.focus();
      } else {
        flushSync(() => {
          setServerProblems({});
          setFormProblems([message]);
        });
        summaryRef.current?.focus();
      }
    }
  });

  const reload = useMutation({
    mutationFn: async () => {
      const fresh = await getFlow(latest.id);
      const step = findStep(fresh, stepId);
      if (step) await refreshFlowAssistant(queryClient, fresh.id, step.assistant_id);
      return fresh;
    },
    onSuccess: (fresh) => {
      setReceived(fresh);
      setPinned(fresh);
      setStale(false);
      setServerProblems({});
      setFormProblems([]);
      announce(t("flow_step_editor_reloaded"));
    }
  });

  // --- Loading and missing states -------------------------------------------------

  if (!session) {
    return (
      <div className="flex flex-col gap-4">
        <Banner
          role="alert"
          status="warning"
          title={t("flow_step_editor_step_missing")}
          collapsible={false}
        />
        <div>
          <Button label={t("close")} onClick={onCancel} />
        </div>
      </div>
    );
  }
  if (assistantQuery.isPending) {
    return <LoadingState label={t("flow_step_editor_loading")} rows={6} />;
  }
  if (assistantQuery.isError || !assistantDraft || !savedAssistant) {
    return (
      <ListError
        error={assistantQuery.error}
        onRetry={() => void assistantQuery.refetch()}
        title={t("flow_step_editor_assistant_failed")}
      />
    );
  }

  const { draft, stepOrder, flow } = session;
  const usesModel = stepUsesModel(draft);
  const isLast = isLastStep(flow, { step_order: stepOrder });
  const groups = variableGroups({ flow, stepOrder, inputConfig: draft.input_config });
  // Only the AI instruction runs once per section, so only it reads the section's number.
  const promptGroups = variableGroups({
    flow,
    stepOrder,
    inputConfig: draft.input_config,
    sectionVariables: readTextProcessingMode(draft.input_config) === "process_each_section"
  });
  const wholeValueGroups = variableGroups({
    flow,
    stepOrder,
    inputConfig: draft.input_config,
    wholeValue: true
  });

  // --- Edits ------------------------------------------------------------------------

  function pin() {
    if (!pinned || !pinnedSession?.dirty) setPinned(flow);
  }

  function changeStep(next: StepConfig) {
    if (!session) return;
    pin();
    const current = session.draft;
    const changed = EDITABLE_STEP_FIELDS.filter((field) => !sameJson(current[field], next[field]));
    if (changed.length === 0) return;
    setStepEdits((edits) => ({
      ...edits,
      ...Object.fromEntries(changed.map((field) => [field, next[field]]))
    }));
    setServerProblems((problems) => {
      const cleared = new Set(changed.flatMap(anchorsOf));
      return Object.fromEntries(
        Object.entries(problems).filter(([anchor]) => !cleared.has(anchor as FieldAnchor))
      );
    });
  }

  function changeAssistant(change: Partial<AssistantConfig>) {
    pin();
    setAssistantEdits((edits) => ({ ...edits, ...change }));
    setServerProblems((problems) => {
      const cleared = new Set(
        (Object.keys(change) as (keyof AssistantConfig)[]).map((field) => ASSISTANT_ANCHORS[field])
      );
      return Object.fromEntries(
        Object.entries(problems).filter(([anchor]) => !cleared.has(anchor as FieldAnchor))
      );
    });
  }

  // --- Checks before a save -----------------------------------------------------------

  function localProblems(current: StepConfig): FieldProblems {
    const problems: FieldProblems = {};
    const name = current.user_description?.trim() ?? "";
    if (!name) problems.user_description = t("flow_step_editor_name_required");
    else if (name.length > 200) problems.user_description = t("flow_step_editor_name_too_long");
    else if (stepNameTaken(flow, name, stepId)) {
      problems.user_description = t("flow_step_editor_name_taken");
    }
    if (current.input_source === "http_get") {
      const problem = httpUrlProblem(readHttpConfig(current.input_config, "input").url);
      if (problem) {
        problems["input_config.http"] =
          problem === "missing"
            ? t("flow_step_editor_http_url_missing")
            : t("flow_step_editor_http_url_invalid");
      }
    }
    if (current.output_mode === "http_post") {
      const problem = httpUrlProblem(readHttpConfig(current.output_config, "output").url);
      if (problem) {
        problems["output_config.http"] =
          problem === "missing"
            ? t("flow_step_editor_http_url_missing")
            : t("flow_step_editor_http_url_invalid");
      }
    }
    if (current.input_source === "tool" && readToolConfig(current.input_config) === null) {
      problems["input_config.tool"] = t("flow_step_editor_tool_required");
    }
    for (const field of ["input_contract", "output_contract"] as const) {
      const text = contractDrafts[field];
      if (text !== undefined && parseContract(text) === undefined) {
        problems[field] = t("flow_step_editor_contract_invalid");
      }
    }
    return problems;
  }

  const shownProblems: FieldProblems = {
    ...serverProblems,
    ...(checked ? localProblems(draft) : {})
  };

  function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || save.isPending || effectiveReadOnly) return;
    const problems = localProblems(session.draft);
    const first = FIELD_ANCHORS.find((anchor) => problems[anchor]);
    if (first) {
      flushSync(() => setChecked(true));
      if (!focusAnchor(formId, first)) summaryRef.current?.focus();
      return;
    }
    if (!session.dirty) {
      announce(t("flow_step_editor_nothing_to_save"));
      return;
    }
    setFormProblems([]);
    save.mutate(session);
  }

  function requestCancel() {
    if (dirty && !effectiveReadOnly) {
      setConfirmDiscard(true);
      return;
    }
    uploads.release();
    onCancel();
  }

  const changeCount =
    (stepPatch ? Object.keys(stepPatch).length : 0) +
    (assistantUpdate ? Object.keys(assistantUpdate).length : 0);
  const name = draft.user_description?.trim() || t("flow_step_editor_unnamed");

  const header = (
    <header className="flex flex-col gap-2">
      <Text type="supporting" size="sm">
        {t("flow_step_editor_step_number", { order: stepOrder })}
      </Text>
      <Heading level={2} id={headingId}>
        {name}
      </Heading>
      <div className="flex flex-wrap items-center gap-2">
        <Token label={inputSourceLabel(draft.input_source, t)} size="sm" />
        <ArrowRight className="text-ax-text-secondary size-4" aria-hidden="true" />
        <Token label={outputModeLabel(draft.output_mode, t)} size="sm" color="blue" />
      </div>
      <StepRequestPreviewButton
        flow={flow}
        stepOrder={stepOrder}
        draft={draft}
        assistant={assistantDraft}
      />
    </header>
  );

  if (effectiveReadOnly) {
    return (
      <section aria-labelledby={headingId} className="flex flex-col gap-6">
        {header}
        {latest.published_version != null && !readOnly && (
          <Banner status="info" title={t("flow_step_editor_published")} collapsible={false} />
        )}
        <StepReadOnly flow={flow} step={draft} assistant={assistantDraft} />
        <div>
          <Button label={t("close")} onClick={onCancel} />
        </div>
      </section>
    );
  }

  return (
    <section aria-labelledby={headingId} className="flex min-h-0 flex-col">
      <form
        id={formId}
        noValidate
        onSubmit={submit}
        // Tab and focus() scroll a field into view above the docked save bar (WCAG 2.4.11).
        className="flex flex-col gap-6 pb-4 [&_:is(input,textarea,button,[tabindex])]:scroll-mb-28"
      >
        {header}

        <div
          ref={summaryRef}
          tabIndex={-1}
          className="focus-visible:outline-ring flex flex-col gap-3 outline-none focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          {stale && (
            <Banner
              role="alert"
              status="error"
              title={t("flow_step_editor_stale_title")}
              description={t("flow_step_editor_stale_description")}
              collapsible={false}
              endContent={
                <Button
                  label={t("flow_step_editor_reload")}
                  size="sm"
                  isLoading={reload.isPending}
                  isInterruptible
                  onClick={() => {
                    if (!reload.isPending) reload.mutate();
                  }}
                />
              }
            />
          )}
          {reload.isError && (
            <Banner
              role="alert"
              status="error"
              title={t("flow_step_editor_reload_failed")}
              collapsible={false}
            />
          )}
          {newerElsewhere && !stale && (
            <Banner
              status="info"
              title={t("flow_step_editor_newer_title")}
              description={t("flow_step_editor_newer_description")}
              collapsible={false}
              endContent={
                <Button
                  label={t("flow_step_editor_reload")}
                  size="sm"
                  onClick={() => {
                    setPinned(latest);
                    void refreshFlowAssistant(queryClient, latest.id, session.assistantId);
                  }}
                />
              }
            />
          )}
          {formProblems.length > 0 && (
            <Banner
              role="alert"
              status="error"
              title={t("flow_step_editor_save_refused")}
              description={formProblems.join(" ")}
              collapsible={false}
            />
          )}
          {checked && Object.keys(localProblems(draft)).length > 0 && (
            <Banner
              role="alert"
              status="error"
              title={t("flow_step_editor_fix_fields", {
                count: Object.keys(localProblems(draft)).length
              })}
              collapsible={false}
            />
          )}
        </div>

        {/* Remounted per saved revision: local states (a secret being replaced) start over. */}
        <RecordUploadProvider value={uploads.record}>
          <TemplateScope value={{ flow, stepOrder }}>
            <div key={flow.draft_revision} className="flex flex-col gap-6">
              <Anchor formId={formId} anchor="user_description">
                <TextInput
                  label={t("flow_step_name")}
                  description={t("flow_step_editor_name_description")}
                  value={draft.user_description ?? ""}
                  onChange={(value) => changeStep({ ...draft, user_description: value || null })}
                  isRequired
                  autoComplete="off"
                  status={problemStatus(shownProblems.user_description)}
                />
              </Anchor>

              {usesModel && (
                <StepAiSection
                  formId={formId}
                  sectionId={`${formId}-ai`}
                  draft={draft}
                  assistant={assistantDraft}
                  savedAssistant={savedAssistant}
                  onAssistantChange={changeAssistant}
                  onStepChange={changeStep}
                  problems={shownProblems}
                  groups={promptGroups}
                  classification={classification}
                />
              )}

              <StepInputSection
                formId={formId}
                sectionId={`${formId}-input`}
                flow={flow}
                stepId={stepId}
                stepOrder={stepOrder}
                draft={draft}
                onChange={changeStep}
                problems={shownProblems}
                groups={groups}
                toolGroups={wholeValueGroups}
                showUnderlag={
                  draft.output_mode !== "transcribe_only" && draft.output_mode !== "template_fill"
                }
              />

              <StepOutputSection
                formId={formId}
                sectionId={`${formId}-output`}
                flow={flow}
                stepId={stepId}
                draft={draft}
                isLast={isLast}
                onChange={changeStep}
                problems={shownProblems}
                groups={groups}
                wholeValueGroups={wholeValueGroups}
                onContractProposed={(contract) => {
                  // The advanced section shows the accepted contract, not text typed before it.
                  setContractDrafts((drafts) => ({ ...drafts, output_contract: undefined }));
                  changeStep({ ...draft, output_contract: contract });
                  announce(t("flow_editor_tools_contract_example_accepted"));
                }}
              />

              <StepControlSection
                formId={formId}
                sectionId={`${formId}-control`}
                draft={draft}
                onChange={changeStep}
                problems={shownProblems}
                preview={{
                  data: classification,
                  isPending: preview.isPending && previewRequest !== null,
                  error: preview.isError ? preview.error : null
                }}
              />

              <StepAdvancedSection
                formId={formId}
                sectionId={`${formId}-advanced`}
                draft={draft}
                onChange={changeStep}
                drafts={contractDrafts}
                onDraftsChange={(next) => {
                  pin();
                  setContractDrafts(next);
                }}
                problems={shownProblems}
              />
            </div>
          </TemplateScope>
        </RecordUploadProvider>
      </form>

      <div
        data-clear-of-toasts
        className="bg-ax-surface border-ax-border sticky bottom-0 flex flex-wrap items-center gap-3 border-t py-3"
      >
        <Text type="supporting" size="sm" className="min-w-0 flex-1">
          {dirty
            ? t("flow_step_editor_changes", { count: Math.max(changeCount, 1) })
            : t("flow_step_editor_no_changes")}
        </Text>
        <Button label={t("cancel")} onClick={requestCancel} />
        <Button
          type="submit"
          form={formId}
          variant="primary"
          label={t("flow_step_editor_save")}
          isLoading={save.isPending}
          isInterruptible
        />
      </div>

      <ConfirmDialogControlled
        open={confirmDiscard}
        onOpenChange={setConfirmDiscard}
        title={t("flow_step_editor_discard_title")}
        description={t("flow_step_editor_discard_description")}
        confirmLabel={t("flow_step_editor_discard")}
        variant="destructive"
        onConfirm={() => {
          setConfirmDiscard(false);
          uploads.release();
          onCancel();
        }}
      />
    </section>
  );
}
