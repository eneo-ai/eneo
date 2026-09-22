<script lang="ts">
  import type { ConversationMessage } from "@eneo/eneo-js";
  import { Markdown } from "@eneo/ui";
  import { sanitizeLinkHref } from "@eneo/ui/components/markdown";
  import { tick } from "svelte";
  import { Check, ChevronRight, Copy, ExternalLink, FileText, X } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import {
    messageSources,
    referenceIndexer,
    setWidgetMessageContext,
    sourceReferenceText,
    type WidgetSource
  } from "../widgetMessageContext";
  import { linkHost } from "../urls";
  import { stepServers, widgetToolSteps } from "../widgetToolSteps";
  import WidgetInref from "./WidgetInref.svelte";
  import InternalToolStep from "$lib/features/chat/components/conversation/InternalToolStep.svelte";
  import TypingIndicator from "$lib/features/chat/components/conversation/TypingIndicator.svelte";

  type Props = {
    message: ConversationMessage;
    index: number;
    isLast: boolean;
    isLoading: boolean;
    /** Off when the widget hides citations and the source list. */
    showSources?: boolean;
  };

  let { message, index, isLast, isLoading, showSources = true }: Props = $props();

  const anchorFor = (sourceIndex: number) => `widget-source-${index}-${sourceIndex}`;
  const listId = $derived(`widget-sources-${index}`);
  const sources = $derived(showSources ? messageSources(message) : []);
  const indexer = $derived(referenceIndexer(message));

  // Collapsed by default: the answer is what the visitor came for, the
  // sources are one click away, and a citation marker opens them in place.
  let expanded = $state(false);
  let copiedId = $state<string | null>(null);
  let copyFailedId = $state<string | null>(null);
  let announcement = $state("");
  let copiedTimer: ReturnType<typeof setTimeout> | null = null;

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
      announcement = m.widget_reference_copied();
      if (copiedTimer) clearTimeout(copiedTimer);
      copiedTimer = setTimeout(() => (copiedId = null), 2000);
    } catch {
      // Clipboard access is denied in some embedding contexts; leave the
      // text on screen so the visitor can select it instead.
      copyFailedId = source.id;
      announcement = m.widget_reference_copy_failed();
    }
  }

  const waiting = $derived(isLast && isLoading && message.answer.trim().length === 0);

  // Tool activity: while the assistant works only the latest step shows and
  // each new call replaces it; once done, several steps fold into one line
  // that opens to the full list. A single step never folds.
  const streaming = $derived(isLast && isLoading);
  const steps = $derived(widgetToolSteps(message, { streaming, working: waiting }));
  const stepsWorking = $derived(
    waiting || steps.some((step) => step.status === "preparing" || step.status === "running")
  );
  const stepsFailed = $derived(
    steps.some((step) => step.status === "failed" || step.status === "denied")
  );
  const foldedSteps = $derived(!stepsWorking && steps.length > 1);
  const visibleSteps = $derived(stepsWorking ? steps.slice(-1) : steps);
  let stepsOpen = $state(false);
  const stepsSummary = $derived(
    `${stepServers(steps).join(" · ")} · ${m.internal_tool_steps_count({ count: steps.length })}`
  );
</script>

<li class="flex flex-col gap-3">
  <div class="flex justify-end">
    <p class="widget-bubble max-w-[85%] rounded-br-sm px-4 py-2 text-base whitespace-pre-wrap">
      <span class="sr-only">{m.widget_you()}: </span>{message.question}
    </p>
  </div>

  <div class="flex flex-col gap-2">
    <span class="sr-only">{m.widget_assistant()}: </span>
    {#if steps.length > 0}
      <div class="flex flex-col gap-0.5" aria-label={m.widget_activity()} role="group">
        {#if foldedSteps}
          <button
            type="button"
            class="text-secondary hover:text-primary focus-visible:ring-accent-default flex w-fit max-w-full items-center gap-1.5 rounded-md text-sm leading-tight focus-visible:ring-2 focus-visible:outline-none"
            aria-expanded={stepsOpen}
            onclick={() => (stepsOpen = !stepsOpen)}
          >
            <ChevronRight
              class={`size-3.5 shrink-0 transition-transform ${stepsOpen ? "rotate-90" : ""}`}
              aria-hidden="true"
            />
            {#if stepsFailed}
              <X class="text-negative-default size-3.5 shrink-0" aria-hidden="true" />
            {/if}
            <span class="truncate">{stepsSummary}</span>
          </button>
        {/if}
        {#if !foldedSteps || stepsOpen}
          <div class={`flex flex-col gap-0.5 ${foldedSteps ? "pl-5" : ""}`}>
            {#each visibleSteps as step, stepIndex (step.toolCallId ?? stepIndex)}
              <InternalToolStep
                runningLabel={step.toolName}
                doneLabel={step.doneLabel}
                serverName={step.serverName}
                detail={step.detail}
                args={step.args}
                status={step.status}
              />
            {/each}
          </div>
        {/if}
      </div>
    {/if}
    {#if waiting && steps.length === 0}
      <TypingIndicator />
    {:else if !waiting}
      <Markdown
        class="text-primary max-w-none text-base"
        source={message.answer}
        customRenderers={{ inref: WidgetInref }}
      />
      {#if sources.length > 0}
        <section aria-label={m.widget_references()} class="border-default mt-1 border-t pt-2">
          <button
            type="button"
            class="text-secondary hover:text-primary focus-visible:ring-accent-default flex items-center gap-1.5 rounded-md text-sm focus-visible:ring-2 focus-visible:outline-none"
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
                  class="border-default focus-visible:ring-accent-default flex items-start gap-2.5 rounded-md border px-2.5 py-2 focus-visible:ring-2 focus-visible:outline-none"
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
                      <span class="text-secondary text-xs">{m.widget_source_document()}</span>
                      <button
                        type="button"
                        class="text-accent-default focus-visible:ring-accent-default mt-1 inline-flex w-fit items-center gap-1 rounded-md text-xs underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:outline-none"
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
                  </div>
                </li>
              {/each}
            </ol>
          {/if}
          <span class="sr-only" aria-live="polite">{announcement}</span>
        </section>
      {/if}
    {/if}
  </div>
</li>

<style>
  .widget-bubble {
    background: var(--widget-accent);
    color: var(--widget-on-accent);
    border-radius: var(--widget-radius);
    border-bottom-right-radius: 4px;
  }
</style>
