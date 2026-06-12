<script lang="ts">
  import { onMount } from "svelte";
  import { browser } from "$app/environment";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { Info, AlertTriangle, Eye, EyeOff } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { getChatService } from "../../ChatService.svelte";

  const chat = getChatService();

  type Props = { onNewConversation?: () => void };
  const { onNewConversation }: Props = $props();
  const startNewConversation = () => {
    if (onNewConversation) onNewConversation();
    else chat.newConversation();
  };

  const VISIBILITY_STORAGE_KEY = "contextUsageBarVisible";
  let isVisible = $state(true);
  let hasHydratedVisibility = $state(false);

  onMount(() => {
    if (!browser) {
      hasHydratedVisibility = true;
      return;
    }
    try {
      const stored = window.localStorage.getItem(VISIBILITY_STORAGE_KEY);
      isVisible = stored !== "false";
    } catch (error) {
      console.warn("Unable to read context usage bar preference", error);
    } finally {
      hasHydratedVisibility = true;
    }
  });

  $effect(() => {
    if (!browser || !hasHydratedVisibility) return;
    try {
      window.localStorage.setItem(VISIBILITY_STORAGE_KEY, isVisible ? "true" : "false");
    } catch (error) {
      console.warn("Unable to persist context usage bar preference", error);
    }
  });

  // Bar segments (left to right):
  //   1. Locked input  — what was sent to the LLM last turn (system + MCP +
  //      RAG + history + question, lumped together in provider's prompt_tokens)
  //   2. Locked output — the model's previous reply
  //   3. Pending text  — exact tokens for the text in the input right now
  //   4. Pending files — exact tokens the attached files will add
  const pendingTotal = $derived(chat.pendingInputTokens + chat.pendingFileTokens);
  const projectedTotal = $derived(chat.contextTokens + pendingTotal);

  function pct(value: number): number {
    return chat.contextLimit > 0 ? (value / chat.contextLimit) * 100 : 0;
  }

  // Display percentages — capped so segments never overflow the bar visually.
  // We track the cumulative width as we lay them out so each segment stops
  // exactly where the next one starts.
  const segments = $derived.by(() => {
    const limit = chat.contextLimit;
    if (limit <= 0) return [];

    const raw = [
      { key: "lockedInput", tokens: chat.lockedInputTokens },
      { key: "lockedOutput", tokens: chat.lockedOutputTokens },
      { key: "pendingText", tokens: chat.pendingInputTokens },
      { key: "pendingFiles", tokens: chat.pendingFileTokens }
    ];

    let cursor = 0;
    return raw.map((s) => {
      const widthPct = (s.tokens / limit) * 100;
      const capped = Math.max(0, Math.min(100 - cursor, widthPct));
      const result = { ...s, leftPct: cursor, widthPct: capped };
      cursor += capped;
      return result;
    });
  });

  // Read from ChatService so the bar and the Send-button can't drift.
  const willExceed = $derived(chat.willExceedContext);
  const projectedPercent = $derived(pct(projectedTotal));

  // Top-line summary color — green / amber / red based on projected total.
  const summaryTone = $derived(
    willExceed
      ? "text-negative-stronger"
      : projectedPercent >= 80
        ? "text-warning-stronger"
        : "text-secondary"
  );

  // Four visually distinct hues, all using *-stronger variants so each segment
  // keeps WCAG-grade contrast against the track (and against each other) in
  // both light and dark themes (WCAG 1.4.1 / 1.4.11).
  function segmentClass(key: string): string {
    if (willExceed && (key === "pendingText" || key === "pendingFiles")) {
      return "bg-negative-stronger";
    }
    switch (key) {
      case "lockedInput":
        return "bg-muted-foreground/70";
      case "lockedOutput":
        return "bg-positive-stronger";
      case "pendingText":
        return "bg-accent-stronger";
      case "pendingFiles":
        return "bg-warning-stronger";
      default:
        return "bg-muted-foreground/70";
    }
  }

  const fmt = (n: number) => n.toLocaleString();

  // Single source of truth lives in ChatService so the label and the context
  // window can't disagree about which model is active.
  const modelName = $derived(chat.activeModelName);

  const hasUsage = $derived(chat.contextLimit > 0 && (chat.contextTokens > 0 || pendingTotal > 0));
  const showBar = $derived(hasUsage && isVisible);
  const showRevealButton = $derived(hasUsage && !isVisible);

  const hasCumulative = $derived(chat.cumulativeTokens > 0 && chat.turnCount > 0);
  const cumulativeSummary = $derived(
    chat.turnCount === 1
      ? m.context_usage_cumulative_summary_singular({
          total: fmt(chat.cumulativeTokens),
          turns: chat.turnCount
        })
      : m.context_usage_cumulative_summary({
          total: fmt(chat.cumulativeTokens),
          turns: chat.turnCount
        })
  );
</script>

{#if showRevealButton}
  <div class="flex w-full justify-end px-1 pt-1">
    <button
      type="button"
      onclick={() => (isVisible = true)}
      aria-label={m.context_usage_show_bar()}
      title={m.context_usage_show_bar()}
      class="text-tertiary hover:text-default flex items-center gap-1 text-[11px] leading-none transition-colors"
    >
      <Eye class="h-3 w-3" aria-hidden="true" />
    </button>
  </div>
{/if}

{#if showBar}
  <Popover.Root>
    <Popover.Trigger
      class="text-secondary hover:text-default flex w-full items-center gap-3 px-1 pt-1 text-[11px] leading-none transition-colors"
      aria-label={m.context_usage()}
    >
      <div
        class="bg-tertiary border-dimmer relative h-2.5 flex-1 overflow-hidden rounded-full border"
        role="progressbar"
        aria-valuenow={projectedTotal}
        aria-valuemin="0"
        aria-valuemax={chat.contextLimit}
      >
        {#each segments as seg (seg.key)}
          {#if seg.widthPct > 0}
            <div
              class="absolute top-0 bottom-0 my-auto h-[calc(100%-2px)] rounded-full transition-all duration-300 ease-out {segmentClass(
                seg.key
              )}"
              style:left="{seg.leftPct}%"
              style:width="max(3px, calc({seg.widthPct}% - 2px))"
              style:margin-left="1px"
            ></div>
          {/if}
        {/each}
      </div>
      <span class="flex items-center gap-1.5 whitespace-nowrap tabular-nums {summaryTone}">
        {#if willExceed}
          <AlertTriangle class="h-3 w-3" aria-hidden="true" />
        {/if}
        {fmt(projectedTotal)} / {fmt(chat.contextLimit)} ({projectedPercent.toFixed(
          projectedPercent >= 10 ? 0 : 1
        )}%)
        <Info class="text-tertiary h-3 w-3" aria-hidden="true" />
      </span>
    </Popover.Trigger>

    <Popover.Content side="top" class="w-[340px] p-0" align="end">
      <div class="border-default border-b px-4 py-3">
        <p class="text-default text-sm font-medium">{m.context_usage()}</p>
        <p class="text-secondary mt-0.5 text-xs tabular-nums">
          {fmt(projectedTotal)} / {fmt(chat.contextLimit)}
          {m.chat_tokens_separator()}
          {projectedPercent.toFixed(1)}%
        </p>
      </div>

      <div class="space-y-3 px-4 py-3 text-xs">
        {#if chat.lockedInputTokens > 0 || chat.lockedOutputTokens > 0}
          <div class="space-y-1.5">
            <p class="text-tertiary text-[10px] font-medium tracking-wide uppercase">
              {m.context_usage_section_locked()}
            </p>
            <div class="flex items-baseline justify-between gap-3">
              <span class="text-default flex items-center gap-2">
                <span class="bg-muted-foreground/70 inline-block h-2.5 w-2.5 rounded-full"></span>
                {m.context_usage_label_input()}
              </span>
              <span class="text-secondary tabular-nums">{fmt(chat.lockedInputTokens)}</span>
            </div>
            <p class="text-tertiary pl-[18px] text-[10px] leading-snug">
              {m.context_usage_label_input_hint()}
            </p>
            <div class="flex items-baseline justify-between gap-3">
              <span class="text-default flex items-center gap-2">
                <span class="bg-positive-stronger inline-block h-2.5 w-2.5 rounded-full"></span>
                {m.context_usage_label_output()}
              </span>
              <span class="text-secondary tabular-nums">{fmt(chat.lockedOutputTokens)}</span>
            </div>
          </div>
        {/if}

        {#if pendingTotal > 0}
          <div class="border-default space-y-1.5 border-t pt-3">
            <p class="text-tertiary text-[10px] font-medium tracking-wide uppercase">
              {m.context_usage_section_pending()}
            </p>
            {#if chat.pendingInputTokens > 0}
              <div class="flex items-baseline justify-between gap-3">
                <span class="text-default flex items-center gap-2">
                  <span class="bg-accent-stronger inline-block h-2.5 w-2.5 rounded-full"></span>
                  {m.context_usage_label_your_text()}
                </span>
                <span class="text-secondary tabular-nums">{fmt(chat.pendingInputTokens)}</span>
              </div>
            {/if}
            {#if chat.pendingFileTokens > 0}
              <div class="flex items-baseline justify-between gap-3">
                <span class="text-default flex items-center gap-2">
                  <span class="bg-warning-stronger inline-block h-2.5 w-2.5 rounded-full"></span>
                  {m.context_usage_label_files()}
                </span>
                <span class="text-secondary tabular-nums">{fmt(chat.pendingFileTokens)}</span>
              </div>
            {/if}
          </div>
        {/if}

        {#if pendingTotal > 0}
          <div class="border-default space-y-1.5 border-t pt-3">
            <p class="text-tertiary text-[10px] font-medium tracking-wide uppercase">
              {m.context_usage_section_excluded()}
            </p>
            <p class="text-secondary leading-snug">
              {m.context_usage_excluded_hint()}
            </p>
          </div>
        {/if}

        {#if hasCumulative}
          <div class="border-default space-y-1.5 border-t pt-3">
            <p class="text-tertiary text-[10px] font-medium tracking-wide uppercase">
              {m.context_usage_section_cumulative()}
            </p>
            <div class="flex items-baseline justify-between gap-3">
              <span class="text-default">{m.context_usage_cumulative_label()}</span>
              <span class="text-secondary tabular-nums">{cumulativeSummary}</span>
            </div>
            {#if chat.turnCount > 1}
              <p class="text-tertiary pl-0 text-[10px] leading-snug tabular-nums">
                {m.context_usage_cumulative_average({ average: fmt(chat.averageTokensPerTurn) })}
              </p>
            {/if}
            <p class="text-secondary leading-snug">
              {m.context_usage_cumulative_hint()}
            </p>
          </div>
        {/if}

        {#if willExceed}
          <div
            class="bg-negative-dimmer/30 text-negative-stronger flex flex-col gap-2 rounded-md px-2 py-1.5"
          >
            <div class="flex items-start gap-2">
              <AlertTriangle class="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
              <span class="text-[11px] leading-snug">
                {m.context_usage_will_exceed()}
              </span>
            </div>
            <button
              type="button"
              onclick={startNewConversation}
              class="border-negative-stronger/40 hover:bg-negative-dimmer/50 self-start rounded-md border px-2 py-1 text-[11px] font-medium transition-colors"
            >
              {m.new_conversation()}
            </button>
          </div>
        {/if}
      </div>

      <div
        class="border-default bg-muted/30 flex items-center justify-between gap-2 border-t px-4 py-2"
      >
        {#if modelName}
          <p class="text-tertiary text-[10px]">
            {m.context_usage_model_label()}: <span class="text-secondary">{modelName}</span>
          </p>
        {:else}
          <span></span>
        {/if}
        <button
          type="button"
          onclick={() => (isVisible = false)}
          class="text-tertiary hover:text-default flex items-center gap-1 text-[10px] transition-colors"
        >
          <EyeOff class="h-3 w-3" aria-hidden="true" />
          {m.context_usage_hide_bar()}
        </button>
      </div>
    </Popover.Content>
  </Popover.Root>
{/if}
