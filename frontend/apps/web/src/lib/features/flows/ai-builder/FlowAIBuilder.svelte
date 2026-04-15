<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { fade } from "svelte/transition";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
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

  function handleDismissResumeBanner() {
    wasAutoResumed = false;
  }

  function handleStartFreshFromResume() {
    wasAutoResumed = false;
    service.startFreshSession("create");
  }
</script>

{#if service.isInitializing}
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
  <div class="bg-primary flex w-full flex-1 flex-col max-md:overflow-y-auto md:min-h-0">
    <!-- Auto-resume banner: inline Alert, flex row, no absolute positioning -->
    {#if wasAutoResumed && service.hasSession && service.messages.length > 0}
      <div
        class="w-full shrink-0 px-4 pt-3 max-sm:px-3 max-sm:pt-2"
        transition:fade={{ duration: 180 }}
      >
        <Alert.Root
          class="border-default bg-secondary flex items-center gap-3 rounded-lg px-3.5 py-2.5"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 16 16"
            fill="currentColor"
            class="text-accent-default size-4 shrink-0"
            aria-hidden="true"
          >
            <path
              fill-rule="evenodd"
              d="M13.836 2.477a.75.75 0 0 1 .75.75v3.182a.75.75 0 0 1-.75.75h-3.182a.75.75 0 0 1 0-1.5h1.37l-.84-.841a4.5 4.5 0 0 0-7.08.932.75.75 0 0 1-1.3-.75 6 6 0 0 1 9.44-1.242l.842.84V3.227a.75.75 0 0 1 .75-.75Zm-.911 7.5A.75.75 0 0 1 13.199 11a6 6 0 0 1-9.44 1.241l-.84-.84v1.371a.75.75 0 0 1-1.5 0V9.591a.75.75 0 0 1 .75-.75H5.35a.75.75 0 0 1 0 1.5H3.98l.841.841a4.5 4.5 0 0 0 7.08-.932.75.75 0 0 1 1.025-.273Z"
              clip-rule="evenodd"
            />
          </svg>
          <Alert.Description class="text-primary min-w-0 flex-1 text-[0.8125rem] leading-relaxed">
            {m.ai_builder_resumed_from()}
          </Alert.Description>
          <div class="flex shrink-0 items-center gap-1">
            <Button variant="ghost" size="xs" onclick={handleStartFreshFromResume}>
              {m.ai_builder_resumed_start_fresh()}
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={m.ai_builder_dismiss()}
              onclick={handleDismissResumeBanner}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 16 16"
                fill="currentColor"
                aria-hidden="true"
              >
                <path
                  d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 1 0 1.06 1.06L8 9.06l2.72 2.72a.75.75 0 1 0 1.06-1.06L9.06 8l2.72-2.72a.75.75 0 0 0-1.06-1.06L8 6.94 5.28 4.22Z"
                />
              </svg>
            </Button>
          </div>
        </Alert.Root>
      </div>
    {/if}

    <!--
      Layout strategy:
      - <md: chat + plan stack vertically (plan inline below chat). User scrolls.
      - md → 2xl: side-by-side, chat ~45% / plan flex-1.
      - >2xl (≥1536px): cap the whole builder shell at max-w-[1680px] centered to avoid sparse ultra-wide layouts.
      No width transitions (per design system: avoid animating layout properties).
    -->
    <div
      class="flex flex-col md:min-h-0 md:flex-1 md:flex-row 2xl:mx-auto 2xl:w-full 2xl:max-w-[1680px]"
    >
      <!-- Chat pane -->
      <div
        class="flex min-w-0 flex-col md:min-h-0 {hasPlanContent
          ? 'md:w-[45%] md:max-w-[640px] md:min-w-[380px]'
          : 'w-full'}"
      >
        <FlowAIBuilderChat bind:this={chatRef} {targetKind} />
      </div>

      <!--
        Plan pane:
        - <md: stacks below chat with NATURAL height (page scrolls)
        - md+: side-by-side, flex-1, internal scroll
      -->
      {#if hasPlanContent}
        <div
          class="border-default bg-primary border-t md:flex md:min-h-0 md:flex-1 md:flex-col md:overflow-hidden md:border-t-0 md:border-l"
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
