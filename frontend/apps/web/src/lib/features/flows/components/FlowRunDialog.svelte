<script lang="ts">
  import type {
    Flow,
    FlowRun,
    FlowRunContract,
    FlowRunContractStepInput,
    FlowRuntimeUploadTimeoutEvent,
    Eneo,
    UploadedFile
  } from "@eneo/eneo-js";
  import { createFlowRuntimeUploadTimeoutController } from "@eneo/eneo-js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { EneoError } from "@eneo/eneo-js";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { buildRecordedAudioFile } from "$lib/features/audio/recordedAudioFile";
  import { downloadRecordedAudioFile } from "$lib/features/audio/downloadRecordedAudioFile";
  import type { RecordingStopReason } from "$lib/features/audio/recordedAudioFile";
  import {
    buildSegmentFilenameBase,
    RecordingSession,
    type RecordingSessionDeps,
    type SessionState
  } from "$lib/features/audio/recordingSession";
  import type { SessionRecoveryHint } from "$lib/features/audio/recordingSessionStore";
  import {
    buildContractSnapshotFromStep,
    detachUploadedSegmentFromLedger,
    makeReuploadFileFromRecord,
    markSegmentUploaded,
    persistRecordingSegment,
    purgeAllSessions,
    purgeSession,
    readSessionRecords,
    scanRecoverableSessionsForSteps,
    synthesizeUploadedFileFromRecord
  } from "$lib/features/audio/flowRunRecordingSession";
  import { diffContractSnapshot } from "$lib/features/audio/recordingSession";
  import type { FlowCareDataPolicy } from "$lib/features/flows/flowCareDataPolicy";
  import { normalizeFlowFormFields } from "$lib/features/flows/flowFormSchema";
  import {
    buildFlowRunInputPayload,
    buildFlowRunIntent,
    buildStepInputsPayload,
    computeReusedFlowRunInput,
    getFlowRunReviewFieldValue,
    getMissingFlowRunRequiredFields
  } from "$lib/features/flows/flowRunContract";
  import {
    buildFlowRunBlockers,
    buildFlowRunReviewSummary,
    buildFlowRunWizardPages,
    runtimeStepPageId,
    type FlowLocale,
    type FlowRunWizardPage
  } from "$lib/features/flows/flowRunWizard";
  import { getFlowRuntimeErrorMessage } from "$lib/features/flows/flowRuntimeErrorMapping";
  import { formatBytes } from "$lib/features/flows/flowByteSize";
  import { getFlowRunDialogLabels } from "./flowRunDialogLabels";
  import FlowRunDialogForm from "./FlowRunDialogForm.svelte";
  import FlowRunDialogRuntimeStep from "./FlowRunDialogRuntimeStep.svelte";
  import FlowRunDialogReview from "./FlowRunDialogReview.svelte";
  import FlowRunDialogTemplateOverview from "./FlowRunDialogTemplateOverview.svelte";
  import FlowRunDialogHeader from "./FlowRunDialogHeader.svelte";
  import FlowRunDialogWizardHeader from "./FlowRunDialogWizardHeader.svelte";
  import FlowRunDialogFreeformPage from "./FlowRunDialogFreeformPage.svelte";
  import FlowRunDialogFooter from "./FlowRunDialogFooter.svelte";
  import { FlowRunFileInputState } from "./FlowRunFileInputState.svelte";
  import { FlowRunLaunchInputState } from "./FlowRunLaunchInputState.svelte";
  import { onDestroy, onMount } from "svelte";

  let {
    open = $bindable(false),
    flow,
    careDataPolicy = undefined,
    eneo,
    lastInputPayload,
    onRunCreated
  }: {
    open: boolean;
    flow: Flow;
    careDataPolicy?: FlowCareDataPolicy;
    eneo: Eneo;
    lastInputPayload: Record<string, unknown> | null;
    onRunCreated?: (detail: { run: FlowRun }) => void;
  } = $props();

  let isSubmitting = $state(false);
  let runContract = $state<FlowRunContract | null>(null);
  let runContractError = $state<string | null>(null);
  let runContractLoadedForFlowId = $state<string | null>(null);

  const launchInputState = new FlowRunLaunchInputState();
  const fileInputState = new FlowRunFileInputState();
  let currentPageIndex = $state(0);
  let showCloseConfirmation = $state(false);
  let pageContentEl = $state<HTMLElement | null>(null);
  let resumeScannedForFlowId: string | null = null;

  // The RecordingSession class owns the per-step state machine (idle →
  // recording → reconnecting → paused-failed) and schedules getUserMedia
  // retries when the browser ends a track mid-recording. The dialog still
  // owns persistence and upload — the session only coordinates state and
  // drives the recorder via the imperative startExternal/stopExternal API.
  type RecorderImperativeRef = {
    startExternal: () => Promise<void>;
    stopExternal: () => void;
  };
  const recordingSessionsByStepId: Record<string, RecordingSession | null> = {};
  const recorderRefsByStepId: Record<string, RecorderImperativeRef | null> = {};
  let dialogGeneration = 0;
  function isStale(operationGeneration: number, operationFlowId: string) {
    return operationGeneration !== dialogGeneration || flow.id !== operationFlowId;
  }
  // Promise tails coordinate side effects and must not trigger rendering.
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  const uploadTailsByStepId = new Map<string, Promise<void>>();

  const AUDIO_ACCEPT_FILTER = "audio/*,video/webm,video/mp4";
  const locale = (getLocale() === "en" ? "en" : "sv") as FlowLocale;
  const labels = getFlowRunDialogLabels(locale);

  const formFields = $derived.by(() => normalizeFlowFormFields(runContract?.form_fields ?? []));
  const hasFormFields = $derived(formFields.length > 0);
  const hasRequiredFormFields = $derived(formFields.some((field) => field.required));
  const missingRequiredFields = $derived.by(() =>
    getMissingFlowRunRequiredFields(launchInputState.formValuesSnapshot, formFields)
  );
  const missingRequiredFieldNames = $derived(
    missingRequiredFields.map((field) => field.name.trim()).filter((name) => name.length > 0)
  );

  const stepCount = $derived(flow.steps?.length ?? 0);
  type DialogRuntimeStepInput = FlowRunContractStepInput & { accepted_mimetypes: string[] };
  const stepsRequiringInput = $derived(
    (runContract?.steps_requiring_input ?? []).map(normalizeRuntimeStepInput)
  );
  const templateReadinessItems = $derived(runContract?.template_readiness ?? []);
  const hasRuntimeFileInputs = $derived(stepsRequiringInput.length > 0);
  const showFreeformTextInput = $derived(!hasFormFields && !hasRuntimeFileInputs);
  const hasTemplateOverview = $derived(templateReadinessItems.length > 0);
  const wizardPages = $derived.by(() =>
    buildFlowRunWizardPages({
      locale,
      hasTemplateOverview,
      hasFormFields,
      hasFreeformTextInput: showFreeformTextInput,
      stepsRequiringInput
    })
  );
  const currentPage = $derived.by(() => {
    const idx = currentPageIndex;
    return wizardPages[idx] ?? wizardPages[0] ?? null;
  });
  const runBlockers = $derived.by(() =>
    buildFlowRunBlockers({
      locale,
      missingRequiredFieldNames,
      stepsRequiringInput,
      runtimeFilesByStepId: fileInputState.runtimeFilesSnapshot,
      localRecordingStepIds: fileInputState.localRecordingStepIds,
      templateReadinessItems,
      uploadingStepIds: fileInputState.uploadingStepIdsSnapshot,
      recordingStepIds: fileInputState.recordingStepIdsSnapshot
    })
  );
  const currentPageProgressBlockers = $derived(
    currentPage
      ? runBlockers.filter((blocker) => blocker.pageId === currentPage.id && blocker.blocksProgress)
      : []
  );
  const currentRuntimeStep = $derived(
    currentPage?.kind === "runtime-step"
      ? (stepsRequiringInput.find((step) => step.step_id === currentPage.stepId) ?? null)
      : null
  );
  const currentTemplateBlockers = $derived(
    currentPage?.kind === "overview"
      ? runBlockers.filter((blocker) => blocker.pageId === "overview")
      : []
  );
  const reviewFileGroups = $derived.by(() =>
    stepsRequiringInput
      .map((step) => ({
        step,
        files: fileInputState.getUploadedFiles(step.step_id)
      }))
      .filter((group) => group.files.length > 0)
  );
  const uploadedFileCount = $derived(
    reviewFileGroups.reduce((count, group) => count + group.files.length, 0)
  );
  const templateReadyCount = $derived(
    templateReadinessItems.filter((item) => item.status === "ready").length
  );
  const completedFormFieldSummaries = $derived.by(() => {
    const formValues = launchInputState.formValuesSnapshot;
    return formFields
      .map((field) => ({
        field,
        value: getFlowRunReviewFieldValue(formValues, field)
      }))
      .filter((item) => item.value.length > 0);
  });
  const reviewSummaryItems = $derived.by(() =>
    buildFlowRunReviewSummary({
      locale,
      templateCount: templateReadyCount,
      filledFieldCount: completedFormFieldSummaries.length,
      runtimeStepCountWithFiles: reviewFileGroups.length,
      uploadedFileCount
    })
  );
  const progressLabel = $derived(
    wizardPages.length > 0 ? labels.progress(currentPageIndex + 1, wizardPages.length) : ""
  );
  // Runtime-step pages collect one required input each. Number them as
  // "input N of M" over the input screens only (not the whole wizard), so the
  // user reads it as collecting run material rather than builder-step progress.
  const runtimeInputTotal = $derived(stepsRequiringInput.length);
  const currentInputPosition = $derived(
    currentPage?.kind === "runtime-step"
      ? stepsRequiringInput.findIndex((step) => step.step_id === currentPage.stepId) + 1
      : 0
  );
  const canGoNext = $derived(
    currentPageIndex < wizardPages.length - 1 &&
      currentPageProgressBlockers.length === 0 &&
      !isSubmitting
  );
  // Surfaced as visible helper text next to the Next button so a blocked step
  // explains itself, not just as a hover title. Undefined while submitting.
  const nextDisabledReason = $derived(getDisabledNextReason());
  const canSubmitRun = $derived(
    runContract !== null && !runContractError && !isSubmitting && runBlockers.length === 0
  );
  const isReviewPage = $derived(currentPage?.kind === "review");
  const showReuseLastInput = $derived(
    lastInputPayload !== null && (currentPage?.kind === "form" || currentPage?.kind === "freeform")
  );
  const showPrevious = $derived(currentPageIndex > 0);

  const currentStepUploadedFiles = $derived(
    currentRuntimeStep ? fileInputState.getUploadedFiles(currentRuntimeStep.step_id) : []
  );
  const currentStepRecordedFile = $derived(
    currentRuntimeStep ? fileInputState.getRecordedFile(currentRuntimeStep.step_id) : null
  );
  const currentStepRecorderResetToken = $derived(
    currentRuntimeStep ? fileInputState.getRecorderResetToken(currentRuntimeStep.step_id) : 0
  );
  const currentStepFileCount = $derived(currentStepUploadedFiles.length);
  const currentStepRemainingSlots = $derived(
    currentRuntimeStep?.max_files != null
      ? currentRuntimeStep.max_files - currentStepFileCount
      : Infinity
  );
  const currentStepIsUploading = $derived(
    currentRuntimeStep ? fileInputState.isStepUploading(currentRuntimeStep.step_id) : false
  );
  const currentStepUploadError = $derived(
    currentRuntimeStep ? fileInputState.getUploadError(currentRuntimeStep.step_id) : null
  );
  const currentStepRecordingNotice = $derived(
    currentRuntimeStep ? fileInputState.getRecordingNotice(currentRuntimeStep.step_id) : null
  );
  const currentStepSkippedMessage = $derived(
    currentRuntimeStep ? fileInputState.getSkippedMessage(currentRuntimeStep.step_id) : null
  );
  const isDirty = $derived.by(
    () =>
      fileInputState.hasActiveRecording ||
      fileInputState.hasLocalRecordedFiles ||
      fileInputState.hasRuntimeFiles ||
      launchInputState.hasDirtyInput
  );
  const closeBehavior = $derived<"close" | "ignore">(isDirty ? "ignore" : "close");

  const beforeUnloadHandler = (event: BeforeUnloadEvent) => {
    if (!fileInputState.hasActiveRecording && !fileInputState.hasLocalRecordedFiles) return;
    event.preventDefault();
    event.returnValue = m.recording_unsaved_warning();
  };

  onMount(() => {
    window.addEventListener("beforeunload", beforeUnloadHandler);
  });

  onDestroy(() => {
    window.removeEventListener("beforeunload", beforeUnloadHandler);
    disposeAllRecordingSessions();
  });

  function disposeAllRecordingSessions() {
    for (const stepId of Object.keys(recordingSessionsByStepId)) {
      recordingSessionsByStepId[stepId]?.dispose();
      recordingSessionsByStepId[stepId] = null;
      fileInputState.forgetSessionPhase(stepId);
    }
  }

  $effect(() => {
    if (wizardPages.length > 0 && currentPageIndex > wizardPages.length - 1) {
      currentPageIndex = wizardPages.length - 1;
    }
  });

  async function loadRunContract(flowId: string) {
    try {
      runContractError = null;
      runContract = await eneo.flows.runContract.get({ id: flowId });
    } catch (error) {
      runContract = null;
      runContractError = getFlowRuntimeErrorMessage(
        error,
        error instanceof EneoError ? error.getReadableMessage() : String(error)
      );
    }
  }

  $effect(() => {
    if (open && flow?.id && runContractLoadedForFlowId !== flow.id) {
      runContractLoadedForFlowId = flow.id;
      currentPageIndex = 0;
      void loadRunContract(flow.id);
    }
  });

  // Reset runs only once the close animation is fully complete and bits-ui
  // has unmounted the dialog content tree. Doing it inside an `$effect` that
  // tracked `open` cascaded through `isDirty` → `closeBehavior` → bits-ui
  // props and tripped Svelte's effect-depth guard; it also nulled
  // `currentRuntimeStep` while child components were still alive. The
  // `onOpenChangeComplete` callback is the right Svelte 5 hook for one-shot
  // close cleanup — the docs explicitly warn against using `$effect` to
  // synchronise state.
  function handleOpenChangeComplete(isOpen: boolean) {
    if (!isOpen) {
      resetDialogState();
    }
  }

  function resetDialogState() {
    dialogGeneration += 1;
    uploadTailsByStepId.clear();
    runContractLoadedForFlowId = null;
    runContract = null;
    runContractError = null;
    launchInputState.reset();
    fileInputState.resetForDialogClose();
    currentPageIndex = 0;
    showCloseConfirmation = false;
    resumeScannedForFlowId = null;
    disposeAllRecordingSessions();
  }

  async function refreshRecoverableSessions() {
    const operationGeneration = dialogGeneration;
    const operationFlowId = flow.id;
    if (!runContract || resumeScannedForFlowId === operationFlowId) return;
    resumeScannedForFlowId = operationFlowId;
    const hints = await scanRecoverableSessionsForSteps({
      flowId: operationFlowId,
      steps: stepsRequiringInput
    });
    if (isStale(operationGeneration, operationFlowId)) return;
    const firstWithHints = stepsRequiringInput.find((s) => hints[s.step_id]?.length);
    fileInputState.applyResumeScan(hints, firstWithHints?.step_id ?? null);
  }

  $effect(() => {
    if (
      open &&
      flow?.id &&
      runContract !== null &&
      runContractLoadedForFlowId === flow.id &&
      resumeScannedForFlowId !== flow.id
    ) {
      void refreshRecoverableSessions();
    }
  });

  function requestCloseConfirmation() {
    showCloseConfirmation = true;
  }

  function handleCancelClose() {
    showCloseConfirmation = false;
  }

  function handleInteractOutside() {
    if (isDirty) {
      requestCloseConfirmation();
    }
  }

  function handleEscapeKeydown() {
    if (isDirty) {
      requestCloseConfirmation();
    }
  }

  function applyLastRunInput() {
    launchInputState.applyReusedInput(
      computeReusedFlowRunInput({
        currentFormValues: launchInputState.formValuesSnapshot,
        currentFreeformText: launchInputState.freeformText,
        lastInputPayload,
        formFields,
        hasFormFields,
        showFreeformTextInput
      })
    );
  }

  function normalizeRuntimeStepInput(step: FlowRunContractStepInput): DialogRuntimeStepInput {
    return {
      ...step,
      accepted_mimetypes: step.accepted_mimetypes ?? []
    };
  }

  function getStepAcceptFilter(step: DialogRuntimeStepInput): string | undefined {
    if (step.accepted_mimetypes.length > 0) {
      return step.accepted_mimetypes.join(",");
    }
    return step.input_format === "audio" ? AUDIO_ACCEPT_FILTER : undefined;
  }

  function openFilePicker(step: DialogRuntimeStepInput) {
    const operationGeneration = dialogGeneration;
    const operationFlowId = flow.id;
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    const accept = getStepAcceptFilter(step);
    if (accept) {
      input.accept = accept;
    }
    input.onchange = (event) => {
      const target = event.target as HTMLInputElement;
      if (target.files) {
        void uploadFilesForStep(
          step,
          Array.from(target.files),
          {},
          operationGeneration,
          operationFlowId
        );
      }
      input.value = "";
    };
    input.click();
  }

  function handleDrop(step: DialogRuntimeStepInput, event: DragEvent) {
    event.preventDefault();
    fileInputState.clearDrag();
    if (event.dataTransfer?.files) {
      void uploadFilesForStep(step, Array.from(event.dataTransfer.files));
    }
  }

  function handleDragOver(stepId: string, event: DragEvent) {
    event.preventDefault();
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = "copy";
    }
    fileInputState.dragEnteredStep(stepId);
  }

  function handleDragLeave(stepId: string, event: DragEvent) {
    const target = event.currentTarget as HTMLElement;
    if (!target.contains(event.relatedTarget as Node)) {
      fileInputState.dragLeftStep(stepId);
    }
  }

  function getRuntimeUploadTimeoutMessage(
    event: FlowRuntimeUploadTimeoutEvent,
    fileName: string
  ): string {
    const seconds = String(Math.round(event.timeoutMs / 1000));
    if (event.reason === "not_started") {
      return m.flow_run_upload_timeout_not_started({ seconds, name: fileName });
    }
    if (event.reason === "server_not_responding") {
      return m.flow_run_upload_timeout_server_not_responding({ seconds, name: fileName });
    }
    return m.flow_run_upload_timeout_stalled({ seconds, name: fileName });
  }

  async function uploadRuntimeFileWithTimeout(
    flowId: string,
    step: FlowRunContractStepInput,
    file: File
  ): Promise<UploadedFile> {
    const controller = new AbortController();
    let handleProgress = (_event: ProgressEvent) => {};
    let clearUploadTimeout = () => {};
    const timeoutPromise = new Promise<never>((_, reject) => {
      const uploadTimeout = createFlowRuntimeUploadTimeoutController({
        fileSizeBytes: file.size,
        policy: runContract?.runtime_upload_policy,
        abortController: controller,
        onTimeout: (event) => {
          reject(new Error(getRuntimeUploadTimeoutMessage(event, file.name)));
        }
      });
      handleProgress = uploadTimeout.onProgress;
      clearUploadTimeout = uploadTimeout.clear;
    });

    try {
      const uploadPromise = eneo.flows.steps.runtimeFiles.upload({
        id: flowId,
        stepId: step.step_id,
        file,
        abortController: controller,
        onProgress: handleProgress
      });
      // Keep the Promise.race loser from surfacing a secondary abort rejection.
      uploadPromise.catch(() => {});
      return await Promise.race([uploadPromise, timeoutPromise]);
    } finally {
      clearUploadTimeout();
    }
  }

  type StepUploadResult = {
    uploadedCount: number;
    uploadedFiles: UploadedFile[];
    failed: boolean;
  };

  async function uploadFilesForStep(
    step: FlowRunContractStepInput,
    files: File[],
    options: { clearRecordingNotice?: boolean } = {},
    operationGeneration: number = dialogGeneration,
    operationFlowId: string = flow.id
  ): Promise<StepUploadResult> {
    const staleResult: StepUploadResult = {
      uploadedCount: 0,
      uploadedFiles: [],
      failed: true
    };
    if (isStale(operationGeneration, operationFlowId)) {
      return staleResult;
    }
    fileInputState.beginStepUpload(step.step_id, options);
    const previousTail = uploadTailsByStepId.get(step.step_id) ?? Promise.resolve();
    let releaseTail = () => {};
    const currentTail = new Promise<void>((resolve) => {
      releaseTail = resolve;
    });
    uploadTailsByStepId.set(step.step_id, currentTail);
    let uploadedCount = 0;
    const uploadedFiles: UploadedFile[] = [];
    let failed = false;

    try {
      await previousTail.catch(() => undefined);
      if (isStale(operationGeneration, operationFlowId)) {
        return staleResult;
      }
      const currentFileCount = fileInputState.getUploadedFiles(step.step_id).length;
      const remainingSlots = step.max_files == null ? Infinity : step.max_files - currentFileCount;
      const toUpload =
        remainingSlots !== Infinity ? files.slice(0, Math.max(remainingSlots, 0)) : files;

      if (toUpload.length < files.length && step.max_files != null) {
        failed = true;
        fileInputState.recordSkippedFiles(
          step.step_id,
          m.flow_run_max_files_exceeded({
            attempted: String(files.length),
            limit: String(step.max_files),
            skipped: String(files.length - toUpload.length)
          })
        );
      }

      if (toUpload.length === 0) {
        return { uploadedCount, uploadedFiles, failed: files.length > 0 };
      }

      for (const file of toUpload) {
        if (step.max_file_size_bytes != null && file.size > step.max_file_size_bytes) {
          failed = true;
          fileInputState.recordUploadFailure(
            step.step_id,
            `${file.name}: ${m.flow_run_upload_max_size({
              size: formatBytes(step.max_file_size_bytes)
            })}`
          );
          continue;
        }

        try {
          const uploaded = await uploadRuntimeFileWithTimeout(operationFlowId, step, file);
          if (isStale(operationGeneration, operationFlowId)) {
            return staleResult;
          }
          uploadedCount += 1;
          uploadedFiles.push(uploaded);
          fileInputState.recordUploadedFile(step.step_id, uploaded);
        } catch (error) {
          if (isStale(operationGeneration, operationFlowId)) {
            return staleResult;
          }
          failed = true;
          fileInputState.recordUploadFailure(
            step.step_id,
            getFlowRuntimeErrorMessage(error, String(error))
          );
        }
      }
      return { uploadedCount, uploadedFiles, failed };
    } finally {
      if (!isStale(operationGeneration, operationFlowId)) {
        fileInputState.finishStepUpload(step.step_id);
        if (uploadTailsByStepId.get(step.step_id) === currentTail) {
          uploadTailsByStepId.delete(step.step_id);
        }
      }
      releaseTail();
    }
  }

  function removeFile(stepId: string, fileId: string) {
    const sessionId = fileInputState.removeUploadedFile(stepId, fileId);

    // Drop any matching IDB record so resume cannot reattach the file
    // we just removed. detach is best-effort: if no record matches (the
    // file came from a non-recorded upload, or from a different
    // session), the call silently no-ops.
    if (flow?.id && sessionId) {
      void detachUploadedSegmentFromLedger({
        flowId: flow.id,
        stepId,
        sessionId,
        uploadedFileId: fileId
      });
    }
  }

  function setStepRecordingState(
    stepId: string,
    active: boolean,
    meta: { origin: "user" | "external" } = { origin: "user" }
  ) {
    if (active) {
      fileInputState.recordingStarted(stepId);
    } else {
      fileInputState.recordingStopped(stepId);
    }

    if (!active) return;

    // External (retry-driven) starts are owned by the session itself; we
    // must NOT call ensureRecordingSessionForStep, otherwise we would
    // create a fresh session on top of the one whose retry just succeeded.
    if (meta.origin === "external") return;

    // User-driven start: if there's a stale session sitting in reconnecting
    // or paused-failed, hand it off to ensureRecordingSessionForStep, which
    // handles dispose-and-recreate or pre-empt-retry. The previous
    // implementation bailed early on "reconnecting" and left the queued
    // retry timer alive — when it later fired, it tore down the recording
    // the user had just started.
    ensureRecordingSessionForStep(stepId);
  }

  function makeRecordingSessionDeps(stepId: string): RecordingSessionDeps {
    return {
      // Retry: the session calls this after a backoff. We delegate to
      // the recorder's imperative startExternal which throws on failure
      // — that's how the session learns whether to retry again or to
      // give up and surface the paused-failed CTA.
      startSegment: async () => {
        const ref = recorderRefsByStepId[stepId];
        if (!ref) return { ok: false, error: new Error("Recorder unmounted") };
        try {
          await ref.startExternal();
          return { ok: true };
        } catch (error) {
          return { ok: false, error };
        }
      },
      stopSegment: () => {
        recorderRefsByStepId[stepId]?.stopExternal();
      }
    };
  }

  function ensureRecordingSessionForStep(stepId: string): RecordingSession | null {
    if (!flow?.id) return null;
    const step = stepsRequiringInput.find((s) => s.step_id === stepId);
    if (!step) return null;

    const existing = recordingSessionsByStepId[stepId];
    if (existing) {
      const phase = existing.summary().state;
      // The dialog owns persistence and upload through handleRecordedAudio;
      // RecordingSession only manages recorder lifecycle and retry state.
      // The session knows how to take over a queued retry; let it cancel
      // its own retry timer rather than disposing the session here.
      if (phase === "reconnecting") {
        existing.beginRecordingExternal();
        return existing;
      }
      if (phase === "paused-failed") {
        existing.dispose();
        recordingSessionsByStepId[stepId] = null;
      } else {
        return existing;
      }
    }

    const session = new RecordingSession(makeRecordingSessionDeps(stepId), {
      onStateChange: (state: SessionState) => {
        fileInputState.syncSessionPhase(stepId, state);
      },
      onAutoRecovered: () => {
        toast.success(m.recording_session_auto_recovered());
      },
      onRetryFailed: () => {
        // The session has already transitioned to paused-failed; the
        // CTA in FlowRunDialogRuntimeStep takes it from here.
      }
    });
    recordingSessionsByStepId[stepId] = session;
    session.beginRecordingExternal();
    return session;
  }

  function disposeRecordingSession(stepId: string) {
    const session = recordingSessionsByStepId[stepId];
    if (session) {
      session.dispose();
      recordingSessionsByStepId[stepId] = null;
    }
    fileInputState.forgetSessionPhase(stepId);
  }

  function handleRecorderRefChange(stepId: string, ref: RecorderImperativeRef | null) {
    recorderRefsByStepId[stepId] = ref;
  }

  function retryRecordingSession(stepId: string) {
    disposeRecordingSession(stepId);
    const ref = recorderRefsByStepId[stepId];
    if (!ref) return;
    void ref.startExternal().catch((error) => {
      console.warn("Manual retry failed", error);
    });
  }

  function dismissSessionFailure(stepId: string) {
    disposeRecordingSession(stepId);
  }

  function recordingNoticeForReason(reason: RecordingStopReason): string | null {
    switch (reason) {
      case "limit":
        return m.recording_limit_reached();
      case "stall":
        return m.recording_stalled();
      case "error":
        return m.recording_saved_after_error();
      default:
        return null;
    }
  }

  async function discardRecordedFile(stepId: string) {
    const operationGeneration = dialogGeneration;
    const operationFlowId = flow.id;
    const sessionId = fileInputState.sessionIdsByStepIdSnapshot[stepId];
    fileInputState.discardStepRecording(stepId);
    if (sessionId) {
      await purgeSession({ eneo, flowId: operationFlowId, stepId, sessionId });
      if (isStale(operationGeneration, operationFlowId)) return;
    }
    disposeRecordingSession(stepId);
  }

  async function downloadRecordedFile(step: FlowRunContractStepInput) {
    const file = fileInputState.getRecordedFile(step.step_id);
    if (!file) {
      toast.error(m.recording_not_found());
      return;
    }

    try {
      await downloadRecordedAudioFile(file);
    } catch (error) {
      console.error("Failed to save recording:", error);
      toast.error(m.recording_save_failed());
    }
  }

  async function retryRecordedFileUpload(step: DialogRuntimeStepInput) {
    const operationGeneration = dialogGeneration;
    const operationFlowId = flow.id;
    const file = fileInputState.getRecordedFile(step.step_id);
    if (!file) {
      openFilePicker(step);
      return;
    }

    const result = await uploadFilesForStep(
      step,
      [file],
      { clearRecordingNotice: false },
      operationGeneration,
      operationFlowId
    );
    if (isStale(operationGeneration, operationFlowId)) return;
    if (result.uploadedCount > 0 && !result.failed) {
      fileInputState.clearPreservedRecording(step.step_id);
    }
  }

  async function handleRecordedAudio(
    step: FlowRunContractStepInput,
    params: { blob: Blob; mimeType: string; reason: RecordingStopReason; durationMs: number }
  ) {
    const operationGeneration = dialogGeneration;
    const operationFlowId = flow.id;
    const prepared = fileInputState.prepareRecordedSegment(step.step_id);
    const capturedAt = Date.now();
    const filenameBase = buildSegmentFilenameBase(
      prepared.sessionId,
      prepared.segmentIndex,
      capturedAt
    );
    const file = buildRecordedAudioFile({
      blob: params.blob,
      mimeType: params.mimeType,
      fileNameBase: filenameBase
    });

    // Persist before upload so a refresh during the upload still leaves
    // the captured audio recoverable from IndexedDB.
    const persistResult = await persistRecordingSegment({
      flowId: operationFlowId,
      stepId: step.step_id,
      sessionId: prepared.sessionId,
      segmentIndex: prepared.segmentIndex,
      blob: params.blob,
      mimeType: params.mimeType,
      reason: params.reason,
      durationMs: params.durationMs,
      capturedAt,
      contractSnapshot: buildContractSnapshotFromStep(
        step,
        runContract?.published_flow_version ?? null
      )
    });
    if (isStale(operationGeneration, operationFlowId)) return;
    fileInputState.recordSegmentPersistence({
      stepId: step.step_id,
      file,
      notice: recordingNoticeForReason(params.reason),
      degraded: persistResult.degraded
    });
    const result = await uploadFilesForStep(
      step,
      [file],
      { clearRecordingNotice: false },
      operationGeneration,
      operationFlowId
    );
    if (isStale(operationGeneration, operationFlowId)) return;
    if (result.uploadedCount > 0 && !result.failed) {
      const uploaded = result.uploadedFiles[0];
      if (uploaded?.id) {
        await markSegmentUploaded({
          flowId: operationFlowId,
          stepId: step.step_id,
          sessionId: prepared.sessionId,
          segmentIndex: prepared.segmentIndex,
          uploadedFileId: uploaded.id
        });
        if (isStale(operationGeneration, operationFlowId)) return;
      }
      fileInputState.clearPreservedRecording(step.step_id);
    }

    // After persistence + upload settles, hand the reason to the session
    // controller. error/stall trip the reconnect retry loop; manual/limit
    // close out the session so the next user-click starts fresh.
    if (isStale(operationGeneration, operationFlowId)) return;
    const session = recordingSessionsByStepId[step.step_id];
    if (session) {
      if (params.reason === "error" || params.reason === "stall") {
        session.notifyHardFailure();
      } else {
        disposeRecordingSession(step.step_id);
      }
    }
  }

  async function downloadUploadedFile(file: UploadedFile) {
    try {
      const { url } = await eneo.files.generateSignedUrl({
        fileId: file.id,
        contentDisposition: "attachment"
      });
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = file.name;
      anchor.rel = "noopener";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } catch (error) {
      console.error("Failed to download uploaded file:", error);
      toast.error(m.error_downloading_file());
    }
  }

  function focusPageHeading() {
    requestAnimationFrame(() => {
      // data-wizard-heading is in the header area, not inside pageContentEl
      const dialogEl = pageContentEl?.closest("[data-slot='dialog-content']");
      const heading = dialogEl?.querySelector<HTMLElement>("[data-wizard-heading]");
      if (heading) {
        heading.focus();
      }
      // Scroll content area to top on page change
      if (pageContentEl) {
        pageContentEl.scrollTop = 0;
      }
    });
  }

  function goToPreviousPage() {
    if (currentPageIndex <= 0) return;
    currentPageIndex -= 1;
    focusPageHeading();
  }

  function goToNextPage() {
    if (!canGoNext) return;
    currentPageIndex += 1;
    focusPageHeading();
  }

  function goToPageById(pageId: FlowRunWizardPage["id"]) {
    const nextIndex = wizardPages.findIndex((page) => page.id === pageId);
    if (nextIndex < 0) return;
    currentPageIndex = nextIndex;
    focusPageHeading();
  }

  function retryUpload(step: DialogRuntimeStepInput) {
    fileInputState.retryRequested(step.step_id);
    if (fileInputState.getRecordedFile(step.step_id)) {
      void retryRecordedFileUpload(step);
    } else {
      openFilePicker(step);
    }
  }

  function getDisabledNextReason(): string | undefined {
    if (isSubmitting) return undefined;
    if (currentPageProgressBlockers.length > 0) {
      return currentPageProgressBlockers[0]?.title;
    }
    return undefined;
  }

  async function continueResumedSession(stepId: string, hint: SessionRecoveryHint) {
    const operationGeneration = dialogGeneration;
    const operationFlowId = flow.id;
    if (!fileInputState.beginResumeAction(stepId)) return;
    try {
      const records = await readSessionRecords(operationFlowId, stepId, hint.sessionId);
      if (isStale(operationGeneration, operationFlowId)) return;
      if (records.length === 0) {
        fileInputState.dismissResumePrompt();
        return;
      }

      // Diff the stored contract against the live one BEFORE reattaching:
      // a published-version bump, narrowed accepted MIMEs, smaller
      // max-files cap, or a deleted step would otherwise re-upload audio
      // that no longer matches the flow. Anything block-resume or
      // block-submit aborts the reattach with a user-visible toast; the
      // user keeps the option to download/discard from the prompt.
      const step = stepsRequiringInput.find((s) => s.step_id === stepId);
      const currentSnapshot = step
        ? buildContractSnapshotFromStep(step, runContract?.published_flow_version ?? null)
        : {
            publishedFlowVersion: runContract?.published_flow_version ?? null,
            maxFiles: null,
            maxFileSizeBytes: null,
            acceptedMimetypes: [],
            inputFormat: null
          };
      const segmentMeta = records.map((r) => ({ mimeType: r.mimeType, bytes: r.blob.size }));
      const issues = diffContractSnapshot(hint.contractSnapshot, currentSnapshot, segmentMeta);
      const blocked =
        !step || issues.some((i) => i.severity === "block-resume" || i.severity === "block-submit");
      if (blocked) {
        toast.error(m.recording_resume_diff_blocked());
        fileInputState.dismissResumePrompt();
        return;
      }

      if (isStale(operationGeneration, operationFlowId)) return;
      fileInputState.attachRecoveredSession(stepId, hint.sessionId, records.length);
      goToPageById(runtimeStepPageId(stepId));

      // Process records in segment-index order so the per-segment
      // transcription header (Del 1 / Del 2 / ...) matches the document
      // order. Mixing reattach + re-upload would otherwise leave the
      // re-uploaded segments at the tail of the file input state.
      for (const record of records) {
        if (record.uploadedFileId) {
          if (isStale(operationGeneration, operationFlowId)) return;
          const synthesized = synthesizeUploadedFileFromRecord(record);
          fileInputState.recordUploadedFile(stepId, synthesized);
          continue;
        }

        const reuploadFile = makeReuploadFileFromRecord(record);
        const result = await uploadFilesForStep(
          step,
          [reuploadFile],
          { clearRecordingNotice: false },
          operationGeneration,
          operationFlowId
        );
        if (isStale(operationGeneration, operationFlowId)) return;
        if (result.uploadedCount > 0 && !result.failed) {
          const uploaded = result.uploadedFiles[0];
          if (uploaded?.id) {
            await markSegmentUploaded({
              flowId: operationFlowId,
              stepId,
              sessionId: hint.sessionId,
              segmentIndex: record.segmentIndex,
              uploadedFileId: uploaded.id
            });
            if (isStale(operationGeneration, operationFlowId)) return;
          }
        }
      }
    } finally {
      if (!isStale(operationGeneration, operationFlowId)) {
        fileInputState.finishResumeAction();
      }
    }
  }

  async function discardResumedSession(stepId: string, hint: SessionRecoveryHint) {
    const operationGeneration = dialogGeneration;
    const operationFlowId = flow.id;
    if (!fileInputState.beginResumeAction(stepId)) return;
    try {
      await purgeSession({ eneo, flowId: operationFlowId, stepId, sessionId: hint.sessionId });
      if (isStale(operationGeneration, operationFlowId)) return;
      fileInputState.discardRecoveredSession(stepId);
    } finally {
      if (!isStale(operationGeneration, operationFlowId)) {
        fileInputState.finishResumeAction();
      }
    }
  }

  function dismissResumePrompt() {
    fileInputState.dismissResumePrompt();
  }

  function saveForLater() {
    // The IDB ledger persists for 24 h regardless of the dialog state, so
    // closing without resetting state is exactly the "save and continue
    // later" semantics the user expects.
    open = false;
    if (fileInputState.isStorageDegraded) {
      // In memory-only mode the ledger does not survive a page reload, so
      // the success toast would lie. Tell the user the truth.
      toast.warning(m.recording_session_storage_degraded());
    } else {
      toast.success(m.recording_save_for_later_toast());
    }
  }

  async function triggerRun() {
    if (!flow.id || !runContract || runBlockers.length > 0) return;

    isSubmitting = true;
    try {
      const payload = buildFlowRunInputPayload({
        formValues: launchInputState.formValuesSnapshot,
        freeformText: launchInputState.freeformText,
        formFields,
        hasFormFields,
        showFreeformTextInput
      });

      const stepInputs = buildStepInputsPayload(fileInputState.runtimeFilesSnapshot);
      const runIntent = buildFlowRunIntent({
        publishedFlowVersion: runContract.published_flow_version,
        inputPayloadJson: payload,
        stepInputs
      });
      const idempotencyKey = await eneo.flows.runs.deriveUploadIntentIdempotencyKey({
        flowId: flow.id,
        expectedFlowVersion: runIntent.expected_flow_version,
        input_payload_json: runIntent.input_payload_json,
        ...(runIntent.step_inputs ? { step_inputs: runIntent.step_inputs } : {})
      });
      const createdRun = await eneo.flows.runs.create({
        flow: { id: flow.id },
        ...runIntent,
        idempotencyKey
      });

      onRunCreated?.({ run: createdRun });
      toast.success(m.flow_run_started_toast());

      // Clear all persisted sessions for this flow on success — the run was
      // accepted by the backend, so the local copy is no longer needed.
      await purgeAllSessions({
        flowId: flow.id,
        sessionIdsByStepId: fileInputState.sessionIdsByStepIdSnapshot
      });

      open = false;
      launchInputState.reset();
      fileInputState.resetAfterRunAccepted();
    } catch (error) {
      toast.error(
        getFlowRuntimeErrorMessage(
          error,
          error instanceof EneoError ? error.getReadableMessage() : String(error)
        )
      );
    } finally {
      isSubmitting = false;
    }
  }
</script>

<Dialog.Root bind:open onOpenChangeComplete={handleOpenChangeComplete}>
  <Dialog.Content
    class="!flex max-h-[92vh] min-h-[24rem] !max-w-5xl flex-col !gap-0 overflow-hidden !rounded-2xl !p-0 sm:min-h-[30rem]"
    showCloseButton={false}
    interactOutsideBehavior={closeBehavior}
    escapeKeydownBehavior={closeBehavior}
    onInteractOutside={handleInteractOutside}
    onEscapeKeydown={handleEscapeKeydown}
  >
    <FlowRunDialogHeader
      flowName={flow.name}
      {stepCount}
      {isDirty}
      {isSubmitting}
      onRequestClose={requestCloseConfirmation}
    />

    {#if runContract === null && !runContractError}
      <div class="mt-5 flex flex-col gap-3 px-4 sm:px-6 lg:px-8" aria-busy="true">
        <Skeleton class="h-[6rem] rounded-xl" />
        <Skeleton class="h-[8rem] rounded-xl" />
      </div>
    {:else if runContractError}
      <div class="mx-4 mt-5 sm:mx-6 lg:mx-8">
        <Alert.Root variant="destructive">
          <Alert.Title>{m.flow_run_contract_load_failed_title()}</Alert.Title>
          <Alert.Description>
            <span>{m.flow_run_contract_load_failed_desc()}</span>
            <span class="mt-1 block text-xs break-words opacity-80">{runContractError}</span>
          </Alert.Description>
          <Alert.Action>
            <Button
              variant="outline"
              size="sm"
              onclick={() => {
                runContractLoadedForFlowId = null;
              }}
            >
              {labels.retryUpload}
            </Button>
          </Alert.Action>
        </Alert.Root>
      </div>
    {:else if currentPage}
      <FlowRunDialogWizardHeader
        {wizardPages}
        {currentPage}
        {currentPageIndex}
        {progressLabel}
        {currentInputPosition}
        {runtimeInputTotal}
        onGoToPage={goToPageById}
      />

      <div
        class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-5 sm:px-6 sm:py-6 lg:px-8"
        bind:this={pageContentEl}
      >
        {#if currentPage.kind === "overview"}
          <FlowRunDialogTemplateOverview
            {templateReadinessItems}
            publishedFlowVersion={runContract?.published_flow_version}
            {currentTemplateBlockers}
            {labels}
          />
        {:else if currentPage.kind === "form"}
          <FlowRunDialogForm
            {formFields}
            {launchInputState}
            {missingRequiredFields}
            {hasRequiredFormFields}
            {labels}
          />
        {:else if currentPage.kind === "freeform"}
          <FlowRunDialogFreeformPage
            freeformText={launchInputState.freeformText}
            onInput={(value) => launchInputState.setFreeformText(value)}
          />
        {:else if currentPage.kind === "runtime-step" && currentRuntimeStep}
          <FlowRunDialogRuntimeStep
            step={currentRuntimeStep}
            files={currentStepUploadedFiles}
            recordedFile={currentStepRecordedFile}
            recorderResetToken={currentStepRecorderResetToken}
            fileCount={currentStepFileCount}
            remainingSlots={currentStepRemainingSlots}
            isUploading={currentStepIsUploading}
            uploadError={currentStepUploadError}
            recordingNotice={currentStepRecordingNotice}
            skippedMessage={currentStepSkippedMessage}
            dragging={fileInputState.isDraggingStep(currentRuntimeStep.step_id)}
            {labels}
            {locale}
            resumeHint={fileInputState.getResumeHint(currentRuntimeStep.step_id)}
            showResumePrompt={fileInputState.isResumePromptForStep(currentRuntimeStep.step_id)}
            resumeBusy={fileInputState.isResumeBusyForStep(currentRuntimeStep.step_id)}
            storageDegraded={fileInputState.isStorageDegraded}
            onOpenFilePicker={() => openFilePicker(currentRuntimeStep)}
            onRemoveFile={(fileId) => removeFile(currentRuntimeStep.step_id, fileId)}
            onDownloadUploadedFile={(file) => void downloadUploadedFile(file)}
            onRetryUpload={() => retryUpload(currentRuntimeStep)}
            onDownloadRecordedAudio={() => void downloadRecordedFile(currentRuntimeStep)}
            onRetryRecordedAudio={() => void retryRecordedFileUpload(currentRuntimeStep)}
            onDiscardRecordedAudio={() => void discardRecordedFile(currentRuntimeStep.step_id)}
            onSaveForLater={saveForLater}
            onContinueResume={(hint) =>
              void continueResumedSession(currentRuntimeStep.step_id, hint)}
            onDiscardResume={(hint) => void discardResumedSession(currentRuntimeStep.step_id, hint)}
            onDismissResumePrompt={dismissResumePrompt}
            sessionPhase={fileInputState.getSessionPhase(currentRuntimeStep.step_id)}
            onRecordingDone={(params) => void handleRecordedAudio(currentRuntimeStep, params)}
            onRecordingStateChange={(active, meta) =>
              setStepRecordingState(currentRuntimeStep.step_id, active, meta)}
            onRecorderRef={handleRecorderRefChange}
            onSessionRetry={() => retryRecordingSession(currentRuntimeStep.step_id)}
            onSessionDismissFailure={() => dismissSessionFailure(currentRuntimeStep.step_id)}
            onDrop={(event) => handleDrop(currentRuntimeStep, event)}
            onDragOver={(event) => handleDragOver(currentRuntimeStep.step_id, event)}
            onDragLeave={(event) => handleDragLeave(currentRuntimeStep.step_id, event)}
          />
        {:else if currentPage.kind === "review"}
          <FlowRunDialogReview
            {runBlockers}
            {reviewSummaryItems}
            {completedFormFieldSummaries}
            {careDataPolicy}
            inputText={launchInputState.freeformText}
            {showFreeformTextInput}
            {reviewFileGroups}
            {labels}
            onGoToPage={goToPageById}
          />
        {/if}
      </div>
    {/if}

    <FlowRunDialogFooter
      {showCloseConfirmation}
      {isDirty}
      {isSubmitting}
      {canGoNext}
      {canSubmitRun}
      {isReviewPage}
      {showReuseLastInput}
      {showPrevious}
      {nextDisabledReason}
      {labels}
      onCancelClose={handleCancelClose}
      onGoNext={goToNextPage}
      onGoPrevious={goToPreviousPage}
      onTriggerRun={triggerRun}
      onApplyLastInput={applyLastRunInput}
      onRequestClose={requestCloseConfirmation}
    />
  </Dialog.Content>
</Dialog.Root>
