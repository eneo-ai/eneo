"use client";

import {
  DropdownMenu,
  DropdownMenuDivider,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem
} from "@astryxdesign/core/DropdownMenu";
import { Token } from "@astryxdesign/core/Token";
import { useTranslations } from "next-intl";
import { speakerColor, speakerText } from "./transcript-speakers";

const NO_SPEAKER = "__none__";

/**
 * A speaker badge that is also the menu for who said the line, the part or
 * the turn: another speaker, a new one, "unknown speaker" (left for someone
 * to check), or back to the speaker the transcription heard. The button's
 * name starts with the speaker it shows, then says what it changes.
 */
export function SpeakerMenu({
  label,
  name,
  context,
  speakers,
  names,
  newLabel,
  overridden,
  saving,
  onChoose,
  onReset
}: {
  label: string | null;
  name: string | null;
  /** What the menu changes, for its name: "raden 0:05", "repliken 1:20". */
  context: string;
  speakers: readonly string[];
  names: Record<string, string | null>;
  newLabel: string;
  /** A speaker edit gave the badge its speaker: it can be reset. */
  overridden: boolean;
  saving: boolean;
  /** The speaker chosen; null for "unknown speaker". */
  onChoose: (speaker: string | null) => void;
  onReset: () => void;
}) {
  const t = useTranslations();
  const shown = name ?? label ?? t("flow_runs_transcript_unknown_speaker");
  return (
    <DropdownMenu
      button={{
        label: t("flow_transcript_speaker_menu", { name: shown, context }),
        variant: "ghost",
        size: "sm",
        className: "h-auto min-h-6 px-0.5 py-0 align-baseline",
        children: <Token size="sm" color={label ? speakerColor(label) : "default"} label={shown} />
      }}
      hasChevron={false}
      menuWidth={240}
    >
      <DropdownMenuRadioGroup
        label={t("flow_transcript_speaker_menu_group")}
        value={label ?? NO_SPEAKER}
        onChange={(value) => {
          if (saving) return;
          if (value !== (label ?? NO_SPEAKER)) onChoose(value === NO_SPEAKER ? null : value);
        }}
      >
        {speakers.map((speaker) => (
          <DropdownMenuRadioItem
            key={speaker}
            value={speaker}
            label={speakerText(speaker, names, t)}
          />
        ))}
        <DropdownMenuRadioItem
          value={newLabel}
          label={t("flow_transcript_speaker_new", { label: newLabel })}
        />
        <DropdownMenuRadioItem
          value={NO_SPEAKER}
          label={t("flow_runs_transcript_unknown_speaker")}
        />
      </DropdownMenuRadioGroup>
      {overridden ? (
        <>
          <DropdownMenuDivider />
          <DropdownMenuItem
            label={t("flow_transcript_speaker_reset")}
            onClick={() => {
              if (!saving) onReset();
            }}
          />
        </>
      ) : null}
    </DropdownMenu>
  );
}
