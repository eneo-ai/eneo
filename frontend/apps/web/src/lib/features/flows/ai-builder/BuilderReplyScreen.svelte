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
  <div class="w-full max-w-[47.5rem] 2xl:max-w-[53.75rem]">
    <div class="border-default bg-primary rounded-xl border p-[1.125rem] max-sm:p-4">
      {#if waiting}
        <p class="text-secondary text-[0.8125rem]" role="status" aria-live="polite">
          {m.ai_builder_reply_reading()}
        </p>
        <div class="mt-3 flex flex-col gap-2" aria-hidden="true">
          <Skeleton class="h-3 w-3/4 rounded" />
          <Skeleton class="h-3 w-1/2 rounded" />
        </div>
      {:else if assistantText}
        <p class="text-secondary text-[0.72rem] font-semibold">{m.ai_builder_reply_from_eneo()}</p>
        <div class="text-primary mt-1.5 text-[0.9375rem] leading-relaxed">
          <Markdown source={assistantText} />
        </div>
      {/if}
    </div>
    {#if !waiting}
      <div class="mt-3">
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
