<script lang="ts">
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { IconTrash } from "@eneo/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { SessionRecoveryHint } from "$lib/features/audio/recordingSessionStore";

  let {
    hint,
    busy = false,
    locale,
    onContinue,
    onDiscard,
    onDismiss
  }: {
    hint: SessionRecoveryHint;
    busy?: boolean;
    locale: "sv" | "en";
    onContinue: (hint: SessionRecoveryHint) => void;
    onDiscard: (hint: SessionRecoveryHint) => void;
    onDismiss: () => void;
  } = $props();

  function formatDuration(totalMs: number): string {
    if (!Number.isFinite(totalMs) || totalMs <= 0) return "0 min";
    const totalMinutes = Math.max(1, Math.round(totalMs / 60000));
    if (totalMinutes < 60) return `${totalMinutes} min`;
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    return minutes > 0 ? `${hours} h ${minutes} min` : `${hours} h`;
  }

  function formatWhen(epochMs: number): string {
    try {
      return new Date(epochMs).toLocaleString(locale === "sv" ? "sv-SE" : "en-US", {
        dateStyle: "short",
        timeStyle: "short"
      });
    } catch {
      return new Date(epochMs).toISOString();
    }
  }
</script>

<Alert.Root class="border-accent-default/30 bg-accent-dimmer/40 text-accent-stronger mb-5">
  <Alert.Title>{m.recording_resume_prompt_title()}</Alert.Title>
  <Alert.Description class="text-accent-stronger/90">
    {m.recording_resume_prompt_body({
      count: String(hint.segmentCount),
      time: formatWhen(hint.earliestCapturedAt)
    })}
    <span class="mt-1 block text-xs opacity-80">
      {m.recording_segments_saved_status({
        count: String(hint.segmentCount),
        duration: formatDuration(hint.totalDurationMs)
      })}
    </span>
  </Alert.Description>
  <div class="mt-3 flex flex-wrap gap-2">
    <Button size="sm" disabled={busy} onclick={() => onContinue(hint)}>
      {#if busy}
        <IconLoadingSpinner data-icon="inline-start" class="animate-spin" />
      {/if}
      {m.recording_resume_continue_recording()}
    </Button>
    <Button variant="outline" size="sm" disabled={busy} onclick={() => onDiscard(hint)}>
      <IconTrash data-icon="inline-start" />
      {m.recording_resume_discard()}
    </Button>
    <Button variant="ghost" size="sm" disabled={busy} onclick={() => onDismiss()}>
      {m.cancel()}
    </Button>
  </div>
</Alert.Root>
