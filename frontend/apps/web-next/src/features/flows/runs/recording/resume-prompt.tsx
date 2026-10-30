"use client";

import { Button } from "@astryxdesign/core/Button";
import { Trash2 } from "lucide-react";
import { useLocale, useTranslations } from "use-intl";
import { Banner } from "@astryxdesign/core/Banner";
import type { ResumeRefusal, SavedRecording } from "./recording-keeper";

type Translator = ReturnType<typeof useTranslations>;

/** "2 h 5 min", "12 min", "45 s": how long a kept recording is. */
export function keptLengthText(ms: number, t: Translator): string {
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return t("flow_transcript_length_seconds", { seconds });
  const minutes = Math.round(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return t("flow_transcript_length_minutes", { minutes });
  if (rest === 0) return t("flow_transcript_length_hours", { hours });
  return t("flow_transcript_length_hours_minutes", { hours, minutes: rest });
}

export function resumeRefusalText(refusal: ResumeRefusal, t: Translator): string {
  switch (refusal) {
    case "step_changed":
      return t("flow_transcript_resume_step_changed");
    case "too_many_parts":
      return t("flow_transcript_resume_too_many_parts");
    case "type_not_accepted":
      return t("flow_transcript_resume_type_not_accepted");
  }
}

/**
 * Offers a recording kept on this device (after a closed tab, a reload, a
 * crash or "Spara och fortsätt senare") to continue: its parts are added to
 * the step and recording again goes on with it. It can also be discarded,
 * or left for later.
 */
export function ResumePrompt({
  saved,
  busy,
  onContinue,
  onDiscard,
  onDismiss
}: {
  saved: SavedRecording;
  busy: "continue" | "discard" | null;
  onContinue: () => void;
  onDiscard: () => void;
  onDismiss: () => void;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const when = new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  }).format(saved.startedAt);
  const until =
    saved.interruptedAt === null
      ? null
      : new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(
          saved.interruptedAt
        );
  return (
    <Banner
      status="info"
      title={t("flow_transcript_resume_title")}
      description={[
        t("flow_transcript_resume_body", {
          time: when,
          length: keptLengthText(saved.durationMs, t),
          parts: saved.parts
        }),
        until ? t("flow_transcript_resume_interrupted", { time: until }) : null,
        t("flow_transcript_resume_choice")
      ]
        .filter(Boolean)
        .join(" ")}
      collapsible={false}
    >
      <div className="flex flex-wrap gap-2">
        <Button
          label={t("flow_transcript_resume_continue")}
          variant="primary"
          size="sm"
          isLoading={busy === "continue"}
          isInterruptible
          onClick={() => {
            if (!busy) onContinue();
          }}
        />
        <Button
          label={t("flow_transcript_resume_discard")}
          icon={<Trash2 aria-hidden="true" />}
          size="sm"
          isLoading={busy === "discard"}
          isInterruptible
          onClick={() => {
            if (!busy) onDiscard();
          }}
        />
        <Button
          label={t("flow_transcript_resume_not_now")}
          variant="ghost"
          size="sm"
          onClick={() => {
            if (!busy) onDismiss();
          }}
        />
      </div>
    </Banner>
  );
}
