"use client";

import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Text } from "@astryxdesign/core/Text";
import { Toolbar } from "@astryxdesign/core/Toolbar";
import { X } from "lucide-react";
import { useTranslations } from "use-intl";
import { speakerText } from "./transcript-speakers";

/** Keeps the marked text marked: a press on the toolbar must not end the selection it acts on. */
const keepSelection = (event: React.PointerEvent | React.MouseEvent) => event.preventDefault();

/**
 * Gives the text marked in the transcript to a speaker: one button per
 * speaker, a new speaker, or "unknown speaker" (left for someone to check).
 * It shows right below the line or turn where the marking ends, so the
 * keyboard reaches it next (Tab), arrow keys move inside it, and Esc
 * closes it.
 */
export function SelectionToolbar({
  lines,
  speakers,
  names,
  newLabel,
  saving,
  problem,
  onChoose,
  onClose
}: {
  /** How many lines the marked text spans. */
  lines: number;
  speakers: readonly string[];
  names: Record<string, string | null>;
  newLabel: string;
  saving: boolean;
  problem: string | null;
  /** The speaker chosen; null for "unknown speaker". */
  onChoose: (speaker: string | null) => void;
  onClose: () => void;
}) {
  const t = useTranslations();
  const choose = (speaker: string | null) => () => {
    if (!saving) onChoose(speaker);
  };
  const shared = {
    onPointerDown: keepSelection,
    onMouseDown: keepSelection,
    onKeyDown: (event: React.KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    }
  };
  return (
    <div className="border-ax-border-strong bg-ax-popover rounded-ax-element shadow-ax-med my-1 flex flex-col gap-1 border p-2">
      <Text type="supporting" as="p">
        {t("flow_transcript_selection_hint", { count: lines })}
      </Text>
      <Toolbar
        label={t("flow_transcript_selection_toolbar")}
        size="sm"
        startContent={
          <div className="flex flex-wrap items-center gap-1">
            {speakers.map((label) => (
              <Button
                key={label}
                label={speakerText(label, names, t)}
                size="sm"
                onClick={choose(label)}
                {...shared}
              />
            ))}
            <Button
              label={t("flow_transcript_speaker_new", { label: newLabel })}
              size="sm"
              variant="ghost"
              onClick={choose(newLabel)}
              {...shared}
            />
            <Button
              label={t("flow_runs_transcript_unknown_speaker")}
              size="sm"
              variant="ghost"
              onClick={choose(null)}
              {...shared}
            />
          </div>
        }
        endContent={
          <IconButton
            label={t("flow_transcript_selection_close")}
            icon={<X aria-hidden="true" />}
            variant="ghost"
            size="sm"
            onClick={onClose}
            {...shared}
          />
        }
      />
      {problem ? <p className="text-ax-error m-0 text-sm">{problem}</p> : null}
    </div>
  );
}
