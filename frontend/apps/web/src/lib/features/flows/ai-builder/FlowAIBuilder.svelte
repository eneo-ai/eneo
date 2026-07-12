<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { fade } from "svelte/transition";
  import { SvelteSet } from "svelte/reactivity";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import FlowAIBuilderChat from "./FlowAIBuilderChat.svelte";
  import FlowAIBuilderDraftRecovery from "./FlowAIBuilderDraftRecovery.svelte";
  import FlowAIBuilderPhaseIndicator from "./FlowAIBuilderPhaseIndicator.svelte";
  import FlowAIBuilderPlanPane from "./FlowAIBuilderPlanPane.svelte";
  import { shouldShowEditStartOver } from "./flowAIBuilderReset";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import type { AIBuilderSuggestChangeIntent } from "./protocol";
  import { onMount } from "svelte";

  interface Props {
    targetKind?: "create" | "edit";
    onapplied?: (detail: { flow_id: string; focusStepIndex: number | null }) => void;
    initialPrompt?: string | null;
  }

  let { targetKind = "edit", onapplied, initialPrompt = null }: Props = $props();

  const service = getAIBuilderService();

  let chatRef = $state<FlowAIBuilderChat | undefined>();
  let wasAutoResumed = $state(false);
  // One-shot seed: only the value present at mount matters, by design.
  // svelte-ignore state_referenced_locally
  let pendingPrefill = $state(initialPrompt);

  const hasPlanContent = $derived(
    service.currentPlan !== null ||
      service.isConflict ||
      service.statusMessage !== null ||
      (service.hasSeenPlanInSession && service.isStreaming)
  );

  // Narrow-container view state. Both panes stay mounted at every width so
  // drafts, scroll positions and open sections survive switching; below the
  // split threshold only the active one is displayed.
  let activePane = $state<"task" | "plan">("task");
  let hadPlanContent = false;

  $effect(() => {
    if (hasPlanContent && !hadPlanContent) {
      // The plan pane also hosts the generation wait state, so the first
      // appearance of plan content pulls narrow layouts over to it.
      activePane = "plan";
    } else if (!hasPlanContent) {
      activePane = "task";
    }
    hadPlanContent = hasPlanContent;
  });

  const canStartOver = $derived(
    shouldShowEditStartOver({
      targetKind,
      hasSession: service.hasSession,
      messageCount: service.messages.length,
      hasPlan: service.currentPlan !== null,
      isConflict: service.isConflict,
      statusMessage: service.statusMessage,
      hasApplyError: service.applyError !== null,
      hasApplyResult: service.applyResult !== null,
      isStreaming: service.isStreaming
    })
  );

  const answeredQuestionCount = $derived.by(() => {
    const ids = new SvelteSet<string>();
    for (const msg of service.messages) {
      const qa =
        msg.metadata && typeof msg.metadata === "object" && "question_answer" in msg.metadata
          ? msg.metadata.question_answer
          : null;
      if (
        qa &&
        typeof qa === "object" &&
        "question_id" in qa &&
        typeof qa.question_id === "string"
      ) {
        ids.add(qa.question_id);
      }
    }
    return ids.size;
  });

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
      // A seeded prompt from the create dialog always starts a fresh session:
      // initialize() would otherwise defer to draft recovery and the seed
      // could silently attach to (or be ignored by) an old draft.
      if (targetKind === "create" && pendingPrefill) {
        void service.startFreshSession("create");
      } else {
        void service.initialize(targetKind);
      }
    }
  });

  $effect(() => {
    if (pendingPrefill && service.hasSession && !service.isInitializing && chatRef) {
      chatRef.focusInput({ prefill: pendingPrefill });
      pendingPrefill = null;
    }
  });

  function handleDismissResumeBanner() {
    wasAutoResumed = false;
  }

  function handleStartFreshFromResume() {
    wasAutoResumed = false;
    service.startFreshSession("create");
  }

  function handleStartOver() {
    chatRef?.resetComposerContext();
    void service.startFreshSession("edit");
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
  <!--
    Layout contract (docs/flows/plan-review-handoff.md §1). All thresholds are
    container queries on this element ("builder") — the app shell has a
    collapsible sidebar, so viewport breakpoints would lie about available width.
    - ≥1040px container: split view. Page never scrolls; each pane owns its scroll.
    - <1040px: Uppgift/Plan switcher; the active pane owns the page scroll.
    - ≥1760px: workspace capped and centered; header content aligns to the same cap.
  -->
  <!-- The container element itself cannot respond to its own query, so the
       size-dependent scroll behavior lives on the inner wrapper below. -->
  <div class="bg-primary @container/builder flex min-h-0 w-full flex-1 flex-col">
    <!-- Narrow-layout page scroll owner. Scroll padding keeps focused controls
         clear of the sticky header group (top) and the sticky composer or
         action bar (bottom) when the browser scrolls them into view (§1.3).
         Clearance values live in the builder-page-scroll style block. -->
    <div
      class="builder-page-scroll flex min-h-0 w-full flex-1 flex-col overflow-y-auto break-words hyphens-auto @[1040px]/builder:overflow-hidden"
    >
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

      <!-- Phase bar + pane switcher: stuck below the page header while the
           page scrolls in the narrow layouts (§1.4); static in split view,
           where the page never scrolls. -->
      <div class="bg-primary sticky top-0 z-20 w-full shrink-0 @[1040px]/builder:static">
        {#if service.messages.length > 0 || canStartOver}
          <div class="border-border-default w-full shrink-0 border-b">
            <div
              class="flex w-full items-center @[1760px]/builder:mx-auto @[1760px]/builder:max-w-[1760px]"
            >
              {#if service.messages.length > 0}
                <div class="min-w-0 flex-1">
                  <FlowAIBuilderPhaseIndicator
                    phase={service.phase}
                    answeredCount={answeredQuestionCount}
                  />
                </div>
              {:else}
                <div class="min-h-0 flex-1" aria-hidden="true"></div>
              {/if}

              {#if canStartOver}
                <div class="shrink-0 pr-4 max-sm:pr-3">
                  <Button
                    variant="outline"
                    size="sm"
                    onclick={handleStartOver}
                    disabled={service.isCreating}
                  >
                    {m.ai_builder_start_fresh()}
                  </Button>
                </div>
              {/if}
            </div>
          </div>
        {/if}

        <!--
      Uppgift/Plan switcher (<1040px container only). Toggle buttons rather
      than ARIA tabs on purpose: the panes are permanent layout regions that
      both render in the split view, so tagging them role="tabpanel" would be
      wrong at desktop widths, and roles cannot be container-query-conditional.
    -->
        {#if hasPlanContent}
          <div
            class="border-border-default flex w-full shrink-0 items-stretch border-b px-4 max-sm:px-3 @[1040px]/builder:hidden"
            role="group"
            aria-label={m.ai_builder_pane_switcher_aria()}
          >
            <button
              type="button"
              class="pane-tab"
              class:selected={activePane === "task"}
              aria-pressed={activePane === "task"}
              aria-controls="ai-builder-task-pane"
              onclick={() => (activePane = "task")}
            >
              {m.ai_builder_pane_tab_task()}
            </button>
            <button
              type="button"
              class="pane-tab"
              class:selected={activePane === "plan"}
              aria-pressed={activePane === "plan"}
              aria-controls="ai-builder-plan-pane"
              onclick={() => (activePane = "plan")}
            >
              {m.ai_builder_pane_tab_plan()}
            </button>
          </div>
        {/if}
      </div>

      <!-- Workspace: split at ≥1040, capped and centered at ≥1760 -->
      <div
        class="flex w-full flex-1 flex-col @[1040px]/builder:min-h-0 @[1040px]/builder:flex-row @[1760px]/builder:mx-auto @[1760px]/builder:max-w-[1760px]"
      >
        <!-- Task pane (conversation + composer). Fixed clamped width in split view:
           growing screens get whitespace, not a wider pane. -->
        <div
          id="ai-builder-task-pane"
          class="flex min-w-0 flex-col @[1040px]/builder:flex @[1040px]/builder:min-h-0 {hasPlanContent
            ? '@[1040px]/builder:w-[clamp(340px,37cqw,480px)] @[1040px]/builder:shrink-0 @[1180px]/builder:w-[clamp(380px,37cqw,480px)]'
            : 'w-full'}"
          class:hidden={hasPlanContent && activePane !== "task"}
        >
          <FlowAIBuilderChat bind:this={chatRef} {targetKind} />
        </div>

        <!-- Plan pane: owns its scroll in split view; the split border lives here
           so it stays inside the capped workspace on ultrawide screens. -->
        {#if hasPlanContent}
          <div
            id="ai-builder-plan-pane"
            class="border-border-default bg-primary flex min-w-0 flex-col border-t @[1040px]/builder:min-h-0 @[1040px]/builder:flex-1 @[1040px]/builder:flex @[1040px]/builder:overflow-hidden @[1040px]/builder:border-t-0 @[1040px]/builder:border-l"
            class:hidden={activePane !== "plan"}
          >
            <FlowAIBuilderPlanPane
              onapplied={(detail) => onapplied?.(detail)}
              onsuggestchange={(intent: AIBuilderSuggestChangeIntent) =>
                chatRef?.focusInput(intent)}
            />
          </div>
        {/if}
      </div>
    </div>
  </div>
{/if}

<style lang="postcss">
  @reference "@eneo/ui/styles";

  /* Sticky-region clearance contract for the narrow layouts (§1.3): scroll
     padding = fixed-region height + 16px margin, so focus-triggered scrolling
     never lands under the sticky header group or the sticky footer regions.
     Header: phase bar + pane switcher (~90px). Footer: composer at rest or the
     horizontal action bar (~160px). Below the sm viewport breakpoint the
     action-bar buttons stack vertically (status + two secondaries + primary),
     so the footer clearance grows to cover that stack plus the safe-area
     inset. Irrelevant in split view, where the page never scrolls. */
  .builder-page-scroll {
    --builder-header-clearance: 7rem;
    --builder-footer-clearance: 11rem;
    scroll-padding-block-start: var(--builder-header-clearance);
    scroll-padding-block-end: var(--builder-footer-clearance);
  }

  @media (max-width: 639.98px) {
    .builder-page-scroll {
      --builder-footer-clearance: calc(17rem + env(safe-area-inset-bottom));
    }
  }

  .pane-tab {
    appearance: none;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    padding: 0.625rem 0.875rem;
    font-size: 0.8125rem;
    font-weight: 500;
    line-height: 1.2;
    color: var(--text-secondary);
    cursor: pointer;
    min-height: 2.75rem;
  }

  .pane-tab:hover {
    color: var(--text-primary);
  }

  .pane-tab:focus-visible {
    outline: 2px solid var(--accent-default);
    outline-offset: -2px;
    border-radius: var(--radius-sm);
  }

  .pane-tab.selected {
    color: var(--text-primary);
    font-weight: 600;
    border-bottom-color: var(--accent-default);
  }
</style>
