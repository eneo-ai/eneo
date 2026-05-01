<script lang="ts">
  import type {
    Flow,
    FlowRunContract,
    FlowRunContractStepInput,
    FlowRunContractTemplateReadiness,
    Intric,
    UploadedFile
  } from "@intric/intric-js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { IntricError } from "@intric/intric-js";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
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
  import {
    getFlowFormFieldRuntimeKey,
    normalizeFlowFormFields,
    type FlowFormField,
    type NormalizedFlowFormField
  } from "$lib/features/flows/flowFormSchema";
  import {
    buildFlowRunIntent,
    buildStepInputsPayload,
    normalizeTemplateReadiness
  } from "$lib/features/flows/flowRunContract";
  import {
    buildFlowRunBlockers,
    buildFlowRunReviewSummary,
    buildFlowRunWizardPages,
    runtimeStepPageId,
    type FlowLocale,
    type FlowRunWizardPage
  } from "$lib/features/flows/flowRunWizard";
  import {
    getFlowRuntimeErrorMessage,
    getFlowRuntimeErrorMessageByCode
  } from "$lib/features/flows/flowRuntimeErrorMapping";
  import { IconXMark } from "@intric/icons/x-mark";
  import { getFlowRunDialogLabels } from "./flowRunDialogLabels";
  import FlowRunDialogForm from "./FlowRunDialogForm.svelte";
  import FlowRunDialogRuntimeStep from "./FlowRunDialogRuntimeStep.svelte";
  import FlowRunDialogReview from "./FlowRunDialogReview.svelte";
  import { FlowRunFileInputState } from "./FlowRunFileInputState.svelte";
  import { onDestroy, onMount } from "svelte";

  let {
    open = $bindable(false),
    flow,
    careDataPolicy = undefined,
    intric,
    lastInputPayload,
    onRunCreated
  }: {
    open: boolean;
    flow: Flow;
    careDataPolicy?: FlowCareDataPolicy;
    intric: Intric;
    lastInputPayload: Record<string, unknown> | null;
    onRunCreated?: (detail: { runId: string }) => void;
  } = $props();

  let inputText = $state("");
  let isSubmitting = $state(false);
  let runContract = $state<FlowRunContract | null>(null);
  let runContractError = $state<string | null>(null);
  let runContractLoadedForFlowId = $state<string | null>(null);

  let formValues = $state<Record<string, unknown>>({});
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

  const FLOW_UPLOAD_TIMEOUT_MS = 120_000;
  const AUDIO_ACCEPT_FILTER = "audio/*,video/webm,video/mp4";
  const locale = (getLocale() === "en" ? "en" : "sv") as FlowLocale;
  const labels = getFlowRunDialogLabels(locale);

  const formFields = $derived.by(() =>
    normalizeFlowFormFields(
      ((runContract?.form_fields as { fields?: FlowFormField[] } | undefined)?.fields ??
        runContract?.form_fields ??
        []) as FlowFormField[]
    )
  );
  const hasFormFields = $derived(formFields.length > 0);
  const hasRequiredFormFields = $derived(formFields.some((field) => field.required));
  const missingRequiredFields = $derived.by(() =>
    formFields.filter((field) => {
      if (!field.required) return false;
      const value = formValues[getFlowFormFieldRuntimeKey(field.name)];
      if (field.type === "multiselect") {
        return !Array.isArray(value) || value.length === 0;
      }
      if (value === null || value === undefined) return true;
      return String(value).trim().length === 0;
    })
  );
  const missingRequiredFieldNames = $derived(
    missingRequiredFields.map((field) => field.name.trim()).filter((name) => name.length > 0)
  );

  const stepCount = $derived(flow.steps?.length ?? 0);
  type DialogRuntimeStepInput = FlowRunContractStepInput & { accepted_mimetypes: string[] };
  const stepsRequiringInput = $derived(
    (runContract?.steps_requiring_input ?? []).map(normalizeRuntimeStepInput)
  );
  const templateReadinessItems = $derived(
    normalizeTemplateReadiness(runContract?.template_readiness)
  );
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
        files: getUploadedFiles(step.step_id)
      }))
      .filter((group) => group.files.length > 0)
  );
  const uploadedFileCount = $derived(
    reviewFileGroups.reduce((count, group) => count + group.files.length, 0)
  );
  const templateReadyCount = $derived(
    templateReadinessItems.filter((item) => item.status === "ready").length
  );
  const completedFormFieldSummaries = $derived.by(() =>
    formFields
      .map((field) => ({
        field,
        value: getReviewFieldValue(field)
      }))
      .filter((item) => item.value.length > 0)
  );
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
  const canGoNext = $derived(
    currentPageIndex < wizardPages.length - 1 &&
      currentPageProgressBlockers.length === 0 &&
      !isSubmitting
  );
  const canSubmitRun = $derived(
    runContract !== null && !runContractError && !isSubmitting && runBlockers.length === 0
  );

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
  const currentStepBlockers = $derived(
    currentRuntimeStep
      ? runBlockers.filter(
          (b) => b.pageId === runtimeStepPageId(currentRuntimeStep.step_id) && b.blocksProgress
        )
      : []
  );
  const isDirty = $derived.by(
    () =>
      fileInputState.hasActiveRecording ||
      fileInputState.hasLocalRecordedFiles ||
      fileInputState.hasRuntimeFiles ||
      Object.entries(formValues).some(([_, v]) => v != null && String(v).trim() !== "") ||
      inputText.trim() !== ""
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
      runContract = await intric.flows.runContract.get({ id: flowId });
    } catch (error) {
      runContract = null;
      runContractError = error instanceof IntricError ? error.getReadableMessage() : String(error);
    }
  }

  $effect(() => {
    if (open && flow?.id && runContractLoadedForFlowId !== flow.id) {
      runContractLoadedForFlowId = flow.id;
      currentPageIndex = 0;
      void loadRunContract(flow.id);
    }
  });

  $effect(() => {
    if (!open) {
      resetDialogState();
    }
  });

  function resetDialogState() {
    runContractLoadedForFlowId = null;
    runContract = null;
    runContractError = null;
    fileInputState.resetForDialogClose();
    currentPageIndex = 0;
    showCloseConfirmation = false;
    resumeScannedForFlowId = null;
    disposeAllRecordingSessions();
  }

  async function refreshRecoverableSessions() {
    if (!flow?.id || !runContract || resumeScannedForFlowId === flow.id) return;
    resumeScannedForFlowId = flow.id;
    const hints = await scanRecoverableSessionsForSteps({
      flowId: flow.id,
      steps: stepsRequiringInput
    });
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

  function handleCancel() {
    if (isDirty && !isSubmitting) {
      showCloseConfirmation = true;
    } else {
      open = false;
    }
  }

  function handleConfirmClose() {
    showCloseConfirmation = false;
    open = false;
  }

  function handleCancelClose() {
    showCloseConfirmation = false;
  }

  function handleInteractOutside() {
    if (isDirty) {
      showCloseConfirmation = true;
    }
  }

  function handleEscapeKeydown() {
    if (isDirty) {
      showCloseConfirmation = true;
    }
  }

  function getFieldValue(field: NormalizedFlowFormField): string {
    const value = formValues[getFlowFormFieldRuntimeKey(field.name)];
    if (Array.isArray(value)) return "";
    if (value === null || value === undefined) return "";
    return String(value);
  }

  function getFieldMultiValue(field: NormalizedFlowFormField): string[] {
    const value = formValues[getFlowFormFieldRuntimeKey(field.name)];
    if (Array.isArray(value)) return value.map((item) => String(item));
    if (typeof value === "string" && value.trim().length > 0) {
      return value
        .split(",")
        .map((item) => item.trim())
        .filter((item) => item.length > 0);
    }
    return [];
  }

  function setFieldValue(field: NormalizedFlowFormField, value: unknown) {
    const key = getFlowFormFieldRuntimeKey(field.name);
    formValues = {
      ...formValues,
      [key]: value
    };
  }

  function reuseLastInput() {
    if (lastInputPayload) {
      if (hasFormFields) {
        const nextValues: Record<string, unknown> = { ...formValues };
        for (const field of formFields) {
          const key = getFlowFormFieldRuntimeKey(field.name);
          const previous = lastInputPayload[key];
          if (field.type === "multiselect") {
            nextValues[key] = Array.isArray(previous)
              ? previous.map((item) => String(item))
              : typeof previous === "string"
                ? previous
                    .split(",")
                    .map((item) => item.trim())
                    .filter((item) => item.length > 0)
                : [];
          } else if (previous !== undefined) {
            nextValues[key] = previous;
          } else {
            nextValues[key] = "";
          }
        }
        formValues = nextValues;
      } else if (showFreeformTextInput) {
        inputText = String(lastInputPayload.text ?? JSON.stringify(lastInputPayload));
      }
    }
  }

  function getUploadedFiles(stepId: string): UploadedFile[] {
    return fileInputState.getUploadedFiles(stepId);
  }

  function getStepFileCount(step: FlowRunContractStepInput): number {
    return getUploadedFiles(step.step_id).length;
  }

  function getRemainingFileSlots(step: FlowRunContractStepInput): number {
    if (step.max_files == null) return Infinity;
    return step.max_files - getStepFileCount(step);
  }

  function getTemplateStatusLabel(status: string | null | undefined): string {
    switch (status) {
      case "ready":
        return labels.templateReady;
      case "needs_action":
        return labels.templateNeedsAction;
      case "read_only":
        return labels.templateReadOnly;
      default:
        return labels.templateUnavailable;
    }
  }

  function getTemplateStatusClasses(status: string | null | undefined): string {
    switch (status) {
      case "ready":
        return "border-positive-default/30 bg-positive-default/10 text-positive-stronger";
      case "read_only":
        return "border-accent-default/30 bg-accent-dimmer text-accent-stronger";
      case "needs_action":
        return "border-warning-default/30 bg-warning-dimmer text-warning-stronger";
      default:
        return "border-negative-default/30 bg-negative-dimmer text-negative-stronger";
    }
  }

  function getTemplateReadinessMessage(item: FlowRunContractTemplateReadiness): string | null {
    return (
      getFlowRuntimeErrorMessageByCode(item.message_code) ??
      (item.status === "read_only"
        ? labels.templateReadOnlyMessage
        : item.status === "ready"
          ? null
          : labels.templateNeedsActionMessage)
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
        void uploadFilesForStep(step, Array.from(target.files));
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

  async function uploadRuntimeFileWithTimeout(
    step: FlowRunContractStepInput,
    file: File
  ): Promise<UploadedFile> {
    const controller = new AbortController();
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    const timeoutPromise = new Promise<never>((_, reject) => {
      timeoutId = setTimeout(() => {
        controller.abort();
        reject(
          new Error(
            `Upload timed out after ${Math.round(FLOW_UPLOAD_TIMEOUT_MS / 1000)}s for ${file.name}.`
          )
        );
      }, FLOW_UPLOAD_TIMEOUT_MS);
    });

    try {
      const uploadPromise = intric.flows.steps.runtimeFiles.upload({
        id: flow.id,
        stepId: step.step_id,
        file,
        signal: controller.signal
      });
      return await Promise.race([uploadPromise, timeoutPromise]);
    } finally {
      if (timeoutId) clearTimeout(timeoutId);
    }
  }

  type StepUploadResult = {
    uploadedCount: number;
    failed: boolean;
  };

  async function uploadFilesForStep(
    step: FlowRunContractStepInput,
    files: File[],
    options: { clearRecordingNotice?: boolean } = {}
  ): Promise<StepUploadResult> {
    if (!flow.id) return { uploadedCount: 0, failed: true };

    fileInputState.beginStepUpload(step.step_id, options);
    let uploadedCount = 0;
    let failed = false;

    try {
      const remainingSlots = getRemainingFileSlots(step);
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
        return { uploadedCount, failed: files.length > 0 };
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
          const uploaded = await uploadRuntimeFileWithTimeout(step, file);
          uploadedCount += 1;
          fileInputState.recordUploadedFile(step.step_id, uploaded);
        } catch (error) {
          failed = true;
          fileInputState.recordUploadFailure(
            step.step_id,
            getFlowRuntimeErrorMessage(error, String(error))
          );
        }
      }
      return { uploadedCount, failed };
    } finally {
      fileInputState.finishStepUpload(step.step_id);
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
      },
      // The dialog already owns persistence + upload via handleRecordedAudio,
      // so the session-class deps for upload/delete are no-ops here. We
      // never call session.onSegmentFinalized — only notifyHardFailure —
      // so these branches don't run in practice but must satisfy the type.
      uploadSegment: async () => ({ ok: true, fileId: "" }),
      deleteUploadedSegment: async () => undefined
    };
  }

  function ensureRecordingSessionForStep(stepId: string): RecordingSession | null {
    if (!flow?.id) return null;
    const step = stepsRequiringInput.find((s) => s.step_id === stepId);
    if (!step) return null;
    const contractSnapshot = buildContractSnapshotFromStep(
      step,
      runContract?.published_flow_version ?? null
    );

    const existing = recordingSessionsByStepId[stepId];
    if (existing) {
      const phase = existing.summary().state;
      // The session knows how to take over a queued retry; let it cancel
      // its own retry timer rather than disposing the session here.
      if (phase === "reconnecting") {
        existing.beginRecordingExternal({ flowId: flow.id, stepId, contractSnapshot });
        return existing;
      }
      // Terminal states need a fresh session — beginRecordingExternal would
      // refuse on a session that has already produced segments.
      if (phase === "completed" || phase === "discarded" || phase === "paused-failed") {
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
    session.beginRecordingExternal({
      flowId: flow.id,
      stepId,
      contractSnapshot
    });
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
    const sessionId = fileInputState.sessionIdsByStepIdSnapshot[stepId];
    fileInputState.discardStepRecording(stepId);
    if (flow?.id && sessionId) {
      await purgeSession({ intric, flowId: flow.id, stepId, sessionId });
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
    const file = fileInputState.getRecordedFile(step.step_id);
    if (!file) {
      openFilePicker(step);
      return;
    }

    const result = await uploadFilesForStep(step, [file], { clearRecordingNotice: false });
    if (result.uploadedCount > 0 && !result.failed) {
      fileInputState.clearPreservedRecording(step.step_id);
    }
  }

  async function handleRecordedAudio(
    step: FlowRunContractStepInput,
    params: { blob: Blob; mimeType: string; reason: RecordingStopReason; durationMs: number }
  ) {
    if (!flow?.id) return;
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
      flowId: flow.id,
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
    fileInputState.recordSegmentPersistence({
      stepId: step.step_id,
      file,
      notice: recordingNoticeForReason(params.reason),
      degraded: persistResult.degraded
    });
    const beforeUploadCount = fileInputState.getUploadedFiles(step.step_id).length;
    const result = await uploadFilesForStep(step, [file], { clearRecordingNotice: false });
    if (result.uploadedCount > 0 && !result.failed) {
      const uploaded = fileInputState.getUploadedFiles(step.step_id)[beforeUploadCount];
      if (uploaded?.id) {
        await markSegmentUploaded({
          flowId: flow.id,
          stepId: step.step_id,
          sessionId: prepared.sessionId,
          segmentIndex: prepared.segmentIndex,
          uploadedFileId: uploaded.id
        });
      }
      fileInputState.clearPreservedRecording(step.step_id);
    }

    // After persistence + upload settles, hand the reason to the session
    // controller. error/stall trip the reconnect retry loop; manual/limit
    // close out the session so the next user-click starts fresh.
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
      const { url } = await intric.files.generateSignedUrl({
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
    if (!flow?.id || !fileInputState.beginResumeAction(stepId)) return;
    try {
      const records = await readSessionRecords(flow.id, stepId, hint.sessionId);
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

      fileInputState.attachRecoveredSession(stepId, hint.sessionId, records.length);
      goToPageById(runtimeStepPageId(stepId));

      // Process records in segment-index order so the per-segment
      // transcription header (Del 1 / Del 2 / ...) matches the document
      // order. Mixing reattach + re-upload would otherwise leave the
      // re-uploaded segments at the tail of the file input state.
      for (const record of records) {
        if (record.uploadedFileId) {
          const synthesized = synthesizeUploadedFileFromRecord(record);
          fileInputState.recordUploadedFile(stepId, synthesized);
          continue;
        }

        const reuploadFile = makeReuploadFileFromRecord(record);
        const before = fileInputState.getUploadedFiles(step.step_id).length;
        const result = await uploadFilesForStep(step, [reuploadFile], {
          clearRecordingNotice: false
        });
        if (result.uploadedCount > 0 && !result.failed) {
          const uploaded = fileInputState.getUploadedFiles(step.step_id)[before];
          if (uploaded?.id) {
            await markSegmentUploaded({
              flowId: flow.id,
              stepId,
              sessionId: hint.sessionId,
              segmentIndex: record.segmentIndex,
              uploadedFileId: uploaded.id
            });
          }
        }
      }
    } finally {
      fileInputState.finishResumeAction();
    }
  }

  async function discardResumedSession(stepId: string, hint: SessionRecoveryHint) {
    if (!flow?.id || !fileInputState.beginResumeAction(stepId)) return;
    try {
      await purgeSession({ intric, flowId: flow.id, stepId, sessionId: hint.sessionId });
      fileInputState.discardRecoveredSession(stepId);
    } finally {
      fileInputState.finishResumeAction();
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
      let payload: Record<string, unknown>;
      if (hasFormFields) {
        payload = {};
        for (const field of formFields) {
          const key = getFlowFormFieldRuntimeKey(field.name);
          if (field.type === "multiselect") {
            payload[key] = getFieldMultiValue(field);
          } else if (field.type === "number") {
            const raw = getFieldValue(field).trim();
            payload[key] = raw.length > 0 ? Number(raw) : raw;
          } else {
            payload[key] = getFieldValue(field);
          }
        }
      } else if (showFreeformTextInput) {
        payload = { text: inputText };
      } else {
        payload = {};
      }

      const stepInputs = buildStepInputsPayload(fileInputState.runtimeFilesSnapshot);
      const runIntent = buildFlowRunIntent({
        publishedFlowVersion: runContract.published_flow_version,
        inputPayloadJson: payload,
        stepInputs
      });
      const idempotencyKey = await intric.flows.runs.deriveUploadIntentIdempotencyKey({
        flowId: flow.id,
        expectedFlowVersion: runIntent.expected_flow_version,
        input_payload_json: runIntent.input_payload_json,
        ...(runIntent.step_inputs ? { step_inputs: runIntent.step_inputs } : {})
      });
      const createdRun = await intric.flows.runs.create({
        flow: { id: flow.id },
        ...runIntent,
        idempotencyKey
      });

      onRunCreated?.({ runId: createdRun.id });
      toast.success(m.flow_run_started_toast());

      // Clear all persisted sessions for this flow on success — the run was
      // accepted by the backend, so the local copy is no longer needed.
      await purgeAllSessions({
        flowId: flow.id,
        sessionIdsByStepId: fileInputState.sessionIdsByStepIdSnapshot
      });

      open = false;
      inputText = "";
      formValues = {};
      fileInputState.resetAfterRunAccepted();
    } catch (error) {
      toast.error(
        getFlowRuntimeErrorMessage(
          error,
          error instanceof IntricError ? error.getReadableMessage() : String(error)
        )
      );
    } finally {
      isSubmitting = false;
    }
  }

  function getReviewFieldValue(field: NormalizedFlowFormField): string {
    if (field.type === "multiselect") {
      return getFieldMultiValue(field).join(", ");
    }
    return getFieldValue(field).trim();
  }

  function formatBytes(bytes: number): string {
    if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let value = bytes;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024;
      unitIndex += 1;
    }
    return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content
    class="!flex max-h-[92vh] min-h-[24rem] !max-w-5xl flex-col !gap-0 overflow-hidden !rounded-2xl !p-0 sm:min-h-[30rem]"
    showCloseButton={false}
    interactOutsideBehavior={closeBehavior}
    escapeKeydownBehavior={closeBehavior}
    onInteractOutside={handleInteractOutside}
    onEscapeKeydown={handleEscapeKeydown}
  >
    <header class="border-default/60 shrink-0 border-b px-4 py-4 sm:px-6 sm:py-5 lg:px-8">
      <div class="flex items-start justify-between gap-4">
        <div class="min-w-0">
          <Dialog.Title class="text-primary text-lg font-semibold tracking-tight sm:text-xl">
            {m.flow_run_trigger()}
          </Dialog.Title>
          <Dialog.Description
            class="text-secondary mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm"
          >
            <span class="text-primary truncate font-medium">{flow.name}</span>
            {#if stepCount > 0}
              <Badge variant="outline" class="h-5 text-xs font-medium tabular-nums">
                {m.flow_run_step_count({ count: String(stepCount) })}
              </Badge>
            {/if}
          </Dialog.Description>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          class="text-muted hover:text-primary -mt-1 -mr-1 shrink-0"
          aria-label={m.flow_run_trigger_close()}
          onclick={handleCancel}
        >
          <IconXMark />
        </Button>
      </div>
    </header>

    {#if runContract === null && !runContractError}
      <div class="mt-5 flex flex-col gap-3 px-4 sm:px-6 lg:px-8" aria-busy="true">
        <div class="bg-secondary/25 h-[6rem] animate-pulse rounded-xl"></div>
        <div class="bg-secondary/25 h-[8rem] animate-pulse rounded-xl"></div>
      </div>
    {:else if runContractError}
      <div class="mx-4 mt-5 sm:mx-6 lg:mx-8">
        <Alert.Root variant="destructive">
          <Alert.Description>{runContractError}</Alert.Description>
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
      <div class="border-default/60 shrink-0 border-b px-4 py-4 sm:px-6 lg:px-8">
        <div class="grid gap-4 md:grid-cols-[minmax(0,1fr)_17rem] md:items-center">
          <div class="min-w-0">
            <p class="text-muted mb-1 text-[0.6875rem] font-medium tracking-[0.08em] uppercase">
              {progressLabel}
            </p>
            <h3
              class="text-primary text-base font-semibold tracking-tight sm:text-lg"
              data-wizard-heading
              tabindex="-1"
            >
              {currentPage.title}
            </h3>
            <p class="text-secondary mt-1 text-sm leading-relaxed">
              {currentPage.description}
            </p>
          </div>
          <nav class="flex items-center gap-1.5" aria-label={progressLabel}>
            {#each wizardPages as page, pageIndex (page.id)}
              {@const isCompleted = pageIndex < currentPageIndex}
              {@const isCurrent = pageIndex === currentPageIndex}
              {@const isClickable = isCompleted}
              <button
                type="button"
                title={page.title}
                class="focus-visible:ring-ring/50 relative h-1.5 flex-1 rounded-full transition-colors duration-200 before:absolute before:-inset-x-0 before:-inset-y-5 before:content-[''] focus-visible:ring-2 focus-visible:ring-offset-2 {isCompleted
                  ? 'bg-accent-default'
                  : isCurrent
                    ? 'bg-accent-default/55'
                    : 'bg-hover-dimmer'}"
                aria-label={page.title}
                aria-current={isCurrent ? "step" : undefined}
                disabled={!isClickable}
                class:cursor-pointer={isClickable}
                class:cursor-default={!isClickable}
                onclick={() => {
                  if (isClickable) goToPageById(page.id);
                }}
              ></button>
            {/each}
          </nav>
        </div>
      </div>

      <div
        class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-5 sm:px-6 sm:py-6 lg:px-8"
        bind:this={pageContentEl}
      >
        {#if currentPage.kind === "overview"}
          <div class="flex flex-col gap-4">
            <div class="border-default bg-primary rounded-xl border px-4 py-4">
              <div class="flex items-center justify-between gap-3">
                <div>
                  <p class="text-sm font-semibold">{labels.templateStatusTitle}</p>
                  <p class="text-secondary mt-1 text-sm leading-relaxed">
                    {labels.templateStatusDescription}
                  </p>
                </div>
                <span
                  class="border-default text-secondary rounded-full border px-2.5 py-1 text-xs font-medium"
                >
                  v{runContract?.published_flow_version ?? "—"}
                </span>
              </div>
              <div class="mt-4 flex flex-col gap-3">
                {#each templateReadinessItems as item (item.step_id)}
                  <div class="border-default bg-secondary/20 rounded-xl border px-4 py-3.5">
                    <div class="flex flex-wrap items-start justify-between gap-3">
                      <div class="min-w-0">
                        <p class="text-sm font-medium">
                          {item.template_name ?? labels.templateFallbackName(item.step_id)}
                        </p>
                        {#if getTemplateReadinessMessage(item)}
                          <p class="text-secondary mt-1 text-xs leading-relaxed">
                            {getTemplateReadinessMessage(item)}
                          </p>
                        {/if}
                      </div>
                      <span
                        class={`rounded-full border px-2.5 py-1 text-xs font-medium ${getTemplateStatusClasses(item.status)}`}
                      >
                        {getTemplateStatusLabel(item.status)}
                      </span>
                    </div>
                  </div>
                {/each}
              </div>
            </div>

            {#if currentTemplateBlockers.length > 0}
              <div
                class="border-warning-default/30 bg-warning-dimmer text-warning-stronger rounded-xl border px-4 py-3 text-sm"
              >
                <p class="font-medium">{labels.runBlockersTitle}</p>
                <ul class="mt-2 space-y-1.5">
                  {#each currentTemplateBlockers as blocker (blocker.id)}
                    <li>{blocker.title}</li>
                  {/each}
                </ul>
              </div>
            {/if}
          </div>
        {:else if currentPage.kind === "form"}
          <FlowRunDialogForm
            {formFields}
            {formValues}
            {missingRequiredFields}
            {hasRequiredFormFields}
            {labels}
            onFieldChange={setFieldValue}
          />
        {:else if currentPage.kind === "freeform"}
          <Field.Field>
            <Field.Label for="flow-run-freeform-input" class="text-sm font-medium">
              {m.flow_run_input()}
            </Field.Label>
            <Field.Description>{m.flow_run_input_desc()}</Field.Description>
            <Textarea
              id="flow-run-freeform-input"
              class="min-h-[14rem] font-mono text-[0.8125rem] leading-relaxed"
              bind:value={inputText}
              placeholder={m.flow_run_input_placeholder()}
            />
          </Field.Field>
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
            blockers={currentStepBlockers}
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
            {inputText}
            {showFreeformTextInput}
            {reviewFileGroups}
            {labels}
            onGoToPage={goToPageById}
          />
        {/if}
      </div>
    {/if}

    <!-- Footer -->
    <footer
      class="border-default shrink-0 border-t px-4 py-3 sm:px-6 sm:py-3.5 lg:px-8 {showCloseConfirmation
        ? 'bg-warning-dimmer/25'
        : ''}"
    >
      {#if showCloseConfirmation}
        <div
          class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
          role="alertdialog"
          aria-label={labels.closeConfirmTitle}
          aria-describedby="close-confirm-desc"
        >
          <div class="min-w-0">
            <p class="text-primary text-sm font-medium">{labels.closeConfirmTitle}</p>
            <p id="close-confirm-desc" class="text-muted mt-0.5 text-sm">
              {labels.closeConfirmMessage}
            </p>
          </div>
          <div class="flex shrink-0 gap-2">
            <Button variant="outline" size="sm" onclick={handleCancelClose}>
              {labels.closeConfirmKeep}
            </Button>
            <Button variant="destructive" size="sm" onclick={handleConfirmClose}>
              {labels.closeConfirmDiscard}
            </Button>
          </div>
        </div>
      {:else}
        <div class="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
          <div class="order-2 flex gap-2 sm:order-1">
            {#if lastInputPayload && (currentPage?.kind === "form" || currentPage?.kind === "freeform")}
              <Button variant="outline" onclick={reuseLastInput} class="w-full sm:w-auto">
                {m.flow_run_reuse_last_input()}
              </Button>
            {/if}
          </div>

          <div class="hidden flex-grow sm:order-2 sm:block"></div>

          <div
            class="order-1 flex w-full flex-col gap-2 sm:order-3 sm:w-auto sm:flex-row sm:items-center"
          >
            {#if currentPage && currentPage.kind === "review"}
              <Button
                onclick={triggerRun}
                disabled={!canSubmitRun}
                class="order-1 w-full min-w-[8rem] sm:order-3 sm:w-auto"
              >
                {#if isSubmitting}
                  <IconLoadingSpinner data-icon="inline-start" class="animate-spin" />
                {/if}
                {m.flow_run_trigger_confirm()}
              </Button>
            {:else}
              <Button
                onclick={goToNextPage}
                disabled={!canGoNext}
                title={!canGoNext ? getDisabledNextReason() : undefined}
                class="order-1 w-full min-w-[7rem] sm:order-3 sm:w-auto"
              >
                {labels.next}
              </Button>
            {/if}

            <Button
              variant="outline"
              onclick={handleCancel}
              class="order-3 w-full sm:order-2 sm:w-auto">{m.cancel()}</Button
            >

            {#if currentPageIndex > 0}
              <Button
                variant="outline"
                onclick={goToPreviousPage}
                class="order-2 w-full sm:order-1 sm:w-auto"
              >
                {labels.previous}
              </Button>
            {/if}
          </div>
        </div>
      {/if}
    </footer>
  </Dialog.Content>
</Dialog.Root>
