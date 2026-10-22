"use client";

import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { Token } from "@astryxdesign/core/Token";
import { Pencil } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import { QuietBanner } from "@/components/astryx/banner";
import { clockTime, type ShownSegment, type TranscriptTarget } from "./transcript";
import { withLineText, withoutLineText, type CorrectionSet } from "./transcript-corrections";
import { useTranscriptPlayback } from "./transcript-player";
import { textRuns, type PlacedWord } from "./transcript-playback";

/** What editing a transcript's lines needs: the saved set, and a save that says what went wrong. */
export type LineEditing = {
  set: CorrectionSet;
  /** Saves the set; null when it was saved, else why not, as a sentence. */
  save: (next: CorrectionSet, done: string) => Promise<string | null>;
  saving: boolean;
};

type Translator = ReturnType<typeof useTranslations>;

function lineTime(segment: ShownSegment, multiFile: boolean, t: Translator): string {
  return multiFile
    ? t("flow_runs_transcript_time_in_file", {
        file: segment.fileIndex + 1,
        time: clockTime(segment.start)
      })
    : clockTime(segment.start);
}

/** Corrects one line's text: saved as a correction of the raw text, which stays. */
function LineEditor({
  segment,
  time,
  editing,
  onClose
}: {
  segment: ShownSegment;
  time: string;
  editing: LineEditing;
  onClose: () => void;
}) {
  const t = useTranslations();
  const [text, setText] = useState(segment.text);
  const [problem, setProblem] = useState<string | null>(null);
  const changed = text !== segment.text;

  async function save(next: CorrectionSet, done: string) {
    const failed = await editing.save(next, done);
    if (failed) setProblem(failed);
    else onClose();
  }

  return (
    <form
      noValidate
      className="border-ax-border rounded-ax-inner mt-1 mb-2 flex flex-col gap-3 border p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (editing.saving) return;
        if (!changed) {
          onClose();
          return;
        }
        void save(
          withLineText(editing.set, { index: segment.index, text: segment.raw }, text),
          t("flow_transcript_line_saved")
        );
      }}
    >
      {problem ? (
        <QuietBanner
          status="error"
          title={t("flow_transcript_line_not_saved")}
          description={problem}
          collapsible={false}
        />
      ) : null}
      <TextArea
        label={t("flow_transcript_line_text", { time })}
        value={text}
        onChange={setText}
        rows={3}
        width="100%"
      />
      {segment.corrected ? (
        <Text type="supporting" as="p">
          {t("flow_transcript_line_original", { text: segment.raw })}
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
        {segment.corrected ? (
          <Button
            label={t("flow_transcript_line_revert")}
            isInterruptible
            onClick={() => {
              if (editing.saving) return;
              void save(
                withoutLineText(editing.set, segment.index),
                t("flow_transcript_line_reverted")
              );
            }}
          />
        ) : null}
        <Button label={t("cancel")} variant="ghost" onClick={onClose} />
      </div>
    </form>
  );
}

function SegmentLine({
  segment,
  multiFile,
  id,
  active,
  activeWord,
  words,
  onSeek,
  editing,
  isEditing,
  onEdit,
  onCloseEditor
}: {
  segment: ShownSegment;
  multiFile: boolean;
  id: string;
  active: boolean;
  activeWord: number;
  /** The line's placed words, when they still match its text. */
  words: readonly PlacedWord[] | undefined;
  /** Plays the line from `time`; absent without audio. */
  onSeek: ((time: number) => void) | null;
  editing: LineEditing | null;
  isEditing: boolean;
  onEdit: () => void;
  onCloseEditor: () => void;
}) {
  const t = useTranslations();
  const speaker = segment.name ?? segment.label ?? t("flow_runs_transcript_unknown_speaker");
  const time = lineTime(segment, multiFile, t);
  // Words are placed in the raw text: a corrected line is marked as a whole.
  const runs = words && !segment.corrected ? textRuns(segment.text, words) : null;
  const body = (
    <>
      <span className="text-ax-text-secondary text-xs tabular-nums sm:pt-0.5">
        {onSeek ? <span className="sr-only">{t("flow_transcript_play_from")} </span> : null}
        {time}
      </span>
      <span className="text-ax-text text-sm break-words">
        <span className="font-semibold">{speaker}:</span>{" "}
        {runs
          ? runs.map((run, index) =>
              run.word === null ? (
                <span key={index}>{run.text}</span>
              ) : (
                <span
                  key={index}
                  data-word={run.word}
                  className={
                    active && run.word === activeWord ? "bg-ax-accent-muted rounded-sm" : undefined
                  }
                >
                  {run.text}
                </span>
              )
            )
          : segment.text}
        {segment.corrected ? (
          <>
            {" "}
            <Token size="sm" label={t("flow_transcript_line_corrected")} />
          </>
        ) : null}
      </span>
    </>
  );
  const layout = "grid gap-x-3 gap-y-0.5 py-1.5 sm:grid-cols-[minmax(6rem,max-content)_1fr]";
  return (
    <li id={id} className={active ? "bg-ax-selected rounded-ax-inner" : undefined}>
      <div className="flex items-start gap-1">
        {onSeek ? (
          <button
            type="button"
            aria-current={active ? "time" : undefined}
            className={`${layout} hover:bg-ax-hover focus-visible:outline-ring rounded-ax-inner min-w-0 flex-1 px-1 text-left outline-none focus-visible:outline-2 focus-visible:outline-offset-2`}
            onClick={(event) => {
              // A click on a word plays from that word; the keyboard plays the line.
              const word = (event.target as HTMLElement).closest<HTMLElement>("[data-word]");
              const placed = word ? words?.[Number(word.dataset.word)] : undefined;
              onSeek(placed ? placed.start : segment.start);
            }}
          >
            {body}
          </button>
        ) : (
          <div className={`${layout} min-w-0 flex-1 px-1`}>{body}</div>
        )}
        {editing && !isEditing ? (
          <span id={`${id}-edit`} className="shrink-0">
            <IconButton
              label={t("flow_transcript_line_edit", { time })}
              icon={<Pencil aria-hidden="true" />}
              variant="ghost"
              size="sm"
              onClick={onEdit}
            />
          </span>
        ) : null}
      </div>
      {editing && isEditing ? (
        <LineEditor segment={segment} time={time} editing={editing} onClose={onCloseEditor} />
      ) : null}
    </li>
  );
}

/**
 * The lines of one transcript, with its audio player above them. Someone who
 * may correct the transcript corrects a line's text in place; the line then
 * shows that it is corrected and what it said before, and the correction can
 * be reverted.
 */
export function TranscriptLines({
  flowId,
  runId,
  target,
  shown,
  sourceHash,
  multiFile,
  editing,
  children
}: {
  flowId: string;
  runId: string;
  target: TranscriptTarget;
  shown: ShownSegment[];
  sourceHash: string;
  multiFile: boolean;
  editing: LineEditing | null;
  children?: React.ReactNode;
}) {
  const t = useTranslations();
  const playback = useTranscriptPlayback({ flowId, runId, target, lines: shown, sourceHash });
  const [open, setOpen] = useState<number | null>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const corrected = shown.filter((segment) => segment.corrected).length;

  function lineId(position: number, segment: ShownSegment) {
    return playback?.lineId(position) ?? `${target.stepId}-line-${segment.index}`;
  }

  function openEditor(id: string, index: number) {
    flushSync(() => setOpen(index));
    document.getElementById(id)?.querySelector("textarea")?.focus();
  }

  function closeEditor(id: string) {
    flushSync(() => setOpen(null));
    // Back to the line's edit button.
    listRef.current?.querySelector<HTMLElement>(`[id="${id}-edit"] button`)?.focus();
  }

  return (
    <div className="flex flex-col gap-4">
      {children}
      {playback?.player}
      {corrected > 0 ? (
        <Text type="supporting" as="p">
          {t("flow_transcript_corrected_count", { count: corrected })}
        </Text>
      ) : null}
      <ol
        ref={listRef}
        aria-label={t("flow_runs_transcript_lines")}
        className="m-0 flex flex-col p-0"
      >
        {shown.map((segment, position) => {
          const id = lineId(position, segment);
          return (
            <SegmentLine
              key={segment.index}
              id={id}
              segment={segment}
              multiFile={multiFile}
              active={playback?.activeLine === position}
              activeWord={playback?.activeLine === position ? playback.activeWord : -1}
              words={playback?.words.get(segment.index)}
              onSeek={playback ? (time) => playback.seek(segment.fileIndex, time) : null}
              editing={editing}
              isEditing={open === segment.index}
              onEdit={() => openEditor(id, segment.index)}
              onCloseEditor={() => closeEditor(id)}
            />
          );
        })}
      </ol>
    </div>
  );
}
