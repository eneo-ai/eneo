<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import * as Sheet from "$lib/components/ui/sheet/index.js";
  import FlowAIBuilderChat from "./FlowAIBuilderChat.svelte";
  import type { AIBuilderSuggestChangeIntent } from "./protocol";

  interface Props {
    open?: boolean;
    /** The phase screen currently owns the composer; the sheet then only shows the transcript. */
    showComposer?: boolean;
    oneditanswer?: (questionId: string) => void;
  }

  let { open = $bindable(false), showComposer = true, oneditanswer }: Props = $props();

  let chatRef = $state<FlowAIBuilderChat | undefined>();

  /** Open the sheet and focus its composer, e.g. for a change request. */
  export async function focusComposer(intent?: string | AIBuilderSuggestChangeIntent) {
    open = true;
    // The sheet content mounts on open; give it a frame before focusing.
    await new Promise((resolve) => requestAnimationFrame(resolve));
    chatRef?.focusInput(intent);
  }

  export function resetComposerContext() {
    chatRef?.resetComposerContext();
  }
</script>

<Sheet.Root bind:open>
  <Sheet.Content
    side="right"
    class="bg-primary flex w-full max-w-full flex-col gap-0 p-0 sm:max-w-[26rem]"
    aria-label={m.ai_builder_conversation_aria()}
  >
    <Sheet.Header class="border-default gap-0.5 border-b px-4 py-3.5 pr-12">
      <Sheet.Title class="text-[0.9375rem] font-bold"
        >{m.ai_builder_conversation_title()}</Sheet.Title
      >
      <Sheet.Description class="text-secondary text-xs">
        {m.ai_builder_conversation_subtitle()}
      </Sheet.Description>
    </Sheet.Header>
    <FlowAIBuilderChat bind:this={chatRef} {showComposer} {oneditanswer} />
    <Sheet.Footer class="border-default border-t px-4 py-3 sm:flex-col">
      <p class="text-secondary text-xs text-pretty">{m.ai_builder_conversation_footnote()}</p>
    </Sheet.Footer>
  </Sheet.Content>
</Sheet.Root>
