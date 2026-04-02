<script lang="ts">
  import { m } from "$lib/paraglide/messages";
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
  <div class="loading-gate" aria-hidden="true">
    <div class="skeleton-bar"></div>
    <div class="skeleton-messages">
      <div class="skeleton-line wide"></div>
      <div class="skeleton-line medium"></div>
      <div class="skeleton-line short"></div>
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
  <div class="builder-wrapper">
    <!-- Resume banner -->
    {#if wasAutoResumed && service.hasSession && service.messages.length > 0}
      <div class="resume-banner">
        <span class="resume-banner-text">
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
          class="resume-banner-link"
          onclick={() => {
            wasAutoResumed = false;
            service.startFreshSession("create");
          }}
        >
          {m.ai_builder_resumed_start_fresh()}
        </button>
        <button
          class="resume-banner-dismiss"
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

    <div class="builder-layout">
      <!-- Chat Pane -->
      <div class="chat-pane" class:chat-pane-full={!hasPlanContent}>
        <FlowAIBuilderChat bind:this={chatRef} {targetKind} />
      </div>

      <!-- Plan Pane — slides in when plan arrives -->
      {#if hasPlanContent}
        <div class="plan-pane-wrapper">
          <FlowAIBuilderPlanPane
            onapplied={(detail) => onapplied?.(detail)}
            onsuggestchange={(prefill) => chatRef?.focusInput(prefill)}
          />
        </div>
      {/if}
    </div>
  </div>
{/if}

<style lang="postcss">
  @reference "@intric/ui/styles";

  .loading-gate {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 2rem;
    padding: 2rem 1.5rem;
    min-height: 0;
  }

  .skeleton-bar {
    height: 2.5rem;
    border-radius: 0.5rem;
    background: var(--bg-secondary);
    animation: skeleton-pulse 1.5s ease-in-out infinite;
  }

  .skeleton-messages {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .skeleton-line {
    height: 1rem;
    border-radius: 0.25rem;
    background: var(--bg-secondary);
    animation: skeleton-pulse 1.5s ease-in-out infinite;
  }

  .skeleton-line.wide {
    width: 80%;
    animation-delay: 0.1s;
  }

  .skeleton-line.medium {
    width: 60%;
    animation-delay: 0.2s;
  }

  .skeleton-line.short {
    width: 40%;
    animation-delay: 0.3s;
  }

  @keyframes skeleton-pulse {
    0%,
    100% {
      opacity: 0.4;
    }
    50% {
      opacity: 0.8;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .skeleton-bar,
    .skeleton-line {
      animation: none;
      opacity: 0.5;
    }

    .plan-pane-wrapper,
    .resume-banner {
      animation: none;
    }
  }

  /* --- Resume banner --- */

  .resume-banner {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 1rem;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-default);
    font-size: 0.8125rem;
    animation: banner-slide-down 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  }

  .resume-banner-text {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    color: var(--text-secondary);
  }

  .resume-banner-link {
    color: var(--accent-default);
    font-weight: 500;
    cursor: pointer;
    background: none;
    border: none;
    padding: 0;
    font-size: 0.8125rem;
  }

  .resume-banner-link:hover {
    text-decoration: underline;
  }

  .resume-banner-dismiss {
    margin-left: auto;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 1.5rem;
    height: 1.5rem;
    border-radius: 0.25rem;
    color: var(--text-muted);
    cursor: pointer;
    background: none;
    border: none;
    transition:
      color 0.1s ease,
      background 0.1s ease;
  }

  .resume-banner-dismiss:hover {
    color: var(--text-primary);
    background: oklch(0 0 0 / 0.04);
  }

  @keyframes banner-slide-down {
    from {
      opacity: 0;
      transform: translateY(-100%);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  /* --- Builder layout --- */

  .builder-wrapper {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    width: 100%;
  }

  .builder-layout {
    display: flex;
    flex: 1;
    min-height: 0;
    width: 100%;
    background: var(--bg-primary);
  }

  .chat-pane {
    display: flex;
    min-height: 0;
    min-width: 0;
    flex-direction: column;
    width: 100%;
    transition: width 0.4s cubic-bezier(0.16, 1, 0.3, 1);
  }

  @media (min-width: 768px) {
    .chat-pane {
      width: 45%;
      min-width: 380px;
    }

    .chat-pane-full {
      width: 100%;
      min-width: 0;
    }
  }

  .plan-pane-wrapper {
    display: none;
    min-height: 0;
    flex: 1;
    flex-direction: column;
    overflow: hidden;
    border-left: 1px solid var(--border-default);
    background: var(--bg-primary);
    animation: plan-slide-in 0.45s cubic-bezier(0.16, 1, 0.3, 1) forwards;
  }

  @media (min-width: 768px) {
    .plan-pane-wrapper {
      display: flex;
    }
  }

  @keyframes plan-slide-in {
    from {
      opacity: 0;
      transform: translateX(2rem);
    }
    to {
      opacity: 1;
      transform: translateX(0);
    }
  }
</style>
