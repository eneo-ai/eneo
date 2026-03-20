<script lang="ts">
  import { Markdown } from "@intric/ui";
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
    requirementsConfirmed = false,
    requirementsActive = true,
    onQuestionAnswer = undefined,
    onRequirementsConfirm = undefined,
    onRequirementsChange = undefined,
  }: Props = $props();
</script>

<div class="message-row" class:is-user={role === "user"} class:is-assistant={role === "assistant"} class:message-enter={isLast}>
  {#if role === "user"}
    <!-- User message: right-aligned bubble -->
    <div class="flex justify-end">
      <div class="user-bubble">
        <p class="text-sm leading-relaxed whitespace-pre-wrap">{content}</p>
      </div>
    </div>
  {:else}
    <!-- Assistant message: left-aligned, no bubble -->
    <div class="assistant-message">
      <div class="text-primary prose-sm text-sm leading-relaxed">
        {#if content}
          <Markdown source={content} />
        {/if}
        {#if isStreaming && isLast}
          <span class="streaming-cursor"></span>
        {/if}
      </div>
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
  @reference "@intric/ui/styles";

  .message-row {
    margin-bottom: 1.5rem;
  }

  .message-row.is-assistant {
    margin-top: 0.5rem;
  }

  .user-bubble {
    max-width: min(85%, 36rem);
    border-radius: 1.25rem 1.25rem 0.25rem 1.25rem;
    padding: 0.75rem 1.25rem;
    background: oklch(from var(--accent-default) l c h / 0.08);
    color: var(--text-primary);
    box-shadow: inset 0 1px 0 oklch(1 0 0 / 0.2);
  }

  .assistant-message {
    max-width: 100%;
  }

  /* Enforce consistent text size on Markdown output */
  .assistant-message :global(p),
  .assistant-message :global(li),
  .assistant-message :global(span) {
    font-size: 0.875rem;
    line-height: 1.65;
  }

  /* --- Message entrance animations --- */

  .message-enter.is-user {
    animation: user-enter 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards;
  }

  .message-enter.is-assistant {
    animation: assistant-enter 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards;
  }

  @keyframes user-enter {
    from {
      opacity: 0.6;
      transform: translateX(0.5rem);
    }
    to {
      opacity: 1;
      transform: translateX(0);
    }
  }

  @keyframes assistant-enter {
    from {
      opacity: 0.6;
      transform: translateX(-0.5rem);
    }
    to {
      opacity: 1;
      transform: translateX(0);
    }
  }

  /* Streaming cursor — subtle fading blink */
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
