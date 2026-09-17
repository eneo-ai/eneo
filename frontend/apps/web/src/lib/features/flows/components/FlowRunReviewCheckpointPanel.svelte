<script lang="ts">
  import type {
    FlowRunReviewCheckpoint,
    FlowRunReviewCheckpointEdit,
    FlowRunReviewCheckpointEditPage,
    Eneo
  } from "@eneo/eneo-js";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import ChevronRight from "lucide-svelte/icons/chevron-right";
  import { onMount } from "svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import FlowCitationSummary from "./FlowCitationSummary.svelte";
  import { readAttachedCitationSummary } from "./flowCitationSummary";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { getFlowRuntimeErrorMessage } from "$lib/features/flows/flowRuntimeErrorMapping";
  import SpeakerMappingReviewEditor from "./SpeakerMappingReviewEditor.svelte";
  import FlowStructuredReviewEditor from "./FlowStructuredReviewEditor.svelte";
  import TranscriptPlayer from "./TranscriptPlayer.svelte";
  import {
    buildEditedMapping,
    buildSpeakerRows,
    getSpeakerMappingInferNames,
    getSpeakerMappingParticipants,
    getSpeakerMappingSourceStep,
    isSpeakerMappingCheckpoint,
    speakerNamesFromRows,
    type SpeakerMappingRow
  } from "$lib/features/flows/speakerMappingReview";
  import {
    attachWords,
    parseTranscript,
    isPureTranscript,
    segmentsFromMetadata,
    fileReviewsFromMetadata,
    type TranscriptFileReview,
    type TranscriptSegment
  } from "$lib/features/flows/transcriptSegments";
  import TranscriptCorrectionReviewDialog from "./TranscriptCorrectionReviewDialog.svelte";
  import {
    createTranscriptCorrectionsController,
    type TranscriptCorrectionsController
  } from "$lib/features/flows/transcriptCorrectionsController.svelte";

  let {
    runId,
    flowId,
    eneo,
    onChanged
  }: {
    runId: string;
    flowId: string;
    eneo: Eneo;
    onChanged?: () => void;
  } = $props();

  type ReviewAction = "edit" | "approve" | "reject" | "resume";

  let checkpoint = $state<FlowRunReviewCheckpoint | null>(null);
  let loading = $state(true);
  let loadError: string | null = $state(null);
  let actionError: string | null = $state(null);
  let draftValueText = $state("");
  let historyExpanded = $state(false);
  let showOriginal = $state(false);
  let transcriptPlayer = $state<{ playSpeakerSample: (label: string) => void }>();
  let speakerReviews = $state<TranscriptFileReview[]>([]);
  let speakerRows = $state<SpeakerMappingRow[]>([]);
  // Every saved change to the checkpoint's output, oldest first, with the
  // baseline the first page's items are compared against. Loaded per
  // checkpoint and again after each of this panel's own mutations.
  let history = $state<FlowRunReviewCheckpointEditPage | null>(null);
  let historyLoading = $state(false);
  let historyError: string | null = $state(null);
  let selectedHistoryRevision = $state<number | null>(null);
  let rejectExpanded = $state(false);
  // Which checkpoint and cursor the next history page is for, so a retry
  // re-asks the same question.
  let historyRequest: { checkpointId: string; afterRevision: number | null } | null = $state(null);
  // A save and an approval can each refresh the history while the other's
  // request is still in flight; only the newest request may write state.
  let historyGeneration = 0;
  // The signed-in user's id, so their own changes read as "you"; other
  // reviewers are named by id because the run has no user directory access.
  let currentUserId = $state<string | null>(null);
  // The transcription step's stored segments and audio, loaded once per
  // checkpoint so the reviewer can listen while naming speakers.
  let storedSegments = $state<TranscriptSegment[] | null>(null);
  let transcriptStepId = $state<string | null>(null);
  let audioFileIds = $state<string[]>([]);
  let audioContextPending = $state(true);
  let audioContextError: string | null = $state(null);

  // Text corrections share the run-scoped store with the finished-run
  // evidence view, so a fix made during review survives into the final run.
  let correctionsController = $state<TranscriptCorrectionsController | null>(null);

  // Created imperatively, never in an $effect: prop reads inside a reactive
  // context chain into the run-history polling signals, which would re-create
  // the controller (and refetch corrections) on every 5s poll tick.
  function setupCorrectionsController() {
    const segments = storedSegments;
    const stepId = transcriptStepId;
    if (!segments || !stepId) {
      correctionsController = null;
      return;
    }
    const controller = createTranscriptCorrectionsController({
      eneo,
      flowId,
      runId,
      stepId,
      rawSegments: segments
    });
    correctionsController = controller;
    void controller.load();
  }
  const isSpeakerMapping = $derived(isSpeakerMappingCheckpoint(checkpoint?.current_payload_json));
  // Stored segments carry raw labels, so the reviewer's draft names apply
  // live; the rendered text already has the saved names baked in.
  const isTranscriptReview = $derived(isSpeakerMapping || isPureTranscript(draftValueText));
  const transcriptSegments = $derived(storedSegments ?? parseTranscript(draftValueText));
  const speakerNames = $derived(speakerNamesFromRows(speakerRows));
  const speakerParticipants = $derived(
    getSpeakerMappingParticipants(checkpoint?.current_payload_json)
  );
  const speakerNamesInferred = $derived(
    getSpeakerMappingInferNames(checkpoint?.current_payload_json)
  );
  // Reviewer edits not yet sent to the server.
  const speakerEditsPending = $derived(
    isSpeakerMapping &&
      JSON.stringify(buildEditedMapping(speakerRows)) !==
        JSON.stringify(buildEditedMapping(buildSpeakerRows(checkpoint?.current_payload_json)))
  );
  const savedValueText = $derived(
    checkpoint ? renderEditableValue(checkpoint.current_payload_json, checkpoint.output_type) : ""
  );
  const outputEditsPending = $derived(
    checkpoint !== null && !isSpeakerMapping && draftValueText !== savedValueText
  );
  let rejectReason = $state("");
  let activeAction: ReviewAction | null = $state(null);
  let nowMs = $state(Date.now());

  const deadlineHasPassed = $derived(checkpoint ? hasDeadlinePassed(checkpoint, nowMs) : false);
  const reviewDecisionExpired = $derived(
    deadlineHasPassed && (checkpoint?.state === "awaiting_review" || checkpoint?.state === "edited")
  );
  const checkpointExpired = $derived(checkpoint?.state === "expired");
  const canDecide = $derived(
    !reviewDecisionExpired &&
      (checkpoint?.state === "awaiting_review" || checkpoint?.state === "edited")
  );
  // The flow author decides whether this step's output may be replaced at all.
  const canEdit = $derived(canDecide && checkpoint?.review_mode === "edit");
  const canApprove = $derived(
    canDecide &&
      !showOriginal &&
      (!isTranscriptReview ||
        (!audioContextPending &&
          !audioContextError &&
          (!correctionsController ||
            (correctionsController.ready &&
              !correctionsController.error &&
              !correctionsController.dialog))))
  );
  const canReject = $derived(canDecide);
  // Attached by every checkpoint response (active read and mutations), so
  // an edit flips staleness in the same response without a second fetch.
  const citationSummary = $derived(readAttachedCitationSummary(checkpoint));
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

  /** The reviewer edits the step's own output, not the persisted payload envelope. */
  function renderEditableValue(
    payload: Record<string, unknown> | null | undefined,
    outputType: FlowRunReviewCheckpoint["output_type"]
  ): string {
    // A speaker-mapping step's text is the transcript with names applied, which
    // is what the reviewer wants to compare, not the mapping JSON.
    if (outputType === "json" && !isSpeakerMappingCheckpoint(payload)) {
      return JSON.stringify(payload?.structured ?? {}, null, 2);
    }
    return typeof payload?.text === "string" ? payload.text : "";
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
      draftValueText = renderEditableValue(
        nextCheckpoint.current_payload_json,
        nextCheckpoint.output_type
      );
      speakerRows = buildSpeakerRows(nextCheckpoint.current_payload_json);
      selectedHistoryRevision = null;
      void loadHistory(nextCheckpoint);
    } else {
      history = null;
    }
  }

  async function loadHistory(target: FlowRunReviewCheckpoint, afterRevision: number | null = null) {
    const generation = ++historyGeneration;
    historyRequest = { checkpointId: target.id, afterRevision };
    historyLoading = true;
    historyError = null;
    try {
      const page = await eneo.flows.runs.reviewCheckpoints.edits({
        flowId,
        runId,
        checkpointId: target.id,
        afterRevision
      });
      if (generation !== historyGeneration) return;
      const previous = history;
      history =
        afterRevision === null || previous === null
          ? page
          : { ...page, baseline: previous.baseline, items: [...previous.items, ...page.items] };
    } catch (error) {
      if (generation !== historyGeneration) return;
      console.error("Failed to load review checkpoint history", error);
      // Pages already shown stay; the failed page can be asked for again.
      historyError = getFlowRuntimeErrorMessage(error, m.flow_run_review_history_load_failed());
      historyExpanded = true;
    } finally {
      if (generation === historyGeneration) historyLoading = false;
    }
  }

  function retryHistory() {
    if (!checkpoint || !historyRequest || historyRequest.checkpointId !== checkpoint.id) return;
    void loadHistory(checkpoint, historyRequest.afterRevision);
  }

  // The payload each history item changed: the page baseline for the first
  // item (the original output on the first page), otherwise the item before.
  function historyPredecessor(index: number): Record<string, unknown> | null {
    if (!history) return null;
    return index === 0 ? history.baseline.payload_json : history.items[index - 1].payload_json;
  }

  function historyCauseLabel(cause: FlowRunReviewCheckpointEdit["cause"]): string {
    return cause === "corrections_folded"
      ? m.flow_run_review_history_cause_corrections_folded()
      : m.flow_run_review_history_cause_reviewer_edit();
  }

  function historyEditorLabel(item: FlowRunReviewCheckpointEdit): string {
    const service = item.edited_by_service_principal;
    if (service) return m.flow_run_review_history_editor_service({ name: service.display_name });
    if (item.edited_by_user_id && item.edited_by_user_id === currentUserId) {
      return m.flow_run_review_history_editor_you();
    }
    return m.flow_run_review_history_editor_user({
      id: item.edited_by_user_id?.slice(0, 8) ?? item.edited_by_service_id?.slice(0, 8) ?? "?"
    });
  }

  async function loadCurrentUser() {
    try {
      currentUserId = (await eneo.users.me()).id;
    } catch (error) {
      console.error("Failed to load the current user for review history labels", error);
      currentUserId = null;
    }
  }

  async function loadTranscriptContext(payload: Record<string, unknown> | null | undefined) {
    const source = getSpeakerMappingSourceStep(payload);
    audioContextPending = true;
    audioContextError = null;
    try {
      const steps = await eneo.flows.runs.steps({ flowId, runId });
      const sourceStep =
        steps.find((step) => step.step_id === (source.stepId ?? checkpoint?.step_id)) ??
        steps.find((step) => step.step_order === source.stepOrder) ??
        steps.find((step) => readTranscription(step.input_payload_json) !== null);
      const transcription = readTranscription(sourceStep?.input_payload_json);
      const fileIds = Array.isArray(transcription?.file_ids)
        ? transcription.file_ids.filter((id): id is string => typeof id === "string")
        : (sourceStep?.runtime_input_file_ids ?? []);
      speakerReviews = fileReviewsFromMetadata(transcription);
      const segments = segmentsFromMetadata(transcription);
      const stepId = sourceStep?.step_id ?? null;
      storedSegments =
        segments && stepId ? attachWords(segments, await loadTranscriptWords(stepId)) : segments;
      transcriptStepId = stepId;
      audioFileIds = fileIds;
      setupCorrectionsController();
    } catch (error) {
      console.error("Failed to load transcript context", error);
      audioContextError = getFlowRuntimeErrorMessage(
        error,
        m.flow_run_review_audio_context_failed()
      );
    } finally {
      audioContextPending = false;
    }
  }

  // Word timings are optional: a step that stored none answers 404 and the
  // player falls back to segment-level playback.
  async function loadTranscriptWords(stepId: string) {
    try {
      return await eneo.flows.runs.transcriptWords.get({ flowId, runId, stepId });
    } catch {
      return null;
    }
  }

  function readTranscription(payload: unknown): Record<string, unknown> | null {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
    const raw = (payload as Record<string, unknown>).transcription;
    return raw && typeof raw === "object" && !Array.isArray(raw)
      ? (raw as Record<string, unknown>)
      : null;
  }

  function getAudioUrl(fileIndex: number) {
    const fileId = audioFileIds[fileIndex];
    if (!fileId) return Promise.reject(new Error("No audio file for this part"));
    return eneo.flows.runs.inputFileSignedUrl({
      flowId,
      runId,
      fileId,
      contentDisposition: "inline"
    });
  }

  async function loadCheckpoint() {
    loading = true;
    loadError = null;
    actionError = null;
    try {
      const active = await eneo.flows.runs.reviewCheckpoints.active({ flowId, runId });
      applyCheckpoint(active);
      if (active && isTranscriptReview) {
        void loadTranscriptContext(active.current_payload_json);
      }
    } catch (error) {
      console.error("Failed to load review checkpoint", error);
      loadError = getFlowRuntimeErrorMessage(error, m.flow_run_review_load_failed());
    } finally {
      loading = false;
    }
  }

  function parseDraftValue(
    outputType: FlowRunReviewCheckpoint["output_type"]
  ): string | Record<string, unknown> | unknown[] | null {
    if (outputType !== "json") {
      return draftValueText;
    }
    try {
      const parsed: unknown = JSON.parse(draftValueText);
      if (!parsed || typeof parsed !== "object") {
        actionError = m.flow_run_review_payload_invalid();
        return null;
      }
      return parsed as Record<string, unknown> | unknown[];
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
    const editedValue = isSpeakerMapping
      ? buildEditedMapping(speakerRows)
      : parseDraftValue(checkpoint.output_type);
    if (editedValue === null) return;
    activeAction = "edit";
    actionError = null;
    try {
      applyCheckpoint(
        await eneo.flows.runs.reviewCheckpoints.edit({
          flowId,
          runId,
          checkpointId: checkpoint.id,
          expectedCheckpointRevision: checkpoint.revision,
          editedValue
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
      // Approval accepts the visible draft, and uses the revision returned by its save.
      if (correctionsController && !(await correctionsController.flush())) {
        actionError =
          correctionsController.error ?? m.flow_run_transcript_corrections_save_failed();
        return;
      }
      let current = checkpoint;
      if ((speakerEditsPending || outputEditsPending) && canEdit) {
        const editedValue = isSpeakerMapping
          ? buildEditedMapping(speakerRows)
          : parseDraftValue(current.output_type);
        if (editedValue === null) return;
        current = await eneo.flows.runs.reviewCheckpoints.edit({
          flowId,
          runId,
          checkpointId: current.id,
          expectedCheckpointRevision: current.revision,
          editedValue
        });
        applyCheckpoint(current);
      }
      applyCheckpoint(
        await eneo.flows.runs.reviewCheckpoints.approve({
          flowId,
          runId,
          checkpointId: current.id,
          expectedCheckpointRevision: current.revision
        })
      );
      if (isTranscriptReview && checkpoint?.state === "approved") {
        activeAction = "resume";
        const result = await eneo.flows.runs.reviewCheckpoints.resume({
          flowId,
          runId,
          checkpointId: checkpoint.id,
          expectedCheckpointRevision: checkpoint.revision,
          idempotencyKey: `flow-review-resume:${checkpoint.id}:${checkpoint.revision}`
        });
        applyCheckpoint(result.checkpoint);
        toast.success(m.flow_run_review_resumed());
      } else toast.success(m.flow_run_review_approved());
      onChanged?.();
    } catch (error) {
      console.error("Failed to approve review checkpoint", error);
      actionError = getFlowRuntimeErrorMessage(
        error,
        activeAction === "resume"
          ? m.flow_run_review_resume_failed()
          : m.flow_run_review_approve_failed()
      );
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
    void loadCurrentUser();
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
  <!-- The panel renders inside a table cell that keeps its own text on one
       line; review prose must wrap. -->
  <div
    class="bg-primary flex max-w-[53.75rem] min-w-0 flex-col gap-5 rounded-lg p-3 whitespace-normal sm:p-5 2xl:max-w-[62.5rem]"
  >
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="min-w-0">
        <h3 class="text-primary text-sm font-semibold">
          {checkpoint.step_label || m.flow_run_review_checkpoint_title()}
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
    {:else if checkpoint.review_mode !== "edit" && canDecide}
      <Alert.Root>
        <Alert.Description>{m.flow_run_review_view_only()}</Alert.Description>
      </Alert.Root>
    {:else if checkpoint.state === "approved" && deadlineHasPassed}
      <Alert.Root>
        <Alert.Title>{m.flow_run_review_deadline()}</Alert.Title>
        <Alert.Description>{m.flow_run_review_deadline_approved()}</Alert.Description>
      </Alert.Root>
    {/if}

    {#if citationSummary}
      <div class="border-default bg-primary rounded-lg border p-3">
        <FlowCitationSummary
          summary={citationSummary}
          title={m.flow_citation_summary_review_title()}
        />
      </div>
    {/if}

    <Field.Group class="grid gap-4 {isTranscriptReview ? 'grid-cols-1' : 'lg:grid-cols-2'}">
      {#if isTranscriptReview}
        {#if isSpeakerMapping}
          <SpeakerMappingReviewEditor
            rows={speakerRows}
            sampleAvailable={(label) =>
              transcriptSegments.some(
                (s) =>
                  s.speaker === label &&
                  s.speakerAttribution !== "provisional" &&
                  s.speakerAttribution !== "unassigned"
              ) &&
              audioFileIds.length > 0 &&
              !audioContextPending}
            onListen={(label) => transcriptPlayer?.playSpeakerSample(label)}
            participants={speakerParticipants}
            inferred={speakerNamesInferred}
            disabled={!canEdit || activeAction !== null}
            onChange={(rows) => (speakerRows = rows)}
          />
        {:else}
          <p class="text-muted text-sm">
            {m.flow_transcript_review_help()}
          </p>
        {/if}
        <Field.Field>
          <Field.Label class="text-primary text-xs font-medium">
            {m.flow_run_review_speakers_preview()}
          </Field.Label>
          {#if audioContextError}
            <Alert.Root>
              <Alert.Description>{audioContextError}</Alert.Description>
              <Alert.Action>
                <Button
                  variant="outline"
                  size="sm"
                  onclick={() => void loadTranscriptContext(checkpoint?.current_payload_json)}
                >
                  {m.flow_retry()}
                </Button>
              </Alert.Action>
            </Alert.Root>
          {/if}
          {#if correctionsController?.error}
            <Alert.Root variant="destructive">
              <Alert.Description class="text-xs">
                {correctionsController.error}
                <p>
                  {m.flow_transcript_editor_draft_preserved()}
                </p>
                <button
                  class="mt-2 mr-4 underline"
                  onclick={() => void correctionsController?.retry()}
                  >{m.flow_transcript_editor_retry()}</button
                >
                <button
                  class="mt-2 underline"
                  onclick={() => correctionsController?.downloadDraft()}
                  >{m.flow_transcript_editor_download_draft()}</button
                >
              </Alert.Description>
            </Alert.Root>
          {/if}
          {#if correctionsController?.saving}<p class="text-muted text-xs" role="status">
              {m.flow_transcript_editor_saving()}
            </p>{/if}
          {#if correctionsController && correctionsController.staleCount > 0}
            <Alert.Root>
              <Alert.Description class="text-xs">
                {m.flow_run_transcript_corrections_stale({
                  count: String(correctionsController.staleCount)
                })}
              </Alert.Description>
            </Alert.Root>
          {/if}
          {#if !storedSegments}
            <p class="text-muted text-sm">
              {m.flow_transcript_review_details_unavailable()}
            </p>
          {/if}
          {#key checkpoint.id}
            <TranscriptPlayer
              bind:this={transcriptPlayer}
              reviewEditor
              {speakerReviews}
              onChange={correctionsController?.replaceDraft}
              segments={transcriptSegments}
              fileCount={audioFileIds.length}
              {getAudioUrl}
              {speakerNames}
              textFallback={draftValueText}
              audioPending={audioContextPending}
              editable={canEdit &&
                storedSegments !== null &&
                (correctionsController?.ready ?? false)}
              corrections={correctionsController?.occurrences ?? []}
              speakerEdits={correctionsController?.speakerEdits ?? []}
              busy={activeAction !== null}
              onSaveLine={correctionsController ? correctionsController.saveLine : undefined}
              onRevertLine={correctionsController ? correctionsController.revertLine : undefined}
              onSaveSpeakerEdits={correctionsController
                ? correctionsController.saveSpeakerEdits
                : undefined}
              class="lg:min-h-80"
            />
          {/key}
        </Field.Field>
      {:else if checkpoint.output_type === "json"}
        <div class="min-w-0 lg:col-span-2">
          {#key checkpoint.id}
            <FlowStructuredReviewEditor
              text={draftValueText}
              bind:showOriginal
              originalText={renderEditableValue(
                checkpoint.original_payload_json,
                checkpoint.output_type
              )}
              schema={checkpoint.output_contract}
              disabled={!canEdit || activeAction !== null}
              onChange={(text) => (draftValueText = text)}
            />
          {/key}
        </div>
      {:else}
        <Field.Field>
          <Field.Label class="text-primary text-xs font-medium" for="flow-review-current-payload">
            {m.flow_run_review_current_payload()}
          </Field.Label>
          <Textarea
            id="flow-review-current-payload"
            bind:value={draftValueText}
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
            class="border-default bg-hover-dimmer min-h-72 overflow-auto rounded-lg border p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap lg:min-h-80">{renderEditableValue(
              checkpoint.original_payload_json,
              checkpoint.output_type
            )}</pre>
        </Field.Field>
      {/if}
    </Field.Group>

    <details
      bind:open={historyExpanded}
      class="border-default border-t py-2"
      aria-labelledby="flow-review-history-title"
    >
      <summary
        id="flow-review-history-title"
        class="text-primary focus-visible:ring-accent-default flex min-h-10 cursor-pointer list-none items-center py-2 text-sm font-medium focus-visible:ring-2 [&::-webkit-details-marker]:hidden"
      >
        <ChevronRight
          class="text-secondary mr-2 size-4 shrink-0 motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out) {historyExpanded
            ? 'rotate-90'
            : ''}"
          aria-hidden="true"
        />
        {m.flow_run_review_history_title()}
        {#if history}<span class="text-secondary ml-2 tabular-nums"
            >({history.items.length}{history.truncated ? "+" : ""})</span
          >{/if}
        {#if historyLoading}<IconLoadingSpinner
            class="ml-2 inline-block size-4 animate-spin"
          />{/if}
      </summary>
      <Field.Description class="mt-1 text-xs">{m.flow_run_review_history_help()}</Field.Description>
      {#if historyError}
        <Alert.Root variant="destructive" class="mt-2 flex items-center gap-3">
          <Alert.Description class="flex-1">{historyError}</Alert.Description>
          <Button variant="outline" size="sm" disabled={historyLoading} onclick={retryHistory}>
            {m.retry()}
          </Button>
        </Alert.Root>
      {/if}
      {#if history && history.items.length === 0}
        <Field.Description class="mt-2 text-xs"
          >{m.flow_run_review_history_empty()}</Field.Description
        >
      {:else if history}
        <ol class="mt-2 flex flex-col gap-1">
          {#each history.items as item, index (item.id)}
            {@const selected = selectedHistoryRevision === item.revision}
            <li>
              <button
                type="button"
                class="border-default hover:bg-hover-dimmer flex w-full flex-wrap items-baseline gap-x-3 gap-y-1 rounded-md border px-3 py-2 text-left text-xs"
                aria-expanded={selected}
                onclick={() => (selectedHistoryRevision = selected ? null : item.revision)}
              >
                <span class="text-primary font-medium"
                  >{m.flow_run_review_history_revision({ revision: item.revision })}</span
                >
                <span>{historyCauseLabel(item.cause)}</span>
                <span>{historyEditorLabel(item)}</span>
                <span class="ml-auto">{formatReviewDeadline(item.created_at)}</span>
              </button>
              {#if selected}
                <div class="mt-2 grid gap-3 lg:grid-cols-2">
                  <div>
                    <Field.Label class="text-primary text-xs font-medium">
                      {index === 0 && !history.baseline.revision
                        ? m.flow_run_review_history_original()
                        : m.flow_run_review_history_before()}
                    </Field.Label>
                    {#if checkpoint.output_type === "json" && !isSpeakerMapping}
                      <FlowStructuredReviewEditor
                        text={renderEditableValue(
                          historyPredecessor(index),
                          checkpoint.output_type
                        )}
                        schema={checkpoint.output_contract}
                        disabled
                        original
                        onChange={() => {}}
                      />
                    {:else}
                      <pre
                        class="border-default bg-hover-dimmer mt-1 max-h-80 overflow-auto rounded-lg border p-3 text-sm leading-relaxed whitespace-pre-wrap">{renderEditableValue(
                          historyPredecessor(index),
                          checkpoint.output_type
                        )}</pre>
                    {/if}
                  </div>
                  <div>
                    <Field.Label class="text-primary text-xs font-medium">
                      {m.flow_run_review_history_after()}
                    </Field.Label>
                    {#if checkpoint.output_type === "json" && !isSpeakerMapping}
                      <FlowStructuredReviewEditor
                        text={renderEditableValue(item.payload_json, checkpoint.output_type)}
                        schema={checkpoint.output_contract}
                        disabled
                        original
                        onChange={() => {}}
                      />
                    {:else}
                      <pre
                        class="border-default bg-hover-dimmer mt-1 max-h-80 overflow-auto rounded-lg border p-3 text-sm leading-relaxed whitespace-pre-wrap">{renderEditableValue(
                          item.payload_json,
                          checkpoint.output_type
                        )}</pre>
                    {/if}
                  </div>
                </div>
              {/if}
            </li>
          {/each}
        </ol>
        {#if history.truncated && history.next_after_revision !== null}
          <Button
            variant="ghost"
            size="sm"
            class="mt-2"
            disabled={historyLoading}
            onclick={() =>
              checkpoint && void loadHistory(checkpoint, history?.next_after_revision ?? null)}
          >
            {m.flow_run_review_history_load_more()}
          </Button>
        {/if}
      {/if}
    </details>

    <details bind:open={rejectExpanded} class="text-secondary border-default border-t text-sm">
      <summary
        class="focus-visible:ring-accent-default flex min-h-10 cursor-pointer list-none items-center py-3 focus-visible:ring-2 [&::-webkit-details-marker]:hidden"
      >
        <ChevronRight
          class="mr-2 size-4 shrink-0 motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out) {rejectExpanded
            ? 'rotate-90'
            : ''}"
          aria-hidden="true"
        />
        {isTranscriptReview ? m.flow_transcript_editor_reject() : m.flow_run_review_reject_open()}
      </summary>
      <div class="flex flex-col gap-3 pb-2">
        <p class="max-w-prose text-sm">{m.flow_run_review_reject_help()}</p>
        <Field.Field data-invalid={reviewDecisionExpired ? "true" : undefined}>
          <Field.Label for="flow-review-reject-reason"
            >{m.flow_run_review_reject_reason()}</Field.Label
          >
          <Textarea
            id="flow-review-reject-reason"
            bind:value={rejectReason}
            disabled={!canReject || activeAction !== null}
            aria-invalid={reviewDecisionExpired || checkpointExpired}
            maxlength={1024}
            class="min-h-20 resize-y text-sm"
          />
        </Field.Field>
        <Button
          variant="destructive"
          class="min-h-10 self-start"
          disabled={!canReject || activeAction !== null || !rejectReason.trim()}
          onclick={() => void rejectCheckpoint()}
        >
          {activeAction === "reject" ? m.flow_run_review_rejecting() : m.reject()}
        </Button>
      </div>
    </details>

    <div
      class="border-default flex flex-col gap-3 border-t pt-4 sm:flex-row sm:items-center sm:justify-between"
    >
      <div class="flex min-w-0 flex-col gap-1.5" role="status" aria-live="polite">
        {#if outputEditsPending || speakerEditsPending}
          <span
            class="bg-warning-dimmer text-warning-stronger self-start rounded px-2 py-1 text-xs font-medium"
            >{m.flow_run_review_unsaved()}</span
          >
        {/if}
        {#if canResume && !showOriginal}
          <p class="text-secondary max-w-prose text-sm">{m.flow_run_review_resume_help()}</p>
        {:else if !isTranscriptReview && canEdit && !showOriginal}
          <p class="text-secondary max-w-prose text-sm">{m.flow_run_review_approve_help()}</p>
        {/if}
      </div>
      <div class="flex shrink-0 flex-wrap justify-end gap-2">
        {#if !isTranscriptReview && !canResume && !showOriginal}
          <Button
            variant="outline"
            class="min-h-10"
            disabled={!canEdit || activeAction !== null || !outputEditsPending}
            onclick={() => void saveEdit()}
          >
            {activeAction === "edit" ? m.saving() : m.flow_run_review_save_edit()}
          </Button>
        {/if}
        {#if showOriginal}
          <Button class="min-h-10" onclick={() => (showOriginal = false)}
            >{m.flow_run_review_back_to_edit()}</Button
          >
        {:else if canResume}
          <Button
            class="min-h-10"
            disabled={activeAction !== null}
            onclick={() => void resumeCheckpoint()}
          >
            {activeAction === "resume" ? m.flow_run_review_resuming() : m.flow_run_review_resume()}
          </Button>
        {:else}
          <Button
            class="min-h-10"
            disabled={!canApprove || activeAction !== null}
            onclick={() => void approveCheckpoint()}
          >
            {activeAction === "approve" || activeAction === "resume"
              ? m.flow_run_review_approving()
              : isTranscriptReview
                ? m.flow_transcript_editor_approve_continue()
                : m.approve()}
          </Button>
        {/if}
      </div>
    </div>
  </div>
{/if}

{#if correctionsController?.dialog && storedSegments}
  <TranscriptCorrectionReviewDialog
    open={true}
    originalText={correctionsController.dialog.originalText}
    correctedText={correctionsController.dialog.correctedText}
    candidates={correctionsController.dialog.candidates}
    segments={storedSegments}
    busy={correctionsController.saving}
    onConfirm={(selected) => void correctionsController?.confirmSuggestions(selected)}
    onSkip={() => void correctionsController?.dismissSuggestions()}
  />
{/if}
