<script lang="ts">
  import type { FlowRunReviewCheckpoint, Intric } from "@intric/intric-js";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { onMount } from "svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { getFlowRuntimeErrorMessage } from "$lib/features/flows/flowRuntimeErrorMapping";

  let {
    runId,
    flowId,
    eneo,
    onChanged
  }: {
    runId: string;
    flowId: string;
    eneo: Intric;
    onChanged?: () => void;
  } = $props();

  type ReviewAction = "edit" | "approve" | "reject" | "resume";

  let checkpoint = $state<FlowRunReviewCheckpoint | null>(null);
  let loading = $state(true);
  let loadError: string | null = $state(null);
  let actionError: string | null = $state(null);
  let draftPayloadText = $state("{}");
  let rejectReason = $state("");
  let activeAction: ReviewAction | null = $state(null);
  let nowMs = $state(Date.now());

  const deadlineHasPassed = $derived(checkpoint ? hasDeadlinePassed(checkpoint, nowMs) : false);
  const reviewDecisionExpired = $derived(
    deadlineHasPassed && (checkpoint?.state === "awaiting_review" || checkpoint?.state === "edited")
  );
  const checkpointExpired = $derived(checkpoint?.state === "expired");
  const canEdit = $derived(
    !reviewDecisionExpired &&
      (checkpoint?.state === "awaiting_review" || checkpoint?.state === "edited")
  );
  const canApprove = $derived(canEdit);
  const canReject = $derived(canEdit);
  const canResume = $derived(checkpoint?.state === "approved");
  const checkpointStateLabel = $derived(
    checkpoint ? getCheckpointStateLabel(checkpoint.state) : null
  );
  const deadlineDisplay = $derived(formatReviewDeadline(checkpoint?.expires_at));
  const deadlineBadgeVariant = $derived(
    reviewDecisionExpired || checkpointExpired ? ("destructive" as const) : ("outline" as const)
  );
  const stateBadgeVariant = $derived(
    reviewDecisionExpired || checkpointExpired ? ("destructive" as const) : ("secondary" as const)
  );

  function renderJson(payload: Record<string, unknown> | null | undefined): string {
    return JSON.stringify(payload ?? {}, null, 2);
  }

  function parseTimestampMs(value: string | null | undefined): number | null {
    if (!value) return null;
    const timestampMs = new Date(value).getTime();
    return Number.isNaN(timestampMs) ? null : timestampMs;
  }

  function hasDeadlinePassed(
    currentCheckpoint: FlowRunReviewCheckpoint,
    currentTimeMs: number
  ): boolean {
    if (currentCheckpoint.state === "expired" || currentCheckpoint.expired_at) return true;

    const expiresAtMs = parseTimestampMs(currentCheckpoint.expires_at);
    return expiresAtMs !== null && currentTimeMs >= expiresAtMs;
  }

  function formatReviewDeadline(value: string | null | undefined): string | null {
    const timestampMs = parseTimestampMs(value);
    if (timestampMs === null) return null;

    return new Intl.DateTimeFormat(getLocale(), {
      dateStyle: "medium",
      timeStyle: "short"
    }).format(new Date(timestampMs));
  }

  function applyCheckpoint(nextCheckpoint: FlowRunReviewCheckpoint | null) {
    checkpoint = nextCheckpoint;
    if (nextCheckpoint) {
      draftPayloadText = renderJson(nextCheckpoint.current_payload_json);
    }
  }

  async function loadCheckpoint() {
    loading = true;
    loadError = null;
    actionError = null;
    try {
      applyCheckpoint(await eneo.flows.runs.reviewCheckpoints.active({ flowId, runId }));
    } catch (error) {
      console.error("Failed to load review checkpoint", error);
      loadError = getFlowRuntimeErrorMessage(error, m.flow_run_review_load_failed());
    } finally {
      loading = false;
    }
  }

  function parseDraftPayload(): Record<string, unknown> | null {
    try {
      const parsed = JSON.parse(draftPayloadText);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
        actionError = m.flow_run_review_payload_invalid();
        return null;
      }
      return parsed as Record<string, unknown>;
    } catch {
      actionError = m.flow_run_review_payload_invalid();
      return null;
    }
  }

  function getCheckpointStateLabel(state: FlowRunReviewCheckpoint["state"]): string {
    switch (state) {
      case "awaiting_review":
        return m.flow_run_review_state_awaiting_review();
      case "edited":
        return m.flow_run_review_state_edited();
      case "approved":
        return m.flow_run_review_state_approved();
      case "rejected":
        return m.flow_run_review_state_rejected();
      case "resumed":
        return m.flow_run_review_state_resumed();
      case "cancelled":
        return m.flow_run_review_state_cancelled();
      case "expired":
        return m.flow_run_review_state_expired();
    }
  }

  async function saveEdit() {
    if (!checkpoint || !canEdit) return;
    const currentPayloadJson = parseDraftPayload();
    if (!currentPayloadJson) return;
    activeAction = "edit";
    actionError = null;
    try {
      applyCheckpoint(
        await eneo.flows.runs.reviewCheckpoints.edit({
          flowId,
          runId,
          checkpointId: checkpoint.id,
          expectedCheckpointRevision: checkpoint.revision,
          currentPayloadJson
        })
      );
      toast.success(m.flow_run_review_saved());
      onChanged?.();
    } catch (error) {
      console.error("Failed to save review checkpoint", error);
      actionError = getFlowRuntimeErrorMessage(error, m.flow_run_review_save_failed());
    } finally {
      activeAction = null;
    }
  }

  async function approveCheckpoint() {
    if (!checkpoint || !canApprove) return;
    activeAction = "approve";
    actionError = null;
    try {
      applyCheckpoint(
        await eneo.flows.runs.reviewCheckpoints.approve({
          flowId,
          runId,
          checkpointId: checkpoint.id,
          expectedCheckpointRevision: checkpoint.revision
        })
      );
      toast.success(m.flow_run_review_approved());
      onChanged?.();
    } catch (error) {
      console.error("Failed to approve review checkpoint", error);
      actionError = getFlowRuntimeErrorMessage(error, m.flow_run_review_approve_failed());
    } finally {
      activeAction = null;
    }
  }

  async function rejectCheckpoint() {
    if (!checkpoint || !canReject || rejectReason.trim().length === 0) return;
    activeAction = "reject";
    actionError = null;
    try {
      applyCheckpoint(
        await eneo.flows.runs.reviewCheckpoints.reject({
          flowId,
          runId,
          checkpointId: checkpoint.id,
          expectedCheckpointRevision: checkpoint.revision,
          reason: rejectReason.trim()
        })
      );
      toast.success(m.flow_run_review_rejected());
      onChanged?.();
    } catch (error) {
      console.error("Failed to reject review checkpoint", error);
      actionError = getFlowRuntimeErrorMessage(error, m.flow_run_review_reject_failed());
    } finally {
      activeAction = null;
    }
  }

  async function resumeCheckpoint() {
    if (!checkpoint || !canResume) return;
    activeAction = "resume";
    actionError = null;
    try {
      const result = await eneo.flows.runs.reviewCheckpoints.resume({
        flowId,
        runId,
        checkpointId: checkpoint.id,
        expectedCheckpointRevision: checkpoint.revision,
        idempotencyKey: `flow-review-resume:${checkpoint.id}:${checkpoint.revision}`
      });
      applyCheckpoint(result.checkpoint);
      toast.success(m.flow_run_review_resumed());
      onChanged?.();
    } catch (error) {
      console.error("Failed to resume review checkpoint", error);
      actionError = getFlowRuntimeErrorMessage(error, m.flow_run_review_resume_failed());
    } finally {
      activeAction = null;
    }
  }

  onMount(() => {
    void loadCheckpoint();
    const timer = window.setInterval(() => {
      nowMs = Date.now();
    }, 30000);

    return () => window.clearInterval(timer);
  });
</script>

{#if loading}
  <div class="text-muted flex items-center justify-center gap-2 py-8 text-sm">
    <IconLoadingSpinner class="size-4 animate-spin" />
    {m.flow_loading()}
  </div>
{:else if loadError}
  <Alert.Root variant="destructive" class="flex items-center gap-3">
    <Alert.Description class="flex-1 text-sm">{loadError}</Alert.Description>
    <Button variant="outline" size="sm" onclick={() => void loadCheckpoint()}>
      {m.flow_retry()}
    </Button>
  </Alert.Root>
{:else if !checkpoint}
  <Alert.Root>
    <Alert.Description>{m.flow_run_review_no_active_checkpoint()}</Alert.Description>
  </Alert.Root>
{:else}
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="min-w-0">
        <h3 class="text-primary text-sm font-semibold">
          {m.flow_run_review_checkpoint_title()}
        </h3>
        <p class="text-muted mt-1 text-xs">
          {m.flow_run_review_checkpoint_step({ step: checkpoint.step_order })}
        </p>
      </div>
      <div class="flex flex-wrap items-center justify-end gap-2">
        {#if deadlineDisplay}
          <Tooltip.Provider delayDuration={150}>
            <Tooltip.Root>
              <Tooltip.Trigger>
                {#snippet child({ props })}
                  <Badge
                    {...props}
                    variant={deadlineBadgeVariant}
                    class="h-6 max-w-full shrink-0 tabular-nums"
                  >
                    {m.flow_run_review_deadline_timestamp({ value: deadlineDisplay })}
                  </Badge>
                {/snippet}
              </Tooltip.Trigger>
              <Tooltip.Content class="max-w-72">
                {m.flow_run_review_deadline_help()}
              </Tooltip.Content>
            </Tooltip.Root>
          </Tooltip.Provider>
        {/if}
        <Badge variant={stateBadgeVariant} class="h-6 shrink-0">
          {checkpointStateLabel}
        </Badge>
      </div>
    </div>

    {#if actionError}
      <Alert.Root variant="destructive">
        <Alert.Description>{actionError}</Alert.Description>
      </Alert.Root>
    {/if}

    {#if reviewDecisionExpired || checkpointExpired}
      <Alert.Root variant="destructive">
        <Alert.Title>{m.flow_run_review_deadline()}</Alert.Title>
        <Alert.Description>{m.flow_run_review_deadline_expired()}</Alert.Description>
      </Alert.Root>
    {:else if checkpoint.state === "approved" && deadlineHasPassed}
      <Alert.Root>
        <Alert.Title>{m.flow_run_review_deadline()}</Alert.Title>
        <Alert.Description>{m.flow_run_review_deadline_approved()}</Alert.Description>
      </Alert.Root>
    {/if}

    <Field.Group class="grid gap-4 lg:grid-cols-2">
      <Field.Field>
        <Field.Label class="text-primary text-xs font-medium" for="flow-review-current-payload">
          {m.flow_run_review_current_payload()}
        </Field.Label>
        <Textarea
          id="flow-review-current-payload"
          bind:value={draftPayloadText}
          disabled={!canEdit || activeAction !== null}
          aria-invalid={reviewDecisionExpired || checkpointExpired}
          class="min-h-72 resize-y font-mono text-xs leading-relaxed lg:min-h-80"
          spellcheck={false}
        />
      </Field.Field>
      <Field.Field>
        <Field.Label class="text-primary text-xs font-medium">
          {m.flow_run_review_original_payload()}
        </Field.Label>
        <pre
          class="border-default bg-hover-dimmer min-h-72 overflow-auto rounded-lg border p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap lg:min-h-80">{renderJson(
            checkpoint.original_payload_json
          )}</pre>
      </Field.Field>
    </Field.Group>

    <Field.Field data-invalid={reviewDecisionExpired ? "true" : undefined}>
      <Field.Label class="text-primary text-xs font-medium" for="flow-review-reject-reason">
        {m.flow_run_review_reject_reason()}
      </Field.Label>
      <Textarea
        id="flow-review-reject-reason"
        bind:value={rejectReason}
        disabled={!canReject || activeAction !== null}
        aria-invalid={reviewDecisionExpired || checkpointExpired}
        maxlength={1024}
        class="min-h-24 resize-y text-sm"
      />
      {#if deadlineDisplay}
        <Field.Description class="text-xs">
          {m.flow_run_review_deadline_help()}
        </Field.Description>
      {/if}
    </Field.Field>

    <div
      class="flex flex-col-reverse gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-end"
    >
      <Button
        variant="outline"
        size="sm"
        class="min-h-10 sm:min-h-8"
        disabled={!canEdit || activeAction !== null}
        onclick={() => void saveEdit()}
      >
        {activeAction === "edit" ? m.saving() : m.flow_run_review_save_edit()}
      </Button>
      <Button
        variant="outline"
        size="sm"
        class="min-h-10 sm:min-h-8"
        disabled={!canApprove || activeAction !== null}
        onclick={() => void approveCheckpoint()}
      >
        {activeAction === "approve" ? m.flow_run_review_approving() : m.approve()}
      </Button>
      <Button
        variant="destructive"
        size="sm"
        class="min-h-10 sm:min-h-8"
        disabled={!canReject || activeAction !== null || rejectReason.trim().length === 0}
        onclick={() => void rejectCheckpoint()}
      >
        {activeAction === "reject" ? m.flow_run_review_rejecting() : m.reject()}
      </Button>
      <Button
        size="sm"
        class="min-h-10 sm:min-h-8"
        disabled={!canResume || activeAction !== null}
        onclick={() => void resumeCheckpoint()}
      >
        {activeAction === "resume" ? m.flow_run_review_resuming() : m.flow_run_review_resume()}
      </Button>
    </div>
  </div>
{/if}
