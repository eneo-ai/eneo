"use client";

import { Token } from "@astryxdesign/core/Token";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import {
  speakerMapping,
  withGivenNames,
  type SpeakerConfidence,
  type SpeakerRow
} from "./run-step-facts";
import { transcriptCorrectionsQueryOptions, type RunStep } from "./runs-api";
import { SpeakerBadge } from "./transcript-speakers";

const CONFIDENCE_KEYS: Record<SpeakerConfidence, string> = {
  high: "flow_run_more_confidence_high",
  medium: "flow_run_more_confidence_medium",
  low: "flow_run_more_confidence_low"
};

/**
 * The names a person gave the speakers of the mapping's transcription, from
 * the transcript corrections the page has already read (the transcript
 * section reads them): this reads nothing itself.
 */
function useGivenNames(
  flowId: string,
  runId: string,
  sourceStepId: string | null
): Record<string, string | null> {
  const corrections = useQuery({
    ...transcriptCorrectionsQueryOptions(flowId, runId),
    enabled: false
  });
  const current = (corrections.data ?? []).filter((entry) => !entry.stale);
  const entry = sourceStepId
    ? current.find((item) => item.step_id === sourceStepId)
    : current.length === 1
      ? current[0]
      : undefined;
  return entry?.speaker_names ?? {};
}

function SpeakerRowItem({ row }: { row: SpeakerRow }) {
  const t = useTranslations();
  return (
    <li className="border-ax-border flex flex-wrap items-center gap-x-3 gap-y-1 border-t py-2 first:border-t-0">
      <SpeakerBadge label={row.label} name={null} />
      <span
        className={`text-sm font-medium break-words ${row.name ? "text-ax-text" : "text-ax-text-secondary"}`}
      >
        {row.name ?? t("flow_run_more_speaker_unknown")}
      </span>
      <Token size="sm" label={t(CONFIDENCE_KEYS[row.confidence])} />
      {row.evidence ? (
        <span className="text-ax-text-secondary basis-full text-xs break-words">
          {row.evidence}
        </span>
      ) : null}
    </li>
  );
}

/**
 * Whom a speaker-mapping step named: each diarized speaker with the name
 * (or "unknown"), how sure the step was, and why. A name a person gave in
 * the transcript since replaces the step's, as the transcript shows it.
 */
export function StepSpeakerMapping({
  flowId,
  runId,
  payload
}: {
  flowId: string;
  runId: string;
  payload: RunStep["output_payload_json"];
}) {
  const t = useTranslations();
  const mapping = speakerMapping(payload);
  const names = useGivenNames(flowId, runId, mapping?.sourceStepId ?? null);
  if (!mapping) return null;
  return (
    <ul aria-label={t("flow_run_more_speakers")} className="m-0 flex flex-col p-0">
      {withGivenNames(mapping.rows, names).map((row) => (
        <SpeakerRowItem key={row.label} row={row} />
      ))}
    </ul>
  );
}
