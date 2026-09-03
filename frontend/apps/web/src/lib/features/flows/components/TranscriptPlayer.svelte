<script lang="ts">
  import { IconPlay } from "@eneo/icons/play";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { untrack } from "svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    countFiles,
    countUncertainWords,
    findActiveSegmentIndex,
    findActiveWordIndex,
    formatClock,
    speakerColorIndex,
    type TranscriptSegment
  } from "$lib/features/flows/transcriptSegments";
  import {
    applyTextCorrections,
    type CorrectionOccurrence
  } from "$lib/features/flows/transcriptCorrections";
  import {
    computeSegmentDetails,
    nextSpeakerLabel,
    speakerLabels,
    type SpeakerEdit,
    type SpeakerSpanInput
  } from "$lib/features/flows/transcriptRuns";
  import {
    computeTurns,
    splitTurnEdit,
    turnSelectionToDisplaySpans,
    type TranscriptTurn,
    type TurnPart
  } from "$lib/features/flows/transcriptTurns";
  import {
    selectionToSpans,
    type SegmentGeometry,
    type SelectionSpan
  } from "$lib/features/flows/transcriptSelection";
  import TranscriptTurnBlock from "./TranscriptTurn.svelte";
  import TranscriptSpeakerToolbar from "./TranscriptSpeakerToolbar.svelte";

  export type SignedAudio = { url: string; expires_at: number };

  let {
    segments,
    fileCount = 1,
    getAudioUrl,
    speakerNames = {},
    textFallback = "",
    audioPending = false,
    editable = false,
    corrections = [],
    speakerEdits = [],
    busy = false,
    onSaveLine,
    onRevertLine,
    onSaveSpeakerEdits,
    class: className = ""
  }: {
    /** Transcript lines in time; empty when the transcript has no timestamps. */
    segments: readonly TranscriptSegment[];
    /** Audio files behind the transcript, in `fileIndex` order. */
    fileCount?: number;
    /** Signs a playable URL for one file; rejects when the audio is unavailable. */
    getAudioUrl: (fileIndex: number) => Promise<SignedAudio>;
    /** Speaker label to name, applied on top of the segments' own labels. */
    speakerNames?: Readonly<Record<string, string | null | undefined>>;
    /** Shown verbatim when there are no segments to render. */
    textFallback?: string;
    /** True while the caller is still finding out which audio files exist. */
    audioPending?: boolean;
    /** Offers editing; false renders a clean read-only conversation. */
    editable?: boolean;
    /** Stored corrections, applied as an overlay on the raw segment text. */
    corrections?: readonly CorrectionOccurrence[];
    /** Stored speaker reassignments, applied as an overlay on the raw labels. */
    speakerEdits?: readonly SpeakerEdit[];
    /** Disables edit controls while the caller is saving. */
    busy?: boolean;
    /** Commits one segment's edited display text; resolve true on success. */
    onSaveLine?: (
      segmentIndex: number,
      editedText: string,
      options?: { suggest?: boolean }
    ) => Promise<boolean>;
    /** Drops the stored text corrections of one segment. */
    onRevertLine?: (segmentIndex: number) => Promise<void> | void;
    /** Reassigns raw-space spans (null span = whole segment) to a speaker. */
    onSaveSpeakerEdits?: (edits: SpeakerSpanInput[]) => Promise<boolean>;
    class?: string;
  } = $props();

  const SKIP_ARROW_SECONDS = 5;
  const SKIP_JKL_SECONDS = 10;
  const REFRESH_LEAD_MS = 60_000;
  // Signed URLs live at most an hour; a longer expiry is refreshed daily so
  // the timer stays inside what setTimeout can schedule.
  const REFRESH_MAX_DELAY_MS = 24 * 60 * 60 * 1000;
  const RATES = [1, 1.25, 1.5, 2];

  let audioEl = $state<HTMLAudioElement | null>(null);
  let listEl = $state<HTMLDivElement | null>(null);
  let src = $state<string | null>(null);
  let expiresAt = $state<number | null>(null);
  let currentFile = $state(0);
  let currentTime = $state(0);
  let duration = $state(0);
  let paused = $state(true);
  let playbackRate = $state(1);
  let follow = $state(true);
  let activeIndex = $state(-1);
  // Word within the active segment, when that segment has stored words.
  let activeWordIndex = $state(-1);
  let loadingAudio = $state(false);
  let audioUnavailable = $state(false);

  // Applied once the next source has its metadata, so a seek into a file that
  // is not loaded yet lands where the reviewer clicked.
  let pendingSeek: number | null = null;
  let pendingAutoplay = false;
  // Scrolls this component starts must not switch "follow" off.
  let programmaticScrollUntil = 0;
  // Only the newest load may touch the element; an older signing that
  // resolves late would otherwise swap the source under a playing track.
  let loadGeneration = 0;

  // Corrections rewrite text, speaker edits rewrite attribution, and speaker
  // names rewrite labels at render time; the overlays are orthogonal and
  // compose. The raw `segments` prop is never mutated. The display unit is
  // the speaker TURN; the segment stays the storage anchor underneath.
  const applied = $derived(applyTextCorrections(segments, corrections));
  const shown = $derived(applied.segments);
  const correctedFrom = $derived(applied.correctedFrom);
  const lineDetails = $derived(computeSegmentDetails(segments, corrections, speakerEdits));
  const turns = $derived(computeTurns(segments, corrections, speakerEdits, lineDetails));
  const totalFiles = $derived(Math.max(fileCount, countFiles(segments)));
  const hasSegments = $derived(shown.length > 0);
  const withHours = $derived(duration >= 3600 || shown.some((segment) => segment.end >= 3600));
  const seekable = $derived(!audioUnavailable && hasSegments);
  // Words the aligner could not place: the reviewer's cue to listen there.
  const uncertainWords = $derived(countUncertainWords(segments));

  const speakerEditingEnabled = $derived(editable && onSaveSpeakerEdits !== undefined);
  const labels = $derived(speakerLabels(segments, speakerEdits));
  const newLabel = $derived(nextSpeakerLabel(labels));

  function displayName(label: string): string {
    const name = speakerNames[label];
    return typeof name === "string" && name.trim() ? name.trim() : label;
  }

  const speakerOptions = $derived(
    labels.map((label) => ({
      label,
      display: displayName(label),
      colorClass: speakerClass(label)
    }))
  );

  async function loadAudio(fileIndex: number, seekTo: number | null = null, autoplay = false) {
    const generation = ++loadGeneration;
    loadingAudio = true;
    audioUnavailable = false;
    try {
      const signed = await getAudioUrl(fileIndex);
      if (generation !== loadGeneration) return;
      pendingSeek = seekTo;
      pendingAutoplay = autoplay;
      currentFile = fileIndex;
      expiresAt = signed.expires_at;
      src = signed.url;
    } catch (error) {
      if (generation !== loadGeneration) return;
      console.error("Failed to load transcript audio", error);
      audioUnavailable = true;
    } finally {
      if (generation === loadGeneration) loadingAudio = false;
    }
  }

  // A play() that was interrupted by a source swap or a pause is not a broken
  // recording; only a refusal to play the media is.
  function markPlayFailure(error: unknown) {
    if ((error as { name?: string } | null)?.name !== "AbortError") audioUnavailable = true;
  }

  function onLoadedMetadata() {
    if (!audioEl) return;
    if (pendingSeek !== null) {
      audioEl.currentTime = pendingSeek;
      pendingSeek = null;
    }
    if (pendingAutoplay) {
      pendingAutoplay = false;
      void audioEl.play().catch(() => {
        // Autoplay can be refused until the reviewer interacts; the controls still work.
      });
    }
  }

  function onTimeUpdate() {
    if (!audioEl) return;
    const time = audioEl.currentTime;
    const previous = activeIndex;
    activeIndex = findActiveSegmentIndex(shown, currentFile, time, activeIndex);
    const words = segments[activeIndex]?.words;
    activeWordIndex = words
      ? findActiveWordIndex(words, time, previous === activeIndex ? activeWordIndex : -1)
      : -1;
  }

  function togglePlay() {
    if (!audioEl || audioUnavailable) return;
    if (audioEl.paused) {
      void audioEl.play().catch(markPlayFailure);
    } else {
      audioEl.pause();
    }
  }

  function seekToTime(time: number) {
    if (!audioEl) return;
    const bounded = Math.min(Math.max(0, time), Number.isFinite(duration) ? duration : time);
    audioEl.currentTime = bounded;
    activeIndex = findActiveSegmentIndex(shown, currentFile, bounded);
    activeWordIndex = -1;
  }

  function seekBy(delta: number) {
    if (!audioEl) return;
    seekToTime(audioEl.currentTime + delta);
  }

  /**
   * Positions the playhead silently; playback stays under the transport.
   * `time` targets a stored word inside the part; otherwise the part's start.
   */
  function seekToPart(part: TurnPart, time?: number) {
    if (!seekable) return;
    const target = time ?? part.start;
    activeIndex = part.segmentIndex;
    activeWordIndex = -1;
    if (part.fileIndex !== currentFile || !audioEl) {
      void loadAudio(part.fileIndex, target, false);
      return;
    }
    audioEl.currentTime = target;
  }

  // ---- Turn editing -----------------------------------------------------
  let editingTurnIndex = $state(-1);
  let followBeforeEdit = false;

  function startEditTurn(turn: TranscriptTurn) {
    editingTurnIndex = turn.index;
    toolbar = null;
    // The list must not scroll away under an open editor while audio plays;
    // follow is restored when the editor closes.
    followBeforeEdit = follow;
    follow = false;
  }

  function closeEditor() {
    editingTurnIndex = -1;
    follow = followBeforeEdit;
  }

  function displaySpanToRaw(
    geometry: SegmentGeometry,
    displayStart: number,
    displayEnd: number
  ): { charStart: number; charEnd: number } | null {
    let charStart = geometry.displayToRaw(displayStart, "start");
    let charEnd = geometry.displayToRaw(displayEnd, "end");
    const raw = geometry.rawText;
    while (charStart < charEnd && /\s/.test(raw[charStart])) charStart += 1;
    while (charEnd > charStart && /\s/.test(raw[charEnd - 1])) charEnd -= 1;
    return charStart < charEnd ? { charStart, charEnd } : null;
  }

  async function commitTurnEdit(
    turn: TranscriptTurn,
    text: string,
    reassign?: { joinedStart: number; joinedEnd: number }
  ) {
    if (!onSaveLine) return;
    const edits = splitTurnEdit(turn, text, (index) => shown[index]?.text ?? "");
    let accepted = true;
    for (const edit of edits) {
      accepted = await onSaveLine(edit.segmentIndex, edit.newSegmentText, {
        // The dialog would interleave with sequential saves or a pending
        // reassignment; offer suggestions only for a plain single-part edit.
        suggest: edits.length === 1 && !reassign
      });
      if (!accepted) break;
    }
    if (!accepted) return; // the editor stays open with the draft
    closeEditor();
    if (!reassign || !onSaveSpeakerEdits) return;
    // The derived turns now include the committed text, so the editor's
    // offsets address the successor turn one-to-one.
    const anchor = turn.parts[0];
    const successor = turns.find(
      (candidate) =>
        candidate.parts[0]?.segmentIndex === anchor.segmentIndex &&
        candidate.parts[0]?.rawStart === anchor.rawStart
    );
    if (!successor) return;
    const spans: SelectionSpan[] = [];
    for (const span of turnSelectionToDisplaySpans(
      successor,
      reassign.joinedStart,
      reassign.joinedEnd
    )) {
      const geometry = lineDetails.get(span.segmentIndex)?.geometry;
      if (!geometry) continue;
      const raw = displaySpanToRaw(geometry, span.displayStart, span.displayEnd);
      if (raw) spans.push({ segmentIndex: span.segmentIndex, ...raw });
    }
    if (spans.length === 0) return;
    const block = listEl?.querySelector<HTMLElement>(`[data-turn-index="${successor.index}"]`);
    toolbar = {
      anchorTop: block?.offsetTop ?? 0,
      anchorBottom: block?.offsetTop ?? 0,
      left: 8,
      spans
    };
  }

  async function revertTurn(turn: TranscriptTurn) {
    if (!onRevertLine) return;
    const segmentIndexes = turn.parts
      .map((part) => part.segmentIndex)
      .filter((value, index, all) => all.indexOf(value) === index);
    for (const segmentIndex of segmentIndexes) {
      if (correctedFrom.has(segmentIndex)) {
        // Sequential so every save works against the fresh revision.
        await onRevertLine(segmentIndex);
      }
    }
  }

  function reassignTurn(turn: TranscriptTurn, speaker: string) {
    void onSaveSpeakerEdits?.(
      turn.parts.map((part) => ({
        segment_index: part.segmentIndex,
        char_start: part.rawStart,
        char_end: part.rawEnd,
        speaker
      }))
    );
  }

  /** Overridden parts go back to their stored speakers; the overlay merge
      then drops the edits entirely. */
  function resetTurn(turn: TranscriptTurn) {
    const inputs: SpeakerSpanInput[] = [];
    for (const part of turn.parts) {
      const stored = segments[part.segmentIndex]?.speaker;
      if (!part.overridden || !stored) continue;
      inputs.push({
        segment_index: part.segmentIndex,
        char_start: part.rawStart,
        char_end: part.rawEnd,
        speaker: stored
      });
    }
    if (inputs.length > 0) void onSaveSpeakerEdits?.(inputs);
  }

  // ---- Selection toolbar ------------------------------------------------
  let toolbar = $state<{
    anchorTop: number;
    anchorBottom: number;
    left: number;
    spans: SelectionSpan[];
  } | null>(null);

  function updateSelectionToolbar() {
    const list = listEl;
    if (!list || !speakerEditingEnabled || busy || editingTurnIndex >= 0) {
      toolbar = null;
      return;
    }
    const selection = document.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      toolbar = null;
      return;
    }
    const range = selection.getRangeAt(0);
    if (!list.contains(range.startContainer) || !list.contains(range.endContainer)) {
      toolbar = null;
      return;
    }
    const spans = selectionToSpans(
      list,
      range,
      (segmentIndex) => lineDetails.get(segmentIndex)?.geometry ?? null
    );
    if (spans.length === 0) {
      toolbar = null;
      return;
    }
    // jsdom's Range has no rect; anchoring falls back to the list origin.
    const rect =
      typeof range.getBoundingClientRect === "function"
        ? range.getBoundingClientRect()
        : { top: 0, bottom: 0, left: 0 };
    const listRect = list.getBoundingClientRect();
    toolbar = {
      anchorTop: Math.max(0, rect.top - listRect.top + list.scrollTop),
      anchorBottom: Math.max(0, rect.bottom - listRect.top + list.scrollTop),
      left: Math.max(
        4,
        Math.min(rect.left - listRect.left + list.scrollLeft, list.clientWidth - 240)
      ),
      spans
    };
  }

  /** Listens for selections while mounted; reads state only inside events. */
  function watchSelection(node: HTMLElement) {
    void node;
    let frame = 0;
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(updateSelectionToolbar);
    };
    document.addEventListener("selectionchange", schedule);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("selectionchange", schedule);
    };
  }

  async function chooseSpeakerForSelection(speaker: string) {
    const current = toolbar;
    if (!current || !onSaveSpeakerEdits) return;
    toolbar = null;
    const accepted = await onSaveSpeakerEdits(
      current.spans.map((span) => ({
        segment_index: span.segmentIndex,
        char_start: span.charStart,
        char_end: span.charEnd,
        speaker
      }))
    );
    if (accepted) window.getSelection()?.removeAllRanges();
  }

  function selectFile(fileIndex: number) {
    if (fileIndex === currentFile) return;
    activeIndex = -1;
    void loadAudio(fileIndex, 0, false);
  }

  function onKeydown(event: KeyboardEvent) {
    const target = event.target as HTMLElement | null;
    if (target?.closest("input, select, textarea, [contenteditable]")) return;
    if (event.key === "Escape") {
      toolbar = null;
      return;
    }
    // A focused button handles Space itself (play/pause, or its own action).
    if (event.key === " " && target?.closest("button")) return;
    switch (event.key) {
      case " ":
      case "k":
      case "K":
        event.preventDefault();
        if (event.key === " ") togglePlay();
        else audioEl?.pause();
        break;
      case "ArrowLeft":
        event.preventDefault();
        seekBy(-SKIP_ARROW_SECONDS);
        break;
      case "ArrowRight":
        event.preventDefault();
        seekBy(SKIP_ARROW_SECONDS);
        break;
      case "j":
      case "J":
        event.preventDefault();
        seekBy(-SKIP_JKL_SECONDS);
        break;
      case "l":
      case "L":
        event.preventDefault();
        seekBy(SKIP_JKL_SECONDS);
        break;
    }
  }

  function onUserScroll() {
    if (Date.now() > programmaticScrollUntil) follow = false;
    toolbar = null;
  }

  // Keep the playing turn in view while the reviewer has not scrolled away.
  $effect(() => {
    const index = activeIndex;
    const list = listEl;
    if (!follow || !list || index < 0) return;
    const part = list.querySelector<HTMLElement>(`[data-segment-index="${index}"]`);
    const block = part?.closest<HTMLElement>("[data-turn-index]") ?? part;
    if (!block || typeof list.scrollTo !== "function") return;
    const top = block.offsetTop - list.clientHeight / 2 + block.offsetHeight / 2;
    programmaticScrollUntil = Date.now() + 800;
    list.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
  });

  // A signed URL is short-lived; swap it in place before it expires so a long
  // review session does not stop mid-sentence.
  $effect(() => {
    const expires = expiresAt;
    if (expires === null) return;
    const delay = Math.min(
      REFRESH_MAX_DELAY_MS,
      Math.max(5_000, expires * 1000 - Date.now() - REFRESH_LEAD_MS)
    );
    const timer = window.setTimeout(() => {
      const at = audioEl?.currentTime ?? 0;
      const playing = audioEl ? !audioEl.paused : false;
      void loadAudio(currentFile, at, playing);
    }, delay);
    return () => window.clearTimeout(timer);
  });

  // Load the first file once the caller knows which files exist. The load
  // itself is untracked: the caller's signing function may read its own
  // state, and that must not re-run this effect and sign again.
  $effect(() => {
    const ready = hasSegments && !audioPending && fileCount > 0;
    if (!ready) return;
    untrack(() => {
      if (src === null && !loadingAudio) void loadAudio(0);
    });
  });

  // One theme token pair per palette slot so a person keeps a colour in both
  // themes; SPEAKER_PALETTE_SIZE slots cycle for larger groups.
  const SPEAKER_CLASSES = [
    "bg-accent-dimmer text-accent-stronger",
    "bg-positive-dimmer text-positive-stronger",
    "bg-warning-dimmer text-warning-stronger",
    "bg-negative-dimmer text-negative-stronger",
    "bg-label-dimmer text-label-stronger",
    "bg-chart-1/15 text-chart-1",
    "bg-chart-2/15 text-chart-2",
    "bg-chart-3/15 text-chart-3"
  ];

  function speakerClass(label: string): string {
    return SPEAKER_CLASSES[speakerColorIndex(label) % SPEAKER_CLASSES.length];
  }
</script>

<!-- The region takes focus so playback shortcuts work while reading; the
     buttons inside stay the primary controls for assistive technology. -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div
  class="border-default flex min-h-72 flex-col overflow-hidden rounded-lg border {className}"
  role="region"
  aria-label={m.flow_run_transcript_player_label()}
  tabindex="0"
  onkeydown={onKeydown}
>
  {#if hasSegments}
    <audio
      bind:this={audioEl}
      {src}
      preload="metadata"
      bind:currentTime
      bind:duration
      bind:paused
      bind:playbackRate
      ontimeupdate={onTimeUpdate}
      onloadedmetadata={onLoadedMetadata}
      onerror={() => (audioUnavailable = true)}
    ></audio>

    <div class="border-default bg-primary flex flex-col gap-2 border-b px-3 py-2">
      {#if audioUnavailable}
        <Alert.Root variant="destructive" class="flex items-center gap-3 py-2">
          <Alert.Description class="flex-1 text-xs">
            {m.flow_run_transcript_audio_unavailable()}
          </Alert.Description>
          <Button
            variant="outline"
            size="sm"
            class="h-7 text-xs"
            onclick={() => void loadAudio(currentFile, audioEl?.currentTime ?? 0)}
          >
            {m.flow_retry()}
          </Button>
        </Alert.Root>
      {/if}
      <div class="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="icon"
          class="size-9 shrink-0 rounded-full"
          aria-label={paused ? m.flow_run_transcript_play() : m.flow_run_transcript_pause()}
          disabled={audioUnavailable || loadingAudio || audioPending}
          onclick={togglePlay}
        >
          {#if loadingAudio || audioPending}
            <IconLoadingSpinner class="size-4 animate-spin" />
          {:else if paused}
            <IconPlay class="size-4" />
          {:else}
            <svg class="size-4" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
              <rect x="3" y="2" width="4" height="12" rx="1" />
              <rect x="9" y="2" width="4" height="12" rx="1" />
            </svg>
          {/if}
        </Button>
        <span class="text-secondary min-w-[4.5rem] text-xs tabular-nums">
          {formatClock(currentTime, withHours)}
        </span>
        <input
          type="range"
          class="accent-accent-default min-w-32 flex-1"
          min="0"
          max={Number.isFinite(duration) && duration > 0 ? duration : 0}
          step="0.1"
          value={currentTime}
          disabled={!seekable || !(duration > 0)}
          aria-label={m.flow_run_transcript_seek()}
          aria-valuetext={formatClock(currentTime, withHours)}
          oninput={(event) => seekToTime(Number(event.currentTarget.value))}
        />
        <span class="text-secondary min-w-[4.5rem] text-right text-xs tabular-nums">
          {Number.isFinite(duration) && duration > 0 ? formatClock(duration, withHours) : "--:--"}
        </span>
        <label class="text-secondary flex items-center gap-1 text-xs">
          <span class="sr-only">{m.flow_run_transcript_rate()}</span>
          <select
            bind:value={playbackRate}
            class="border-default bg-primary rounded-md border px-1.5 py-1 text-xs"
            disabled={audioUnavailable}
          >
            {#each RATES as rate (rate)}
              <option value={rate}>{rate}×</option>
            {/each}
          </select>
        </label>
        <Button
          variant={follow ? "secondary" : "outline"}
          size="sm"
          class="h-7 text-xs"
          aria-pressed={follow}
          title={m.flow_run_transcript_follow_help()}
          onclick={() => (follow = !follow)}
        >
          {m.flow_run_transcript_follow()}
        </Button>
      </div>
      {#if totalFiles > 1}
        <div class="flex flex-wrap items-center gap-1" role="group">
          {#each { length: totalFiles } as _, fileIndex (fileIndex)}
            <Button
              variant={fileIndex === currentFile ? "secondary" : "ghost"}
              size="sm"
              class="h-7 text-xs"
              aria-pressed={fileIndex === currentFile}
              disabled={audioUnavailable}
              onclick={() => selectFile(fileIndex)}
            >
              {m.flow_run_transcript_part({ n: String(fileIndex + 1) })}
            </Button>
          {/each}
        </div>
      {/if}
      {#if uncertainWords > 0}
        <p class="text-warning-stronger text-xs" data-uncertain-words={uncertainWords}>
          {m.flow_run_transcript_uncertain_count({ count: String(uncertainWords) })}
        </p>
      {/if}
      <p class="text-muted sr-only">{m.flow_run_transcript_shortcuts()}</p>
    </div>

    <!-- Scroll listeners only observe whether the reviewer moved away from
         the playing turn; they add no interaction of their own. -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      bind:this={listEl}
      class="bg-primary selection:bg-accent-dimmer selection:text-accent-stronger relative max-h-[32rem] flex-1 overflow-auto p-2"
      onwheel={onUserScroll}
      ontouchmove={onUserScroll}
      onscroll={onUserScroll}
      {@attach watchSelection}
    >
      <div class="flex flex-col gap-1.5">
        {#each turns as turn, position (turn.index)}
          {#if totalFiles > 1 && (position === 0 || turns[position - 1].fileIndex !== turn.fileIndex)}
            <p class="text-muted px-2 pt-2 pb-1 text-xs font-semibold" aria-hidden="true">
              {m.flow_run_transcript_part({ n: String(turn.fileIndex + 1) })}
            </p>
          {/if}
          <TranscriptTurnBlock
            {turn}
            activeSegmentIndex={activeIndex}
            {activeWordIndex}
            {withHours}
            {editable}
            {busy}
            editing={editable && editingTurnIndex === turn.index}
            {displayName}
            {speakerClass}
            speakerOptions={speakerEditingEnabled ? speakerOptions : []}
            newSpeakerLabel={newLabel}
            correctedFrom={(segmentIndex) => correctedFrom.get(segmentIndex) ?? null}
            onSeek={seekToPart}
            onStartEdit={() => startEditTurn(turn)}
            onCancelEdit={closeEditor}
            onCommitEdit={(text, reassign) => void commitTurnEdit(turn, text, reassign)}
            onRevertTurn={() => void revertTurn(turn)}
            onReassignTurn={(speaker) => reassignTurn(turn, speaker)}
            onResetTurn={() => resetTurn(turn)}
          />
        {/each}
      </div>
      {#if toolbar}
        <TranscriptSpeakerToolbar
          anchorTop={toolbar.anchorTop}
          anchorBottom={toolbar.anchorBottom}
          left={toolbar.left}
          options={speakerOptions}
          newSpeakerLabel={newLabel}
          disabled={busy}
          onChoose={(speaker) => void chooseSpeakerForSelection(speaker)}
        />
      {/if}
    </div>
  {:else}
    <div class="border-default bg-primary border-b px-3 py-2">
      <p class="text-muted text-xs">{m.flow_run_transcript_no_segments()}</p>
    </div>
    <pre
      class="bg-hover-dimmer max-h-[32rem] flex-1 overflow-auto p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">{textFallback}</pre>
  {/if}
</div>
