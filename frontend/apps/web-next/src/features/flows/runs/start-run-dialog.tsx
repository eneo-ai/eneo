"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { QuietBanner } from "@/components/astryx/banner";
import { ListError } from "@/components/composites/query-state";
import { LoadingState } from "@/components/composites/loading-state";
import type { FlowPublic } from "../flows-api";
import {
  blockingTemplates,
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
import { useRuntimeUploads } from "./use-runtime-uploads";

type ServerProblems = {
  fields: Record<string, string>;
  inputs: Record<string, string>;
};

const NO_SERVER_PROBLEMS: ServerProblems = { fields: {}, inputs: {} };

/** The record without `key`. */
function without(record: Record<string, string>, key: string): Record<string, string> {
  return Object.fromEntries(Object.entries(record).filter(([name]) => name !== key));
}

/** The notices that keep the flow from running, or that the person should know first. */
function ContractNotices({ contract }: { contract: RunContract }) {
  const t = useTranslations();
  const classification = contract.security_classification;
  const labels = contract.transcription?.speaker_labels;
  const templates = blockingTemplates(contract);
  return (
    <>
      {classification ? (
        <QuietBanner
          status="info"
          title={t("flow_runs_classification_title", { name: classification.name })}
          description={classification.description?.trim() || undefined}
          collapsible={false}
        />
      ) : null}
      {templates.length > 0 ? (
        <QuietBanner
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
        <QuietBanner
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
    </>
  );
}

function StartRunForm({
  flow,
  contract,
  formId,
  onPendingChange,
  onStarted
}: {
  flow: FlowPublic;
  contract: RunContract;
  formId: string;
  onPendingChange: (pending: boolean) => void;
  onStarted: (run: RunPublic) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const summaryRef = useRef<HTMLDivElement>(null);
  const lastRequest = useRef<{ body: string; key: string } | null>(null);
  const { uploads, add, remove, claim } = useRuntimeUploads(
    flow.id,
    contract.runtime_upload_policy
  );
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

  const start = useMutation({
    mutationFn: (body: RunCreateRequest) => {
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
      onStarted(run);
    },
    onError: (error) => {
      const message = refusalText(error, t);
      const targets = refusalTargets(error, contract);
      const first = targets[0];
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
    if (start.isPending) return;
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
    start.mutate(
      runRequest(contract, {
        values,
        freeText,
        uploads,
        singleRecording,
        speakerLabels,
        maxSpeakers
      })
    );
  }

  const maxSpeakerOption = contract.transcription?.max_speakers;

  return (
    <form id={formId} noValidate onSubmit={submit} className="flex flex-col gap-5">
      <ContractNotices contract={contract} />
      <div
        ref={summaryRef}
        tabIndex={-1}
        className="focus-visible:outline-ring outline-none focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        {formProblem || tooManyInAll ? (
          <Banner
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
            add(input, files);
          }}
          onRemove={(key) => {
            clearInputProblem(input.step_id);
            remove(input.step_id, key);
          }}
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
 * lands at the field it names.
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
  const contract = useQuery({ ...runContractQueryOptions(flow.id), enabled: open });

  function requestOpenChange(next: boolean) {
    if (!next && pending) return;
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
        <StartRunForm
          flow={flow}
          contract={contract.data}
          formId={formId}
          onPendingChange={setPending}
          onStarted={onStarted}
        />
      );
    }
  }

  return (
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
                <Button
                  label={t("cancel")}
                  isDisabled={pending}
                  onClick={() => requestOpenChange(false)}
                />
                {contract.data ? (
                  <Button
                    type="submit"
                    form={formId}
                    variant="primary"
                    label={t("flow_runs_start_submit")}
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
  );
}
