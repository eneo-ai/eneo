<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import FlowAIBuilderInput from "./FlowAIBuilderInput.svelte";
  import type { AIBuilderEditContext } from "./protocol";

  interface Props {
    targetKind: "create" | "edit";
    /** Other unfinished drafts in this space (the current session excluded). */
    otherDraftCount?: number;
    flowsHref: string;
    editContext?: AIBuilderEditContext | null;
    editContextLabel?: string | null;
    oncleareditcontext?: () => void;
  }

  let {
    targetKind,
    otherDraftCount = 0,
    flowsHref,
    editContext = null,
    editContextLabel = null,
    oncleareditcontext
  }: Props = $props();

  let inputRef = $state<FlowAIBuilderInput | undefined>();

  export function focusInput(options?: { placeholder?: string; prefill?: string }) {
    inputRef?.focus(options);
  }

  // Examples write a full description into the field, so a first-time user
  // sees what a good task sounds like instead of guessing.
  const examples: { label: () => string; text: () => string }[] = [
    { label: m.flow_create_example_summarize, text: m.ai_builder_example_summarize_text },
    { label: m.flow_create_example_review, text: m.ai_builder_example_review_text },
    { label: m.ai_builder_example_transcribe, text: m.ai_builder_example_transcribe_text },
    { label: m.flow_create_example_decision, text: m.ai_builder_example_decision_text }
  ];

  const isEdit = $derived(targetKind === "edit");
</script>

<!-- Anchored a little below the rail rather than centred: on a tall screen a
     centred prompt floats half a viewport down, and the composer is the
     first thing the reader should reach. -->
<div
  class="flex flex-1 justify-center px-7 pt-[clamp(2.5rem,14vh,7.5rem)] pb-8 max-sm:px-3 max-sm:pt-6 max-sm:pb-5"
>
  <div class="task-screen w-full max-w-[40.625rem] 2xl:max-w-[45rem]">
    <h2
      class="text-primary text-[1.6875rem] leading-tight font-extrabold tracking-[-0.03em] text-pretty"
    >
      {isEdit ? m.ai_builder_task_title_edit() : m.ai_builder_task_title()}
    </h2>
    <p class="text-secondary mt-2 max-w-[54ch] text-[0.9rem] leading-relaxed text-pretty">
      {isEdit ? m.ai_builder_edit_promise() : m.ai_builder_task_intro()}
    </p>

    <div class="mt-5">
      <FlowAIBuilderInput
        bind:this={inputRef}
        {editContext}
        {editContextLabel}
        {oncleareditcontext}
        placeholder={isEdit
          ? m.ai_builder_task_placeholder_edit()
          : m.ai_builder_task_placeholder()}
      />
    </div>
    <p class="text-secondary mt-2 px-0.5 text-xs">{m.ai_builder_task_model_note()}</p>

    {#if !isEdit}
      <div class="mt-4 flex flex-wrap items-center gap-2">
        <span class="text-secondary text-xs">{m.ai_builder_task_examples_label()}</span>
        {#each examples as example (example.label())}
          <Button
            variant="outline"
            size="sm"
            class="rounded-full font-normal max-sm:h-[44px]"
            onclick={() => inputRef?.focus({ prefill: example.text() })}
          >
            {example.label()}
          </Button>
        {/each}
      </div>

      <div
        class="border-default mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 border-t pt-4 text-xs"
      >
        {#if otherDraftCount > 0}
          <span class="text-secondary">{m.ai_builder_task_drafts_question()}</span>
          <Button variant="link" class="h-auto p-0 text-xs font-semibold" href={flowsHref}>
            {otherDraftCount === 1
              ? m.ai_builder_task_drafts_link_one()
              : m.ai_builder_task_drafts_link({ count: String(otherDraftCount) })}
          </Button>
        {/if}
        <span class="text-secondary ml-auto max-sm:ml-0">
          {m.ai_builder_task_manual_question()}
          <Button variant="link" class="h-auto p-0 text-xs font-semibold" href={flowsHref}>
            {m.ai_builder_task_manual_link()}
          </Button>
        </span>
      </div>
    {/if}
  </div>
</div>

<style lang="postcss">
  .task-screen {
    animation: builder-screen-in 0.22s cubic-bezier(0.16, 1, 0.3, 1);
  }
  @keyframes builder-screen-in {
    from {
      opacity: 0.4;
      transform: translateY(6px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .task-screen {
      animation: none;
    }
  }
</style>
