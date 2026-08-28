<script lang="ts">
  import { IconPlay } from "@eneo/icons/play";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { untrack } from "svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    applySpeakerNames,
    countFiles,
    findActiveSegmentIndex,
    formatClock,
    speakerColorIndex,
    type TranscriptSegment
  } from "$lib/features/flows/transcriptSegments";

  export type SignedAudio = { url: string; expires_at: number };

  let {
    segments,
    fileCount = 1,
    getAudioUrl,
    speakerNames = {},
    textFallback = "",
    audioPending = false,
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

  const shown = $derived(applySpeakerNames(segments, speakerNames));
  const totalFiles = $derived(Math.max(fileCount, countFiles(segments)));
  const hasSegments = $derived(shown.length > 0);
  const withHours = $derived(duration >= 3600 || shown.some((segment) => segment.end >= 3600));
  const seekable = $derived(!audioUnavailable && hasSegments);

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
    activeIndex = findActiveSegmentIndex(shown, currentFile, audioEl.currentTime, activeIndex);
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
  }

  function seekBy(delta: number) {
    if (!audioEl) return;
    seekToTime(audioEl.currentTime + delta);
  }

  function seekToSegment(segment: TranscriptSegment) {
    if (!seekable) return;
    follow = true;
    activeIndex = segment.index;
    if (segment.fileIndex !== currentFile || !audioEl) {
      void loadAudio(segment.fileIndex, segment.start, true);
      return;
    }
    audioEl.currentTime = segment.start;
    void audioEl.play().catch(markPlayFailure);
  }

  function selectFile(fileIndex: number) {
    if (fileIndex === currentFile) return;
    activeIndex = -1;
    void loadAudio(fileIndex, 0, false);
  }

  function onKeydown(event: KeyboardEvent) {
    const target = event.target as HTMLElement | null;
    if (target?.closest("input, select, textarea")) return;
    // A focused button handles Space itself (play/pause, or seek to its line).
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
  }

  // Keep the playing line in view while the reviewer has not scrolled away.
  $effect(() => {
    const index = activeIndex;
    const list = listEl;
    if (!follow || !list || index < 0) return;
    const line = list.querySelector<HTMLElement>(`[data-segment-index="${index}"]`);
    if (!line || typeof list.scrollTo !== "function") return;
    const top = line.offsetTop - list.clientHeight / 2 + line.offsetHeight / 2;
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
      <p class="text-muted sr-only">{m.flow_run_transcript_shortcuts()}</p>
    </div>

    <!-- Scroll listeners only observe whether the reviewer moved away from
         the playing line; they add no interaction of their own. -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      bind:this={listEl}
      class="bg-primary relative max-h-[32rem] flex-1 overflow-auto p-2"
      onwheel={onUserScroll}
      ontouchmove={onUserScroll}
      onscroll={onUserScroll}
    >
      <ol class="flex flex-col gap-0.5">
        {#each shown as segment, position (segment.index)}
          {#if totalFiles > 1 && (position === 0 || shown[position - 1].fileIndex !== segment.fileIndex)}
            <li class="text-muted px-2 pt-2 pb-1 text-xs font-semibold" aria-hidden="true">
              {m.flow_run_transcript_part({ n: String(segment.fileIndex + 1) })}
            </li>
          {/if}
          <li>
            <button
              type="button"
              data-segment-index={segment.index}
              class="hover:bg-hover-dimmer focus-visible:ring-accent-default flex w-full items-start gap-2 rounded-md border-l-4 border-transparent px-2 py-1.5 text-left text-sm leading-relaxed transition-colors focus-visible:ring-2 focus-visible:outline-none disabled:cursor-default disabled:hover:bg-transparent {segment.index ===
              activeIndex
                ? 'border-accent-default bg-accent-dimmer ring-accent-default/40 ring-1 ring-inset'
                : ''}"
              aria-current={segment.index === activeIndex ? "true" : undefined}
              disabled={!seekable}
              title={m.flow_run_transcript_seek_to({ time: formatClock(segment.start, withHours) })}
              onclick={() => seekToSegment(segment)}
            >
              <span
                class="mt-0.5 w-14 shrink-0 text-xs tabular-nums sm:w-[4.5rem] {segment.index ===
                activeIndex
                  ? 'text-accent-stronger font-semibold'
                  : 'text-muted'}"
              >
                {formatClock(segment.start, withHours)}
              </span>
              <span class="min-w-0 flex-1">
                {#if segment.speaker}
                  <span
                    class="mr-1.5 inline-block rounded px-1.5 py-px align-baseline text-xs font-semibold {speakerClass(
                      segment.speaker
                    )}"
                  >
                    {segment.speaker}
                  </span>
                {/if}
                <span
                  class={segment.index === activeIndex
                    ? "text-primary font-medium"
                    : "text-primary"}>{segment.text}</span
                >
              </span>
            </button>
          </li>
        {/each}
      </ol>
    </div>
  {:else}
    <div class="border-default bg-primary border-b px-3 py-2">
      <p class="text-muted text-xs">{m.flow_run_transcript_no_segments()}</p>
    </div>
    <pre
      class="bg-hover-dimmer max-h-[32rem] flex-1 overflow-auto p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">{textFallback}</pre>
  {/if}
</div>
