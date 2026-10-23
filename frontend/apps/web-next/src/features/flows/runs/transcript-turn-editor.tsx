"use client";

import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import type { ShownSegment } from "./transcript";
import { withoutLineText, type CorrectionSet } from "./transcript-corrections";
import type { LineEditing } from "./transcript-lines";
import { suggestionsFor, type Suggestions } from "./transcript-suggestions";
import { turnText, withTurnText, type Turn } from "./transcript-turns";

/**
 * Corrects a whole turn as one text, as it reads: the edit is saved as the
 * corrections of the lines it changes (their raw text stays). A correction
 * of one line that the transcript likely says elsewhere too is offered for
 * those places first, as in the line editor. The turn's corrected lines can
 * be reverted together.
 */
export function TurnEditor({
  turn,
  time,
  editing,
  lines,
  rawLines,
  onSuggest,
  onDirty,
  onClose
}: {
  turn: Turn;
  time: string;
  editing: LineEditing;
  lines: ReadonlyMap<number, ShownSegment>;
  /** Every line's raw text, where the same correction may apply. */
  rawLines: readonly { index: number; text: string }[];
  onSuggest: (next: CorrectionSet, suggestions: Suggestions) => void;
  /** Whether the text differs from the turn's, as it is typed. */
  onDirty: (dirty: boolean) => void;
  onClose: () => void;
}) {
  const t = useTranslations();
  const [original] = useState(() => turnText(turn));
  const [text, setText] = useState(original);
  const [problem, setProblem] = useState<string | null>(null);
  const indices = [...new Set(turn.parts.map((part) => part.segmentIndex))];
  const corrected = indices.filter((index) => lines.get(index)?.corrected);

  async function save(next: CorrectionSet, done: string) {
    const failed = await editing.save(next, done);
    if (failed) setProblem(failed);
    else onClose();
  }

  function submit() {
    if (editing.saving) return;
    if (text === original) {
      onClose();
      return;
    }
    const { next, texts } = withTurnText(editing.set, turn, text, lines);
    const [only] = texts.size === 1 ? [...texts] : [];
    if (only) {
      const [index, edited] = only;
      const line = lines.get(index);
      const offer = line ? suggestionsFor(next, { index, text: line.raw }, edited, rawLines) : null;
      if (offer) {
        onSuggest(next, offer);
        return;
      }
    }
    void save(next, t("flow_transcript_turn_saved"));
  }

  return (
    <div className="border-ax-border rounded-ax-inner mx-1 mb-2 flex flex-col gap-3 border p-3">
      {problem ? (
        <Banner
          status="error"
          title={t("flow_transcript_line_not_saved")}
          description={problem}
          collapsible={false}
        />
      ) : null}
      <form
        noValidate
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <TextArea
          label={t("flow_transcript_turn_text", { time })}
          description={t("flow_transcript_turn_text_hint")}
          value={text}
          onChange={(value) => {
            setText(value);
            onDirty(value !== original);
          }}
          rows={Math.min(8, Math.max(3, Math.ceil(original.length / 80)))}
          width="100%"
        />
        {corrected.length > 0 ? (
          <Text type="supporting" as="p">
            {t("flow_transcript_turn_corrected", { count: corrected.length })}
          </Text>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button
            type="submit"
            variant="primary"
            label={t("flow_transcript_line_save")}
            isLoading={editing.saving}
            isInterruptible
          />
          {corrected.length > 0 ? (
            <Button
              label={t("flow_transcript_turn_revert")}
              isInterruptible
              onClick={() => {
                if (editing.saving) return;
                void save(
                  corrected.reduce((set, index) => withoutLineText(set, index), editing.set),
                  t("flow_transcript_turn_reverted")
                );
              }}
            />
          ) : null}
          <Button label={t("cancel")} variant="ghost" onClick={onClose} />
        </div>
      </form>
    </div>
  );
}
