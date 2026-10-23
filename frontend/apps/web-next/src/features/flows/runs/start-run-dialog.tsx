"use client";

import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useImperativeHandle, useRef, useState, type Ref } from "react";
import { flushSync } from "react-dom";
import { ListError } from "@/components/composites/query-state";
import { LoadingState } from "@/components/composites/loading-state";
import { toast } from "@/lib/toast";
import { restrictedBeforeApproval } from "../flow-form-fields";
import type { FlowPublic } from "../flows-api";
import { RecordingKeeper } from "./recording/recording-keeper";
import { RunRecorder, type RecorderHandle } from "./recording/run-recorder";
import {
  blockingTemplates,
  doneKeys,
  exceedsAggregate,
  fieldProblems,
  inputProblems,
  labelsSpeakers,
  offersMaxSpeakers,
  offersSingleRecording,
  orderedFields,
  orderedInputs,
  refusalTargets,
  runRequest,
  speakersBlockRun,
  takesFreeText,
  type FieldValue,
  type FormValues
} from "./run-contract";
import { inputAnchorId, inputProblemText, RunFileInput } from "./run-file-inputs";
import {
  fieldAnchorId,
  fieldProblemText,
  focusFirstControl,
  RunFormFieldControl
} from "./run-form-fields";
import { flowErrorText, refusalText } from "./run-messages";
import {
  newIdempotencyKey,
  runContractQueryOptions,
  runKeys,
  startRun,
  type RunContract,
  type RunCreateRequest,
  type RunPublic
} from "./runs-api";
import { startSummary, withRunLabel, type StartSummary } from "./start-run-checks";
import {
  RunLabelField,
  ReuseLastInput,
  TemplateReadiness,
  useAudioLengthCheck
} from "./start-run-extras";
import { StartRunSummary } from "./start-run-summary";
import { useRuntimeUploads } from "./use-runtime-uploads";

type ServerProblems = {
  fields: Record<string, string>;
  inputs: Record<string, string>;
};

const NO_SERVER_PROBLEMS: ServerProblems = { fields: {}, inputs: {} };

/** What the dialog asks of its form. */
type StartRunFormHandle = {
  /** A recording runs, or recorded parts would be thrown away with the form. */
  holdsRecording: () => boolean;
  /** Something is filled in or uploaded that closing the form would throw away. */
  holdsInput: () => boolean;
  /** The form's recordings are thrown away, from this device too. */
  discardRecordings: () => void;
  /** Moves focus to the form's first control, after going back from the summary. */
  focusForm: () => void;
};

/** The record without `key`. */
function without(record: Record<string, string>, key: string): Record<string, string> {
  return Object.fromEntries(Object.entries(record).filter(([name]) => name !== key));
}

/** The notices that keep the flow from running, or that the person should know first. */
function ContractNotices({ flow, contract }: { flow: FlowPublic; contract: RunContract }) {
  const t = useTranslations();
  const classification = contract.security_classification;
  const labels = contract.transcription?.speaker_labels;
  const templates = blockingTemplates(contract);
  return (
    <>
      {classification ? (
        <Banner
          status="info"
          title={t("flow_runs_classification_title", { name: classification.name })}
          description={classification.description?.trim() || undefined}
          collapsible={false}
        />
      ) : null}
      {restrictedBeforeApproval(flow.metadata_json) ? (
        <Banner
          status="warning"
          title={t("flow_runs_sensitive_title")}
          description={t("flow_runs_sensitive_body")}
          collapsible={false}
        />
      ) : null}
      {templates.length > 0 ? (
        <Banner
          status="error"
          title={t("flow_runs_template_blocked_title")}
          description={templates
            .map(
              (item) =>
                flowErrorText(item.message_code, t) ??
                (item.template_name
                  ? t("flow_runs_template_blocked_named", { name: item.template_name })
                  : t("flow_runs_template_blocked"))
            )
            .join(" ")}
          collapsible={false}
        />
      ) : null}
      {labels?.unavailable_reason ? (
        <Banner
          status={labels.required ? "error" : "warning"}
          title={
            labels.required
              ? t("flow_runs_speakers_blocked_title")
              : t("flow_runs_speakers_skipped_title")
          }
          description={
            labels.unavailable_reason === "not_chosen"
              ? t("flow_runs_speakers_not_chosen")
              : t("flow_runs_speakers_picked_unavailable")
          }
          collapsible={false}
        />
      ) : null}
      <TemplateReadiness contract={contract} />
    </>
  );
}

function StartRunForm({
  flow,
  contract,
  formId,
  reviewing,
  onReview,
  onPendingChange,
  onStarted,
  onSaveForLater,
  handleRef
}: {
  flow: FlowPublic;
  contract: RunContract;
  formId: string;
  /** The summary shows: the form is hidden, and sending it starts the run. */
  reviewing: boolean;
  /** Shows the summary of what the form sends, or (null) the form again. */
  onReview: (summary: StartSummary | null) => void;
  onPendingChange: (pending: boolean) => void;
  onStarted: (run: RunPublic) => void;
  /** Closes the form; its recordings stay on the device to continue later. */
  onSaveForLater: () => void;
  handleRef?: Ref<StartRunFormHandle>;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const summaryRef = useRef<HTMLDivElement>(null);
  const lastRequest = useRef<{ body: string; key: string } | null>(null);
  const { uploads, add, remove, retry, fileOf, claim } = useRuntimeUploads(
    flow.id,
    contract.runtime_upload_policy
  );
  // Each audio step's recorder, asked from the event handlers below.
  const recorders = useRef(new Map<string, RecorderHandle>());
  const [waitingForText, setWaitingForText] = useState(false);
  // The step whose recording ran when the person tried to start the run.
  const [stopFirst, setStopFirst] = useState<string | null>(null);

  // The form's recordings, kept on the device until the run takes them or they are thrown away.
  const [keeper] = useState(() => new RecordingKeeper(flow.id));

  function recorderRef(stepId: string) {
    return (handle: RecorderHandle | null) => {
      if (handle) recorders.current.set(stepId, handle);
      else recorders.current.delete(stepId);
    };
  }
  const [values, setValues] = useState<FormValues>({});
  const [freeText, setFreeText] = useState("");
  const [singleRecording, setSingleRecording] = useState<ReadonlySet<string>>(new Set());
  const [speakerLabels, setSpeakerLabels] = useState<boolean | null>(null);
  const [maxSpeakers, setMaxSpeakers] = useState<number | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [server, setServer] = useState<ServerProblems>(NO_SERVER_PROBLEMS);
  const [formProblem, setFormProblem] = useState<string | null>(null);

  const fields = orderedFields(contract);
  const inputs = orderedInputs(contract);
  const freeTextForm = takesFreeText(contract);
  const labels = contract.transcription?.speaker_labels;
  const blocked = blockingTemplates(contract).length > 0 || speakersBlockRun(contract);

  const fieldIssues = submitted ? fieldProblems(fields, values) : {};
  const inputIssues = submitted ? inputProblems(contract, uploads) : {};
  const tooManyInAll = submitted && exceedsAggregate(contract, uploads);

  function fieldMessage(name: string): string | null {
    const field = fields.find((candidate) => candidate.name === name);
    const issue = fieldIssues[name];
    if (field && issue) return fieldProblemText(field, issue, t);
    return server.fields[name] ?? null;
  }

  function inputMessage(stepId: string): string | null {
    if (stopFirst === stepId) return t("flow_transcript_rec_stop_first");
    const input = inputs.find((candidate) => candidate.step_id === stepId);
    const issue = inputIssues[stepId];
    if (input && issue) return inputProblemText(input, issue, t);
    return server.inputs[stepId] ?? null;
  }

  function setValue(name: string, value: FieldValue) {
    setValues((current) => ({ ...current, [name]: value }));
    if (server.fields[name]) {
      setServer((current) => ({ ...current, fields: without(current.fields, name) }));
    }
  }

  function clearInputProblem(stepId: string) {
    if (!server.inputs[stepId]) return;
    setServer((current) => ({ ...current, inputs: without(current.inputs, stepId) }));
  }

  function showFormProblem(message: string) {
    flushSync(() => setFormProblem(message));
    summaryRef.current?.focus();
  }

  const [runLabel, setRunLabel] = useState("");

  useImperativeHandle(handleRef, () => ({
    holdsRecording: () =>
      [...recorders.current.values()].some((recorder) => recorder.busy()) ||
      Object.values(uploads).some((entries) => entries.some((entry) => entry.recording)),
    holdsInput: () =>
      Object.values(values).some((value) =>
        Array.isArray(value) ? value.some((item) => item.trim()) : value.trim() !== ""
      ) ||
      freeText.trim() !== "" ||
      runLabel.trim() !== "" ||
      Object.values(uploads).some((entries) => entries.length > 0),
    discardRecordings: () => void keeper.forgetAll(),
    focusForm: () => void focusFirstControl(formId)
  }));

  const screenAudio = useAudioLengthCheck((stepId, message) =>
    setServer((current) => ({ ...current, inputs: { ...current.inputs, [stepId]: message } }))
  );

  const start = useMutation({
    mutationFn: (request: RunCreateRequest) => {
      const body = withRunLabel(request, runLabel);
      // A retried request with the same body keeps its key, so a lost
      // response cannot start the run twice; a changed body is a new run.
      const serialized = JSON.stringify(body);
      const key =
        lastRequest.current?.body === serialized ? lastRequest.current.key : newIdempotencyKey();
      lastRequest.current = { body: serialized, key };
      return startRun(flow.id, body, key);
    },
    onMutate: () => onPendingChange(true),
    onSettled: () => onPendingChange(false),
    onSuccess: (run) => {
      claim();
      // The run took the recordings: nothing is left to continue on this device.
      void keeper.forgetAll();
      onStarted(run);
    },
    onError: (error) => {
      const message = refusalText(error, t);
      const targets = refusalTargets(error, contract);
      const first = targets[0];
      // The person fixes what the core refused in the form.
      onReview(null);
      if (first?.kind === "field") {
        flushSync(() =>
          setServer((current) => ({
            ...current,
            fields: { ...current.fields, [first.name]: message }
          }))
        );
        focusFirstControl(fieldAnchorId(formId, first.name));
        return;
      }
      if (first?.kind === "input") {
        flushSync(() =>
          setServer((current) => ({
            ...current,
            inputs: {
              ...current.inputs,
              ...Object.fromEntries(
                targets.flatMap((target) =>
                  target.kind === "input" ? [[target.stepId, message]] : []
                )
              )
            }
          }))
        );
        focusFirstControl(inputAnchorId(formId, first.stepId));
        return;
      }
      // A republished flow may ask for other fields: read the contract again.
      void queryClient.invalidateQueries({ queryKey: runKeys.contract(flow.id) });
      showFormProblem(message);
    }
  });

  function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (start.isPending || waitingForText) return;
    if (reviewing) {
      void startNow();
      return;
    }
    const foundFields = fieldProblems(fields, values);
    const foundInputs = inputProblems(contract, uploads);
    flushSync(() => {
      setSubmitted(true);
      setFormProblem(null);
    });
    const firstField = fields.find((field) => foundFields[field.name]);
    if (firstField) {
      focusFirstControl(fieldAnchorId(formId, firstField.name));
      return;
    }
    // A recording still running is not a file yet.
    const recording = inputs.find((input) => recorders.current.get(input.step_id)?.busy());
    if (recording) {
      flushSync(() => setStopFirst(recording.step_id));
      focusFirstControl(inputAnchorId(formId, recording.step_id));
      return;
    }
    const firstInput = inputs.find((input) => foundInputs[input.step_id]);
    if (firstInput) {
      focusFirstControl(inputAnchorId(formId, firstInput.step_id));
      return;
    }
    if (exceedsAggregate(contract, uploads)) {
      showFormProblem(
        t("flow_runs_too_many_files_in_all", { count: contract.aggregate_max_files ?? 0 })
      );
      return;
    }
    if (blocked) {
      showFormProblem(t("flow_runs_blocked"));
      return;
    }
    // Everything can be sent: the person sees what before the run starts.
    onReview(startSummary(contract, { runLabel, values, freeText, uploads }));
  }

  async function startNow() {
    // The final text of a recording heard whole may spare the run transcribing it again.
    const handles = [...recorders.current.values()];
    if (handles.some((recorder) => recorder.finishing())) {
      setWaitingForText(true);
      onPendingChange(true);
      announce(t("flow_transcript_live_waiting"));
      await Promise.all(handles.map((recorder) => recorder.settled()));
      setWaitingForText(false);
      onPendingChange(false);
    }
    const liveTranscripts = Object.fromEntries(
      inputs.flatMap((input) => {
        const id = recorders.current
          .get(input.step_id)
          ?.liveTranscriptFor(doneKeys(uploads[input.step_id]));
        return id ? [[input.step_id, id]] : [];
      })
    );
    start.mutate(
      runRequest(contract, {
        values,
        freeText,
        uploads,
        singleRecording,
        speakerLabels,
        maxSpeakers,
        liveTranscripts
      })
    );
  }

  const maxSpeakerOption = contract.transcription?.max_speakers;

  return (
    // Kept while the summary shows: the uploads and recordings live in it.
    <form
      id={formId}
      hidden={reviewing}
      noValidate
      onSubmit={submit}
      className="flex flex-col gap-5"
    >
      <ContractNotices flow={flow} contract={contract} />
      <div
        ref={summaryRef}
        tabIndex={-1}
        className="focus-visible:outline-ring outline-none focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        {formProblem || tooManyInAll ? (
          <Banner
            role="alert"
            status="error"
            title={t("flow_runs_not_started")}
            description={
              formProblem ??
              t("flow_runs_too_many_files_in_all", { count: contract.aggregate_max_files ?? 0 })
            }
            collapsible={false}
          />
        ) : null}
      </div>

      <ReuseLastInput
        flowId={flow.id}
        contract={contract}
        onApply={(input) => {
          setValues(input.values);
          if (input.freeText !== null) setFreeText(input.freeText);
          setServer((current) => ({ ...current, fields: {} }));
        }}
      />
      <RunLabelField value={runLabel} onChange={setRunLabel} />

      {fields.map((field) => (
        <RunFormFieldControl
          key={field.name}
          formId={formId}
          field={field}
          value={values[field.name]}
          onChange={(value) => setValue(field.name, value)}
          message={fieldMessage(field.name)}
        />
      ))}

      {freeTextForm ? (
        <TextArea
          label={t("flow_runs_free_text")}
          description={t("flow_runs_free_text_hint")}
          value={freeText}
          onChange={setFreeText}
          rows={5}
          width="100%"
        />
      ) : null}

      {inputs.map((input) => (
        <RunFileInput
          key={input.step_id}
          formId={formId}
          input={input}
          entries={uploads[input.step_id] ?? []}
          message={inputMessage(input.step_id)}
          onAdd={(files) => {
            clearInputProblem(input.step_id);
            screenAudio(input, files, (accepted) => add(input, accepted));
          }}
          onRemove={(key) => {
            clearInputProblem(input.step_id);
            const recorded = uploads[input.step_id]?.find((entry) => entry.key === key)?.recording;
            if (recorded) void keeper.forgetPart(input.step_id, recorded.sessionId, recorded.index);
            remove(input.step_id, key);
          }}
          onRetry={(key) => {
            clearInputProblem(input.step_id);
            retry(input.step_id, key);
          }}
          fileOf={fileOf}
          recorder={
            input.input_format === "audio" ? (
              <RunRecorder
                flowId={flow.id}
                input={input}
                live={contract.transcription?.live}
                entries={uploads[input.step_id] ?? []}
                onPart={(file, recording, label) => {
                  clearInputProblem(input.step_id);
                  setStopFirst((current) => (current === input.step_id ? null : current));
                  return add(input, [file], { recording, label })[0]?.key;
                }}
                keeper={keeper}
                publishedFlowVersion={contract.published_flow_version ?? null}
                onSaveForLater={onSaveForLater}
                onDiscard={(keys) => {
                  clearInputProblem(input.step_id);
                  for (const key of keys) remove(input.step_id, key);
                }}
                handleRef={recorderRef(input.step_id)}
              />
            ) : null
          }
          singleRecording={{
            offered: offersSingleRecording(contract, input, uploads[input.step_id]),
            value: singleRecording.has(input.step_id),
            onChange: (on) =>
              setSingleRecording((current) => {
                const next = new Set(current);
                if (on) next.add(input.step_id);
                else next.delete(input.step_id);
                return next;
              })
          }}
        />
      ))}

      {labels?.selectable ? (
        <CheckboxInput
          label={t("flow_runs_speaker_labels")}
          description={t("flow_runs_speaker_labels_hint")}
          value={labelsSpeakers(contract, speakerLabels)}
          onChange={setSpeakerLabels}
        />
      ) : null}
      {maxSpeakerOption && offersMaxSpeakers(contract, speakerLabels) ? (
        <NumberInput
          label={t("flow_runs_max_speakers")}
          description={
            maxSpeakerOption.default != null
              ? t("flow_runs_max_speakers_default", { count: maxSpeakerOption.default })
              : t("flow_runs_max_speakers_automatic")
          }
          value={maxSpeakers}
          onChange={(next) => setMaxSpeakers(next ?? null)}
          min={1}
          isIntegerOnly
          hasClear
          isOptional
          width="100%"
        />
      ) : null}
    </form>
  );
}

/**
 * Starts a run of a published flow from its run contract: the form fields,
 * each step's files (uploaded as they are picked), the transcription choices
 * the flow offers, and what keeps it from running. Problems show at the
 * field they concern, focus moves to the first, and a refusal from the core
 * lands at the field it names. A form that can be sent shows a summary of
 * what the run is sent before it starts, as the dialog's last step.
 */
export function StartRunDialog({
  flow,
  open,
  onOpenChange,
  onStarted
}: {
  flow: FlowPublic;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted: (run: RunPublic) => void;
}) {
  const t = useTranslations();
  const formId = useId();
  const [pending, setPending] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);
  // What closing would throw away: a recording, or what was filled in and uploaded.
  const [closeLoses, setCloseLoses] = useState<"recording" | "input">("recording");
  // What the run is sent, while the summary step shows; null on the form.
  const [summary, setSummary] = useState<StartSummary | null>(null);
  // Opened again, the dialog starts at the form.
  const [shownOpen, setShownOpen] = useState(open);
  if (shownOpen !== open) {
    setShownOpen(open);
    setSummary(null);
  }
  const summaryHeading = useRef<HTMLHeadingElement>(null);
  const form = useRef<StartRunFormHandle>(null);
  const contract = useQuery({ ...runContractQueryOptions(flow.id), enabled: open });

  function review(next: StartSummary | null) {
    flushSync(() => setSummary(next));
    if (next) summaryHeading.current?.focus();
  }

  function backToForm() {
    review(null);
    form.current?.focusForm();
  }

  function requestOpenChange(next: boolean) {
    if (!next && pending) return;
    // A recording exists only in this form: closing it throws the recording away.
    if (!next && form.current?.holdsRecording()) {
      setCloseLoses("recording");
      setConfirmClose(true);
      return;
    }
    if (!next && form.current?.holdsInput()) {
      setCloseLoses("input");
      setConfirmClose(true);
      return;
    }
    onOpenChange(next);
  }

  let content: React.ReactNode = null;
  if (open) {
    if (contract.isPending) content = <LoadingState label={t("flow_runs_contract_loading")} />;
    else if (contract.isError) {
      content = (
        <ListError
          error={contract.error}
          title={t("flow_runs_contract_failed")}
          onRetry={() => void contract.refetch()}
          isRetrying={contract.isFetching}
        />
      );
    } else {
      content = (
        <>
          {summary ? (
            <StartRunSummary
              summary={summary}
              headingRef={summaryHeading}
              notices={<ContractNotices flow={flow} contract={contract.data} />}
            />
          ) : null}
          <StartRunForm
            flow={flow}
            contract={contract.data}
            formId={formId}
            reviewing={summary !== null}
            onReview={review}
            onPendingChange={setPending}
            onStarted={onStarted}
            onSaveForLater={() => {
              toast.success(t("flow_transcript_save_later_done"));
              onOpenChange(false);
            }}
            handleRef={form}
          />
        </>
      );
    }
  }

  return (
    <>
      <Dialog
        isOpen={open}
        onOpenChange={requestOpenChange}
        purpose="form"
        width={640}
        maxHeight="85dvh"
      >
        <Layout
          height="auto"
          header={
            <DialogHeader
              title={t("flow_runs_start_title", { name: flow.name })}
              onOpenChange={requestOpenChange}
            />
          }
          content={open ? <LayoutContent>{content}</LayoutContent> : null}
          footer={
            open ? (
              <LayoutFooter>
                <div className="flex flex-wrap justify-end gap-2">
                  {summary ? (
                    <Button
                      key="back"
                      label={t("back")}
                      isDisabled={pending}
                      onClick={backToForm}
                    />
                  ) : (
                    <Button
                      key="cancel"
                      label={t("cancel")}
                      isDisabled={pending}
                      onClick={() => requestOpenChange(false)}
                    />
                  )}
                  {contract.data ? (
                    <Button
                      type="submit"
                      form={formId}
                      variant="primary"
                      label={summary ? t("flow_runs_start_submit") : t("flow_runs_summary_next")}
                      isLoading={pending}
                      isInterruptible
                    />
                  ) : null}
                </div>
              </LayoutFooter>
            ) : null
          }
        />
      </Dialog>
      <AlertDialog
        isOpen={confirmClose}
        onOpenChange={setConfirmClose}
        {...(closeLoses === "recording"
          ? {
              title: t("flow_transcript_close_title"),
              description: t("flow_transcript_close_body"),
              actionLabel: t("flow_transcript_close_confirm"),
              cancelLabel: t("flow_transcript_close_cancel")
            }
          : {
              title: t("flow_run_dialog_close_confirm_title"),
              description: t("flow_run_dialog_close_confirm_message"),
              actionLabel: t("flow_run_dialog_close_confirm_discard"),
              cancelLabel: t("flow_run_dialog_close_confirm_keep")
            })}
        onAction={() => {
          setConfirmClose(false);
          if (closeLoses === "recording") form.current?.discardRecordings();
          onOpenChange(false);
        }}
      />
    </>
  );
}
