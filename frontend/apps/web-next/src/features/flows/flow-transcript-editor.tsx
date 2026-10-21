"use client";

import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useLayoutEffect, useRef, useState } from "react";
import { TextInput } from "@/components/astryx/text-input";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { flowKeys, flowTranscriptQueryOptions } from "./flows";
import { flowsApi } from "./flows-api";
import { FlowTranscript, formatClock, type TranscriptSegment } from "./flow-transcript";

type Transcript = Schema<"FlowTranscriptPublic">;
type Correction = Schema<"FlowTranscriptCorrectionsEditRequest">;
const UNKNOWN = "__unknown";

function originalSegments(base: Transcript): TranscriptSegment[] {
  return base.original_segments as TranscriptSegment[];
}

/** Whole-segment replacements use Python's Unicode code-point offsets. */
export function transcriptCorrectionBody(
  base: Transcript,
  texts: string[],
  speakers: (string | null)[],
  names: Record<string, string | null>
): Correction {
  const saved = base.corrections?.stale ? null : base.corrections;
  const originals = originalSegments(base);
  const current = base.segments as TranscriptSegment[];
  const occurrences = originals.flatMap((segment, index) => {
    if (texts[index] === current[index]?.text)
      return (saved?.occurrences ?? []).filter((item) => item.segment_index === index);
    if (!segment.text) return [];
    return [
      {
        segment_index: index,
        char_start: 0,
        char_end: Array.from(segment.text).length,
        original: segment.text,
        corrected: texts[index] ?? segment.text
      }
    ];
  });
  const speaker_edits = originals.flatMap((segment, index) => {
    if (speakers[index] === (current[index]?.speaker ?? null))
      return (saved?.speaker_edits ?? []).filter((item) => item.segment_index === index);
    return [
      {
        segment_index: index,
        original_speaker: segment.speaker ?? null,
        speaker: speakers[index] ?? null,
        decision: speakers[index] ? ("confirmed" as const) : ("unresolved" as const)
      }
    ];
  });
  return {
    schema_version: 3,
    segments_hash: base.segments_hash,
    expected_revision: base.corrections?.revision ?? null,
    occurrences,
    speaker_edits,
    speaker_names: names
  };
}

function TranscriptForm({
  base,
  flowId,
  runId,
  stepId,
  onClose
}: {
  base: Transcript;
  flowId: string;
  runId: string;
  stepId: string;
  onClose: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const formId = useId();
  const originals = originalSegments(base);
  const current = base.segments as TranscriptSegment[];
  const [texts, setTexts] = useState(() => current.map((segment) => segment.text));
  const [speakers, setSpeakers] = useState(() => current.map((segment) => segment.speaker ?? null));
  const [names, setNames] = useState(base.speaker_names);
  const labels = [
    ...new Set([
      ...originals.flatMap((segment) => (segment.speaker ? [segment.speaker] : [])),
      ...Object.keys(base.speaker_names),
      ...speakers.filter((speaker): speaker is string => speaker !== null)
    ])
  ];
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        flowsApi.PATCH("/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/transcript-corrections/", {
          params: { path: { id: flowId, run_id: runId, step_id: stepId } },
          body: transcriptCorrectionBody(base, texts, speakers, names)
        })
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: flowKeys.run(flowId, runId) });
      toast.success(t("flow_transcript_saved"));
      onClose();
    },
    onError: (error) => {
      if (
        error instanceof EneoApiError &&
        error.reason === "flow_transcript_corrections_stale_revision"
      )
        toast.error(t("flow_transcript_conflict"));
      else toastApiError(error, t);
    }
  });
  return (
    <form
      id={formId}
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!save.isPending) save.mutate();
      }}
    >
      <p className="text-ax-text-secondary m-0 text-sm">{t("flow_transcript_edit_hint")}</p>
      {base.corrections?.stale && (
        <p role="alert" className="m-0 text-sm">
          {t("flow_transcript_stale")}
        </p>
      )}
      {labels.map((label) => (
        <TextInput
          key={label}
          label={t("flow_transcript_speaker_name", { label })}
          value={names[label] ?? ""}
          onChange={(value) => setNames((previous) => ({ ...previous, [label]: value || null }))}
        />
      ))}
      {originals.map((segment, index) => {
        const partial =
          !base.corrections?.stale &&
          base.corrections?.speaker_edits.some(
            (edit) => edit.segment_index === index && edit.char_start != null
          );
        return (
          <fieldset
            key={index}
            className="border-ax-border rounded-ax-inner m-0 flex min-w-0 flex-col gap-2 border p-3"
          >
            <legend className="px-1 text-sm">
              {t("flow_transcript_segment", { index: index + 1, time: formatClock(segment.start) })}
            </legend>
            <TextArea
              label={t("flow_transcript_segment_text", { index: index + 1 })}
              value={texts[index] ?? ""}
              rows={3}
              isReadOnly={partial || !segment.text}
              description={partial ? t("flow_transcript_partial_hint") : undefined}
              onChange={(value) =>
                setTexts((previous) => previous.map((text, at) => (at === index ? value : text)))
              }
            />
            <Selector
              label={t("flow_transcript_segment_speaker", { index: index + 1 })}
              value={speakers[index] ?? UNKNOWN}
              isDisabled={partial}
              options={[
                { value: UNKNOWN, label: t("flow_transcript_unknown_speaker") },
                ...labels.map((label) => ({ value: label, label: names[label] || label }))
              ]}
              onChange={(value) =>
                setSpeakers((previous) =>
                  previous.map((speaker, at) =>
                    at === index ? (value === UNKNOWN ? null : value) : speaker
                  )
                )
              }
            />
          </fieldset>
        );
      })}
      <div className="flex flex-wrap gap-2">
        <Button
          label={t("save")}
          type="submit"
          variant="primary"
          isLoading={save.isPending}
          isInterruptible
        />
        <Button
          label={t("cancel")}
          onClick={() => {
            if (!save.isPending) onClose();
          }}
        />
      </div>
    </form>
  );
}

/** Read current corrections and hold an immutable baseline for each edit session. */
export function FlowRunTranscript({
  flowId,
  runId,
  stepId
}: {
  flowId: string;
  runId: string;
  stepId: string;
}) {
  const t = useTranslations();
  const query = useQuery(flowTranscriptQueryOptions(flowId, runId, stepId));
  const [editing, setEditing] = useState<Transcript | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const wasEditing = useRef(false);
  // This inline form replaces its trigger. Move focus with the user's action
  // and return it on close; a dialog focus trap would constrain the whole page.
  useLayoutEffect(() => {
    if (editing)
      root.current
        ?.querySelector<HTMLInputElement | HTMLTextAreaElement>("input, textarea")
        ?.focus();
    else if (wasEditing.current) root.current?.querySelector<HTMLButtonElement>("button")?.focus();
    wasEditing.current = editing !== null;
  }, [editing]);
  return (
    <div ref={root}>
      {editing ? (
        <TranscriptForm
          base={editing}
          flowId={flowId}
          runId={runId}
          stepId={stepId}
          onClose={() => setEditing(null)}
        />
      ) : (
        <QueryStateBoundary query={query} rows={3}>
          {(data) => (
            <div className="flex flex-col gap-3">
              <FlowTranscript
                transcription={{
                  segments: data.segments as TranscriptSegment[],
                  speaker_names: data.speaker_names
                }}
              />
              {(data.original_segments?.length ?? 0) > 0 && (
                <Button
                  label={t("flow_transcript_edit")}
                  size="sm"
                  onClick={() => setEditing(data)}
                  className="self-start"
                />
              )}
            </div>
          )}
        </QueryStateBoundary>
      )}
    </div>
  );
}
