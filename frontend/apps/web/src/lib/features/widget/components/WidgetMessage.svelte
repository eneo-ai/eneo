<script lang="ts">
  import type { ConversationMessage } from "@eneo/eneo-js";
  import { Markdown } from "@eneo/ui";
  import { sanitizeLinkHref } from "@eneo/ui/components/markdown";
  import { tick } from "svelte";
  import { Check, ChevronRight, Copy, ExternalLink, FileText } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import {
    messageSources,
    referenceIndexer,
    setWidgetMessageContext,
    sourceReferenceText,
    type WidgetSource
  } from "../widgetMessageContext";
  import { linkHost } from "../urls";
  import { widgetToolSteps } from "../widgetToolSteps";
  import WidgetInref from "./WidgetInref.svelte";
  import WidgetQuestionBubble from "./WidgetQuestionBubble.svelte";
  import WidgetToolActivity from "./WidgetToolActivity.svelte";
  import TypingIndicator from "$lib/features/chat/components/conversation/TypingIndicator.svelte";

  type Props = {
    message: ConversationMessage;
    index: number;
    isLast: boolean;
    isLoading: boolean;
    /** Off when the widget hides citations and the source list. */
    showSources?: boolean;
    /** Off when the widget keeps the tools behind an answer out of view. */
    showActivity?: boolean;
  };

  let {
    message,
    index,
    isLast,
    isLoading,
    showSources = true,
    showActivity = true
  }: Props = $props();

  const anchorFor = (sourceIndex: number) => `widget-source-${index}-${sourceIndex}`;
  const listId = $derived(`widget-sources-${index}`);
  const sources = $derived(showSources ? messageSources(message) : []);
  const indexer = $derived(referenceIndexer(message));

  // Collapsed by default: the answer is what the visitor came for, the
  // sources are one click away, and a citation marker opens them in place.
  let expanded = $state(false);
  let copiedId = $state<string | null>(null);
  let copyFailedId = $state<string | null>(null);
  // Keyed so a second copy is announced too: the same text set twice would
  // leave the live region untouched.
  let announcement = $state({ id: 0, text: "" });
  let copiedTimer: ReturnType<typeof setTimeout> | null = null;

  function announce(text: string) {
    announcement = { id: announcement.id + 1, text };
  }

  async function revealSource(sourceIndex: number) {
    expanded = true;
    await tick();
    const entry = document.getElementById(anchorFor(sourceIndex));
    entry?.scrollIntoView({ block: "nearest" });
    entry?.focus();
  }

  setWidgetMessageContext({
    referenceIndex: (id) => (showSources ? indexer(id) : null),
    referenceAnchor: anchorFor,
    revealSource
  });

  const sourcesLabel = $derived(
    sources.length === 1
      ? m.widget_sources_count_one({ count: sources.length })
      : m.widget_sources_count_other({ count: sources.length })
  );

  const appOrigin = () => (typeof location === "undefined" ? "" : location.origin);

  async function copyReference(source: WidgetSource) {
    const text = sourceReferenceText(source, appOrigin());
    try {
      await navigator.clipboard.writeText(text);
      copiedId = source.id;
      copyFailedId = null;
      announce(m.widget_reference_copied());
      if (copiedTimer) clearTimeout(copiedTimer);
      copiedTimer = setTimeout(() => (copiedId = null), 2000);
    } catch {
      // Clipboard access is denied in some embedding contexts; leave the
      // text on screen so the visitor can select it instead.
      copyFailedId = source.id;
      announce(m.widget_reference_copy_failed());
    }
  }

  const waiting = $derived(isLast && isLoading && message.answer.trim().length === 0);

  // Tool activity: while the assistant works only the latest step shows and
  // each new call replaces it; once done, several steps fold into one line
  // that opens to the full list. A single step never folds.
  const streaming = $derived(isLast && isLoading);
  const steps = $derived(
    showActivity ? widgetToolSteps(message, { streaming, working: waiting }) : []
  );
  const stepsWorking = $derived(
    waiting || steps.some((step) => step.status === "preparing" || step.status === "running")
  );
</script>

<li class="flex flex-col gap-3">
  <WidgetQuestionBubble text={message.question} />

  <div class="flex flex-col gap-2">
    {#if steps.length > 0}
      <div aria-label={m.widget_activity()} role="group">
        <WidgetToolActivity {steps} working={stepsWorking} />
      </div>
    {/if}
    {#if waiting && steps.length === 0}
      <TypingIndicator />
    {:else if !waiting}
      <span class="sr-only">{m.widget_assistant()}: </span>
      <div class="widget-answer">
        <Markdown
          class="text-primary max-w-none"
          source={message.answer}
          customRenderers={{ inref: WidgetInref }}
        />
      </div>
      {#if sources.length > 0}
        <section aria-label={m.widget_references()} class="border-default mt-1 border-t pt-2">
          <button
            type="button"
            class="text-secondary hover:text-primary flex items-center gap-1.5 rounded-md text-sm"
            aria-expanded={expanded}
            aria-controls={listId}
            onclick={() => (expanded = !expanded)}
          >
            <ChevronRight
              class={`size-4 transition-transform ${expanded ? "rotate-90" : ""}`}
              aria-hidden="true"
            />
            {sourcesLabel}
            {#if expanded}
              <span class="sr-only">({m.widget_sources_hide()})</span>
            {/if}
          </button>
          {#if expanded}
            <ol id={listId} class="mt-2 flex flex-col gap-1.5 text-sm">
              {#each sources as source, sourceIndex (source.id)}
                {@const href = source.url ? sanitizeLinkHref(source.url) : undefined}
                <li
                  id={anchorFor(sourceIndex)}
                  tabindex="-1"
                  class="border-default flex items-start gap-2.5 rounded-md border px-2.5 py-2"
                >
                  <span
                    class="border-default bg-secondary min-w-6 rounded-md border text-center font-mono text-xs leading-6 tabular-nums"
                    aria-hidden="true"
                  >
                    {sourceIndex + 1}
                  </span>
                  <div class="flex min-w-0 flex-1 flex-col gap-0.5">
                    {#if href}
                      <!-- eslint-disable svelte/no-navigation-without-resolve -- external source URL from reference metadata -->
                      <a
                        class="text-accent-default inline-flex items-center gap-1 break-words underline-offset-2 hover:underline"
                        {href}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <span class="sr-only">{sourceIndex + 1}. </span>
                        <span class="min-w-0 break-words">{source.title}</span>
                        <ExternalLink class="size-3.5 shrink-0" aria-hidden="true" />
                        <span class="sr-only"> ({m.widget_open_source()})</span>
                      </a>
                      <span class="text-secondary text-xs">{linkHost(source.url ?? "")}</span>
                    {:else}
                      <span class="text-primary inline-flex items-center gap-1.5 break-words">
                        <FileText class="text-secondary size-3.5 shrink-0" aria-hidden="true" />
                        <span class="sr-only">{sourceIndex + 1}. </span>
                        <span class="min-w-0 break-words">{source.title}</span>
                      </span>
                      {#if !source.document}
                        <span class="text-secondary text-xs">{m.widget_source_tool()}</span>
                      {:else}
                        <span class="text-secondary text-xs">{m.widget_source_document()}</span>
                        <button
                          type="button"
                          class="text-accent-default mt-1 inline-flex w-fit items-center gap-1 rounded-md text-xs underline-offset-2 hover:underline"
                          aria-label={m.widget_copy_reference_for({ title: source.title })}
                          onclick={() => copyReference(source)}
                        >
                          {#if copiedId === source.id}
                            <Check class="size-3.5" aria-hidden="true" />
                            {m.widget_reference_copied()}
                          {:else}
                            <Copy class="size-3.5" aria-hidden="true" />
                            {m.widget_copy_reference()}
                          {/if}
                        </button>
                        {#if copyFailedId === source.id}
                          <p class="text-secondary text-xs">{m.widget_reference_copy_failed()}</p>
                          <p class="text-primary text-xs break-all select-all">
                            {sourceReferenceText(source, appOrigin())}
                          </p>
                        {/if}
                        <p class="text-secondary text-xs">{m.widget_source_request_hint()}</p>
                      {/if}
                    {/if}
                  </div>
                </li>
              {/each}
            </ol>
          {/if}
          <span class="sr-only" aria-live="polite"
            >{#key announcement.id}{announcement.text}{/key}</span
          >
        </section>
      {/if}
    {/if}
  </div>
</li>

<style>
  /* A narrow panel on someone else's page: 14px body, tight lists, quiet headings. */
  .widget-answer :global(.prose) {
    font-size: 0.875rem;
    line-height: 1.5;
  }
  .widget-answer :global(.prose > * + *) {
    margin-top: 0.5rem;
  }
  .widget-answer :global(.prose :is(ul, ol)) {
    padding-left: 1.125rem;
    margin-top: 0.25rem;
  }
  .widget-answer :global(.prose li) {
    margin: 0.125rem 0;
  }
  .widget-answer :global(.prose li > p) {
    margin: 0;
  }
  .widget-answer :global(.prose :is(h1, h2, h3, h4)) {
    font-size: 0.9375rem;
    font-weight: 600;
    margin-top: 0.75rem;
  }
  .widget-answer :global(.prose :is(code, pre)) {
    font-size: 0.8125rem;
  }
</style>
