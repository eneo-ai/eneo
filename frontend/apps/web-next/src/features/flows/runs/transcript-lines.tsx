"use client";

import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Heading } from "@astryxdesign/core/Heading";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { IconButton } from "@astryxdesign/core/IconButton";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { ToggleButton, ToggleButtonGroup } from "@astryxdesign/core/ToggleButton";
import { Token } from "@astryxdesign/core/Token";
import { Download, Pencil, Volume2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { QuietBanner } from "@/components/astryx/banner";
import { useBeforeUnloadWarning } from "@/lib/hooks/use-before-unload-warning";
import { clockTime, type ShownSegment, type TranscriptTarget } from "./transcript";
import {
  nextSpeakerLabel,
  shownToRaw,
  withLineText,
  withoutLineText,
  withSpeaker,
  type CorrectionSet
} from "./transcript-corrections";
import { saveText, transcriptText } from "./transcript-export";
import { uncertainWordCount, useTranscriptPlayback } from "./transcript-player";
import { textRuns, type PlacedWord, type TextRun } from "./transcript-playback";
import { overlapDetectionUnavailable, overlaps, type Overlap } from "./transcript-overlaps";
import { partAttributes, selectedSpans, type SelectedSpan } from "./transcript-selection";
import { SelectionToolbar } from "./transcript-selection-toolbar";
import { SpeakerBadge, speakerText } from "./transcript-speakers";
import { SuggestionsDialog } from "./transcript-suggestions-dialog";
import {
  suggestionsFor,
  withSuggestions,
  type Candidate,
  type Suggestions
} from "./transcript-suggestions";
import { transcriptTurns, type Turn } from "./transcript-turns";
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
type View = "lines" | "turns";

function placeTime(fileIndex: number, start: number, multiFile: boolean, t: Translator): string {
  return multiFile
    ? t("flow_runs_transcript_time_in_file", { file: fileIndex + 1, time: clockTime(start) })
    : clockTime(start);
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
 * stays), and who said it. A correction of a word or a name that the
 * transcript likely says elsewhere too is offered for those places first.
 */
function LineEditor({
  segment,
  time,
  editing,
  lines,
  onSuggest,
  onDirty,
  onClose
}: {
  segment: ShownSegment;
  time: string;
  editing: LineEditing;
  /** Whether the text differs from the line's, as it is typed. */
  onDirty: (dirty: boolean) => void;
  /** Every line's raw text, where the same correction may apply. */
  lines: readonly { index: number; text: string }[];
  onSuggest: (next: CorrectionSet, suggestions: Suggestions) => void;
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
          const line = { index: segment.index, text: segment.raw };
          const next = withLineText(editing.set, line, text);
          const offer = suggestionsFor(next, line, text, lines);
          if (offer) onSuggest(next, offer);
          else void save(next, t("flow_transcript_line_saved"));
        }}
      >
        <TextArea
          ref={textField}
          label={t("flow_transcript_line_text", { time })}
          value={text}
          onChange={(value) => {
            setText(value);
            onDirty(value !== segment.text);
          }}
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

/** Where each part starts in its line's corrected text: the parts follow one another. */
function partStarts(parts: readonly { text: string }[]): number[] {
  return parts.reduce<number[]>(
    (starts, part, index) => [
      ...starts,
      index === 0 ? 0 : starts[index - 1]! + parts[index - 1]!.text.length
    ],
    []
  );
}

function Unresolved() {
  const t = useTranslations();
  return <Token size="sm" color="orange" label={t("flow_transcript_speaker_unresolved")} />;
}

/**
 * The speakers and words of a shown line: one part, or one per speaker when
 * part of it moved. Each part's text carries its anchors, so text marked in
 * it maps back to the line; a placed word carries where it plays from.
 */
function LineText({
  segment,
  runs,
  words,
  active,
  activeWord
}: {
  segment: ShownSegment;
  runs: TextRun[] | null;
  words: readonly PlacedWord[] | undefined;
  active: boolean;
  activeWord: number;
}) {
  if (segment.parts.length > 1) {
    const starts = partStarts(segment.parts);
    return (
      <>
        {segment.parts.map((part, index) => (
          <span key={index}>
            {index > 0 ? " " : null}
            <SpeakerBadge label={part.speaker} name={part.name} />{" "}
            {part.decision === "unresolved" ? (
              <>
                <Unresolved />{" "}
              </>
            ) : null}
            <span {...partAttributes(segment.index, starts[index]!)}>{part.text}</span>
          </span>
        ))}
      </>
    );
  }
  return (
    <>
      <SpeakerBadge label={segment.label} name={segment.name} />{" "}
      {segment.decision === "unresolved" || segment.unsure ? (
        <>
          <Unresolved />{" "}
        </>
      ) : null}
      <span {...partAttributes(segment.index, 0)}>
        {runs
          ? runs.map((run, index) => {
              const word = run.word === null ? undefined : words?.[run.word];
              return word === undefined ? (
                <span key={index}>{run.text}</span>
              ) : (
                <span
                  key={index}
                  data-word={run.word}
                  data-seek={word.start}
                  data-file={segment.fileIndex}
                  className={[
                    "cursor-pointer",
                    active && run.word === activeWord ? "bg-ax-accent-muted rounded-sm" : "",
                    // Where the aligner only guessed the word's time.
                    word.uncertain ? "underline decoration-wavy underline-offset-2" : ""
                  ]
                    .filter(Boolean)
                    .join(" ")}
                >
                  {run.text}
                </span>
              );
            })
          : segment.text}
      </span>
    </>
  );
}

/** Plays from a line or a turn; its accessible name says so before the time. */
function TimeButton({
  time,
  active,
  onPlay
}: {
  time: string;
  active: boolean;
  onPlay: (() => void) | null;
}) {
  const t = useTranslations();
  if (!onPlay) {
    return <span className="text-ax-text-secondary text-xs tabular-nums sm:pt-0.5">{time}</span>;
  }
  return (
    <button
      type="button"
      aria-current={active ? "time" : undefined}
      className="text-ax-text-secondary hover:bg-ax-hover hover:text-ax-text focus-visible:outline-ring rounded-ax-inner min-h-6 self-start px-1 text-left text-xs tabular-nums outline-none focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
      onClick={onPlay}
    >
      <span className="sr-only">{t("flow_transcript_play_from")} </span>
      {time}
    </button>
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
  editor,
  toolbar
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
  editor: React.ReactNode;
  /** The toolbar for text marked up to this line. */
  toolbar: React.ReactNode;
}) {
  const t = useTranslations();
  const time = placeTime(segment.fileIndex, segment.start, multiFile, t);
  // Words are placed in the raw text: a corrected or split line is marked as a whole.
  const runs =
    words && !segment.corrected && segment.parts.length === 1
      ? textRuns(segment.text, words)
      : null;
  return (
    <li id={id} className={active ? "bg-ax-selected rounded-ax-inner" : undefined}>
      <div className="flex items-start gap-1">
        <div className="grid min-w-0 flex-1 gap-x-3 gap-y-0.5 px-1 py-1.5 sm:grid-cols-[minmax(6rem,max-content)_1fr]">
          <TimeButton
            time={time}
            active={active}
            onPlay={onSeek ? () => onSeek(segment.start) : null}
          />
          <span className="text-ax-text text-sm break-words">
            <LineText
              segment={segment}
              runs={runs}
              words={words}
              active={active}
              activeWord={activeWord}
            />
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
        </div>
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
      {editor}
      {toolbar}
    </li>
  );
}

/**
 * The transcript as speaker turns: what one speaker said in a row, as one
 * paragraph, each playable from its start. Text is corrected in the line
 * view; speakers can be given to marked text here too.
 */
function TurnList({
  turns,
  multiFile,
  activeLine,
  onSeek,
  toolbarAt,
  toolbar
}: {
  turns: readonly Turn[];
  multiFile: boolean;
  activeLine: number;
  onSeek: ((fileIndex: number, time: number) => void) | null;
  /** The turn the marked text ends in, which shows the toolbar. */
  toolbarAt: number;
  toolbar: React.ReactNode;
}) {
  const t = useTranslations();
  return (
    <ol aria-label={t("flow_transcript_turns_list")} className="m-0 flex flex-col gap-1 p-0">
      {turns.map((turn, index) => {
        const active = turn.parts.some((part) => part.position === activeLine);
        return (
          <li
            key={`${turn.parts[0]!.segmentIndex}:${turn.parts[0]!.shownStart}`}
            className={active ? "bg-ax-selected rounded-ax-inner" : undefined}
          >
            <div className="flex flex-col gap-1 px-1 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <TimeButton
                  time={placeTime(turn.fileIndex, turn.start, multiFile, t)}
                  active={active}
                  onPlay={onSeek ? () => onSeek(turn.fileIndex, turn.start) : null}
                />
                <SpeakerBadge label={turn.speaker} name={turn.name} />
                {turn.marker ? <Unresolved /> : null}
              </div>
              <p className="text-ax-text m-0 text-sm break-words">
                {turn.parts.map((part, at) => {
                  const previous = turn.parts[at - 1];
                  const gap = previous && !/\s$/.test(previous.text) && !/^\s/.test(part.text);
                  return (
                    <span key={`${part.segmentIndex}:${part.shownStart}`}>
                      {gap ? " " : null}
                      <span
                        {...partAttributes(part.segmentIndex, part.shownStart)}
                        className={
                          part.position === activeLine ? "bg-ax-accent-muted rounded-sm" : undefined
                        }
                      >
                        {part.text}
                      </span>
                    </span>
                  );
                })}
              </p>
            </div>
            {index === toolbarAt ? toolbar : null}
          </li>
        );
      })}
    </ol>
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

/** A line to hear a speaker by: theirs, said with confidence, with words in it. */
function sampleLine(shown: readonly ShownSegment[], label: string): ShownSegment | undefined {
  return shown.find(
    (segment) =>
      segment.label === label &&
      segment.parts.length === 1 &&
      !segment.unsure &&
      segment.decision !== "unresolved" &&
      /[\p{L}\p{N}]/u.test(segment.text)
  );
}

/**
 * A short sample of each speaker's voice: their first line said with
 * confidence, from just before it starts to just after it ends. It helps
 * tell the speakers apart before naming them or reassigning their lines.
 */
function SpeakerSamples({
  shown,
  onPlay
}: {
  shown: readonly ShownSegment[];
  onPlay: (fileIndex: number, time: number, until?: number) => void;
}) {
  const t = useTranslations();
  const headingId = useId();
  const samples = [...new Set(shown.flatMap((segment) => (segment.label ? [segment.label] : [])))]
    .map((label) => ({ label, line: sampleLine(shown, label) }))
    .filter((sample): sample is { label: string; line: ShownSegment } => Boolean(sample.line));
  if (samples.length === 0) return null;
  return (
    <div role="group" aria-labelledby={headingId} className="flex flex-wrap items-center gap-2">
      <Text type="supporting" id={headingId}>
        {t("flow_transcript_samples")}
      </Text>
      {samples.map(({ label, line }) => (
        <Button
          key={label}
          label={t("flow_transcript_sample_listen", {
            name: speakerText(label, { [label]: line.name }, t)
          })}
          icon={<Volume2 aria-hidden="true" />}
          size="sm"
          variant="ghost"
          onClick={() => onPlay(line.fileIndex, Math.max(0, line.start - 0.5), line.end + 0.5)}
        />
      ))}
    </div>
  );
}

/**
 * The lines of one transcript, with its audio player above them. Someone who
 * may correct the transcript corrects a line's text in place; the line then
 * shows that it is corrected and what it said before, and the correction can
 * be reverted. Text marked in the transcript can be given to a speaker, and
 * the transcript reads as lines or as speaker turns.
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
  onUnsavedChange,
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
  /**
   * Hears whether an edit here is not saved yet (a line's text changed, or a
   * correction waiting for its other places), so a review can hold its approval.
   */
  onUnsavedChange?: (unsaved: boolean) => void;
  children?: React.ReactNode;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const playback = useTranscriptPlayback({
    flowId,
    runId,
    target,
    lines: shown,
    sourceHash,
    eagerWords: editing !== null
  });
  const [open, setOpen] = useState<number | null>(null);
  const [view, setView] = useState<View>("lines");
  const [suggesting, setSuggesting] = useState<{
    next: CorrectionSet;
    suggestions: Suggestions;
    lineId: string;
    problem: string | null;
  } | null>(null);
  /** The open line editor's text differs from the line's. */
  const [dirty, setDirty] = useState(false);
  const [picked, setPicked] = useState<SelectedSpan[] | null>(null);
  const [pickProblem, setPickProblem] = useState<string | null>(null);
  const area = useRef<HTMLDivElement>(null);
  const toolbarBox = useRef<HTMLDivElement>(null);
  const corrected = shown.filter((segment) => segment.corrected).length;
  const turns = view === "turns" ? transcriptTurns(shown) : [];
  const byIndex = new Map(shown.map((segment) => [segment.index, segment]));
  const rawLines = shown.map((segment) => ({ index: segment.index, text: segment.raw }));

  const unsaved = dirty || suggesting !== null;
  useBeforeUnloadWarning(unsaved);
  const tellUnsaved = useRef(onUnsavedChange);
  useEffect(() => {
    tellUnsaved.current = onUnsavedChange;
  });
  useEffect(() => {
    tellUnsaved.current?.(unsaved);
  }, [unsaved]);

  /** What the document listeners read: the latest lines, corrections and player. */
  const latest = useRef({ shown, editing, seek: playback?.seek, announce, t });
  useEffect(() => {
    latest.current = { shown, editing, seek: playback?.seek, announce, t };
  });

  // Text marked in the transcript: the toolbar acts on it once it is inside one transcript.
  const markable = editing !== null;
  useEffect(() => {
    if (!markable) return;
    let had = false;
    const onChange = () => {
      const box = area.current;
      const selection = document.getSelection();
      const range =
        selection && selection.rangeCount > 0 && !selection.isCollapsed
          ? selection.getRangeAt(0)
          : null;
      const inside =
        range && box?.contains(range.startContainer) && box.contains(range.endContainer);
      const spans =
        inside && range && box
          ? selectedSpans(box, range, (index) => {
              const { shown: lines, editing: current } = latest.current;
              const line = lines.find((item) => item.index === index);
              return line
                ? {
                    raw: line.raw,
                    occurrences: (current?.set.occurrences ?? []).filter(
                      (item) => item.segment_index === index
                    )
                  }
                : null;
            })
          : [];
      if (spans.length === 0) {
        // A keyboard user who moved into the toolbar keeps it.
        if (toolbarBox.current?.contains(document.activeElement)) return;
        had = false;
        setPicked(null);
        setPickProblem(null);
        return;
      }
      if (!had) latest.current.announce(latest.current.t("flow_transcript_selection_announce"));
      had = true;
      setPicked(spans);
    };
    document.addEventListener("selectionchange", onChange);
    return () => document.removeEventListener("selectionchange", onChange);
  }, [markable]);

  // A click on a word (not the end of marking text) plays from that word. The
  // pointer's shortcut: the keyboard plays a line from its time.
  useEffect(() => {
    const box = area.current;
    if (!box) return;
    const onClick = (event: MouseEvent) => {
      if (!document.getSelection()?.isCollapsed) return;
      const word = (event.target as Element | null)?.closest<HTMLElement>("[data-seek]");
      if (!word || !box.contains(word)) return;
      latest.current.seek?.(Number(word.dataset.file), Number(word.dataset.seek));
    };
    box.addEventListener("click", onClick);
    return () => box.removeEventListener("click", onClick);
  }, []);

  function lineId(position: number, segment: ShownSegment) {
    return playback?.lineId(position) ?? `${target.stepId}-line-${segment.index}`;
  }

  function openEditor(id: string, index: number) {
    flushSync(() => {
      setOpen(index);
      setDirty(false);
    });
    document.getElementById(id)?.querySelector("textarea")?.focus();
  }

  function focusEditButton(id: string) {
    area.current?.querySelector<HTMLElement>(`[id="${id}-edit"] button`)?.focus();
  }

  function closeEditor(id: string) {
    flushSync(() => {
      setOpen(null);
      setDirty(false);
    });
    // Back to the line's edit button.
    focusEditButton(id);
  }

  async function saveSuggested(chosen: Candidate[]) {
    if (!editing || !suggesting) return;
    const next = withSuggestions(suggesting.next, suggesting.suggestions, chosen);
    const failed = await editing.save(
      next,
      chosen.length > 0
        ? t("flow_transcript_suggest_saved", { count: chosen.length + 1 })
        : t("flow_transcript_line_saved")
    );
    if (failed) {
      setSuggesting((current) => (current ? { ...current, problem: failed } : current));
      return;
    }
    const id = suggesting.lineId;
    flushSync(() => setSuggesting(null));
    focusEditButton(id);
  }

  async function assign(speaker: string | null) {
    if (!editing || !picked || editing.saving) return;
    let next = editing.set;
    for (const span of picked) {
      const line = byIndex.get(span.segmentIndex);
      if (!line) continue;
      next = withSpeaker(
        next,
        { index: line.index, text: line.raw, speaker: line.speaker },
        { start: span.start, end: span.end },
        { speaker, decision: speaker === null ? "unresolved" : "confirmed" }
      );
    }
    const failed = await editing.save(next, t("flow_transcript_speaker_saved"));
    if (failed) {
      setPickProblem(failed);
      return;
    }
    closeToolbar();
  }

  function closeToolbar() {
    const focusWasInside = toolbarBox.current?.contains(document.activeElement);
    const last = picked?.at(-1);
    document.getSelection()?.removeAllRanges();
    flushSync(() => {
      setPicked(null);
      setPickProblem(null);
    });
    if (focusWasInside && last) {
      const position = shown.findIndex((segment) => segment.index === last.segmentIndex);
      const line =
        position >= 0 ? document.getElementById(lineId(position, shown[position]!)) : null;
      line?.querySelector<HTMLElement>("button")?.focus();
    }
  }

  const lastPicked = picked?.at(-1)?.segmentIndex;
  const toolbar =
    editing && picked ? (
      <div ref={toolbarBox}>
        <SelectionToolbar
          lines={new Set(picked.map((span) => span.segmentIndex)).size}
          speakers={editing.speakers}
          names={editing.set.names}
          newLabel={nextSpeakerLabel(editing.speakers)}
          saving={editing.saving}
          problem={pickProblem}
          onChoose={(speaker) => void assign(speaker)}
          onClose={closeToolbar}
        />
      </div>
    ) : null;
  const seek = playback
    ? (fileIndex: number, time: number) => playback.seek(fileIndex, time)
    : null;

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
          if (view !== "lines") flushSync(() => setView("lines"));
          const line = document.getElementById(lineId(first, shown[first]!));
          line?.scrollIntoView({ block: "nearest" });
          line?.querySelector<HTMLElement>("button")?.focus();
        }}
      />
      {playback?.player}
      {playback ? <SpeakerSamples shown={shown} onPlay={playback.seek} /> : null}
      {playback && uncertainWordCount(playback.words) > 0 ? (
        <Text type="supporting" as="p">
          {t("flow_transcript_uncertain_words", { count: uncertainWordCount(playback.words) })}
        </Text>
      ) : null}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <ToggleButtonGroup
          label={t("flow_transcript_view_label")}
          value={view}
          onChange={(next) => {
            if (next === "lines" || next === "turns") {
              setOpen(null);
              setDirty(false);
              setPicked(null);
              setView(next);
            }
          }}
          size="sm"
        >
          <ToggleButton value="lines" label={t("flow_transcript_view_lines")} />
          <ToggleButton value="turns" label={t("flow_transcript_view_turns")} />
        </ToggleButtonGroup>
        <div className="flex flex-wrap items-center gap-3">
          {corrected > 0 ? (
            <Text type="supporting">
              {t("flow_transcript_corrected_count", { count: corrected })}
            </Text>
          ) : null}
          <Button
            label={t("flow_transcript_export")}
            icon={<Download aria-hidden="true" />}
            size="sm"
            variant="ghost"
            onClick={() =>
              saveText(
                transcriptText(shown, {
                  part: (number) => t("flow_transcript_audio_part_heading", { part: number }),
                  unknownSpeaker: t("flow_runs_transcript_unknown_speaker"),
                  unsureSpeaker: t("flow_transcript_speaker_unresolved")
                }),
                t("flow_transcript_export_file")
              )
            }
          />
        </div>
      </div>
      {editing ? (
        <Text type="supporting" as="p">
          {view === "turns"
            ? t("flow_transcript_view_turns_hint")
            : t("flow_transcript_selection_intro")}
        </Text>
      ) : null}
      <div ref={area}>
        {view === "turns" ? (
          <TurnList
            turns={turns}
            multiFile={multiFile}
            activeLine={playback?.activeLine ?? -1}
            onSeek={seek}
            toolbarAt={
              lastPicked === undefined
                ? -1
                : turns.findLastIndex((turn) =>
                    turn.parts.some((part) => part.segmentIndex === lastPicked)
                  )
            }
            toolbar={toolbar}
          />
        ) : (
          <ol aria-label={t("flow_runs_transcript_lines")} className="m-0 flex flex-col p-0">
            {shown.map((segment, position) => {
              const id = lineId(position, segment);
              const isEditing = open === segment.index;
              return (
                <SegmentLine
                  key={segment.index}
                  id={id}
                  segment={segment}
                  multiFile={multiFile}
                  active={playback?.activeLine === position}
                  activeWord={playback?.activeLine === position ? playback.activeWord : -1}
                  words={playback?.words.get(segment.index)}
                  onSeek={seek ? (time) => seek(segment.fileIndex, time) : null}
                  editing={editing}
                  isEditing={isEditing}
                  onEdit={() => openEditor(id, segment.index)}
                  editor={
                    editing && isEditing ? (
                      <LineEditor
                        segment={segment}
                        time={placeTime(segment.fileIndex, segment.start, multiFile, t)}
                        editing={editing}
                        lines={rawLines}
                        onSuggest={(next, suggestions) => {
                          flushSync(() => {
                            setOpen(null);
                            setDirty(false);
                            setSuggesting({ next, suggestions, lineId: id, problem: null });
                          });
                        }}
                        onDirty={setDirty}
                        onClose={() => closeEditor(id)}
                      />
                    ) : null
                  }
                  toolbar={segment.index === lastPicked ? toolbar : null}
                />
              );
            })}
          </ol>
        )}
      </div>
      {editing && suggesting ? (
        <SuggestionsDialog
          suggestions={suggesting.suggestions}
          lines={byIndex}
          multiFile={multiFile}
          saving={editing.saving}
          problem={suggesting.problem}
          onConfirm={(chosen) => void saveSuggested(chosen)}
          onSkip={() => void saveSuggested([])}
        />
      ) : null}
    </div>
  );
}
