<script lang="ts">
  /**
   * BoundedLog (handoff §2): a height-bounded conversation record.
   * - `role="log"` scroll region, keyboard-reachable, latest message anchored.
   * - Renders a window of the newest messages; "Visa äldre (n)" loads back.
   * - "NYTT" divider marks messages that arrived while the log was collapsed
   *   (`newSinceIndex` is owned by the parent, which knows open/closed state).
   * - No autoscroll while the user has scrolled up.
   */
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import type { ChatMessage } from "./protocol";

  interface Props {
    messages: ChatMessage[];
    /** Index of the first message not yet seen by the user, or null. */
    newSinceIndex?: number | null;
  }

  let { messages, newSinceIndex = null }: Props = $props();

  const WINDOW_STEP = 20;

  let visibleCount = $state(WINDOW_STEP);
  let logEl = $state<HTMLDivElement | undefined>();
  let pinnedToLatest = true;

  const olderCount = $derived(Math.max(0, messages.length - visibleCount));
  const firstVisibleIndex = $derived(olderCount);
  const visibleMessages = $derived(messages.slice(firstVisibleIndex));

  function showOlder() {
    // Keep the current top message in view while older entries render above it.
    const el = logEl;
    const before = el ? el.scrollHeight - el.scrollTop : 0;
    visibleCount = Math.min(messages.length, visibleCount + WINDOW_STEP);
    if (el) {
      requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight - before;
      });
    }
  }

  function handleScroll() {
    const el = logEl;
    if (!el) return;
    pinnedToLatest = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  $effect(() => {
    void messages.length;
    const el = logEl;
    if (el && pinnedToLatest) {
      requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight;
      });
    }
  });
</script>

<div class="flex flex-col gap-1.5">
  {#if olderCount > 0}
    <Button variant="ghost" size="xs" class="text-secondary w-fit" onclick={showOlder}>
      {m.ai_builder_conversation_show_older({ count: olderCount })}
    </Button>
  {/if}

  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <div
    bind:this={logEl}
    role="log"
    aria-label={m.ai_builder_conversation_aria()}
    tabindex="0"
    onscroll={handleScroll}
    class="bounded-log focus-visible:ring-accent-default/40 flex flex-col gap-2.5 overflow-y-auto pr-1 focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset"
  >
    {#each visibleMessages as message, i (`log-${firstVisibleIndex + i}`)}
      {@const index = firstVisibleIndex + i}
      {#if newSinceIndex !== null && index === newSinceIndex}
        <div class="new-divider" aria-hidden="false">
          <span class="new-divider-label">{m.ai_builder_conversation_new_divider()}</span>
        </div>
      {/if}
      <div class="flex flex-col gap-0.5">
        <span class="text-muted text-[0.6875rem] font-semibold tracking-[0.04em] uppercase">
          {message.role === "user" ? m.ai_builder_role_you() : "Eneo"}
        </span>
        <p class="text-secondary text-[0.8125rem] leading-relaxed break-words whitespace-pre-wrap">
          {message.content}
        </p>
      </div>
    {/each}
  </div>
</div>

<style>
  .bounded-log {
    /* Bounded height (handoff §2): the log never dominates the pane. */
    max-height: min(40cqh, 280px);
  }

  .new-divider {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .new-divider::before,
  .new-divider::after {
    content: "";
    flex: 1 1 auto;
    border-top: 1px solid var(--accent-default);
    opacity: 0.4;
  }

  .new-divider-label {
    color: var(--accent-stronger);
    font-size: 0.6875rem;
    font-weight: 700;
    letter-spacing: 0.06em;
  }
</style>
