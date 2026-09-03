<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import CheckCircle2 from "lucide-svelte/icons/check-circle-2";
  import Loader2 from "lucide-svelte/icons/loader-2";
  import Circle from "lucide-svelte/icons/circle";
  import { untrack } from "svelte";
  import { fade } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";

  type SaveStatus = "saved" | "saving" | "unsaved";

  let {
    status
  }: {
    status: SaveStatus;
  } = $props();

  // The store flips unsaved -> saving -> saved on every typing pause, in under
  // a second. Showing each flip paints three differently coloured badges next
  // to the text the user is writing. What is shown lags the store instead: a
  // save that finishes within a normal round trip is never announced, a save
  // is only called "saving" once it has taken a while, and "unsaved" is
  // reserved for changes that actually stay unsaved.
  const SAVING_SHOWN_AFTER_MS = 800;
  const SAVING_SHOWN_FOR_AT_LEAST_MS = 600;
  const UNSAVED_SHOWN_AFTER_MS = 1500;

  // The initial badge is whatever the store says at mount; from then on the
  // effect below decides what is shown.
  let shown = $state<SaveStatus>(untrack(() => status));
  let savingShownAt = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;

  function clearTimer() {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  }

  function later(ms: number, next: SaveStatus) {
    clearTimer();
    timer = setTimeout(() => {
      timer = null;
      if (next === "saving") savingShownAt = Date.now();
      shown = next;
    }, ms);
  }

  $effect(() => {
    const next = status;
    if (next === "saving") {
      if (shown !== "saving") later(SAVING_SHOWN_AFTER_MS, "saving");
      return clearTimer;
    }
    if (next === "unsaved") {
      if (shown !== "unsaved") later(UNSAVED_SHOWN_AFTER_MS, "unsaved");
      return clearTimer;
    }
    // Saved. A "saving" badge that only just appeared would blink away again.
    const holdLeft =
      shown === "saving" ? savingShownAt + SAVING_SHOWN_FOR_AT_LEAST_MS - Date.now() : 0;
    if (holdLeft > 0) {
      later(holdLeft, "saved");
    } else {
      clearTimer();
      shown = "saved";
    }
    return clearTimer;
  });
</script>

<!-- A fixed minimum width: the three labels differ in length, and a badge
     that grows and shrinks as a draft flips between unsaved, saving and
     saved reflows the whole header row on every keystroke pause. -->
<div aria-live="polite" role="status" class="min-w-[7.25rem]">
  {#if shown === "saved"}
    <span class="flex items-center gap-1.5" in:fade={{ duration: 150 }}>
      <Badge variant="outline" class="border-default/60 text-muted-foreground gap-1.5">
        <CheckCircle2 class="size-3" />
        {m.flow_save_status_saved()}
      </Badge>
    </span>
  {:else if shown === "saving"}
    <span class="flex items-center gap-1.5" in:fade={{ duration: 150 }}>
      <Badge variant="outline" class="border-default bg-secondary/50 text-secondary gap-1.5">
        <Loader2 class="size-3 animate-spin motion-reduce:animate-none" />
        {m.flow_save_status_saving()}
      </Badge>
    </span>
  {:else}
    <span class="flex items-center gap-1.5" in:fade={{ duration: 150 }}>
      <Badge
        variant="outline"
        class="border-warning-default/20 bg-warning-dimmer/50 text-warning-stronger gap-1.5 font-medium"
      >
        <Circle class="size-2.5 fill-current" />
        {m.flow_save_status_unsaved()}
      </Badge>
    </span>
  {/if}
</div>
