<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    applyCasingPattern,
    type OccurrenceCandidate
  } from "$lib/features/flows/transcriptCorrections";
  import { formatClock, type TranscriptSegment } from "$lib/features/flows/transcriptSegments";

  let {
    open = false,
    originalText,
    correctedText,
    candidates,
    segments,
    busy = false,
    onConfirm,
    onSkip
  }: {
    open?: boolean;
    /** The text the user corrected, as it stood in the transcript. */
    originalText: string;
    /** What they corrected it to. */
    correctedText: string;
    candidates: OccurrenceCandidate[];
    /** Raw segments, for timestamps and surrounding context. */
    segments: readonly TranscriptSegment[];
    busy?: boolean;
    onConfirm: (selected: OccurrenceCandidate[]) => void;
    /** Apply only the edited line; also the dialog's close action. */
    onSkip: () => void;
  } = $props();

  // Nothing is applied without explicit confirmation: exact matches are
  // pre-checked as a convenience, fuzzy candidates start unchecked.
  let checked = $derived(candidates.map((candidate) => candidate.kind === "exact"));

  function setChecked(index: number, value: boolean) {
    checked = checked.map((item, i) => (i === index ? value : item));
  }

  const selectedCount = $derived(checked.filter(Boolean).length);
  const withHours = $derived(segments.some((segment) => segment.end >= 3600));

  function candidateTime(candidate: OccurrenceCandidate): string {
    const segment = segments[candidate.segmentIndex];
    return segment ? formatClock(segment.start, withHours) : "";
  }

  function candidateContext(candidate: OccurrenceCandidate): {
    before: string;
    match: string;
    after: string;
  } {
    const text = segments[candidate.segmentIndex]?.text ?? "";
    return {
      before: text.slice(0, candidate.charStart),
      match: text.slice(candidate.charStart, candidate.charEnd),
      after: text.slice(candidate.charEnd)
    };
  }

  function confirmSelected() {
    onConfirm(candidates.filter((_, index) => checked[index]));
  }
</script>

<Dialog.Root
  {open}
  onOpenChange={(next) => {
    if (!next && !busy) onSkip();
  }}
>
  <Dialog.Content class="max-w-2xl">
    <Dialog.Header>
      <Dialog.Title>{m.flow_run_transcript_suggestions_title()}</Dialog.Title>
      <Dialog.Description>
        {m.flow_run_transcript_suggestions_description({
          original: originalText,
          corrected: correctedText
        })}
      </Dialog.Description>
    </Dialog.Header>

    <div class="flex max-h-96 flex-col gap-1 overflow-y-auto py-1">
      {#each candidates as candidate, index (candidate.segmentIndex + ":" + candidate.charStart)}
        {@const context = candidateContext(candidate)}
        <label
          class="hover:bg-hover-dimmer flex cursor-pointer items-start gap-2.5 rounded-md px-2 py-1.5"
        >
          <Checkbox
            checked={checked[index]}
            onCheckedChange={(value) => setChecked(index, value === true)}
            disabled={busy}
            class="mt-0.5"
          />
          <span class="min-w-0 flex-1 text-sm leading-relaxed">
            <span class="text-muted mr-1.5 text-xs tabular-nums">
              {candidateTime(candidate)}
            </span>
            <Badge variant={candidate.kind === "exact" ? "secondary" : "outline"} class="mr-1.5">
              {candidate.kind === "exact"
                ? m.flow_run_transcript_match_exact()
                : m.flow_run_transcript_match_fuzzy()}
            </Badge>
            <span class="text-secondary break-words">
              {context.before}<mark
                class="bg-warning-dimmer text-warning-stronger rounded px-0.5 font-medium"
                >{context.match}</mark
              >{context.after}
            </span>
            <span class="text-muted mt-0.5 block text-xs">
              {context.match} → {applyCasingPattern(context.match, correctedText)}
            </span>
          </span>
        </label>
      {/each}
    </div>

    <Dialog.Footer>
      <Button variant="outline" disabled={busy} onclick={onSkip}>
        {m.flow_run_transcript_suggestions_skip()}
      </Button>
      <Button disabled={busy || selectedCount === 0} onclick={confirmSelected}>
        {busy
          ? m.saving()
          : m.flow_run_transcript_suggestions_confirm({ count: String(selectedCount) })}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
