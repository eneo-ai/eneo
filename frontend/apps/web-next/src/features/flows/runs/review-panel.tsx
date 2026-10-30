"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Heading } from "@astryxdesign/core/Heading";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { TextInput } from "@astryxdesign/core/TextInput";
import { ClientTime } from "@/components/composites/client-time";
import { EneoApiError } from "@/lib/api/errors";
import { CitationSummary } from "./run-citations";
import { focusFirstControl } from "./run-form-fields";
import { JsonValue } from "./run-json";
import { ReviewTranscript } from "./run-transcript";
import type { TranscriptTarget } from "./transcript";
import type { TranscriptDraftHandle } from "./transcript-review-draft";
import { isStaleRefusal, refusalText } from "./run-messages";
import {
  changedFields,
  draftChanged,
  editedValueOf,
  REJECT_REASON_MAX_LENGTH,
  rejectReasonProblem,
  reviewDraftOf,
  reviewOptions,
  type DraftField,
  type DraftProblem,
  type DraftSpeaker,
  type EditedValue,
  type ReviewDraft
} from "./review-draft";
import { ReviewApproveOnly } from "./review-approve-only";
import { ReviewHistory } from "./review-history";
import { ChangedMarker, StructuredReviewEditor } from "./review-structured-editor";
import { isReviewObject, isReviewValue } from "./review-structured";
import {
  approveAndContinue,
  editReview,
  rejectReview,
  resumeReview,
  runKeys,
  type ReviewCheckpoint
} from "./runs-api";

type Problem = { field: string | null; message: string };

function draftProblemText(problem: DraftProblem, t: ReturnType<typeof useTranslations>) {
  switch (problem.reason) {
    case "number":
      return t("flow_runs_review_field_number", { field: problem.field ?? "" });
    case "json":
      return t("flow_runs_review_json_invalid");
    case "json_kind":
      return t("flow_runs_review_json_kind");
  }
}

/** The id of a structured field's wrapper, for moving focus to its problem. */
function fieldAnchor(baseId: string, name: string) {
  return `${baseId}-field-${name.replace(/[^A-Za-z0-9_-]/g, "_")}`;
}

/**
 * A flat JSON output field by field. A field that differs from `original`
 * (the step's own output, before any review changed it) is marked, with its
 * previous value behind a disclosure, and "Visa original" shows that output
 * read-only, as the contract form does. A problem at a field brings the
 * fields back.
 */
function FieldsEditor({
  baseId,
  fields,
  original,
  problem,
  onChange
}: {
  baseId: string;
  fields: DraftField[];
  original: unknown;
  problem: Problem | null;
  onChange: (fields: DraftField[]) => void;
}) {
  const t = useTranslations();
  const [showOriginal, setShowOriginal] = useState(false);
  const before = isReviewValue(original) && isReviewObject(original) ? original : null;
  const changed = before ? changedFields(fields, before) : null;
  const viewingOriginal = before !== null && showOriginal && !problem?.field;
  const set = (name: string, value: string) =>
    onChange(fields.map((field) => (field.name === name ? { ...field, value } : field)));
  return (
    <div className="flex flex-col gap-3">
      {before ? (
        <div>
          <Button
            label={
              viewingOriginal
                ? t("flow_run_review_back_to_edit")
                : t("flow_run_review_show_original")
            }
            size="sm"
            onClick={() => setShowOriginal(!viewingOriginal)}
          />
        </div>
      ) : null}
      {viewingOriginal ? (
        <>
          <p className="text-ax-text-secondary text-sm">{t("flow_run_review_original_help")}</p>
          <JsonValue value={before} />
        </>
      ) : (
        fields.map((field) => {
          const message = problem?.field === field.name ? problem.message : null;
          const status = message ? ({ type: "error", message } as const) : undefined;
          return (
            <div
              key={field.name}
              id={fieldAnchor(baseId, field.name)}
              className="flex flex-col gap-1"
            >
              {field.kind === "boolean" ? (
                <CheckboxInput
                  label={field.name}
                  value={field.value === "true"}
                  onChange={(on) => set(field.name, on ? "true" : "false")}
                />
              ) : field.kind === "string" && field.value.length > 80 ? (
                <TextArea
                  label={field.name}
                  value={field.value}
                  onChange={(value) => set(field.name, value)}
                  rows={4}
                  status={status}
                  width="100%"
                />
              ) : (
                <TextInput
                  label={field.name}
                  value={field.value}
                  onChange={(value) => set(field.name, value)}
                  description={
                    field.kind === "number" ? t("flow_runs_review_number_hint") : undefined
                  }
                  status={status}
                  width="100%"
                />
              )}
              {changed?.has(field.name) ? <ChangedMarker original={before?.[field.name]} /> : null}
            </div>
          );
        })
      )}
    </div>
  );
}

function SpeakersEditor({
  baseId,
  speakers,
  onChange
}: {
  baseId: string;
  speakers: DraftSpeaker[];
  onChange: (speakers: DraftSpeaker[]) => void;
}) {
  const t = useTranslations();
  return (
    <div id={`${baseId}-editor`} className="flex flex-col gap-3">
      <p className="text-ax-text-secondary text-sm">{t("flow_runs_review_speakers_hint")}</p>
      {speakers.map((speaker) => {
        const evidence =
          typeof speaker.rest.evidence === "string" ? speaker.rest.evidence.trim() : "";
        return (
          <TextInput
            key={speaker.label}
            label={t("flow_runs_review_speaker_name", { label: speaker.label })}
            description={evidence || undefined}
            value={speaker.name}
            onChange={(name) =>
              onChange(
                speakers.map((item) => (item.label === speaker.label ? { ...item, name } : item))
              )
            }
            width="100%"
          />
        );
      })}
    </div>
  );
}

/**
 * A run paused for review at one step: what the step produced, a deadline,
 * and the reviewer's choices. In edit mode the output can be corrected (a
 * text as text, a flat JSON object field by field, other JSON as JSON
 * text); approving saves the correction first and then lets the run go on in
 * one request. Rejecting needs a reason and cancels the run. After the
 * deadline nothing can be decided; an approval made in time can still be
 * resumed. Refusals show where they belong, and a checkpoint someone else
 * changed is read again.
 */
export function ReviewPanel({
  checkpoint,
  mayReview,
  now,
  onStale,
  transcript = null
}: {
  checkpoint: ReviewCheckpoint;
  mayReview: boolean;
  /** The transcript the review is about, corrected in the review before approving. */
  transcript?: TranscriptTarget | null;
  /** The time the run's status was last read, for the deadline. */
  now: number;
  /** Someone else changed the checkpoint first; the page says so while it reads it again. */
  onStale: (message: string) => void;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const baseId = useId();
  const headingId = `${baseId}-heading`;
  const summaryRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState<ReviewDraft>(() => reviewDraftOf(checkpoint));
  const [problem, setProblem] = useState<Problem | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [reasonProblem, setReasonProblem] = useState<string | null>(null);
  // The transcript holds approval while one of its edits is not saved.
  const [transcriptUnsaved, setTranscriptUnsaved] = useState(false);
  /** Why approval is held, said below the buttons; null while it is not. */
  const [approvalHeld, setApprovalHeld] = useState<string | null>(null);
  // The transcript's corrections are a draft that saves itself: approval sends it first.
  const transcriptDraft = useRef<TranscriptDraftHandle>(null);
  const [savingTranscript, setSavingTranscript] = useState(false);

  /** True, and says why at the edit, when the transcript has an edit not saved yet. */
  function holdForTranscript(): boolean {
    if (!transcriptUnsaved) return false;
    holdApproval();
    return true;
  }

  function holdApproval() {
    // To the draft's "save again", else to the edit not saved yet.
    const transcriptBox = document.getElementById(`${baseId}-transcript`);
    const retry = transcriptBox?.querySelector<HTMLElement>('[id^="transcript-draft-retry-"]');
    const message = retry
      ? t("flow_transcript_review_draft_unsaved")
      : t("flow_transcript_review_unsaved");
    flushSync(() => setApprovalHeld(message));
    announce(message);
    (retry ?? transcriptBox?.querySelector<HTMLElement>("textarea"))?.focus();
  }

  /** Whether approval may go ahead: no transcript edit is open and its draft is saved. */
  async function transcriptReady(): Promise<boolean> {
    if (holdForTranscript()) return false;
    const draft = transcriptDraft.current;
    if (!draft) return true;
    setSavingTranscript(true);
    try {
      if (await draft.flush()) return true;
    } finally {
      setSavingTranscript(false);
    }
    holdApproval();
    return false;
  }

  const options = reviewOptions(checkpoint, mayReview, now);
  const changed = options.canEdit && draftChanged(draft, checkpoint);
  const runKey = runKeys.run(checkpoint.flow_id, checkpoint.flow_run_id);
  const title = checkpoint.step_label?.trim()
    ? t("flow_runs_review_heading", { order: checkpoint.step_order, label: checkpoint.step_label })
    : t("flow_runs_review_heading_unnamed", { order: checkpoint.step_order });

  function showProblem(next: Problem) {
    flushSync(() => setProblem(next));
    if (next.field && focusFirstControl(fieldAnchor(baseId, next.field))) return;
    if (!next.field && draft.kind !== "file" && focusFirstControl(`${baseId}-editor`)) return;
    summaryRef.current?.focus();
  }

  function refused(error: unknown) {
    if (isStaleRefusal(error)) {
      // Read again; the panel then shows the checkpoint as it is now.
      onStale(refusalText(error, t));
      void queryClient.invalidateQueries({ queryKey: runKey });
      return;
    }
    // A contract violation names the output field it is about.
    const named = error instanceof EneoApiError ? error.context?.payload_field : undefined;
    const field = typeof named === "string" ? named : null;
    showProblem({
      field:
        draft.kind === "fields" && field && draft.fields.some((item) => item.name === field)
          ? field
          : null,
      message: refusalText(error, t)
    });
  }

  /**
   * The reviewer's correction as the edit endpoint takes it: null when there
   * is none, false when it cannot be sent (the problem is shown at its field).
   */
  function correction(): EditedValue | null | false {
    if (!changed) return null;
    const edited = editedValueOf(draft);
    if (edited.ok) return edited.value;
    showProblem({ field: edited.problem.field, message: draftProblemText(edited.problem, t) });
    return false;
  }

  const save = useMutation({
    mutationFn: (value: EditedValue) => editReview(checkpoint, value),
    onSuccess: () => {
      setProblem(null);
      // The saved revision is read back; the panel then starts from it.
      void queryClient.invalidateQueries({ queryKey: runKey });
      announce(t("flow_runs_review_saved"));
    },
    onError: refused
  });

  const approve = useMutation({
    mutationFn: async (value: EditedValue | null) => {
      const current = value === null ? checkpoint : await editReview(checkpoint, value);
      // The key is bound to the revision approved: a retry after a lost
      // response replays it, a new edit makes a new one.
      return approveAndContinue(current, `review-approve:${current.id}:${current.revision}`);
    },
    onSuccess: () => {
      setProblem(null);
      void queryClient.invalidateQueries({ queryKey: runKey });
      announce(t("flow_runs_review_approved"));
    },
    onError: refused
  });

  const resume = useMutation({
    mutationFn: () =>
      resumeReview(checkpoint, `review-resume:${checkpoint.id}:${checkpoint.revision}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: runKey });
      announce(t("flow_runs_review_resumed"));
    },
    onError: refused
  });

  const reject = useMutation({
    mutationFn: () => rejectReview(checkpoint, reason.trim()),
    onSuccess: () => {
      setRejecting(false);
      void queryClient.invalidateQueries({ queryKey: runKey });
      void queryClient.invalidateQueries({ queryKey: runKeys.list(checkpoint.flow_id) });
      announce(t("flow_runs_review_rejected"));
    },
    onError: (error) => {
      const code = error instanceof EneoApiError ? error.reason : null;
      if (
        code === "flow_review_reject_reason_required" ||
        code === "flow_review_reject_reason_too_long"
      ) {
        flushSync(() => setReasonProblem(refusalText(error, t)));
        focusFirstControl(`${baseId}-reason`);
        return;
      }
      refused(error);
    }
  });

  const busy =
    save.isPending || approve.isPending || reject.isPending || resume.isPending || savingTranscript;
  const editorStatus =
    problem && !problem.field ? ({ type: "error", message: problem.message } as const) : undefined;

  return (
    <section
      aria-labelledby={headingId}
      className="border-ax-border bg-ax-card rounded-ax-element flex flex-col gap-4 border p-4"
    >
      <div className="flex flex-col gap-1">
        <h2 id={headingId} className="text-ax-text text-lg font-semibold break-words">
          {title}
        </h2>
        {checkpoint.expires_at ? (
          <p className="text-ax-text-secondary text-sm">
            {options.expired
              ? t("flow_runs_review_deadline_passed")
              : t("flow_runs_review_deadline")}{" "}
            <ClientTime value={checkpoint.expires_at} format="date_time" />
          </p>
        ) : null}
      </div>

      <div
        ref={summaryRef}
        tabIndex={-1}
        className="focus-visible:outline-ring rounded-ax-inner outline-none focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        {options.expired && !options.canResume ? (
          <Banner
            status="warning"
            title={t("flow_runs_review_expired_title")}
            description={t("flow_runs_review_expired")}
            collapsible={false}
          />
        ) : !mayReview ? (
          <Banner
            status="info"
            title={t("flow_runs_review_waiting_title")}
            description={t("flow_runs_review_not_allowed")}
            collapsible={false}
          />
        ) : null}
        {problem && (draft.kind === "file" || !options.canEdit) ? (
          <Banner
            role="alert"
            status="error"
            title={t("flow_runs_review_not_done")}
            description={problem.message}
            collapsible={false}
          />
        ) : null}
      </div>

      <CitationSummary
        summary={checkpoint.citation_summary}
        heading={t("flow_run_extras_review_citations")}
      />

      {draft.kind === "file" ? (
        <p className="text-ax-text text-sm">{t("flow_runs_review_file")}</p>
      ) : !options.canEdit ? (
        draft.kind === "text" ? (
          <p className="text-ax-text text-sm break-words whitespace-pre-wrap">{draft.text}</p>
        ) : (
          <JsonValue value={checkpoint.current_payload_json?.structured ?? null} />
        )
      ) : draft.kind === "text" ? (
        <div id={`${baseId}-editor`}>
          <TextArea
            label={t("flow_runs_review_output")}
            description={t("flow_runs_review_output_hint")}
            value={draft.text}
            onChange={(text) => setDraft({ kind: "text", text })}
            rows={10}
            status={editorStatus}
            width="100%"
          />
        </div>
      ) : draft.kind === "speakers" ? (
        <SpeakersEditor
          baseId={baseId}
          speakers={draft.speakers}
          onChange={(speakers) => setDraft({ ...draft, speakers })}
        />
      ) : draft.kind === "fields" ? (
        <FieldsEditor
          baseId={baseId}
          fields={draft.fields}
          original={checkpoint.original_payload_json?.structured}
          problem={problem}
          onChange={(fields) => setDraft({ kind: "fields", fields })}
        />
      ) : draft.kind === "structured" ? (
        <StructuredReviewEditor
          id={`${baseId}-editor`}
          schema={draft.schema}
          value={draft.value}
          original={checkpoint.original_payload_json?.structured}
          problem={problem?.field === null ? problem.message : null}
          onChange={(value) => setDraft({ ...draft, value })}
        />
      ) : (
        <div id={`${baseId}-editor`}>
          <TextArea
            label={t("flow_runs_review_output_json")}
            description={t("flow_runs_review_output_json_hint")}
            value={draft.text}
            onChange={(text) => setDraft({ kind: "json", text })}
            rows={12}
            status={editorStatus}
            width="100%"
          />
        </div>
      )}
      {options.canEdit &&
      problem?.field === null &&
      (draft.kind === "fields" || draft.kind === "speakers") ? (
        <p className="text-ax-error text-sm">{problem.message}</p>
      ) : null}

      {transcript ? (
        <div id={`${baseId}-transcript`} className="flex flex-col gap-2">
          <Heading level={3}>{t("flow_transcript_review_heading")}</Heading>
          <Text type="supporting" as="p">
            {options.canDecide
              ? t("flow_transcript_review_hint")
              : t("flow_transcript_review_read")}
          </Text>
          <ReviewTranscript
            flowId={checkpoint.flow_id}
            runId={checkpoint.flow_run_id}
            target={transcript}
            mayEdit={options.canDecide}
            onUnsavedChange={setTranscriptUnsaved}
            draftRef={transcriptDraft}
          />
        </div>
      ) : null}

      {rejecting ? (
        <div id={`${baseId}-reason`} className="flex flex-col gap-2">
          <TextArea
            label={t("flow_runs_review_reject_reason")}
            description={t("flow_runs_review_reject_reason_hint")}
            value={reason}
            onChange={(next) => {
              setReason(next);
              setReasonProblem(null);
            }}
            rows={3}
            maxLength={REJECT_REASON_MAX_LENGTH}
            status={reasonProblem ? { type: "error", message: reasonProblem } : undefined}
            isRequired
            width="100%"
          />
          <div className="flex flex-wrap gap-2">
            <Button
              label={t("flow_runs_review_reject_confirm")}
              variant="destructive"
              isLoading={reject.isPending}
              isInterruptible
              onClick={() => {
                if (reject.isPending) return;
                const reasonRefusal = rejectReasonProblem(reason);
                if (reasonRefusal) {
                  flushSync(() =>
                    setReasonProblem(
                      reasonRefusal === "required"
                        ? t("flow_runs_review_reject_reason_required")
                        : t("flow_runs_review_reject_reason_too_long", {
                            max: REJECT_REASON_MAX_LENGTH
                          })
                    )
                  );
                  focusFirstControl(`${baseId}-reason`);
                  return;
                }
                reject.mutate();
              }}
            />
            <Button
              label={t("flow_runs_review_reject_back")}
              onClick={() => {
                if (reject.isPending) return;
                setRejecting(false);
                setReasonProblem(null);
              }}
            />
          </div>
        </div>
      ) : null}

      {options.canDecide && !rejecting && approvalHeld && transcriptUnsaved ? (
        <p className="text-ax-error m-0 text-sm">{approvalHeld}</p>
      ) : null}
      {options.canDecide && !rejecting ? (
        <div className="flex flex-wrap gap-2">
          <Button
            label={changed ? t("flow_runs_review_approve_changed") : t("flow_runs_review_approve")}
            variant="primary"
            isLoading={approve.isPending || savingTranscript}
            isInterruptible
            onClick={() => {
              if (busy) return;
              void transcriptReady().then((ready) => {
                if (!ready) return;
                const value = correction();
                if (value !== false) approve.mutate(value);
              });
            }}
          />
          {changed ? null : (
            <ReviewApproveOnly
              checkpoint={checkpoint}
              isBlocked={busy}
              onRefused={refused}
              mayApprove={transcriptReady}
            />
          )}
          {changed ? (
            <Button
              label={t("flow_runs_review_save")}
              isLoading={save.isPending}
              isInterruptible
              onClick={() => {
                if (busy) return;
                const value = correction();
                if (value !== false && value !== null) save.mutate(value);
              }}
            />
          ) : null}
          <Button
            label={t("flow_runs_review_reject")}
            variant="destructive"
            onClick={() => {
              if (busy) return;
              flushSync(() => setRejecting(true));
              focusFirstControl(`${baseId}-reason`);
            }}
          />
        </div>
      ) : null}
      {options.canResume ? (
        <div className="flex flex-col gap-2">
          <p className="text-ax-text text-sm">{t("flow_runs_review_approved_waiting")}</p>
          <div>
            <Button
              label={t("flow_runs_review_resume")}
              variant="primary"
              isLoading={resume.isPending}
              isInterruptible
              onClick={() => {
                if (!resume.isPending) resume.mutate();
              }}
            />
          </div>
        </div>
      ) : null}
      {checkpoint.revision > 1 ? <ReviewHistory checkpoint={checkpoint} /> : null}
    </section>
  );
}
