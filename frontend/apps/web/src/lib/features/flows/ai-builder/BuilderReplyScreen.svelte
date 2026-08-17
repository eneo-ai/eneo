<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Markdown } from "@eneo/ui";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import FlowAIBuilderInput from "./FlowAIBuilderInput.svelte";
  import type { AIBuilderEditContext } from "./protocol";

  /**
   * Discovery turns that carry neither a question nor a summary: Eneo is
   * reading, or replied in prose and waits for the user's next words.
   */
  interface Props {
    waiting: boolean;
    assistantText: string | null;
    editContext?: AIBuilderEditContext | null;
    editContextLabel?: string | null;
    oncleareditcontext?: () => void;
  }

  let {
    waiting,
    assistantText,
    editContext = null,
    editContextLabel = null,
    oncleareditcontext
  }: Props = $props();
</script>

<div class="flex justify-center px-7 pt-6 pb-10 max-sm:px-3 max-sm:pt-4">
  <div class="w-full max-w-[41.25rem] 2xl:max-w-[45.625rem]">
    <!-- With nothing to read and nothing to wait for there is no card: an
         empty box reads as something that failed to load. -->
    {#if waiting || assistantText}
      <div class="border-default bg-primary rounded-xl border p-[1.125rem] max-sm:p-4">
        {#if waiting}
          <p class="text-secondary text-[0.8125rem]" role="status" aria-live="polite">
            {m.ai_builder_reply_reading()}
          </p>
          <div class="mt-3 flex flex-col gap-[0.4375rem]" aria-hidden="true">
            <Skeleton class="bg-tertiary h-[0.6875rem] w-[74%] rounded" />
            <Skeleton class="bg-tertiary h-[0.5625rem] w-[44%] rounded" />
          </div>
        {:else if assistantText}
          <p class="text-secondary text-[0.72rem] font-semibold">
            {m.ai_builder_reply_from_eneo()}
          </p>
          <div class="text-primary mt-1.5 text-[0.9375rem] leading-relaxed">
            <Markdown source={assistantText} />
          </div>
        {/if}
      </div>
    {/if}

    {#if !waiting}
      <div class:mt-3={assistantText}>
        <FlowAIBuilderInput
          {editContext}
          {editContextLabel}
          {oncleareditcontext}
          placeholder={m.ai_builder_reply_placeholder()}
        />
      </div>
    {/if}
  </div>
</div>
