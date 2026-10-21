"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { QuietBanner } from "@/components/astryx/banner";
import { TextInput } from "@/components/astryx/text-input";
import { ClientTime } from "@/components/composites/client-time";
import { EneoApiError } from "@/lib/api/errors";
import { focusFirstControl } from "./run-form-fields";
import { JsonValue } from "./run-json";
import { isStaleRefusal, refusalText } from "./run-messages";
import {
  draftChanged,
  editedValueOf,
  reviewDraftOf,
  reviewOptions,
  type DraftField,
  type DraftProblem,
  type DraftSpeaker,
  type EditedValue,
  type ReviewDraft
} from "./review-draft";
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

function FieldsEditor({
  baseId,
  fields,
  problem,
  onChange
}: {
  baseId: string;
  fields: DraftField[];
  problem: Problem | null;
  onChange: (fields: DraftField[]) => void;
}) {
  const t = useTranslations();
  const set = (name: string, value: string) =>
    onChange(fields.map((field) => (field.name === name ? { ...field, value } : field)));
  return (
    <div className="flex flex-col gap-3">
      {fields.map((field) => {
        const message = problem?.field === field.name ? problem.message : null;
        const status = message ? ({ type: "error", message } as const) : undefined;
        return (
          <div key={field.name} id={fieldAnchor(baseId, field.name)}>
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
          </div>
        );
      })}
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
  onStale
}: {
  checkpoint: ReviewCheckpoint;
  mayReview: boolean;
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

  const busy = save.isPending || approve.isPending || reject.isPending || resume.isPending;
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
          <QuietBanner
            status="warning"
            title={t("flow_runs_review_expired_title")}
            description={t("flow_runs_review_expired")}
            collapsible={false}
          />
        ) : !mayReview ? (
          <QuietBanner
            status="info"
            title={t("flow_runs_review_waiting_title")}
            description={t("flow_runs_review_not_allowed")}
            collapsible={false}
          />
        ) : null}
        {problem && (draft.kind === "file" || !options.canEdit) ? (
          <Banner
            status="error"
            title={t("flow_runs_review_not_done")}
            description={problem.message}
            collapsible={false}
          />
        ) : null}
      </div>

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
          problem={problem}
          onChange={(fields) => setDraft({ kind: "fields", fields })}
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
                if (!reason.trim()) {
                  flushSync(() => setReasonProblem(t("flow_runs_review_reject_reason_required")));
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

      {options.canDecide && !rejecting ? (
        <div className="flex flex-wrap gap-2">
          <Button
            label={changed ? t("flow_runs_review_approve_changed") : t("flow_runs_review_approve")}
            variant="primary"
            isLoading={approve.isPending}
            isInterruptible
            onClick={() => {
              if (busy) return;
              const value = correction();
              if (value !== false) approve.mutate(value);
            }}
          />
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
    </section>
  );
}
