"use client";

import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useClipboard } from "@astryxdesign/core/hooks";
import { ScrollableArea } from "@astryxdesign/core/ScrollableArea";
import { Text } from "@astryxdesign/core/Text";
import { Check, Copy } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useRef, useState } from "react";
import type { UploadEntry } from "../run-contract";
import type { JournalDegradation } from "./recording-journal";
import type { PartKeeping } from "./recording-keeper";
import { reportText, type PartDiagnostics, type RecordingReport } from "./recorder-diagnostics";
import type { AudioRecorder } from "./recorder";

/** How often an open report reads the recorder again. */
const REFRESH_MS = 1_000;

/** The step's recorded parts as the report tells them: sizes and states, never names. */
export function partDiagnostics(
  entries: readonly UploadEntry[],
  keeping: (sessionId: string, index: number) => PartKeeping | undefined
): PartDiagnostics[] {
  return entries.flatMap((entry) =>
    entry.recording
      ? [
          {
            index: entry.recording.index,
            durationMs: Math.round(entry.recording.durationMs),
            bytes: entry.size,
            upload: entry.state,
            retryable: Boolean(entry.retryable),
            kept: keeping(entry.recording.sessionId, entry.recording.index) ?? "storing"
          }
        ]
      : []
  );
}

/** A report of the recording as it is now. */
export function recordingReport({
  recorder,
  parts,
  storage,
  live,
  now = () => new Date()
}: {
  recorder: Pick<AudioRecorder, "diagnostics">;
  parts: PartDiagnostics[];
  storage: JournalDegradation | null;
  live: string | null;
  now?: () => Date;
}): RecordingReport {
  return {
    generatedAt: now().toISOString(),
    browser: typeof navigator === "undefined" ? "" : navigator.userAgent,
    recorder: recorder.diagnostics(),
    parts,
    storage: storage ?? "ok",
    live
  };
}

/**
 * "Visa diagnostik": what the recording knows about itself, for support when
 * a recording misbehaves: the recorder's state, the microphone's settings,
 * the format, the step's parts, the timings and the recent events, readable
 * here and copied with one button. Nothing in it names the person, the
 * device or the meeting. It reads the recorder again every second while it
 * is open.
 */
export function RecordingDiagnostics({ report }: { report: () => RecordingReport }) {
  const t = useTranslations();
  const { copy, isCopied } = useClipboard({ announce: t("flow_transcript_rec_diag_copied") });
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const latest = useRef(report);
  useEffect(() => {
    latest.current = report;
  });

  useEffect(() => {
    if (!open) return;
    const timer = setInterval(() => setText(reportText(latest.current())), REFRESH_MS);
    return () => clearInterval(timer);
  }, [open]);

  return (
    <Collapsible
      trigger={<span className="text-sm">{t("flow_transcript_rec_diag_show")}</span>}
      isOpen={open}
      onOpenChange={(next) => {
        if (next) setText(reportText(report()));
        setOpen(next);
      }}
    >
      <div className="flex flex-col gap-2 pt-2">
        <Text type="supporting" as="p">
          {t("flow_transcript_rec_diag_hint")}
        </Text>
        <div>
          <Button
            label={
              isCopied ? t("flow_transcript_rec_diag_copied") : t("flow_transcript_rec_diag_copy")
            }
            icon={isCopied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
            size="sm"
            onClick={() => void copy(reportText(report()))}
          />
        </div>
        <ScrollableArea
          axis="both"
          role="region"
          label={t("flow_transcript_rec_diag_label")}
          className="border-ax-border bg-ax-sunken rounded-ax-inner focus-visible:outline-ring max-h-72 border focus-visible:outline-2 focus-visible:-outline-offset-2"
        >
          <pre className="text-ax-text m-0 p-3 font-mono text-xs leading-relaxed">{text}</pre>
        </ScrollableArea>
      </div>
    </Collapsible>
  );
}
