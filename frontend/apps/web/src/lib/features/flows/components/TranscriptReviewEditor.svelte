<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import * as m from "$lib/paraglide/messages";
  const SPACE = " ";
  import { tick } from "svelte";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import type { TranscriptSegment, TranscriptFileReview } from "../transcriptSegments";
  import { formatClock, speakerColorIndex } from "../transcriptSegments";
  import {
    reviewSelectionText,
    reviewFragments,
    reviewParagraphs,
    wholePassage,
    selectionBounds,
    anchorSelection,
    assignSelection,
    pendingSuggestions,
    confirmSuggestions,
    sharedSuggestion,
    replaceReviewText,
    highlightedReviewWords,
    type ReviewDraft,
    type ReviewFragment,
    type ReviewSelection,
    type DisplayRange
  } from "../transcriptReviewEditor";

  let {
    segments,
    speakerReviews = [],
    draft,
    editable = false,
    audioAvailable,
    currentFile,
    currentTime,
    playing,
    displayName,
    speakerOptions,
    onChange,
    onSeek,
    onInteract
  }: {
    segments: readonly TranscriptSegment[];
    speakerReviews?: TranscriptFileReview[];
    draft: ReviewDraft;
    editable?: boolean;
    audioAvailable: boolean;
    currentFile: number;
    currentTime: number;
    playing: boolean;
    displayName: (speaker: string) => string;
    speakerOptions: readonly string[];
    onChange?: (draft: ReviewDraft) => Promise<boolean>;
    onSeek: (file: number, time: number, autoplay: boolean, end?: number) => void;
    onInteract: () => void;
  } = $props();

  let body = $state<HTMLDivElement>();
  let tools = $state<HTMLDivElement>();
  let selection = $state<ReviewSelection[]>([]);
  let undo = $state<ReviewDraft | null>(null);
  let error = $state("");
  let notice = $state("");
  let details = $state(false);
  let editing = $state(false);
  let wordless = $state<{ fileIndex: number; start: number; end: number } | null>(null);
  let textDraft = $state("");
  const shown = $derived(reviewFragments(segments, draft));
  const paragraphs = $derived(reviewParagraphs(shown));
  const pending = $derived(shown.filter((f) => f.pending && f.text.trim()));
  const wordlessIntervals = $derived(
    speakerReviews.flatMap((file) =>
      file.overlaps
        .filter(
          (o) =>
            !segments.some(
              (s) =>
                s.fileIndex === file.fileIndex &&
                s.text.trim() &&
                s.start < o.end &&
                s.end > o.start
            )
        )
        .map((o) => ({ ...o, fileIndex: file.fileIndex }))
    )
  );
  const suggestions = $derived(pendingSuggestions(shown));
  const selectedSuggestions = $derived(pendingSuggestions(shown, selection));
  const selected = $derived(shown.filter((f) => selectionBounds(selection, f, draft).length));
  const suggestion = $derived(sharedSuggestion(selected));
  const confirmed = $derived(
    suggestion && selected.filter((f) => f.text.trim()).every((f) => f.decision === "confirmed")
  );
  const selectedText = $derived(reviewSelectionText(shown, selection, draft));
  const activeWords = $derived(highlightedReviewWords(shown, currentFile, currentTime));
  const colors = [
    "accent-stronger",
    "positive-stronger",
    "warning-stronger",
    "negative-stronger",
    "label-stronger",
    "dynamic-stronger",
    "accent-stronger",
    "positive-stronger"
  ];
  const action =
    "min-h-9 rounded-md px-2.5 py-1.5 text-xs font-medium hover:bg-hover-default focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50";
  const name = (speaker: string | null) => {
    if (!speaker) return m.flow_transcript_editor_unknown();
    const display = displayName(speaker);
    return display === speaker && /^SPEAKER_\d+$/.test(speaker)
      ? m.flow_transcript_editor_speaker({ number: Number(speaker.slice(8)) + 1 })
      : display;
  };
  const color = (speaker: string | null) =>
    speaker
      ? "var(--" + colors[speakerColorIndex(speaker) % colors.length] + ")"
      : "var(--warning-stronger)";
  function label(f: ReviewFragment) {
    return f.decision === "unresolved"
      ? m.flow_transcript_editor_unresolved()
      : f.pending
        ? m.flow_transcript_editor_suggestion({ name: name(f.source.speaker) })
        : name(f.speaker);
  }
  function choose(next: ReviewSelection[], scroll = false) {
    selection = next;
    wordless = null;
    editing = false;
    error = "";
    notice = "";
    onInteract();
    if (scroll)
      void tick().then(() => {
        const fragment = shown.find((f) => selectionBounds(next, f, draft).length);
        body
          ?.querySelector('[data-text-span="' + fragment?.index + '"]')
          ?.scrollIntoView({ block: "center", behavior: "instant" });
      });
  }
  function ranges(range: AbstractRange, exact = false): DisplayRange[] {
    if (!body?.contains(range.startContainer) || !body.contains(range.endContainer)) return [];
    const result: DisplayRange[] = [];
    const native = document.createRange();
    native.setStart(range.startContainer, range.startOffset);
    native.setEnd(range.endContainer, range.endOffset);
    for (const el of body.querySelectorAll<HTMLElement>("[data-text-span]")) {
      if (!native.intersectsNode(el)) continue;
      const offset = (node: Node, at: number, fallback: number) => {
        if (!el.contains(node)) return fallback;
        const prefix = document.createRange();
        prefix.selectNodeContents(el);
        prefix.setEnd(node, at);
        return prefix.toString().length;
      };
      const start = offset(range.startContainer, range.startOffset, 0);
      const end = offset(range.endContainer, range.endOffset, el.textContent?.length ?? 0);
      if (end > start || (exact && el.contains(range.startContainer)))
        result.push({ index: Number(el.dataset.textSpan), start, end });
    }
    return result;
  }
  function captureSelection() {
    const native = window.getSelection();
    if (!native?.rangeCount || native.isCollapsed || editing) return;
    const next = anchorSelection(ranges(native.getRangeAt(0)), shown, draft);
    if (next.length && JSON.stringify(next) !== JSON.stringify(selection)) choose(next);
  }
  function watchSelection() {
    document.addEventListener("selectionchange", captureSelection);
    return () => document.removeEventListener("selectionchange", captureSelection);
  }
  function validate(next: ReviewDraft) {
    for (const o of next.occurrences) {
      if (
        next.speakerEdits.some(
          (e) =>
            e.segment_index === o.segment_index &&
            [e.char_start, e.char_end].some((b) => b !== null && o.char_start < b && b < o.char_end)
        )
      )
        throw new Error(m.flow_transcript_editor_crosses_decision());
    }
  }
  function publish(next: ReviewDraft, message: string) {
    const focused = document.activeElement as HTMLElement | null;
    validate(next);
    undo = {
      occurrences: draft.occurrences.map((o) => ({ ...o })),
      speakerEdits: draft.speakerEdits.map((e) => ({ ...e }))
    };
    void onChange?.(next);
    notice = message;
    error = "";
    editing = false;
    if (focused && tools?.contains(focused))
      void tick().then(() => {
        if (!focused.isConnected || focused.matches(":disabled"))
          tools?.querySelector<HTMLButtonElement>("[data-undo]")?.focus();
      });
  }
  async function restoreCaret(caret: { segmentIndex: number; offset: number }) {
    await tick();
    if (!body) return;
    for (const el of body.querySelectorAll<HTMLElement>("[data-text-span]")) {
      const f = shown[Number(el.dataset.textSpan)];
      if (
        f.source.index !== caret.segmentIndex ||
        caret.offset < f.displayStart ||
        caret.offset > f.displayStart + f.text.length
      )
        continue;
      let remaining = caret.offset - f.displayStart;
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      let node = walker.nextNode();
      while (node && remaining > (node.textContent?.length ?? 0)) {
        remaining -= node.textContent?.length ?? 0;
        node = walker.nextNode();
      }
      const range = document.createRange();
      range.setStart(node ?? el, node ? remaining : 0);
      range.collapse(true);
      body.focus({ preventScroll: true });
      window.getSelection()?.removeAllRanges();
      window.getSelection()?.addRange(range);
      return;
    }
  }
  function typeText(text: string, target?: AbstractRange, deletion?: string) {
    if (!editable || !onChange) return;
    const native = window.getSelection();
    const range = target ?? (native?.rangeCount ? native.getRangeAt(0) : undefined);
    if (!range) return;
    try {
      const selectedRanges = ranges(range, true);
      // Browser target ranges normally include the complete deletion unit.
      if (
        deletion &&
        selectedRanges.length === 1 &&
        selectedRanges[0].start === selectedRanges[0].end
      ) {
        const r = selectedRanges[0],
          f = shown[r.index];
        if (deletion.includes("Backward") && r.start > 0)
          r.start -= Array.from(f.text.slice(0, r.start)).at(-1)!.length;
        else if (deletion.includes("Forward") && r.end < f.text.length)
          r.end += Array.from(f.text.slice(r.end))[0].length;
      }
      const result = replaceReviewText(draft, shown, selectedRanges, text);
      publish(result.draft, m.flow_transcript_editor_text_corrected());
      selection = [];
      onInteract();
      void restoreCaret(result.caret);
    } catch (e) {
      error = e instanceof Error ? e.message : m.flow_transcript_editor_text_failed();
    }
  }
  function beforeInput(event: InputEvent) {
    event.preventDefault();
    if (!editable) return;
    const range = event.getTargetRanges?.()[0];
    if (["insertText", "insertReplacementText"].includes(event.inputType))
      typeText(event.data ?? "", range);
    else if (event.inputType.startsWith("delete")) typeText("", range, event.inputType);
    else if (["insertParagraph", "insertLineBreak"].includes(event.inputType))
      typeText("\n", range);
  }
  function assign(speaker: string | null, reset = false) {
    if (!editable || !selection.length || (!audioAvailable && speaker !== null && !reset)) return;
    try {
      publish(
        assignSelection(draft, segments, selection, speaker, reset),
        reset
          ? m.flow_transcript_editor_reset_notice()
          : speaker
            ? m.flow_transcript_editor_saving_decision()
            : m.flow_transcript_editor_unresolved_notice()
      );
    } catch (e) {
      error = (e as Error).message;
    }
  }
  function confirm(all: boolean) {
    if (!editable || !audioAvailable) return;
    try {
      publish(
        confirmSuggestions(draft, segments, all ? suggestions : selectedSuggestions),
        m.flow_transcript_editor_confirm_notice()
      );
      onInteract();
    } catch (e) {
      error = (e as Error).message;
    }
  }
  function undoLast() {
    if (!editable || !undo) return;
    const previous = undo;
    undo = null;
    void onChange?.(previous);
    notice = m.flow_transcript_editor_undo_notice();
    selection = [];
    onInteract();
  }
  function navigate(direction: number) {
    const passages = [
      ...pending.map((f) => ({
        fileIndex: f.source.fileIndex,
        start: f.source.start,
        end: f.source.end,
        fragment: f
      })),
      ...wordlessIntervals.map((o) => ({ ...o, fragment: null }))
    ].sort((a, b) => a.fileIndex - b.fileIndex || a.start - b.start);
    if (!passages.length) return;
    const first = selection[0];
    let index = passages.findIndex((p) =>
      p.fragment
        ? first &&
          p.fragment.source.index === first.segmentIndex &&
          first.start < p.fragment.rawEnd &&
          first.end > p.fragment.rawStart
        : wordless && p.fileIndex === wordless.fileIndex && p.start === wordless.start
    );
    if (index >= 0) index = (index + direction + passages.length) % passages.length;
    else if (first) {
      const source = segments.find((s) => s.index === first.segmentIndex)!;
      const after = passages.findIndex(
        (p) =>
          p.fileIndex > source.fileIndex ||
          (p.fileIndex === source.fileIndex &&
            (p.start > source.start ||
              (p.fragment &&
                p.fragment.source.index === first.segmentIndex &&
                p.fragment.rawStart >= first.end)))
      );
      index =
        direction > 0 ? (after < 0 ? 0 : after) : after <= 0 ? passages.length - 1 : after - 1;
    } else index = direction > 0 ? 0 : passages.length - 1;
    const passage = passages[index];
    if (passage.fragment) choose(wholePassage(passage.fragment), true);
    else {
      selection = [];
      wordless = passage;
      details = true;
      onInteract();
    }
  }
  function replay() {
    const first = selected[0],
      last = selected.at(-1);
    if (!first || !audioAvailable) return;
    const firstBounds = selectionBounds(selection, first, draft)[0];
    const firstWord = first.words.find((w) => w.charEnd > firstBounds.start);
    const lastBounds = last ? selectionBounds(selection, last, draft).at(-1) : undefined;
    const lastWord = lastBounds
      ? last?.words.findLast((w) => w.charStart < lastBounds.end && w.charEnd > lastBounds.start)
      : undefined;
    const end =
      last?.source.fileIndex === first.source.fileIndex
        ? (lastWord?.end ?? last.source.end)
        : first.source.end;
    onSeek(
      first.source.fileIndex,
      Math.max(0, (firstWord?.start ?? first.source.start) - 1.5),
      true,
      end + 1
    );
    onInteract();
  }
  function saveText() {
    try {
      const selectedRanges = selected.flatMap((f) =>
        selectionBounds(selection, f, draft).map((b) => ({ index: f.index, ...b }))
      );
      publish(
        replaceReviewText(draft, shown, selectedRanges, textDraft).draft,
        m.flow_transcript_editor_text_corrected()
      );
      selection = [];
    } catch (e) {
      error = (e as Error).message;
    }
  }
  function pieces(f: ReviewFragment) {
    const bounds = selectionBounds(selection, f, draft);
    const cuts = [
      ...new Set([
        0,
        f.text.length,
        ...bounds.flatMap((b) => [b.start, b.end]),
        ...f.words.flatMap((w) => [w.charStart, w.charEnd])
      ])
    ].sort((a, b) => a - b);
    return cuts.slice(0, -1).map((start, i) => ({
      start,
      end: cuts[i + 1],
      selected: bounds.some((b) => b.start < cuts[i + 1] && b.end > start),
      word: f.words.find((w) => w.charStart <= start && w.charEnd >= cuts[i + 1])
    }));
  }
  function clickPassage(event: MouseEvent, f: ReviewFragment) {
    if (event.detail > 1 || !window.getSelection()?.isCollapsed) return;
    if (f.pending) {
      choose(wholePassage(f));
      return;
    }
    if (!audioAvailable) return;
    const word = (event.target as HTMLElement).closest<HTMLElement>("[data-word-start]");
    selection = [];
    onSeek(f.source.fileIndex, word ? Number(word.dataset.wordStart) : f.source.start, playing);
    onInteract();
  }
  function keyPassage(event: KeyboardEvent, f: ReviewFragment) {
    if (document.activeElement !== event.currentTarget || !["Enter", " "].includes(event.key))
      return;
    event.preventDefault();
    event.stopPropagation();
    if (f.pending) {
      choose(wholePassage(f));
      void tick().then(() =>
        tools?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus()
      );
    } else if (audioAvailable) {
      onSeek(f.source.fileIndex, f.source.start, playing);
      onInteract();
    }
  }
  function copiedText(): string {
    const native = window.getSelection();
    if (!native?.rangeCount || native.isCollapsed) return selectedText;
    let previous: number | null = null;
    return ranges(native.getRangeAt(0))
      .map((r) => {
        const f = shown[r.index],
          separator = previous !== null && previous !== f.source.index ? " " : "";
        previous = f.source.index;
        return separator + f.text.slice(r.start, r.end);
      })
      .join("");
  }
  function keydown(event: KeyboardEvent) {
    event.stopPropagation();
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
      event.preventDefault();
      if (!event.shiftKey) undoLast();
    }
    if (event.altKey && event.key.toLowerCase() === "t") {
      event.preventDefault();
      tools?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
    }
    if (event.key === "Escape") {
      selection = [];
      editing = false;
    }
  }
</script>

<div class="relative">
  <div
    bind:this={tools}
    class="border-default bg-primary sticky top-0 z-10 border-b px-4 py-3"
    role="group"
    aria-label={m.flow_transcript_editor_tools()}
  >
    <div class="flex flex-wrap items-center gap-2">
      <span class="text-muted mr-auto text-xs" aria-live="polite"
        >{m.flow_transcript_editor_pending({
          count: pending.length + wordlessIntervals.length
        })}</span
      >
      <Button
        variant="ghost"
        size="sm"
        class="min-h-9 text-xs"
        disabled={!editable || !audioAvailable || !suggestions.length}
        onclick={() => confirm(true)}
        >{m.flow_transcript_editor_confirm_all({ count: suggestions.length })}</Button
      >
      <Button
        variant="ghost"
        size="sm"
        class="min-h-9 text-xs"
        disabled={!pending.length && !wordlessIntervals.length}
        onclick={() => navigate(-1)}>{m.flow_transcript_editor_previous()}</Button
      >
      <Button
        variant="ghost"
        size="sm"
        class="min-h-9 text-xs"
        disabled={!pending.length && !wordlessIntervals.length}
        onclick={() => navigate(1)}>{m.flow_transcript_editor_next()}</Button
      >
      <Button
        variant="ghost"
        size="sm"
        class="min-h-9 text-xs"
        aria-expanded={details}
        onclick={() => (details = !details)}>{m.flow_transcript_editor_toggle_details()}</Button
      >
    </div>
    {#if selection.length}
      <div
        class="mt-2 flex flex-wrap items-center gap-1"
        role="group"
        aria-label={m.flow_transcript_editor_selected_words()}
      >
        <Button
          variant="ghost"
          size="sm"
          class="min-h-9 text-xs"
          disabled={!audioAvailable}
          onclick={replay}>{m.flow_transcript_editor_listen()}</Button
        >
        {#if suggestion}
          <Button
            variant="ghost"
            size="sm"
            class="min-h-9 text-xs"
            disabled={!editable || !audioAvailable || !!confirmed}
            onclick={() => assign(suggestion)}
            >{confirmed
              ? m.flow_transcript_editor_confirmed_name({ name: name(suggestion) })
              : m.flow_transcript_editor_confirm_name({ name: name(suggestion) })}</Button
          >
        {:else if selectedSuggestions.length}
          <Button
            variant="ghost"
            size="sm"
            class="min-h-9 text-xs"
            disabled={!editable || !audioAvailable}
            onclick={() => confirm(false)}
            >{m.flow_transcript_editor_confirm_selection({
              count: selectedSuggestions.length
            })}</Button
          >
        {/if}
        <DropdownMenu.Root>
          <DropdownMenu.Trigger class={action} disabled={!editable}>
            {m.flow_transcript_editor_assign()}
          </DropdownMenu.Trigger>
          <DropdownMenu.Content align="start" class="max-w-56">
            {#each speakerOptions as speaker (speaker)}
              <DropdownMenu.Item disabled={!audioAvailable} onclick={() => assign(speaker)}>
                {name(speaker)}
              </DropdownMenu.Item>
            {/each}
            <DropdownMenu.Item onclick={() => assign(null)}>
              {m.flow_transcript_editor_cannot_determine()}
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Root>
        <Button
          variant="ghost"
          size="sm"
          class="min-h-9 text-xs"
          disabled={!editable}
          onclick={() => {
            textDraft = selectedText;
            editing = !editing;
          }}>{m.flow_transcript_editor_correct_text()}</Button
        >
        <Button
          variant="ghost"
          size="sm"
          class="min-h-9 text-xs"
          disabled={!editable || !selected.some((f) => f.decision)}
          onclick={() => assign(null, true)}>{m.flow_transcript_editor_reset()}</Button
        >
        <Button
          variant="ghost"
          size="sm"
          class="min-h-9 text-xs"
          onclick={() => {
            selection = [];
            editing = false;
          }}>{m.flow_transcript_editor_clear()}</Button
        >
      </div>
    {/if}
    {#if editing}
      <label class="mt-2 block text-xs"
        >{m.flow_transcript_editor_correct_selection()}<Textarea
          class="mt-1 min-h-20"
          bind:value={textDraft}
        /></label
      >
      <Button
        variant="ghost"
        size="sm"
        class="min-h-9 text-xs"
        disabled={!editable}
        onclick={saveText}>{m.flow_transcript_editor_save_correction()}</Button
      >
    {/if}
    <div class="flex items-center gap-2">
      <span role="status" class="text-muted text-xs">{notice}</span>
      {#if undo}<Button
          variant="ghost"
          size="sm"
          class="min-h-9 text-xs"
          disabled={!editable}
          data-undo
          onclick={undoLast}>{m.flow_transcript_editor_undo()}</Button
        >{/if}
    </div>
    {#if error}<p role="alert" class="text-negative-stronger mt-2 text-sm">{error}</p>{/if}
  </div>
  {#if details}
    <section
      aria-label={m.flow_transcript_editor_details()}
      class="bg-hover-dimmer border-default border-b p-4 text-xs leading-relaxed"
    >
      {#if wordless}<p>
          {m.flow_transcript_editor_wordless({
            start: formatClock(wordless.start),
            end: formatClock(wordless.end),
            part: wordless.fileIndex + 1
          })}
          <button
            class="underline"
            disabled={!audioAvailable}
            onclick={() => {
              if (wordless)
                onSeek(
                  wordless.fileIndex,
                  Math.max(0, wordless.start - 1.5),
                  true,
                  wordless.end + 1
                );
            }}>{m.flow_transcript_editor_listen_interval()}</button
          >
        </p>{/if}
      {#each speakerReviews as review (review.fileIndex)}
        {#if review.detailsOmitted}<p>
            {m.flow_transcript_editor_omitted()}
          </p>{/if}
        {#if review.overlapDetection === "unavailable"}<p>
            {m.flow_transcript_editor_unavailable_part({ part: review.fileIndex + 1 })}
          </p>{/if}
        {#each review.overlaps as overlap (overlap.id)}<p>
            <button
              class="underline"
              disabled={!audioAvailable}
              onclick={() => {
                onSeek(review.fileIndex, Math.max(0, overlap.start - 1.5), true, overlap.end + 1);
                onInteract();
              }}
              >{m.flow_transcript_editor_part_interval({
                part: review.fileIndex + 1,
                start: formatClock(overlap.start),
                end: formatClock(overlap.end)
              })}</button
            >
            · {m.flow_transcript_editor_voice_count({ count: overlap.detected_speaker_count })}
          </p>{/each}
      {/each}
      <p>{m.flow_transcript_editor_scope()}</p>
      {#each selected as f (f.index)}
        <p>
          {m.flow_transcript_editor_model_suggestion({ name: name(f.source.speaker) })} · {f.decision ===
          "unresolved"
            ? m.flow_transcript_editor_reviewed_unresolved()
            : f.decision === "confirmed"
              ? m.flow_transcript_editor_confirmed()
              : m.flow_transcript_editor_not_reviewed()}
        </p>
      {/each}
      {#each [...new Set(segments.map((s) => s.fileIndex))].filter((file) => !speakerReviews.some((review) => review.fileIndex === file)) as file (file)}
        {@const sources = segments.filter((s) => s.fileIndex === file)}
        <p>
          {m.flow_transcript_editor_part({ number: file + 1 })}
          {sources.some((s) => s.reviewDetection === "unavailable")
            ? m.flow_transcript_editor_detection_unavailable()
            : sources.some((s) => s.reviewDetection === "available")
              ? m.flow_transcript_editor_detection_available()
              : m.flow_transcript_editor_detection_unknown()}
        </p>
        {#each [...new Map(sources.flatMap( (s) => (s.overlaps ?? []).map((o) => [o.id, o] as const) )).values()] as overlap (overlap.id)}
          <p>
            <button
              class="underline"
              disabled={!audioAvailable}
              onclick={() => {
                onSeek(file, Math.max(0, overlap.start - 1.5), true, overlap.end + 1);
                onInteract();
              }}>{formatClock(overlap.start)}–{formatClock(overlap.end)}</button
            >
            · {m.flow_transcript_editor_voice_count({ count: overlap.detected_speaker_count })}
          </p>
        {/each}
      {/each}
    </section>
  {/if}
  <p class="text-muted px-5 pt-4 text-xs leading-relaxed">
    {m.flow_transcript_editor_instructions({
      editingHint: editable ? m.flow_transcript_editor_typing_hint() : ""
    })}
  </p>
  <!-- A contenteditable role="textbox" is a tab stop, and killing the UA
       outline left only the caret to say where focus went, in a region tall
       enough for the caret to be off screen. Same ring the app's Textarea
       uses, inset so it does not clip against the panel. -->
  <div
    bind:this={body}
    class="focus-visible:inset-ring-ring px-5 py-5 outline-none focus:outline-none focus-visible:inset-ring-2 sm:px-7"
    contenteditable="true"
    role="textbox"
    aria-label={m.flow_transcript_editor_textbox()}
    aria-multiline="true"
    aria-readonly={!editable}
    tabindex="0"
    {@attach watchSelection}
    onbeforeinput={beforeInput}
    onkeydown={keydown}
    onmouseup={captureSelection}
    onkeyup={captureSelection}
    oncopy={(e) => {
      e.preventDefault();
      e.clipboardData?.setData("text/plain", copiedText());
    }}
    onpaste={(e) => {
      e.preventDefault();
      typeText(e.clipboardData?.getData("text/plain") ?? "");
    }}
    oncut={(e) => {
      e.preventDefault();
      e.clipboardData?.setData("text/plain", copiedText());
      typeText("");
    }}
    ondrop={(e) => e.preventDefault()}
  >
    {#each paragraphs as paragraph, paragraphIndex (paragraphIndex)}
      {@const first = paragraph.find((f) => f.text.trim())!}
      <div
        class="mb-3 grid min-w-0 grid-cols-1 gap-1 last:mb-0 sm:grid-cols-[6rem_minmax(0,1fr)] sm:gap-4"
        data-turn-index={paragraphIndex}
      >
        <div
          contenteditable="false"
          class="text-muted flex min-w-0 items-start gap-2 text-xs sm:block sm:pt-1"
        >
          <button
            class="focus-visible:ring-ring min-h-[24px] shrink-0 tabular-nums focus-visible:ring-2"
            disabled={!audioAvailable}
            onclick={() => {
              onSeek(first.source.fileIndex, first.source.start, playing);
              onInteract();
            }}>{formatClock(first.source.start)}</button
          >
          <button
            class="focus-visible:ring-ring mt-1 block min-h-[24px] max-w-full text-left text-xs [overflow-wrap:anywhere] whitespace-normal focus-visible:ring-2"
            style:color={color(first.pending ? null : first.speaker)}
            onclick={() => choose(paragraph.flatMap(wholePassage))}>{label(first)}</button
          >
        </div>
        <!-- Keep fragments adjacent so template indentation never becomes transcript text. -->
        <!-- prettier-ignore -->
        <p
          class="text-primary min-w-0 text-base leading-[1.7] [overflow-wrap:anywhere] whitespace-pre-wrap"
        >{#each paragraph as f, i (f.index)}{@const previousSpeech = paragraph.slice(0, i).findLast((fragment) => fragment.text.trim())}{#if i > 0 && paragraph[i - 1].source.index !== f.source.index}{SPACE}{/if}{#if previousSpeech && f.text.trim() && (previousSpeech.speaker !== f.speaker || (previousSpeech.decision !== f.decision && f.decision === "unresolved"))}<span
                contenteditable="false"
                class="bg-hover-dimmer mx-1 inline-block max-w-full rounded px-1.5 text-xs leading-5 [overflow-wrap:anywhere] whitespace-normal"
                style:color={color(f.speaker)}>{label(f)}</span
              >{/if}<span
              data-text-span={f.index}
              data-segment-index={f.source.index}
              role="button"
              tabindex="0"
              aria-label={f.pending
                ? m.flow_transcript_editor_select_passage({
                    text: f.text.trim(),
                    speaker: label(f)
                  })
                : m.flow_transcript_editor_seek_passage({ text: f.text.trim(), speaker: label(f) })}
              onclick={(e) => clickPassage(e, f)}
              onkeydown={(e) => keyPassage(e, f)}
              class="focus-visible:outline-ring py-1 underline decoration-[1.5px] underline-offset-[6px] focus-visible:rounded focus-visible:outline-2 {f.pending
                ? 'cursor-pointer decoration-dotted'
                : 'decoration-solid'}"
              style:text-decoration-color={color(
                f.pending || f.decision === "unresolved" ? null : f.speaker
              )}
            >{#each pieces(f) as piece (piece.start)}{#if f.text.slice(piece.start, piece.end).trim()}<span
                  data-word-start={piece.word?.start}
                  aria-current={piece.word && activeWords.has(piece.word) ? "true" : undefined}
                  class="rounded-sm {piece.word && activeWords.has(piece.word)
                    ? 'bg-accent-default text-on-fill'
                    : piece.selected
                      ? 'bg-accent-dimmer ring-accent-default/40 ring-1'
                      : !f.words.length &&
                          f.source.fileIndex === currentFile &&
                          f.source.start <= currentTime &&
                          currentTime < f.source.end
                        ? 'bg-hover-dimmer'
                        : piece.word?.uncertain
                          ? 'bg-warning-dimmer'
                          : ''}">{f.text.slice(piece.start, piece.end)}</span
                >{:else}{f.text.slice(piece.start, piece.end)}{/if}{/each}</span>{/each}</p>
      </div>
    {/each}
  </div>
</div>
