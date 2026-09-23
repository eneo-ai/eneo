<script lang="ts">
  import { BUILDER_COLUMN } from "./builderColumns";
  import { m } from "$lib/paraglide/messages";
  import { fade } from "svelte/transition";
  import { prefersReducedMotion } from "$lib/core/prefersReducedMotion";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import IconAlertTriangle from "@lucide/svelte/icons/triangle-alert";
  import IconInfo from "@lucide/svelte/icons/info";
  import FlowAIBuilderDiagnosticCopyButton from "./FlowAIBuilderDiagnosticCopyButton.svelte";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import {
    buildAIBuilderDiagnosticReport,
    buildAIBuilderDiagnosticReportPlan,
    buildAIBuilderDiagnosticReportSession
  } from "./aiBuilderDiagnosticReport";
  import { describeFailure, type FailureAction } from "./aiBuilderFailurePresentation";

  /**
   * The chat surface for a failure: the same presentation the generation
   * card renders, above whatever screen is showing. It also carries the
   * one notice that is not a failure, a turn the server is still working
   * on. Ownership rule: it stays out while the plan surface owns the error.
   */
  interface Props {
    targetKind: "create" | "edit";
    /** Another surface (the build screen) already shows this stream error. */
    suppressStreamError?: boolean;
    /** The screen's column width, so the alert's edges line up with the card below. */
    columnClass?: string;
  }

  let {
    targetKind,
    suppressStreamError = false,
    columnClass = BUILDER_COLUMN.sheet
  }: Props = $props();

  const reducedMotion = prefersReducedMotion();

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
  // A refused start-over replaces the unsupported-architecture error with its
  // own, which would take the offer away with it. In create mode it is the
  // only way out, so the offer stays while the driver's refusal error stands.
  const offersStartFresh = $derived(
    targetKind === "create" &&
      (service.error?.code === "unsupported_architecture" ||
        service.forcedCreateRefusedFor(targetKind))
  );
  const presentation = $derived(
    describeFailure({
      error: service.error,
      latestTurn: service.latestTurn,
      capabilities: service.failureRecoveryCapabilities,
      context: { surface: "chat", targetKind, offersStartFresh }
    })
  );
  let isRefreshingTurn = $state(false);
  const busy = $derived(
    service.isStreaming || service.isRecoveringLatestTurn || service.isCreating || isRefreshingTurn
  );

  async function runAction(action: FailureAction) {
    service.reportFailureAction(action.records);
    switch (action.kind) {
      case "retry_same_turn":
        await service.retryLatestTurn();
        return;
      case "retry_same_turn_acknowledged":
        await service.acknowledgeAndRetryLatestTurn();
        return;
      case "refresh":
        await handleTurnRefresh();
        return;
      case "start_fresh":
        try {
          await service.startFreshSession(targetKind);
        } catch {
          // The driver keeps the session it was replacing, its typed error
          // and the standing offer to try again.
        }
        return;
      case "dismiss":
        service.clearError();
        return;
      case "retry_new_turn":
      case "clarify":
      case "attach_template":
        // Never produced for the chat surface.
        return;
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

  const visible = $derived(
    !suppressStreamError && (service.error !== null || turnRecoveryState !== null || turnIsActive)
  );

  // A failure this alert shows is observed as the chat surface, once, whether
  // it is an error payload or a restored turn state without one.
  $effect(() => {
    if (!visible) return;
    const kind = presentation?.kind ?? null;
    if (!kind) return;
    service.reportFailureDisplayed({ surface: "chat", presentedAs: kind });
  });
</script>

{#if visible}
  <div
    class="w-full shrink-0 px-7 pt-3 max-sm:px-3 max-sm:pt-2"
    transition:fade={{ duration: reducedMotion ? 0 : 160 }}
  >
    <Alert.Root
      variant="default"
      role="status"
      aria-live="polite"
      class="mx-auto grid {columnClass} grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 rounded-lg px-3.5 py-3"
    >
      {#if presentation}
        <IconAlertTriangle
          class="text-warning-stronger mt-0.5 size-4 shrink-0"
          aria-hidden="true"
        />
      {:else}
        <IconInfo class="text-secondary mt-0.5 size-4 shrink-0" aria-hidden="true" />
      {/if}
      <div class="min-w-0">
        <Alert.Title class="text-sm leading-snug">
          {presentation?.heading ?? m.ai_builder_turn_active_title()}
        </Alert.Title>
        <Alert.Description
          id="ai-builder-turn-recovery-description"
          class="text-[0.8125rem] leading-relaxed"
        >
          {presentation?.consequence ?? m.ai_builder_turn_active_description()}
          {#if turnRefreshFailed}
            <span class="mt-1 block">{m.ai_builder_turn_refresh_failed()}</span>
          {/if}
        </Alert.Description>
        <div
          class="mt-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center"
          aria-busy={service.isStreaming || service.isRecoveringLatestTurn}
        >
          {#if presentation}
            {#if presentation.primary && presentation.primary.kind !== "dismiss"}
              {@const primary = presentation.primary}
              <Button
                variant="default"
                size="sm"
                class="w-full whitespace-normal sm:w-auto"
                disabled={busy}
                aria-describedby="ai-builder-turn-recovery-description"
                onclick={() => void runAction(primary)}
              >
                {service.isStreaming || service.isRecoveringLatestTurn
                  ? m.ai_builder_turn_retrying()
                  : primary.label}
              </Button>
            {/if}
            {#if presentation.secondary}
              {@const secondary = presentation.secondary}
              <Button
                variant="outline"
                size="sm"
                class="w-full whitespace-normal sm:w-auto"
                disabled={busy}
                onclick={() => void runAction(secondary)}
              >
                {secondary.label}
              </Button>
            {/if}
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
          {#if presentation?.technical}
            {@const technical = presentation.technical}
            <p class="text-secondary text-xs leading-relaxed select-text">
              <span>{m.ai_builder_failure_technical_code({ code: technical.code })}</span>
              {#if technical.requestId}
                <span aria-hidden="true"> · </span>
                <span
                  >{m.ai_builder_failure_technical_request({ request: technical.requestId })}</span
                >
              {/if}
            </p>
          {/if}
          {#if streamErrorDiagnosticReport}
            <FlowAIBuilderDiagnosticCopyButton
              report={streamErrorDiagnosticReport}
              variant="ghost"
              size="xs"
              onselect={() => {
                service.reportFailureAction("diagnostic_copied");
              }}
            />
          {/if}
          {#if presentation?.primary?.kind === "dismiss"}
            {@const dismiss = presentation.primary}
            <Button
              variant="ghost"
              size="xs"
              class="text-secondary"
              onclick={() => void runAction(dismiss)}
            >
              {dismiss.label}
            </Button>
          {/if}
        </div>
      </div>
    </Alert.Root>
  </div>
{/if}
