<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.

    Turns of the insights chat. Built only from context-free chat pieces
    (InternalToolStep, ReasoningTrace, TypingIndicator, Markdown) so it never
    reaches for the regular ChatService. Session citations in the answer
    become links that open the cited conversation.
-->

<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Markdown } from "@eneo/ui";
  import InternalToolStep from "$lib/features/chat/components/conversation/InternalToolStep.svelte";
  import ReasoningTrace from "$lib/features/chat/components/conversation/ReasoningTrace.svelte";
  import TypingIndicator from "$lib/features/chat/components/conversation/TypingIndicator.svelte";
  import {
    internalToolDoneLabel,
    serverDisplayName,
    toolDisplayName
  } from "$lib/features/chat/internalToolLabels";
  import type { InsightsChatMessage, InsightsToolCall } from "../InsightsChatService.svelte";
  import { citedSessionId, linkSessionCitations } from "../sessionCitations";

  type Props = {
    messages: InsightsChatMessage[];
    /** True while the last message is still streaming. */
    isStreaming: boolean;
    /** Loads one tool call's result text for the expandable step. */
    loadToolResult?: (toolCallId: string) => Promise<string | null>;
    /** Called when the operator clicks a cited conversation. */
    onOpenSession?: (sessionId: string) => void;
  };

  let { messages, isStreaming, loadToolResult, onOpenSession }: Props = $props();

  type StepStatus = "preparing" | "running" | "complete" | "failed" | "denied";

  function stepStatus(
    call: InsightsToolCall,
    isLastCall: boolean,
    streamingTurn: boolean,
    answerStarted: boolean
  ): StepStatus {
    if (call.approved === false || call.result_status === "denied") return "denied";
    if (call.result_status === "failed") return "failed";
    // "pending" = the model is still writing the arguments; "approved" = the
    // call is executing. A pending call on a turn that is no longer streaming
    // never ran, so it is shown as failed rather than spinning forever.
    if (call.result_status === "pending") return streamingTurn ? "preparing" : "failed";
    if (call.result_status === "approved" && streamingTurn) return "running";
    if (streamingTurn && !answerStarted && isLastCall) return "running";
    return "complete";
  }

  // The markdown link renderer opens every link in a new tab; a citation
  // link is intercepted here before that happens and opened in the preview.
  // Attached as a delegated listener: the anchors themselves stay the
  // keyboard-accessible controls, the wrapper is not interactive.
  function interceptCitations(node: HTMLElement) {
    const handle = (event: MouseEvent) => {
      const anchor = (event.target as HTMLElement | null)?.closest("a");
      const sessionId = citedSessionId(anchor?.getAttribute("href"));
      if (!anchor || !sessionId) return;
      event.preventDefault();
      onOpenSession?.(sessionId);
    };
    node.addEventListener("click", handle);
    return () => node.removeEventListener("click", handle);
  }
</script>

<ol class="flex flex-col gap-6" aria-live="polite">
  {#each messages as message, index (index)}
    {@const streamingTurn = isStreaming && index === messages.length - 1}
    {@const answerStarted = message.answer.trim().length > 0}
    <li class="flex flex-col gap-3">
      <div class="flex justify-end">
        <p
          class="bg-secondary text-primary max-w-[85%] rounded-2xl rounded-br-md px-4 py-2.5 text-base whitespace-pre-wrap"
        >
          {message.question}
        </p>
      </div>

      <div class="flex flex-col gap-1">
        {#if message.reasoning.trim().length > 0}
          <div class="mb-2">
            <ReasoningTrace
              reasoning={message.reasoning}
              working={streamingTurn && !answerStarted}
            />
          </div>
        {/if}

        {#each message.toolCalls as call, callIndex (call.tool_call_id ?? callIndex)}
          {@const args = call.arguments ?? undefined}
          {@const runningLabel = toolDisplayName(
            call.tool_name,
            call.server_name,
            call.title,
            args
          )}
          {@const toolCallId = call.tool_call_id ?? undefined}
          <InternalToolStep
            {runningLabel}
            doneLabel={internalToolDoneLabel(call.tool_name, call.server_name, args) ??
              runningLabel}
            serverName={serverDisplayName(call.server_name)}
            {args}
            {toolCallId}
            status={stepStatus(
              call,
              callIndex === message.toolCalls.length - 1,
              streamingTurn,
              answerStarted
            )}
            onLoadResult={toolCallId && loadToolResult
              ? () => loadToolResult(toolCallId)
              : undefined}
          />
        {/each}

        {#if answerStarted}
          <div class="prose max-w-[70ch] pt-2" {@attach interceptCitations}>
            <Markdown
              source={linkSessionCitations(message.answer, m.insights_chat_cited_conversation())}
            ></Markdown>
          </div>
        {:else if streamingTurn}
          <div class="flex items-center gap-3 pt-2">
            <TypingIndicator />
            <span class="text-secondary text-sm">{m.insights_chat_analyzing()}</span>
          </div>
        {/if}

        {#if message.error}
          <p class="text-negative-default pt-2 text-sm" role="alert">
            {message.error === "insights_model_unavailable"
              ? m.insights_chat_model_unavailable()
              : m.insights_chat_error()}
          </p>
        {/if}
      </div>
    </li>
  {/each}
</ol>
