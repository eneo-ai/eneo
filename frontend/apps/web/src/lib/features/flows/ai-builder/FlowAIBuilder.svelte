<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import FlowAIBuilderChat from "./FlowAIBuilderChat.svelte";
  import FlowAIBuilderDraftRecovery from "./FlowAIBuilderDraftRecovery.svelte";
  import FlowAIBuilderPlanPane from "./FlowAIBuilderPlanPane.svelte";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import { onMount } from "svelte";

  interface Props {
    targetKind?: "create" | "edit";
    onapplied?: (detail: { flow_id: string; focusStepIndex: number | null }) => void;
  }

  let { targetKind = "edit", onapplied }: Props = $props();

  const service = getAIBuilderService();

  let chatRef = $state<FlowAIBuilderChat | undefined>();
  let wasAutoResumed = $state(false);

  // Keep plan pane visible during streaming (plan rebuild) so it doesn't flash away
  let hadPlanBefore = $state(false);

  $effect(() => {
    if (service.currentPlan !== null) {
      hadPlanBefore = true;
    }
    // Reset when session changes (fresh start)
    if (!service.hasSession) {
      hadPlanBefore = false;
    }
  });

  const hasPlanContent = $derived(
    service.currentPlan !== null ||
      service.isConflict ||
      service.statusMessage !== null ||
      (hadPlanBefore && service.isStreaming)
  );

  // For single-draft: show draft page only when 2+ drafts
  const showDraftPage = $derived(
    targetKind === "create" && !service.hasSession && service.recoverableCreateDrafts.length >= 2
  );

  // Single draft: auto-resume
  $effect(() => {
    if (
      targetKind === "create" &&
      !service.hasSession &&
      !service.isInitializing &&
      service.recoverableCreateDrafts.length === 1
    ) {
      const draft = service.recoverableCreateDrafts[0];
      if (draft) {
        wasAutoResumed = true;
        void service.resumeSession(draft.session_id);
      }
    }
  });

  onMount(() => {
    if (!service.hasSession) {
      void service.initialize(targetKind);
    }
  });
</script>

{#if service.isInitializing}
  <!-- Loading skeleton using shadcn Skeleton -->
  <div class="flex flex-1 flex-col gap-8 p-6" aria-hidden="true">
    <Skeleton class="h-10 w-full rounded-lg" />
    <div class="flex flex-col gap-3">
      <Skeleton class="h-4 w-4/5 rounded" />
      <Skeleton class="h-4 w-3/5 rounded" />
      <Skeleton class="h-4 w-2/5 rounded" />
    </div>
  </div>
{:else if showDraftPage}
  <FlowAIBuilderDraftRecovery
    drafts={service.recoverableCreateDrafts}
    onresume={(sessionId) => service.resumeSession(sessionId)}
    onstartfresh={() => service.startFreshSession("create")}
    ondiscard={(sessionId) => service.discardSession(sessionId)}
  />
{:else}
  <div class="flex min-h-0 w-full flex-1 flex-col">
    <!-- Resume banner -->
    {#if wasAutoResumed && service.hasSession && service.messages.length > 0}
      <div
        class="animate-in slide-in-from-top border-default bg-secondary flex items-center gap-2 border-b px-4 py-2 text-[0.8125rem]"
      >
        <span class="text-secondary flex items-center gap-1.5">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 16 16"
            fill="currentColor"
            class="size-3.5"
          >
            <path
              fill-rule="evenodd"
              d="M13.836 2.477a.75.75 0 0 1 .75.75v3.182a.75.75 0 0 1-.75.75h-3.182a.75.75 0 0 1 0-1.5h1.37l-.84-.841a4.5 4.5 0 0 0-7.08.932.75.75 0 0 1-1.3-.75 6 6 0 0 1 9.44-1.242l.842.84V3.227a.75.75 0 0 1 .75-.75Zm-.911 7.5A.75.75 0 0 1 13.199 11a6 6 0 0 1-9.44 1.241l-.84-.84v1.371a.75.75 0 0 1-1.5 0V9.591a.75.75 0 0 1 .75-.75H5.35a.75.75 0 0 1 0 1.5H3.98l.841.841a4.5 4.5 0 0 0 7.08-.932.75.75 0 0 1 1.025-.273Z"
              clip-rule="evenodd"
            />
          </svg>
          {m.ai_builder_resumed_from()}
        </span>
        <button
          class="text-accent-default text-[0.8125rem] font-medium hover:underline"
          onclick={() => {
            wasAutoResumed = false;
            service.startFreshSession("create");
          }}
        >
          {m.ai_builder_resumed_start_fresh()}
        </button>
        <button
          class="text-muted hover:bg-hover-default hover:text-primary ml-auto flex size-6 items-center justify-center rounded transition-colors"
          onclick={() => {
            wasAutoResumed = false;
          }}
          aria-label={m.ai_builder_dismiss()}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 16 16"
            fill="currentColor"
            class="size-3"
          >
            <path
              d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 1 0 1.06 1.06L8 9.06l2.72 2.72a.75.75 0 1 0 1.06-1.06L9.06 8l2.72-2.72a.75.75 0 0 0-1.06-1.06L8 6.94 5.28 4.22Z"
            />
          </svg>
        </button>
      </div>
    {/if}

    <div class="bg-primary flex min-h-0 flex-1">
      <!-- Chat Pane -->
      <div
        class="flex min-h-0 min-w-0 flex-col transition-[width] duration-400 ease-[cubic-bezier(0.16,1,0.3,1)] {hasPlanContent
          ? 'w-full md:w-[45%] md:min-w-[380px]'
          : 'w-full'}"
      >
        <FlowAIBuilderChat bind:this={chatRef} {targetKind} />
      </div>

      <!-- Plan Pane — slides in when plan arrives -->
      {#if hasPlanContent}
        <div
          class="animate-in slide-in-from-right-8 border-default bg-primary hidden min-h-0 flex-1 flex-col overflow-hidden border-l md:flex"
        >
          <FlowAIBuilderPlanPane
            onapplied={(detail) => onapplied?.(detail)}
            onsuggestchange={(prefill) => chatRef?.focusInput(prefill)}
          />
        </div>
      {/if}
    </div>
  </div>
{/if}
