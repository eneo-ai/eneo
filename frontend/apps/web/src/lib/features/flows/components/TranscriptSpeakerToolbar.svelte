<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import type { SpeakerOption } from "./TranscriptSpeakerBadge.svelte";

  let {
    anchorTop,
    anchorBottom,
    left,
    options = [],
    newSpeakerLabel,
    disabled = false,
    onChoose
  }: {
    /** Anchor edges (list-relative): the selection the toolbar acts on. */
    anchorTop: number;
    anchorBottom: number;
    left: number;
    options?: SpeakerOption[];
    /** The minted label behind "Ny talare". */
    newSpeakerLabel: string;
    disabled?: boolean;
    onChoose: (label: string) => void;
  } = $props();

  // The toolbar measures itself and sits fully above the selection, or below
  // it when there is no room, so it never covers what it acts on.
  let height = $state(0);

  function measure(node: HTMLElement) {
    height = node.offsetHeight;
    return () => {};
  }

  const top = $derived.by(() => {
    const above = anchorTop - height - 8;
    return above >= 4 ? above : anchorBottom + 8;
  });
</script>

<!-- pointerdown is prevented so choosing a speaker never collapses the
     selection the toolbar is acting on. -->
<div
  role="toolbar"
  tabindex="-1"
  aria-label={m.flow_run_transcript_change_speaker_selection()}
  class="border-default bg-primary absolute z-10 flex max-w-[calc(100%-1rem)] flex-wrap items-center gap-1 rounded-md border p-1 shadow-md"
  style="top: {top}px; left: {left}px;"
  {@attach measure}
  onpointerdown={(event) => event.preventDefault()}
>
  <span class="text-muted px-1 text-xs">{m.flow_run_transcript_change_speaker()}:</span>
  {#each options as option (option.label)}
    <button
      type="button"
      {disabled}
      class="rounded px-1.5 py-px text-xs font-semibold {option.colorClass} focus-visible:ring-accent-default cursor-pointer transition-shadow hover:ring-1 hover:ring-current/40 focus-visible:ring-2 focus-visible:outline-none disabled:cursor-default disabled:opacity-50"
      onclick={() => onChoose(option.label)}
    >
      {option.display}
    </button>
  {/each}
  <button
    type="button"
    {disabled}
    class="border-default text-secondary hover:bg-hover-dimmer focus-visible:ring-accent-default rounded border px-1.5 py-px text-xs focus-visible:ring-2 focus-visible:outline-none disabled:opacity-50"
    onclick={() => onChoose(newSpeakerLabel)}
  >
    {m.flow_run_transcript_new_speaker()}
  </button>
</div>
