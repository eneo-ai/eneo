<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import IconArrowLeft from "@lucide/svelte/icons/arrow-left";
  import FlowAIBuilderChat from "./FlowAIBuilderChat.svelte";
  import type { AIBuilderSuggestChangeIntent } from "./protocol";

  /**
   * The whole conversation, in the same column as every other phase screen.
   * It is a screen and not a panel over one: the transcript is where the user
   * reads and changes an earlier answer, and nothing behind it stays half
   * visible while they do.
   */
  interface Props {
    oneditanswer?: (questionId: string) => void;
    onclose?: () => void;
  }

  let { oneditanswer, onclose }: Props = $props();

  let chatRef = $state<FlowAIBuilderChat | undefined>();

  export async function focusComposer(intent?: string | AIBuilderSuggestChangeIntent) {
    await new Promise((resolve) => requestAnimationFrame(resolve));
    chatRef?.focusInput(intent);
  }

  export function resetComposerContext() {
    chatRef?.resetComposerContext();
  }
</script>

<div class="conversation-screen flex justify-center px-7 pt-6 pb-10 max-sm:px-3 max-sm:pt-4">
  <div class="flex w-full max-w-[43.75rem] flex-col 2xl:max-w-[48.125rem]">
    <div class="mb-3 flex flex-wrap items-center gap-3">
      <div class="min-w-0">
        <h2
          class="text-primary text-[0.9375rem] font-bold"
          tabindex="-1"
          data-builder-screen-heading
        >
          {m.ai_builder_conversation_title()}
        </h2>
        <p class="text-secondary text-xs">{m.ai_builder_conversation_subtitle()}</p>
      </div>
      <Button variant="outline" size="sm" class="ml-auto gap-1.5" onclick={() => onclose?.()}>
        <IconArrowLeft class="size-3.5" aria-hidden="true" />
        {m.ai_builder_conversation_back()}
      </Button>
    </div>

    <div class="border-default bg-primary flex min-h-0 flex-col overflow-hidden rounded-xl border">
      <FlowAIBuilderChat bind:this={chatRef} {oneditanswer} />
      <p class="border-default text-secondary border-t px-4 py-3 text-xs text-pretty">
        {m.ai_builder_conversation_footnote()}
      </p>
    </div>
  </div>
</div>

<style lang="postcss">
  .conversation-screen {
    animation: conversation-fade 0.16s ease-out;
  }
  @keyframes conversation-fade {
    from {
      opacity: 0;
    }
    to {
      opacity: 1;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .conversation-screen {
      animation: none;
    }
  }
</style>
