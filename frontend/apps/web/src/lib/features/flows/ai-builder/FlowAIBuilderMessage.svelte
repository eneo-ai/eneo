<script lang="ts">
  import { Markdown } from "@eneo/ui";
  import FlowAIBuilderQuestion from "./FlowAIBuilderQuestion.svelte";
  import FlowAIBuilderRequirementsSummary from "./FlowAIBuilderRequirementsSummary.svelte";
  import type { RequirementsSummary } from "./protocol";
  import type {
    StructuredQuestion,
    StructuredQuestionAnswerPayload
  } from "./structuredQuestionAnswer";

  interface Props {
    role: "user" | "assistant";
    content: string;
    isLast?: boolean;
    isStreaming?: boolean;
    question?: StructuredQuestion;
    questionAnswered?: boolean;
    requirementsSummary?: RequirementsSummary;
    requirementsUserRequest?: string | null;
    requirementsConfirmed?: boolean;
    requirementsActive?: boolean;
    onQuestionAnswer?: (answer: StructuredQuestionAnswerPayload) => void;
    onRequirementsConfirm?: () => void;
    onRequirementsChange?: () => void;
  }

  let {
    role,
    content,
    isLast = false,
    isStreaming = false,
    question = undefined,
    questionAnswered = false,
    requirementsSummary = undefined,
    requirementsUserRequest = null,
    requirementsConfirmed = false,
    requirementsActive = true,
    onQuestionAnswer = undefined,
    onRequirementsConfirm = undefined,
    onRequirementsChange = undefined
  }: Props = $props();
</script>

<div
  class="message-row"
  class:is-user={role === "user"}
  class:is-assistant={role === "assistant"}
  class:message-enter={isLast}
>
  {#if role === "user"}
    <div class="flex justify-end">
      <div class="user-bubble">
        <p class="text-[0.9375rem] leading-relaxed whitespace-pre-wrap">{content}</p>
      </div>
    </div>
  {:else}
    <div class="assistant-message">
      {#if content || (isStreaming && isLast)}
        <div class="assistant-body">
          <span class="assistant-anchor" aria-hidden="true"></span>
          <div class="assistant-prose">
            {#if content}
              <Markdown source={content} />
            {/if}
            {#if isStreaming && isLast}
              <span class="streaming-cursor"></span>
            {/if}
          </div>
        </div>
      {/if}
      {#if question}
        <FlowAIBuilderQuestion
          {question}
          answered={questionAnswered}
          onanswer={(payload) => onQuestionAnswer?.(payload)}
        />
      {/if}
      {#if requirementsSummary}
        <FlowAIBuilderRequirementsSummary
          summary={requirementsSummary}
          userRequest={requirementsUserRequest}
          confirmed={requirementsConfirmed}
          active={requirementsActive}
          onconfirm={requirementsActive ? onRequirementsConfirm : undefined}
          onchange={requirementsActive ? onRequirementsChange : undefined}
        />
      {/if}
    </div>
  {/if}
</div>

<style lang="postcss">
  @reference "@eneo/ui/styles";

  .message-row {
    margin-bottom: 1.25rem;
  }

  .message-row.is-assistant {
    margin-top: 0.25rem;
  }

  .user-bubble {
    max-width: min(72%, 34rem);
    border-radius: 1rem 1rem 0.375rem 1rem;
    padding: 0.625rem 0.9375rem;
    background: var(--bg-secondary);
    border: 1px solid oklch(from var(--border-default) l c h / 0.6);
    color: var(--text-primary);
  }

  .assistant-message {
    max-width: 100%;
  }

  .assistant-body {
    display: flex;
    align-items: flex-start;
    gap: 0.625rem;
  }

  .assistant-anchor {
    display: inline-block;
    flex-shrink: 0;
    margin-top: 0.6875rem;
    width: 0.375rem;
    height: 0.375rem;
    border-radius: 9999px;
    background: var(--border-stronger);
    opacity: 0.7;
  }

  .assistant-prose {
    flex: 1 1 auto;
    min-width: 0;
    color: var(--text-primary);
    font-size: 0.9375rem;
    line-height: 1.65;
  }

  .assistant-prose :global(p),
  .assistant-prose :global(li),
  .assistant-prose :global(span) {
    font-size: 0.9375rem;
    line-height: 1.65;
  }

  .assistant-prose :global(p + p) {
    margin-top: 0.625rem;
  }

  .assistant-prose :global(ul),
  .assistant-prose :global(ol) {
    margin-top: 0.375rem;
    padding-left: 1.25rem;
  }

  .assistant-prose :global(li + li) {
    margin-top: 0.25rem;
  }

  .assistant-prose :global(code) {
    font-size: 0.85em;
    padding: 0.05em 0.3em;
    border-radius: 0.25rem;
    background: var(--bg-secondary);
  }

  .message-enter.is-user {
    animation: user-enter 0.28s cubic-bezier(0.16, 1, 0.3, 1) forwards;
  }

  .message-enter.is-assistant {
    animation: assistant-enter 0.28s cubic-bezier(0.16, 1, 0.3, 1) forwards;
  }

  @keyframes user-enter {
    from {
      opacity: 0.6;
      transform: translateX(0.375rem);
    }
    to {
      opacity: 1;
      transform: translateX(0);
    }
  }

  @keyframes assistant-enter {
    from {
      opacity: 0.6;
      transform: translateX(-0.375rem);
    }
    to {
      opacity: 1;
      transform: translateX(0);
    }
  }

  .streaming-cursor {
    display: inline-block;
    width: 2px;
    height: 1em;
    margin-left: 2px;
    vertical-align: text-bottom;
    background: var(--accent-default);
    border-radius: 1px;
    animation: cursor-blink 1s ease-in-out infinite;
  }

  @keyframes cursor-blink {
    0%,
    100% {
      opacity: 0;
    }
    50% {
      opacity: 1;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .streaming-cursor,
    .message-enter.is-user,
    .message-enter.is-assistant {
      animation: none;
    }

    .streaming-cursor {
      opacity: 0.6;
    }

    .message-enter {
      opacity: 1;
    }
  }
</style>
