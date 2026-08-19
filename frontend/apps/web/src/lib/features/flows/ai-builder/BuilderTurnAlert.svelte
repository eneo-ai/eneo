<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { fade } from "svelte/transition";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import FlowAIBuilderDiagnosticCopyButton from "./FlowAIBuilderDiagnosticCopyButton.svelte";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import {
    buildAIBuilderDiagnosticReport,
    buildAIBuilderDiagnosticReportPlan,
    buildAIBuilderDiagnosticReportSession
  } from "./aiBuilderDiagnosticReport";

  interface Props {
    targetKind: "create" | "edit";
    /** Another surface (the build screen) already shows this stream error. */
    suppressStreamError?: boolean;
    /** Runs before a fresh session replaces an unsupported-architecture one. */
    onbeforestartfresh?: () => void;
  }

  let { targetKind, suppressStreamError = false, onbeforestartfresh }: Props = $props();

  const service = getAIBuilderService();

  const streamErrorDiagnosticReport = $derived.by(() =>
    service.error
      ? buildAIBuilderDiagnosticReport({
          kind: "error",
          surface: "chat_stream",
          error: service.error,
          session: buildAIBuilderDiagnosticReportSession(service.session),
          plan: buildAIBuilderDiagnosticReportPlan(service.currentPlan)
        })
      : null
  );
  const turnRecoveryState = $derived(service.turnRecoveryState);
  const turnIsActive = $derived(
    service.latestTurnState === "open" || service.latestTurnState === "processing"
  );
  const turnRefreshFailed = $derived(service.authoritativeRefreshFailed && service.error !== null);
  const isUnsupportedArchitectureError = $derived(
    service.error?.code === "unsupported_architecture"
  );
  // A refused delegation is about this one question, so it is named in the
  // user's terms rather than shown as a payload error.
  const delegationRefusal = $derived.by(() => {
    if (service.error?.code !== "invalid_question_payload") return null;
    const reason = service.error.details?.reason;
    if (reason === "delegation_without_recommendation") {
      return m.ai_builder_question_delegation_unavailable();
    }
    if (reason === "delegation_without_pending_question") {
      return m.ai_builder_question_delegation_stale();
    }
    // Editing the content list is refused for two different reasons that need
    // two different actions: read the card again, or pick another name.
    if (reason === "requirements_version_stale") {
      return m.ai_builder_content_field_edit_stale();
    }
    if (reason === "invalid_field_name") {
      const field = service.error?.details?.field_name;
      return typeof field === "string" && field.trim()
        ? m.ai_builder_content_field_edit_invalid_named({ field })
        : m.ai_builder_content_field_edit_invalid();
    }
    return null;
  });
  const turnAlertCopy = $derived.by(() => {
    if (turnRecoveryState === "failed_before_provider") {
      return {
        title: m.ai_builder_turn_failed_before_provider_title(),
        description: m.ai_builder_turn_failed_before_provider_description()
      };
    }
    if (turnRecoveryState === "provider_outcome_unknown") {
      return {
        title: m.ai_builder_turn_provider_outcome_unknown_title(),
        description: m.ai_builder_turn_provider_outcome_unknown_description()
      };
    }
    if (delegationRefusal) {
      return {
        title: m.ai_builder_question_delegate(),
        description: delegationRefusal
      };
    }
    if (isUnsupportedArchitectureError) {
      return {
        title: m.ai_builder_unsupported_architecture_title(),
        description: m.ai_builder_unsupported_architecture_description()
      };
    }
    if (turnIsActive) {
      return {
        title: m.ai_builder_turn_active_title(),
        description: m.ai_builder_turn_active_description()
      };
    }
    return null;
  });
  let isRefreshingTurn = $state(false);

  // An unknown provider outcome must keep its explicit cost acknowledgement.
  async function handleTurnRetry() {
    if (turnRecoveryState === "failed_before_provider") {
      await service.retryLatestTurn();
      return;
    }
    if (turnRecoveryState === "provider_outcome_unknown") {
      await service.acknowledgeAndRetryLatestTurn();
    }
  }

  async function handleTurnRefresh() {
    if (isRefreshingTurn) return;
    isRefreshingTurn = true;
    try {
      await service.refreshSession();
    } finally {
      isRefreshingTurn = false;
    }
  }

  async function handleUnsupportedArchitectureStartFresh() {
    onbeforestartfresh?.();
    try {
      await service.startFreshSession(targetKind);
    } catch {
      // The driver retains the typed create-session error for this alert.
    }
  }

  const visible = $derived(
    !suppressStreamError && (service.error !== null || turnRecoveryState !== null || turnIsActive)
  );
</script>

{#if visible}
  <div
    class="w-full shrink-0 px-7 pt-3 max-sm:px-3 max-sm:pt-2"
    transition:fade={{ duration: 160 }}
  >
    <Alert.Root
      variant={turnIsActive && !service.error ? "default" : "destructive"}
      class="mx-auto grid max-w-[43.75rem] grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 rounded-lg px-3.5 py-3"
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 20 20"
        fill="currentColor"
        class="mt-0.5 size-4 shrink-0"
        aria-hidden="true"
      >
        <path
          fill-rule="evenodd"
          d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-7-4a1 1 0 1 0-2 0v4a1 1 0 1 0 2 0V6Zm-1 8a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z"
          clip-rule="evenodd"
        />
      </svg>
      <div class="min-w-0">
        {#if turnAlertCopy}
          <Alert.Title class="text-sm leading-snug">{turnAlertCopy.title}</Alert.Title>
        {/if}
        <Alert.Description
          id="ai-builder-turn-recovery-description"
          class="text-[0.8125rem] leading-relaxed"
        >
          {turnAlertCopy?.description ?? service.error?.message ?? ""}
          {#if turnAlertCopy && turnRefreshFailed}
            <span class="mt-1 block">{m.ai_builder_turn_refresh_failed()}</span>
          {:else if turnAlertCopy && service.error && !isUnsupportedArchitectureError}
            <span class="mt-1 block">{service.error.message}</span>
          {/if}
        </Alert.Description>
        <div
          class="mt-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center"
          aria-busy={service.isStreaming || service.isRecoveringLatestTurn}
        >
          {#if isUnsupportedArchitectureError && targetKind === "create"}
            <Button
              variant="default"
              size="sm"
              class="w-full whitespace-normal sm:w-auto"
              disabled={service.isCreating}
              aria-describedby="ai-builder-turn-recovery-description"
              onclick={handleUnsupportedArchitectureStartFresh}
            >
              {m.ai_builder_start_fresh()}
            </Button>
          {:else if turnRecoveryState}
            <Button
              variant={turnRecoveryState === "provider_outcome_unknown" ? "destructive" : "default"}
              size="sm"
              class="w-full whitespace-normal sm:w-auto"
              disabled={service.isStreaming || service.isRecoveringLatestTurn}
              aria-describedby="ai-builder-turn-recovery-description"
              onclick={handleTurnRetry}
            >
              {service.isStreaming || service.isRecoveringLatestTurn
                ? m.ai_builder_turn_retrying()
                : turnRecoveryState === "provider_outcome_unknown"
                  ? m.ai_builder_turn_retry_with_cost_acknowledgement()
                  : m.ai_builder_turn_retry()}
            </Button>
          {:else if turnIsActive}
            <Button
              variant="default"
              size="sm"
              disabled={isRefreshingTurn}
              aria-describedby="ai-builder-turn-recovery-description"
              onclick={handleTurnRefresh}
            >
              {m.refresh()}
            </Button>
          {/if}
          {#if streamErrorDiagnosticReport}
            <FlowAIBuilderDiagnosticCopyButton
              report={streamErrorDiagnosticReport}
              variant="ghost"
              size="xs"
              class="text-destructive hover:bg-destructive/10 hover:text-destructive"
            />
          {/if}
          {#if !turnRecoveryState && service.error}
            <Button
              variant="ghost"
              size="xs"
              class="text-destructive hover:bg-destructive/10 hover:text-destructive"
              onclick={() => service.clearError()}
            >
              {m.ai_builder_dismiss()}
            </Button>
          {/if}
        </div>
      </div>
    </Alert.Root>
  </div>
{/if}
