<script lang="ts">
  import type { ConversationMessage } from "@eneo/eneo-js";
  import { Markdown } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import {
    messageSources,
    referenceIndexer,
    setWidgetMessageContext
  } from "../widgetMessageContext";
  import WidgetInref from "./WidgetInref.svelte";
  import TypingIndicator from "$lib/features/chat/components/conversation/TypingIndicator.svelte";

  type Props = {
    message: ConversationMessage;
    index: number;
    isLast: boolean;
    isLoading: boolean;
  };

  let { message, index, isLast, isLoading }: Props = $props();

  const anchorFor = (sourceIndex: number) => `widget-source-${index}-${sourceIndex}`;
  const sources = $derived(messageSources(message));
  const indexer = $derived(referenceIndexer(message));

  setWidgetMessageContext({
    referenceIndex: (id) => indexer(id),
    referenceAnchor: anchorFor
  });

  const waiting = $derived(isLast && isLoading && message.answer.trim().length === 0);
</script>

<li class="flex flex-col gap-3">
  <div class="flex justify-end">
    <p
      class="bg-accent-dimmer text-primary max-w-[85%] rounded-2xl rounded-br-sm px-4 py-2 text-base whitespace-pre-wrap"
    >
      <span class="sr-only">{m.widget_you()}: </span>{message.question}
    </p>
  </div>

  <div class="flex flex-col gap-2">
    <span class="sr-only">{m.widget_assistant()}: </span>
    {#if waiting}
      <TypingIndicator />
    {:else}
      <Markdown
        class="text-primary max-w-none text-base"
        source={message.answer}
        customRenderers={{ inref: WidgetInref }}
      />
      {#if sources.length > 0}
        <section aria-label={m.widget_references()} class="mt-1">
          <h2 class="text-secondary mb-1 text-xs font-semibold tracking-wide uppercase">
            {m.widget_references()}
          </h2>
          <ol class="flex flex-col gap-1 text-sm">
            {#each sources as source, sourceIndex (source.id)}
              <li id={anchorFor(sourceIndex)} class="flex gap-2">
                <span class="text-secondary tabular-nums">{sourceIndex + 1}.</span>
                {#if source.url}
                  <!-- eslint-disable svelte/no-navigation-without-resolve -- external source URL from reference metadata -->
                  <a
                    class="text-accent-default break-words underline-offset-2 hover:underline"
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {source.title}
                    <span class="sr-only"> ({m.widget_open_source()})</span>
                  </a>
                {:else}
                  <span class="text-primary break-words">{source.title}</span>
                {/if}
              </li>
            {/each}
          </ol>
        </section>
      {/if}
    {/if}
  </div>
</li>
