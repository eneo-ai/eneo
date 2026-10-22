"use client";

import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Heading } from "@astryxdesign/core/Heading";
import { IconButton } from "@astryxdesign/core/IconButton";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { Token } from "@astryxdesign/core/Token";
import { Pencil } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import { QuietBanner } from "@/components/astryx/banner";
import { clockTime, type ShownSegment, type TranscriptTarget } from "./transcript";
import {
  nextSpeakerLabel,
  shownToRaw,
  withLineText,
  withoutLineText,
  withSpeaker,
  type CorrectionSet
} from "./transcript-corrections";
import { useTranscriptPlayback } from "./transcript-player";
import { textRuns, type PlacedWord, type TextRun } from "./transcript-playback";
import { overlapDetectionUnavailable, overlaps, type Overlap } from "./transcript-overlaps";
import type { TranscriptSpeakerReview } from "./runs-api";

/** What editing a transcript's lines needs: the saved set, and a save that says what went wrong. */
export type LineEditing = {
  set: CorrectionSet;
  /** Every speaker label of the transcript and its speaker edits. */
  speakers: string[];
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

const NEW_SPEAKER = "__new__";
const NO_SPEAKER = "__none__";

function speakerName(label: string | null, names: Record<string, string | null>, t: Translator) {
  if (!label) return t("flow_runs_transcript_unknown_speaker");
  return names[label]?.trim() || label;
}

/**
 * Gives a line, or the part of it marked in the text field, to another
 * speaker; the reviewer can say they are unsure, which keeps the line marked
 * for someone to check (the core's `unresolved` decision).
 */
function SpeakerEditor({
  segment,
  editing,
  textField,
  textChanged,
  onDone,
  onProblem
}: {
  segment: ShownSegment;
  editing: LineEditing;
  textField: React.RefObject<HTMLTextAreaElement | null>;
  textChanged: boolean;
  onDone: () => void;
  onProblem: (problem: string) => void;
}) {
  const t = useTranslations();
  const others = editing.speakers.filter((label) => label !== segment.label);
  const newLabel = nextSpeakerLabel(editing.speakers);
  const [to, setTo] = useState(others[0] ?? NEW_SPEAKER);
  const [scope, setScope] = useState<"line" | "selection">("line");
  const [unsure, setUnsure] = useState(false);
  const reassigned = segment.parts.some((part) => part.overridden);
  const line = { index: segment.index, text: segment.raw, speaker: segment.speaker };

  async function apply() {
    if (editing.saving) return;
    let span: { start: number; end: number } | null = null;
    if (scope === "selection") {
      const field = textField.current;
      if (textChanged) return onProblem(t("flow_transcript_speaker_text_changed"));
      if (!field || field.selectionStart === field.selectionEnd) {
        return onProblem(t("flow_transcript_speaker_select_text"));
      }
      const own = editing.set.occurrences.filter((item) => item.segment_index === segment.index);
      span = {
        start: shownToRaw(segment.raw, own, field.selectionStart, "start"),
        end: shownToRaw(segment.raw, own, field.selectionEnd, "end")
      };
    }
    const speaker = to === NEW_SPEAKER ? newLabel : to === NO_SPEAKER ? null : to;
    const failed = await editing.save(
      withSpeaker(editing.set, line, span, {
        speaker,
        decision: unsure || speaker === null ? "unresolved" : "confirmed"
      }),
      t("flow_transcript_speaker_saved")
    );
    if (failed) onProblem(failed);
    else onDone();
  }

  // The speaker service was unsure; the reviewer keeps its speaker.
  async function confirm() {
    if (editing.saving) return;
    const failed = await editing.save(
      withSpeaker(editing.set, line, null, { speaker: segment.speaker, decision: "confirmed" }),
      t("flow_transcript_speaker_confirmed")
    );
    if (failed) onProblem(failed);
    else onDone();
  }

  async function reset() {
    if (editing.saving) return;
    const failed = await editing.save(
      withSpeaker(editing.set, line, null, "reset"),
      t("flow_transcript_speaker_reset_done")
    );
    if (failed) onProblem(failed);
    else onDone();
  }

  return (
    <div className="border-ax-border flex flex-col gap-3 border-t pt-3">
      <Heading level={5}>{t("flow_transcript_speaker_heading")}</Heading>
      <Selector
        label={t("flow_transcript_speaker_to")}
        value={to}
        onChange={setTo}
        options={[
          ...others.map((label) => ({
            value: label,
            label: speakerName(label, editing.set.names, t)
          })),
          { value: NEW_SPEAKER, label: t("flow_transcript_speaker_new", { label: newLabel }) },
          { value: NO_SPEAKER, label: t("flow_runs_transcript_unknown_speaker") }
        ]}
        width="100%"
      />
      <RadioList
        label={t("flow_transcript_speaker_scope")}
        value={scope}
        onChange={(value) => setScope(value === "selection" ? "selection" : "line")}
        size="sm"
      >
        <RadioListItem value="line" label={t("flow_transcript_speaker_scope_line")} />
        <RadioListItem
          value="selection"
          label={t("flow_transcript_speaker_scope_selection")}
          description={t("flow_transcript_speaker_scope_selection_hint")}
        />
      </RadioList>
      <CheckboxInput
        label={t("flow_transcript_speaker_unsure")}
        description={t("flow_transcript_speaker_unsure_hint")}
        value={unsure}
        onChange={setUnsure}
        size="sm"
      />
      <div className="flex flex-wrap gap-2">
        {segment.unsure ? (
          <Button
            label={t("flow_transcript_speaker_confirm", {
              name: speakerName(segment.label, editing.set.names, t)
            })}
            variant="primary"
            isInterruptible
            onClick={() => void confirm()}
          />
        ) : null}
        <Button
          label={t("flow_transcript_speaker_apply")}
          isLoading={editing.saving}
          isInterruptible
          onClick={() => void apply()}
        />
        {reassigned ? (
          <Button
            label={t("flow_transcript_speaker_reset")}
            variant="ghost"
            isInterruptible
            onClick={() => void reset()}
          />
        ) : null}
      </div>
    </div>
  );
}

/**
 * Corrects one line: its text, saved as a correction of the raw text (which
 * stays), and who said it.
 */
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
  const textField = useRef<HTMLTextAreaElement>(null);
  const [text, setText] = useState(segment.text);
  const [problem, setProblem] = useState<string | null>(null);
  const changed = text !== segment.text;

  async function save(next: CorrectionSet, done: string) {
    const failed = await editing.save(next, done);
    if (failed) setProblem(failed);
    else onClose();
  }

  return (
    <div className="border-ax-border rounded-ax-inner mt-1 mb-2 flex flex-col gap-3 border p-3">
      {problem ? (
        <QuietBanner
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
        <TextArea
          ref={textField}
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
      <SpeakerEditor
        segment={segment}
        editing={editing}
        textField={textField}
        textChanged={changed}
        onDone={onClose}
        onProblem={setProblem}
      />
    </div>
  );
}

/** The speakers and words of a shown line: one part, or one per speaker when part of it moved. */
function LineText({
  segment,
  runs,
  active,
  activeWord
}: {
  segment: ShownSegment;
  runs: TextRun[] | null;
  active: boolean;
  activeWord: number;
}) {
  const t = useTranslations();
  const unresolved = (
    <Token size="sm" color="orange" label={t("flow_transcript_speaker_unresolved")} />
  );
  if (segment.parts.length > 1) {
    return (
      <>
        {segment.parts.map((part, index) => (
          <span key={index}>
            {index > 0 ? " " : null}
            <span className="font-semibold">
              {part.name ?? part.speaker ?? t("flow_runs_transcript_unknown_speaker")}:
            </span>{" "}
            {part.decision === "unresolved" ? <>{unresolved} </> : null}
            {part.text.trim()}
          </span>
        ))}
      </>
    );
  }
  const speaker = segment.name ?? segment.label ?? t("flow_runs_transcript_unknown_speaker");
  return (
    <>
      <span className="font-semibold">{speaker}:</span>{" "}
      {segment.decision === "unresolved" || segment.unsure ? <>{unresolved} </> : null}
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
    </>
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
  const time = lineTime(segment, multiFile, t);
  // Words are placed in the raw text: a corrected or split line is marked as a whole.
  const runs =
    words && !segment.corrected && segment.parts.length === 1
      ? textRuns(segment.text, words)
      : null;
  const body = (
    <>
      <span className="text-ax-text-secondary text-xs tabular-nums sm:pt-0.5">
        {onSeek ? <span className="sr-only">{t("flow_transcript_play_from")} </span> : null}
        {time}
      </span>
      <span className="text-ax-text text-sm break-words">
        <LineText segment={segment} runs={runs} active={active} activeWord={activeWord} />
        {segment.corrected ? (
          <>
            {" "}
            <Token size="sm" label={t("flow_transcript_line_corrected")} />
          </>
        ) : null}
        {segment.overlapIds?.length ? (
          <>
            {" "}
            <Token size="sm" color="gray" label={t("flow_transcript_overlap_line")} />
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
 * The places where more than one voice spoke at once, with how many lines
 * there still need a reviewer's decision on who spoke; each can be gone to
 * (and played from).
 */
function OverlapReview({
  found,
  unavailable,
  multiFile,
  onGo
}: {
  found: Overlap[];
  unavailable: boolean;
  multiFile: boolean;
  onGo: (overlap: Overlap) => void;
}) {
  const t = useTranslations();
  if (found.length === 0) {
    return unavailable ? (
      <Text type="supporting" as="p">
        {t("flow_transcript_overlap_unavailable")}
      </Text>
    ) : null;
  }
  const open = found.filter((overlap) => overlap.open > 0).length;
  return (
    <QuietBanner
      status={open > 0 ? "warning" : "success"}
      title={
        open > 0
          ? t("flow_transcript_overlap_title", { count: open })
          : t("flow_transcript_overlap_done")
      }
      description={t("flow_transcript_overlap_hint")}
      collapsible={false}
    >
      <ol aria-label={t("flow_transcript_overlap_list")} className="m-0 flex flex-col gap-1 p-0">
        {found.map((overlap) => {
          const time = `${clockTime(overlap.start)}–${clockTime(overlap.end)}`;
          const where = multiFile
            ? t("flow_runs_transcript_time_in_file", { file: overlap.fileIndex + 1, time })
            : time;
          return (
            <li key={overlap.id} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="tabular-nums">{where}</span>
              {overlap.voices ? (
                <span className="text-ax-text-secondary">
                  {t("flow_transcript_overlap_voices", { count: overlap.voices })}
                </span>
              ) : null}
              <Token
                size="sm"
                color={overlap.open > 0 ? "orange" : "green"}
                label={
                  overlap.open > 0
                    ? t("flow_transcript_overlap_open", { count: overlap.open })
                    : t("flow_transcript_overlap_checked")
                }
              />
              {overlap.lines.length > 0 ? (
                <Button
                  size="sm"
                  variant="ghost"
                  label={t("flow_transcript_overlap_go", { time: where })}
                  onClick={() => onGo(overlap)}
                />
              ) : null}
            </li>
          );
        })}
      </ol>
    </QuietBanner>
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
  speakerReview = null,
  children
}: {
  flowId: string;
  runId: string;
  target: TranscriptTarget;
  shown: ShownSegment[];
  sourceHash: string;
  multiFile: boolean;
  editing: LineEditing | null;
  /** Where the speaker service heard more than one voice at once. */
  speakerReview?: TranscriptSpeakerReview | null;
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
      <OverlapReview
        found={overlaps(speakerReview, shown)}
        unavailable={overlapDetectionUnavailable(speakerReview)}
        multiFile={multiFile}
        onGo={(overlap) => {
          playback?.seek(overlap.fileIndex, overlap.start);
          const first = overlap.lines[0];
          if (first === undefined) return;
          const line = document.getElementById(lineId(first, shown[first]!));
          line?.scrollIntoView({ block: "nearest" });
          line?.querySelector<HTMLElement>("button")?.focus();
        }}
      />
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
