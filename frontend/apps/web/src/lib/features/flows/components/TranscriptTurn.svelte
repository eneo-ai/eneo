<script lang="ts">
  import PencilLine from "lucide-svelte/icons/pencil-line";
  import Undo2 from "lucide-svelte/icons/undo-2";
  import { untrack } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { formatClock } from "$lib/features/flows/transcriptSegments";
  import {
    turnEditableText,
    type PartWord,
    type TranscriptTurn,
    type TurnPart
  } from "$lib/features/flows/transcriptTurns";
  import TranscriptSpeakerBadge, { type SpeakerOption } from "./TranscriptSpeakerBadge.svelte";

  let {
    turn,
    activeSegmentIndex = -1,
    activeWordIndex = -1,
    withHours = false,
    editable = false,
    busy = false,
    editing = false,
    displayName,
    speakerClass,
    speakerOptions = [],
    newSpeakerLabel,
    correctedFrom,
    onSeek,
    onStartEdit,
    onCancelEdit,
    onCommitEdit,
    onRevertTurn,
    onReassignTurn,
    onResetTurn
  }: {
    turn: TranscriptTurn;
    /** Segment currently spoken; highlights the matching part. */
    activeSegmentIndex?: number;
    /** Word of that segment currently spoken, when it has stored words. */
    activeWordIndex?: number;
    withHours?: boolean;
    /** False renders a clean read-only turn (evidence marks only). */
    editable?: boolean;
    busy?: boolean;
    /** True while this turn's text is being edited in place. */
    editing?: boolean;
    displayName: (label: string) => string;
    speakerClass: (label: string) => string;
    speakerOptions?: SpeakerOption[];
    newSpeakerLabel: string;
    /** Raw text before corrections for a segment, or null. */
    correctedFrom: (segmentIndex: number) => string | null;
    /** Position the playhead at a part (or a time inside it), silently. */
    onSeek: (part: TurnPart, time?: number) => void;
    onStartEdit: () => void;
    onCancelEdit: () => void;
    /**
     * Commit the whole turn's text; the caller splits it back onto segments
     * and owns closing the editor. A selection is passed along when the
     * commit came from the reassign shortcut (Alt+T).
     */
    onCommitEdit: (text: string, reassign?: { joinedStart: number; joinedEnd: number }) => void;
    /** Drop the stored text corrections of every segment in this turn. */
    onRevertTurn: () => void;
    /** Reassign the whole turn to another raw label. */
    onReassignTurn: (speaker: string) => void;
    /** Reset this turn's overridden parts to their stored speakers. */
    onResetTurn?: () => void;
  } = $props();

  const time = $derived(formatClock(turn.start, withHours));
  const active = $derived(turn.parts.some((part) => part.segmentIndex === activeSegmentIndex));
  const overridden = $derived(turn.parts.some((part) => part.overridden));
  const hasCorrections = $derived(
    turn.parts.some((part) => correctedFrom(part.segmentIndex) !== null)
  );
  const speakerEditable = $derived(editable && !editing && !busy && speakerOptions.length > 0);

  // Joins adjacent parts visually; lives outside the anchored run spans so
  // selection offsets stay exact.
  const PART_SEPARATOR = " ";

  type Piece = { text: string; corrected: boolean; word: PartWord | null };

  /**
   * The part's text cut at every corrected-range and word boundary, so each
   * piece is either plain, a corrected span, or one timed word. Words never
   * overlap corrections (see `computeTurns`), so a piece is at most one.
   */
  function pieces(part: TurnPart): Piece[] {
    const words = part.words ?? [];
    if (part.correctedRanges.length === 0 && words.length === 0) {
      return [{ text: part.text, corrected: false, word: null }];
    }
    const cuts = [0, part.text.length];
    for (const range of part.correctedRanges) cuts.push(range.start, range.end);
    for (const word of words) cuts.push(word.displayStart, word.displayEnd);
    const bounds = cuts
      .filter((cut, index) => cut >= 0 && cut <= part.text.length && cuts.indexOf(cut) === index)
      .sort((a, b) => a - b);
    const result: Piece[] = [];
    for (let index = 1; index < bounds.length; index += 1) {
      const from = bounds[index - 1];
      const to = bounds[index];
      if (from >= to) continue;
      result.push({
        text: part.text.slice(from, to),
        corrected: part.correctedRanges.some((range) => range.start <= from && to <= range.end),
        word: words.find((word) => word.displayStart <= from && to <= word.displayEnd) ?? null
      });
    }
    return result;
  }

  function isActiveWord(part: TurnPart, piece: Piece): boolean {
    return (
      piece.word !== null &&
      part.segmentIndex === activeSegmentIndex &&
      piece.word.wordIndex === activeWordIndex
    );
  }

  /** A part with stored words highlights the word, not the whole line. */
  function partActive(part: TurnPart): boolean {
    if (part.segmentIndex !== activeSegmentIndex) return false;
    return !(part.words && part.words.length > 0 && activeWordIndex >= 0);
  }

  function onPartClick(part: TurnPart, event: MouseEvent) {
    const selection = window.getSelection();
    if (selection && !selection.isCollapsed) return;
    if (editing) return;
    const wordEl = (event.target as HTMLElement | null)?.closest?.("[data-word-start]");
    const time = wordEl ? Number((wordEl as HTMLElement).dataset.wordStart) : Number.NaN;
    onSeek(part, Number.isFinite(time) ? time : undefined);
  }

  // ---- In-place turn editing --------------------------------------------
  // The editor is uncontrolled: seeded once on mount, read on commit. A
  // binding would rewrite the text node under the caret on upstream changes.
  let editorEl: HTMLElement | null = null;
  let plaintextSupported = true;
  let cancelling = false;
  let seededText = "";

  function editorText(): string {
    return (editorEl?.textContent ?? "").replace(/[\r\n]+/g, " ");
  }

  function editor(node: HTMLElement) {
    editorEl = node;
    node.setAttribute("contenteditable", "plaintext-only");
    plaintextSupported = node.contentEditable === "plaintext-only";
    if (!plaintextSupported) node.setAttribute("contenteditable", "true");
    untrack(() => {
      seededText = turnEditableText(turn);
      node.textContent = seededText;
    });
    node.focus();
    const selection = window.getSelection();
    if (selection) {
      const range = document.createRange();
      range.selectNodeContents(node);
      range.collapse(false);
      selection.removeAllRanges();
      selection.addRange(range);
    }
    return () => {
      editorEl = null;
    };
  }

  function editorSelectionOffsets(): { joinedStart: number; joinedEnd: number } | null {
    const selection = window.getSelection();
    if (!editorEl || !selection || selection.rangeCount === 0) return null;
    const range = selection.getRangeAt(0);
    if (!editorEl.contains(range.startContainer) || !editorEl.contains(range.endContainer)) {
      return null;
    }
    const prefix = document.createRange();
    prefix.selectNodeContents(editorEl);
    prefix.setEnd(range.startContainer, range.startOffset);
    const joinedStart = prefix.toString().length;
    const joinedEnd = joinedStart + range.toString().length;
    return joinedStart < joinedEnd ? { joinedStart, joinedEnd } : null;
  }

  function cancelEditing() {
    cancelling = true;
    onCancelEdit();
  }

  function onEditorKeydown(event: KeyboardEvent) {
    if (event.isComposing || event.keyCode === 229) return;
    if (event.key === "Escape") {
      event.preventDefault();
      cancelEditing();
      return;
    }
    if (event.altKey && (event.key === "t" || event.key === "T")) {
      const offsets = editorSelectionOffsets();
      if (offsets) {
        event.preventDefault();
        cancelling = true; // the commit below owns closing; ignore the blur
        onCommitEdit(editorText(), offsets);
      }
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      onCommitEdit(editorText());
    }
  }

  function onEditorBlur() {
    if (cancelling) {
      cancelling = false;
      return;
    }
    const text = editorText();
    // A stray click elsewhere only saves when something actually changed.
    if (text === seededText) {
      onCancelEdit();
      return;
    }
    onCommitEdit(text);
  }

  function onEditorPaste(event: ClipboardEvent) {
    if (plaintextSupported) return;
    event.preventDefault();
    const text = event.clipboardData?.getData("text/plain").replace(/[\r\n]+/g, " ") ?? "";
    document.execCommand("insertText", false, text);
  }

  function onEditorBeforeInput(event: InputEvent) {
    if (plaintextSupported) return;
    if (
      event.inputType === "insertParagraph" ||
      event.inputType === "insertLineBreak" ||
      event.inputType.startsWith("format")
    ) {
      event.preventDefault();
    }
  }
</script>

<div
  class="group grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 rounded-md px-2 py-1.5 sm:grid-cols-[7rem_minmax(0,1fr)]"
  data-turn-index={turn.index}
>
  <div class="flex flex-col items-start gap-0.5 pt-0.5">
    {#if turn.speaker}
      <TranscriptSpeakerBadge
        display={displayName(turn.speaker)}
        colorClass={speakerClass(turn.speaker)}
        editable={speakerEditable}
        {overridden}
        changedFrom={null}
        menuLabel={m.flow_run_transcript_change_speaker_for_turn({ time })}
        options={speakerOptions}
        {newSpeakerLabel}
        disabled={busy}
        onSelect={onReassignTurn}
        onReset={overridden ? onResetTurn : undefined}
      />
    {/if}
    <button
      type="button"
      class="hover:text-secondary focus-visible:ring-accent-default rounded px-0.5 text-xs tabular-nums transition-colors focus-visible:ring-2 focus-visible:outline-none {active
        ? 'text-accent-stronger font-semibold'
        : 'text-muted'}"
      aria-label={m.flow_run_transcript_seek_to({ time })}
      title={m.flow_run_transcript_seek_to({ time })}
      onclick={() => onSeek(turn.parts[0])}
    >
      {time}
    </button>
    {#if editable && !editing}
      <div
        class="flex items-center gap-0.5 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100"
      >
        {#if hasCorrections}
          <button
            type="button"
            class="text-muted hover:bg-hover-default hover:text-secondary focus-visible:ring-accent-default rounded-md p-1 transition-colors focus-visible:ring-2 focus-visible:outline-none disabled:opacity-50"
            aria-label={m.flow_run_transcript_revert_turn({ time })}
            disabled={busy}
            onclick={onRevertTurn}
          >
            <Undo2 class="size-3.5" />
          </button>
        {/if}
        <button
          type="button"
          class="text-muted hover:bg-hover-default hover:text-secondary focus-visible:ring-accent-default rounded-md p-1 transition-colors focus-visible:ring-2 focus-visible:outline-none disabled:opacity-50"
          aria-label={m.flow_run_transcript_edit_turn({ time })}
          disabled={busy}
          onclick={onStartEdit}
        >
          <PencilLine class="size-3.5" />
        </button>
      </div>
    {/if}
  </div>

  {#if editing}
    <div class="min-w-0">
      <span
        role="textbox"
        aria-multiline="false"
        aria-label={m.flow_run_transcript_edit_turn({ time })}
        tabindex="0"
        spellcheck="false"
        class="border-default bg-primary focus-visible:ring-accent-default block w-full rounded-md border px-2 py-1.5 text-sm leading-relaxed whitespace-pre-wrap focus-visible:ring-2 focus-visible:outline-none"
        {@attach editor}
        onkeydown={onEditorKeydown}
        onblur={onEditorBlur}
        onpaste={onEditorPaste}
        onbeforeinput={onEditorBeforeInput}
      ></span>
      <div class="mt-1 flex items-center justify-between gap-2">
        <p class="text-muted text-xs">{m.flow_run_transcript_edit_reassign_hint()}</p>
        <div class="flex shrink-0 gap-2">
          <button
            type="button"
            class="text-secondary hover:bg-hover-dimmer rounded-md px-2 py-1 text-xs disabled:opacity-50"
            disabled={busy}
            onpointerdown={(event) => event.preventDefault()}
            onclick={cancelEditing}
          >
            {m.cancel()}
          </button>
          <button
            type="button"
            class="bg-accent-default text-on-fill hover:bg-accent-stronger rounded-md px-2 py-1 text-xs disabled:opacity-50"
            disabled={busy}
            onpointerdown={(event) => event.preventDefault()}
            onclick={() => onCommitEdit(editorText())}
          >
            {busy ? m.saving() : m.save()}
          </button>
        </div>
      </div>
    </div>
  {:else}
    <!-- Click-to-position is a pointer convenience; the timestamp button in
         the gutter is the accessible control for the same action. -->
    <!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
    <p class="min-w-0 text-sm leading-relaxed">
      {#each turn.parts as part, index (part.segmentIndex + ":" + part.rawStart)}
        <span
          data-run-text
          data-segment-index={part.segmentIndex}
          data-display-start={part.displayStart}
          class="rounded-sm transition-colors {partActive(part) ? 'bg-accent-dimmer' : ''}"
          title={correctedFrom(part.segmentIndex) !== null
            ? m.flow_run_transcript_corrected_from({
                original: correctedFrom(part.segmentIndex) ?? ""
              })
            : undefined}
          onclick={(event) => onPartClick(part, event)}
          >{#each pieces(part) as piece, pieceIndex (pieceIndex)}{#if piece.corrected}<span
                class="decoration-accent-default underline decoration-dotted underline-offset-2"
                >{piece.text}</span
              >{:else if piece.word}<span
                data-word-start={piece.word.start}
                class="rounded-sm {isActiveWord(part, piece) ? 'bg-accent-dimmer' : ''} {piece.word
                  .uncertain
                  ? 'decoration-warning-default underline decoration-wavy underline-offset-2'
                  : ''}"
                title={piece.word.uncertain ? m.flow_run_transcript_word_uncertain() : undefined}
                >{piece.text}</span
              >{:else}{piece.text}{/if}{/each}</span
        >{#if index < turn.parts.length - 1}{PART_SEPARATOR}{/if}
      {/each}
    </p>
  {/if}
</div>
