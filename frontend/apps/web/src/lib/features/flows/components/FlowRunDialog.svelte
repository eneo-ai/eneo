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
  import { Button } from "$lib/components/ui/button/index.js";
  import { IntricError } from "@intric/intric-js";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import {
    getFlowFormFieldRuntimeKey,
    normalizeFlowFormFields,
    type FlowFormField,
    type NormalizedFlowFormField
  } from "$lib/features/flows/flowFormSchema";
  import {
    buildStepInputsPayload,
    normalizeTemplateReadiness
  } from "$lib/features/flows/flowRunContract";
  import {
    buildFlowRunBlockers,
    buildFlowRunReviewSummary,
    buildFlowRunWizardPages,
    runtimeStepPageId,
    type FlowLocale,
    type FlowRunBlocker,
    type FlowRunWizardPage
  } from "$lib/features/flows/flowRunWizard";
  import {
    getFlowRuntimeErrorMessage,
    getFlowRuntimeErrorMessageByCode,
    classifyUploadError,
    getUploadErrorHint,
    friendlyMimeNames
  } from "$lib/features/flows/flowRuntimeErrorMapping";
  import { IconUploadCloud } from "@intric/icons/upload-cloud";
  import { IconXMark } from "@intric/icons/x-mark";
  import { IconCheck } from "@intric/icons/check";
  import { IconInfo } from "@intric/icons/info";

  let {
    open = $bindable(false),
    flow,
    intric,
    lastInputPayload,
    onRunCreated
  }: {
    open: boolean;
    flow: Flow;
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
  let runtimeFilesByStepId = $state<Record<string, UploadedFile[]>>({});
  let uploadErrorsByStepId = $state<Record<string, string | null>>({});
  let skippedMessagesByStepId = $state<Record<string, string | null>>({});
  let uploadingStepIds = $state<string[]>([]);
  let draggingStepId = $state<string | null>(null);
  let currentPageIndex = $state(0);
  let showCloseConfirmation = $state(false);
  let pageContentEl = $state<HTMLElement | null>(null);

  const FLOW_UPLOAD_TIMEOUT_MS = 120_000;
  const AUDIO_ACCEPT_FILTER = "audio/*,video/webm,video/mp4";
  const locale = (getLocale() === "en" ? "en" : "sv") as FlowLocale;
  const labels = getRunDialogLabels(locale);

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
  const stepsRequiringInput = $derived(runContract?.steps_requiring_input ?? []);
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
      runtimeFilesByStepId,
      templateReadinessItems,
      uploadingStepIds
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
  const progressPercent = $derived(
    wizardPages.length > 0 ? ((currentPageIndex + 1) / wizardPages.length) * 100 : 0
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
    currentRuntimeStep ? (runtimeFilesByStepId[currentRuntimeStep.step_id] ?? []) : []
  );
  const currentStepFileCount = $derived(currentStepUploadedFiles.length);
  const currentStepRemainingSlots = $derived(
    currentRuntimeStep?.max_files != null
      ? currentRuntimeStep.max_files - currentStepFileCount
      : Infinity
  );
  const currentStepIsUploading = $derived(
    currentRuntimeStep ? uploadingStepIds.includes(currentRuntimeStep.step_id) : false
  );
  const currentStepUploadError = $derived(
    currentRuntimeStep ? (uploadErrorsByStepId[currentRuntimeStep.step_id] ?? null) : null
  );
  const currentStepSkippedMessage = $derived(
    currentRuntimeStep ? (skippedMessagesByStepId[currentRuntimeStep.step_id] ?? null) : null
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
      Object.values(runtimeFilesByStepId).some((files) => files.length > 0) ||
      Object.entries(formValues).some(([_, v]) => v != null && String(v).trim() !== "") ||
      inputText.trim() !== ""
  );
  const closeBehavior = $derived<"close" | "ignore">(isDirty ? "ignore" : "close");

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
    runtimeFilesByStepId = {};
    uploadErrorsByStepId = {};
    skippedMessagesByStepId = {};
    uploadingStepIds = [];
    draggingStepId = null;
    currentPageIndex = 0;
    showCloseConfirmation = false;
  }

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
    return runtimeFilesByStepId[stepId] ?? [];
  }

  function getStepFileCount(step: FlowRunContractStepInput): number {
    return getUploadedFiles(step.step_id).length;
  }

  function getRemainingFileSlots(step: FlowRunContractStepInput): number {
    if (step.max_files == null) return Infinity;
    return step.max_files - getStepFileCount(step);
  }

  function getUploadError(stepId: string): string | null {
    return uploadErrorsByStepId[stepId] ?? null;
  }

  function getSkippedMessage(stepId: string): string | null {
    return skippedMessagesByStepId[stepId] ?? null;
  }

  function isStepUploading(stepId: string): boolean {
    return uploadingStepIds.includes(stepId);
  }

  function getStepLabel(step: FlowRunContractStepInput): string {
    return step.label?.trim() || labels.unnamedStep(step.step_order);
  }

  function getInputFormatLabel(inputFormat: string): string {
    switch (inputFormat) {
      case "audio":
        return labels.audio;
      case "file":
        return labels.file;
      default:
        return labels.document;
    }
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

  function getStepAcceptFilter(step: FlowRunContractStepInput): string | undefined {
    if (step.accepted_mimetypes.length > 0) {
      return step.accepted_mimetypes.join(",");
    }
    return step.input_format === "audio" ? AUDIO_ACCEPT_FILTER : undefined;
  }

  function openFilePicker(step: FlowRunContractStepInput) {
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

  function handleDrop(step: FlowRunContractStepInput, event: DragEvent) {
    event.preventDefault();
    draggingStepId = null;
    if (event.dataTransfer?.files) {
      void uploadFilesForStep(step, Array.from(event.dataTransfer.files));
    }
  }

  function handleDragOver(stepId: string, event: DragEvent) {
    event.preventDefault();
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = "copy";
    }
    draggingStepId = stepId;
  }

  function handleDragLeave(stepId: string, event: DragEvent) {
    const target = event.currentTarget as HTMLElement;
    if (!target.contains(event.relatedTarget as Node)) {
      if (draggingStepId === stepId) {
        draggingStepId = null;
      }
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

  async function uploadFilesForStep(step: FlowRunContractStepInput, files: File[]) {
    if (!flow.id) return;

    uploadErrorsByStepId = { ...uploadErrorsByStepId, [step.step_id]: null };
    skippedMessagesByStepId = { ...skippedMessagesByStepId, [step.step_id]: null };
    uploadingStepIds = [...uploadingStepIds, step.step_id];

    try {
      const remainingSlots = getRemainingFileSlots(step);
      const toUpload =
        remainingSlots !== Infinity ? files.slice(0, Math.max(remainingSlots, 0)) : files;

      if (toUpload.length < files.length && step.max_files != null) {
        skippedMessagesByStepId = {
          ...skippedMessagesByStepId,
          [step.step_id]: m.flow_run_max_files_exceeded({
            attempted: String(files.length),
            limit: String(step.max_files),
            skipped: String(files.length - toUpload.length)
          })
        };
      }

      if (toUpload.length === 0) {
        return;
      }

      for (const file of toUpload) {
        if (step.max_file_size_bytes != null && file.size > step.max_file_size_bytes) {
          uploadErrorsByStepId = {
            ...uploadErrorsByStepId,
            [step.step_id]: `${file.name}: ${m.flow_run_upload_max_size({
              size: formatBytes(step.max_file_size_bytes)
            })}`
          };
          continue;
        }

        try {
          const uploaded = await uploadRuntimeFileWithTimeout(step, file);
          runtimeFilesByStepId = {
            ...runtimeFilesByStepId,
            [step.step_id]: [...getUploadedFiles(step.step_id), uploaded]
          };
        } catch (error) {
          uploadErrorsByStepId = {
            ...uploadErrorsByStepId,
            [step.step_id]: getFlowRuntimeErrorMessage(error, String(error))
          };
        }
      }
    } finally {
      uploadingStepIds = uploadingStepIds.filter((stepId) => stepId !== step.step_id);
    }
  }

  function removeFile(stepId: string, fileId: string) {
    runtimeFilesByStepId = {
      ...runtimeFilesByStepId,
      [stepId]: getUploadedFiles(stepId).filter((file) => file.id !== fileId)
    };
    skippedMessagesByStepId = { ...skippedMessagesByStepId, [stepId]: null };
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

  function retryUpload(step: FlowRunContractStepInput) {
    uploadErrorsByStepId = { ...uploadErrorsByStepId, [step.step_id]: null };
    openFilePicker(step);
  }

  function getDisabledNextReason(): string | undefined {
    if (isSubmitting) return undefined;
    if (currentPageProgressBlockers.length > 0) {
      return currentPageProgressBlockers[0]?.title;
    }
    return undefined;
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

      const stepInputs = buildStepInputsPayload(runtimeFilesByStepId);
      const createdRun = await intric.flows.runs.create({
        flow: { id: flow.id },
        expected_flow_version: runContract.published_flow_version,
        input_payload_json: payload,
        ...(stepInputs ? { step_inputs: stepInputs } : {})
      });

      onRunCreated?.({ runId: createdRun.id });
      toast.success(m.flow_run_started_toast());
      open = false;
      inputText = "";
      formValues = {};
      runtimeFilesByStepId = {};
      uploadErrorsByStepId = {};
      skippedMessagesByStepId = {};
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

  function getCurrentStepBlockerSummary(stepId: string): FlowRunBlocker[] {
    return runBlockers.filter(
      (blocker) => blocker.pageId === runtimeStepPageId(stepId) && blocker.blocksProgress
    );
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

  function getRunDialogLabels(locale: FlowLocale) {
    if (locale === "sv") {
      return {
        progress: (current: number, total: number) => `${current} av ${total}`,
        previous: "Tillbaka",
        next: "Nästa",
        audio: "Ljud",
        file: "Fil",
        document: "Dokument",
        unnamedStep: (stepOrder: number) => `Steg ${stepOrder}`,
        templateReady: "Klar",
        templateNeedsAction: "Åtgärd krävs",
        templateReadOnly: "Skrivskyddad",
        templateUnavailable: "Otillgänglig",
        templateReadOnlyMessage: "Du kan köra flödet men inte byta mall.",
        templateNeedsActionMessage: "Mallen kräver åtgärd innan flödet kan köras.",
        templateStatusTitle: "Mallstatus",
        templateStatusDescription:
          "Kontrollera att publicerade DOCX-mallar fortfarande är tillgängliga innan du kör flödet.",
        templateFallbackName: (stepId: string) => `Mall för ${stepId}`,
        formIntroTitle: "Fyll i innan du kör flödet",
        formIntroDescription:
          "Fyll i de fält du skapade tidigare. Värdena blir sedan tillgängliga i flödet.",
        retryUpload: "Försök igen",
        disabledNextHint: "Fyll i obligatoriska fält först",
        runtimeGroupEyebrow: "Filer för denna körning",
        runtimeScopeHint: (stepOrder: number) => `Detta underlag används bara i steg ${stepOrder}.`,
        runtimeUploadHint: "Ladda upp fil eller dra den hit.",
        runtimeUploadingHint: "Uppladdning pågår. Vänta tills filen är klar innan du går vidare.",
        runtimeStepUploadTitle: "Uppladdning för detta steg",
        allowedTypesToggle: "Visa tillåtna filtyper",
        maxFiles: (count: number) => `Max ${count}`,
        maxFilesReached: "Max antal filer har redan laddats upp för detta steg.",
        requiredBadge: "Obligatoriskt",
        selectedFiles: (count: number) =>
          `${count} fil${count === 1 ? "" : "er"} vald${count === 1 ? "" : "a"}`,
        runBlockersTitle: "Det här behöver lösas innan du kan köra flödet",
        reviewReady: "Allt som krävs är klart. Du kan köra flödet nu.",
        reviewSummaryTitle: "Det här följer med i körningen",
        reviewFieldsTitle: "Fält som skickas med",
        reviewTextTitle: "Text som skickas in",
        reviewFilesTitle: "Uppladdade filer",
        runtimeReviewStep: (stepOrder: number, stepLabel: string) =>
          `Steg ${stepOrder}: ${stepLabel}`,
        closeConfirmTitle: "Du har osparade uppgifter",
        closeConfirmMessage: "Om du stänger dialogen försvinner uppladdade filer och ifyllda fält.",
        closeConfirmDiscard: "Stäng ändå",
        closeConfirmKeep: "Fortsätt redigera",
        technicalMimeToggle: "Visa tekniska MIME-typer"
      };
    }

    return {
      progress: (current: number, total: number) => `${current} of ${total}`,
      previous: "Back",
      next: "Next",
      audio: "Audio",
      file: "File",
      document: "Document",
      unnamedStep: (stepOrder: number) => `Step ${stepOrder}`,
      templateReady: "Ready",
      templateNeedsAction: "Needs action",
      templateReadOnly: "Read-only",
      templateUnavailable: "Unavailable",
      templateReadOnlyMessage: "You can run the flow but you cannot change the template.",
      templateNeedsActionMessage: "The template needs attention before the flow can run.",
      templateStatusTitle: "Template status",
      templateStatusDescription:
        "Check that published DOCX templates are still available before you run the flow.",
      templateFallbackName: (stepId: string) => `Template for ${stepId}`,
      formIntroTitle: "Fill in before running the flow",
      formIntroDescription:
        "Fill in the fields you created earlier. The values will then be available in the flow.",
      retryUpload: "Try again",
      disabledNextHint: "Fill in required fields first",
      runtimeGroupEyebrow: "Files for this run",
      runtimeScopeHint: (stepOrder: number) => `This material is only used in step ${stepOrder}.`,
      runtimeUploadHint: "Upload a file or drag it here.",
      runtimeUploadingHint:
        "Upload in progress. Wait until the file is finished before continuing.",
      runtimeStepUploadTitle: "Upload for this step",
      allowedTypesToggle: "Show allowed file types",
      maxFiles: (count: number) => `Max ${count}`,
      maxFilesReached: "The maximum number of files has already been uploaded for this step.",
      requiredBadge: "Required",
      selectedFiles: (count: number) => `${count} file${count === 1 ? "" : "s"} selected`,
      runBlockersTitle: "This still needs to be resolved before you can run the flow",
      reviewReady: "Everything required is ready. You can run the flow now.",
      reviewSummaryTitle: "Included in this run",
      reviewFieldsTitle: "Fields that will be sent",
      reviewTextTitle: "Text that will be sent",
      reviewFilesTitle: "Uploaded files",
      runtimeReviewStep: (stepOrder: number, stepLabel: string) =>
        `Step ${stepOrder}: ${stepLabel}`,
      closeConfirmTitle: "You have unsaved changes",
      closeConfirmMessage: "Closing this dialog will discard uploaded files and filled-in fields.",
      closeConfirmDiscard: "Discard and close",
      closeConfirmKeep: "Keep editing",
      technicalMimeToggle: "Show technical MIME types"
    };
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content
    class="!flex max-h-[90vh] min-h-[24rem] !max-w-5xl flex-col !gap-0 overflow-hidden !rounded-2xl !p-0 sm:min-h-[30rem]"
    showCloseButton={false}
    interactOutsideBehavior={closeBehavior}
    escapeKeydownBehavior={closeBehavior}
    onInteractOutside={handleInteractOutside}
    onEscapeKeydown={handleEscapeKeydown}
  >
    <div class="shrink-0 px-4 pt-5 sm:px-6 sm:pt-7 lg:px-8">
      <div class="flex items-start justify-between">
        <div>
          <Dialog.Title class="text-xl font-bold">{m.flow_run_trigger()}</Dialog.Title>
          <Dialog.Description class="text-secondary mt-1 text-sm">
            {flow.name}
            {#if stepCount > 0}
              <span class="text-muted ml-1"
                >({m.flow_run_step_count({ count: String(stepCount) })})</span
              >
            {/if}
          </Dialog.Description>
        </div>
        <button
          onclick={() => handleCancel()}
          class="text-muted hover:text-primary -mt-2 -mr-2 flex size-11 shrink-0 items-center justify-center rounded-lg transition-colors"
          type="button"
          aria-label={m.cancel()}
        >
          <IconXMark class="size-4" />
        </button>
      </div>
    </div>

    {#if runContract === null && !runContractError}
      <div class="mt-6 flex flex-col gap-4 px-4 sm:px-6 lg:px-8">
        <div class="bg-secondary/10 h-[7rem] animate-pulse rounded-2xl"></div>
        <div class="bg-secondary/10 h-[10rem] animate-pulse rounded-xl"></div>
      </div>
    {:else if runContractError}
      <div
        class="border-negative-default/20 bg-negative-dimmer text-negative-stronger mx-4 mt-6 rounded-lg border px-4 py-3 text-sm sm:mx-6 lg:mx-8"
        role="alert"
      >
        <p>{runContractError}</p>
        <button
          class="text-negative-stronger mt-2 text-xs font-medium underline underline-offset-2 hover:no-underline"
          onclick={() => {
            runContractLoadedForFlowId = null;
          }}
        >
          {labels.retryUpload}
        </button>
      </div>
    {:else if currentPage}
      <div class="shrink-0 px-4 sm:px-6 lg:px-8">
        <div class="bg-secondary/10 mt-5 rounded-2xl px-4 py-4 ring-1 ring-black/[0.04] sm:px-5">
          <div class="grid gap-4 md:grid-cols-[minmax(0,1fr)_18rem] md:items-start">
            <div class="min-w-0">
              <p class="sr-only">{progressLabel}</p>
              <h3 class="mt-0 text-lg font-semibold" data-wizard-heading tabindex="-1">
                {currentPage.title}
              </h3>
              <p class="text-secondary mt-1 text-sm leading-relaxed">
                {currentPage.description}
              </p>
            </div>
            <nav class="flex items-center gap-1.5 md:pt-3" aria-label={progressLabel}>
              {#each wizardPages as page, pageIndex (page.id)}
                {@const isCompleted = pageIndex < currentPageIndex}
                {@const isCurrent = pageIndex === currentPageIndex}
                {@const isClickable = isCompleted}
                <button
                  type="button"
                  title={page.title}
                  class="focus-visible:ring-accent-default relative h-1.5 flex-1 rounded-full transition-all duration-200 before:absolute before:-inset-x-0 before:-inset-y-5 before:content-[''] focus-visible:ring-2 focus-visible:ring-offset-2 {isCompleted
                    ? 'bg-accent-default'
                    : isCurrent
                      ? 'bg-accent-default/60'
                      : 'bg-hover-dimmer'}"
                  aria-label="{page.title}{isCompleted ? ' (klar)' : ''}"
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
      </div>

      <div
        class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pr-3 sm:px-6 sm:pr-5 lg:px-8 lg:pr-7"
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
          <div class="flex flex-col gap-5">
            <div class="px-1">
              <p class="text-sm font-semibold">{labels.formIntroTitle}</p>
              <div class="mt-1.5 space-y-1">
                <p class="text-secondary text-sm leading-relaxed">
                  {labels.formIntroDescription}
                </p>
                {#if hasRequiredFormFields}
                  <p class="text-muted text-sm">{m.flow_run_required_hint()}</p>
                {/if}
              </div>
            </div>

            {#if missingRequiredFields.length > 0}
              <div
                id="form-validation-banner"
                class="border-accent-default/20 bg-accent-dimmer/30 text-accent-stronger rounded-lg border px-3.5 py-2.5 text-sm"
                role="status"
                aria-live="polite"
              >
                {#if missingRequiredFieldNames.length > 0}
                  {m.flow_run_missing_required_named({
                    fields: missingRequiredFieldNames.join(", ")
                  })}
                {:else}
                  {m.flow_run_missing_required()}
                {/if}
              </div>
            {/if}

            {#each formFields as field, fieldIndex (field.name)}
              <div class="flex flex-col gap-1.5">
                <label class="text-sm font-medium" for={`flow-input-${fieldIndex}`}>
                  {field.name}
                  {#if field.required}
                    <span class="text-negative-default" aria-hidden="true">*</span>
                    <span class="sr-only">({labels.requiredBadge})</span>
                  {/if}
                </label>
                {#if field.type === "multiselect"}
                  <select
                    id={`flow-input-${fieldIndex}`}
                    class="border-default bg-primary ring-default focus-visible:ring-accent-default min-h-[120px] w-full rounded-lg border px-3 py-2 shadow focus-visible:ring-2"
                    multiple
                    required={field.required}
                    aria-required={field.required}
                    aria-describedby={missingRequiredFields.includes(field)
                      ? "form-validation-banner"
                      : undefined}
                    onchange={(event) => {
                      const selected = Array.from(event.currentTarget.selectedOptions).map(
                        (option) => option.value
                      );
                      setFieldValue(field, selected);
                    }}
                  >
                    {#each field.options ?? [] as option (option)}
                      <option value={option} selected={getFieldMultiValue(field).includes(option)}>
                        {option}
                      </option>
                    {/each}
                  </select>
                {:else if field.type === "select"}
                  <select
                    id={`flow-input-${fieldIndex}`}
                    class="border-default bg-primary ring-default focus-visible:ring-accent-default w-full rounded-lg border px-3 py-2 shadow focus-visible:ring-2"
                    value={getFieldValue(field)}
                    required={field.required}
                    aria-required={field.required}
                    aria-describedby={missingRequiredFields.includes(field)
                      ? "form-validation-banner"
                      : undefined}
                    onchange={(event) => setFieldValue(field, event.currentTarget.value)}
                  >
                    <option value="">{m.flow_select_placeholder()}</option>
                    {#each field.options ?? [] as option (option)}
                      <option value={option}>{option}</option>
                    {/each}
                  </select>
                {:else}
                  <input
                    id={`flow-input-${fieldIndex}`}
                    type={field.type === "number"
                      ? "number"
                      : field.type === "date"
                        ? "date"
                        : "text"}
                    class="border-default bg-primary ring-default focus-visible:ring-accent-default w-full rounded-lg border px-3 py-2 shadow focus-visible:ring-2"
                    value={getFieldValue(field)}
                    autocomplete="off"
                    required={field.required}
                    aria-required={field.required}
                    aria-describedby={missingRequiredFields.includes(field)
                      ? "form-validation-banner"
                      : undefined}
                    oninput={(event) => setFieldValue(field, event.currentTarget.value)}
                  />
                {/if}
              </div>
            {/each}
          </div>
        {:else if currentPage.kind === "freeform"}
          <div class="flex flex-col gap-2">
            <span class="text-sm font-medium">{m.flow_run_input()}</span>
            <span class="text-secondary text-sm leading-relaxed">{m.flow_run_input_desc()}</span>
            <textarea
              class="border-default bg-primary ring-default min-h-[220px] w-full rounded-xl border px-3 py-2 font-mono text-sm shadow focus-within:ring-2"
              bind:value={inputText}
              placeholder={m.flow_run_input_placeholder()}
            ></textarea>
          </div>
        {:else if currentPage.kind === "runtime-step" && currentRuntimeStep}
          <div class="flex flex-col gap-5">
            <div class="px-1">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div class="min-w-0">
                  <div class="flex flex-wrap items-center gap-2">
                    <p class="text-muted text-xs font-medium tracking-[0.14em] uppercase">
                      {labels.runtimeStepUploadTitle}
                    </p>
                    {#if currentRuntimeStep.required}
                      <span
                        class="border-default bg-secondary/15 text-secondary rounded-full border px-2 py-0.5 text-xs font-medium"
                      >
                        {labels.requiredBadge}
                      </span>
                    {/if}
                    {#if currentStepFileCount > 0}
                      <span
                        class="border-positive-default/30 bg-positive-dimmer/50 text-positive-stronger rounded-full border px-2 py-0.5 text-xs font-medium"
                      >
                        {labels.selectedFiles(currentStepFileCount)}
                      </span>
                    {/if}
                  </div>
                  <p class="mt-2 text-base font-semibold">{getStepLabel(currentRuntimeStep)}</p>
                  {#if currentRuntimeStep.description}
                    <p class="text-secondary mt-1 text-sm leading-relaxed">
                      {currentRuntimeStep.description}
                    </p>
                  {/if}
                  <p class="text-muted mt-2 text-sm leading-relaxed">
                    {labels.runtimeScopeHint(currentRuntimeStep.step_order)}
                  </p>
                </div>
                <div class="text-secondary flex flex-wrap gap-2 text-xs">
                  <span class="border-default rounded-full border px-2 py-0.5">
                    {getInputFormatLabel(currentRuntimeStep.input_format)}
                  </span>
                  {#if currentRuntimeStep.max_files != null}
                    <span class="border-default rounded-full border px-2 py-0.5">
                      {labels.maxFiles(currentRuntimeStep.max_files)}
                    </span>
                  {/if}
                  {#if currentRuntimeStep.max_file_size_bytes != null}
                    <span class="border-default rounded-full border px-2 py-0.5">
                      Max {formatBytes(currentRuntimeStep.max_file_size_bytes)}/{locale === "sv"
                        ? "fil"
                        : "file"}
                    </span>
                  {/if}
                </div>
              </div>

              {#if currentStepBlockers.length > 0}
                <div
                  class="border-accent-default/20 bg-accent-dimmer/30 text-accent-stronger mt-5 rounded-lg border px-3.5 py-2.5 text-sm"
                  role="status"
                  aria-live="polite"
                >
                  {currentStepBlockers[0]?.title}
                </div>
              {/if}

              {#if currentStepIsUploading}
                <div
                  class="border-accent-default/30 bg-accent-dimmer text-accent-stronger mt-5 flex items-center gap-2 rounded-lg border px-3.5 py-2.5 text-sm"
                  role="status"
                  aria-live="polite"
                >
                  <IconLoadingSpinner class="size-4 shrink-0 animate-spin" />
                  {labels.runtimeUploadingHint}
                </div>
              {/if}

              <div
                class="{currentStepFileCount > 0
                  ? 'mt-4 py-3.5'
                  : 'mt-6 min-h-[132px] py-6 sm:min-h-[100px]'} flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 text-center transition-all duration-150 {draggingStepId ===
                currentRuntimeStep.step_id
                  ? 'border-accent-default bg-accent-dimmer scale-[1.02]'
                  : currentStepFileCount > 0
                    ? 'border-positive-default/30 bg-positive-dimmer/10'
                    : 'border-default bg-secondary/5'} {currentStepRemainingSlots > 0 &&
                draggingStepId !== currentRuntimeStep.step_id
                  ? 'hover:border-accent-default hover:bg-secondary/15'
                  : ''} {currentStepRemainingSlots <= 0 ? 'pointer-events-none opacity-50' : ''}"
                ondragover={(event) => handleDragOver(currentRuntimeStep.step_id, event)}
                ondragleave={(event) => handleDragLeave(currentRuntimeStep.step_id, event)}
                ondrop={(event) => handleDrop(currentRuntimeStep, event)}
                onclick={() => openFilePicker(currentRuntimeStep)}
                role="button"
                tabindex={currentStepRemainingSlots <= 0 ? -1 : 0}
                aria-label="{m.upload_file()} — {getStepLabel(currentRuntimeStep)}"
                aria-disabled={currentStepRemainingSlots <= 0 ? "true" : undefined}
                onkeydown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    openFilePicker(currentRuntimeStep);
                  }
                }}
              >
                {#if currentStepIsUploading}
                  <IconLoadingSpinner class="text-accent-default size-6 animate-spin" />
                  <span class="text-secondary text-sm">{m.loading()}</span>
                {:else if currentStepFileCount > 0}
                  <div class="flex items-center gap-2.5">
                    <div
                      class="bg-positive-default/10 flex size-8 shrink-0 items-center justify-center rounded-full"
                    >
                      <IconCheck class="text-positive-default size-4" />
                    </div>
                    <span class="text-sm font-medium"
                      >{labels.selectedFiles(currentStepFileCount)}</span
                    >
                  </div>
                  {#if currentStepRemainingSlots > 0}
                    <span class="text-muted text-sm">{labels.runtimeUploadHint}</span>
                  {:else}
                    <span class="text-muted text-sm">{labels.maxFilesReached}</span>
                  {/if}
                {:else}
                  <IconUploadCloud class="text-muted size-7" />
                  <span class="text-secondary text-sm">{m.upload_file()}</span>
                  <span class="text-muted text-sm">{labels.runtimeUploadHint}</span>
                {/if}
              </div>

              {#if currentRuntimeStep.accepted_mimetypes.length > 0}
                <details class="border-default bg-secondary/5 mt-3 rounded-lg border px-3 py-2.5">
                  <summary class="cursor-pointer text-sm font-medium">
                    {labels.allowedTypesToggle}
                  </summary>
                  <p class="text-secondary mt-2 max-w-prose text-sm leading-relaxed">
                    {friendlyMimeNames(currentRuntimeStep.accepted_mimetypes).join(", ")}
                  </p>
                  <details class="mt-2">
                    <summary class="text-muted cursor-pointer text-sm hover:underline">
                      {labels.technicalMimeToggle}
                    </summary>
                    <p
                      class="text-muted mt-1.5 max-w-prose text-xs leading-relaxed break-all"
                      title={currentRuntimeStep.accepted_mimetypes.join(", ")}
                    >
                      {currentRuntimeStep.accepted_mimetypes.join(", ")}
                    </p>
                  </details>
                </details>
              {/if}

              {#if currentRuntimeStep.max_files != null}
                <span
                  class="mt-2 inline-flex text-sm"
                  class:text-accent-stronger={currentStepFileCount > 0 &&
                    currentStepRemainingSlots > 0}
                  class:text-warning-stronger={currentStepRemainingSlots <= 0}
                  class:text-muted={currentStepFileCount === 0}
                >
                  {m.flow_run_files_count({
                    current: String(currentStepFileCount),
                    limit: String(currentRuntimeStep.max_files)
                  })}
                </span>
              {/if}

              {#if currentStepSkippedMessage}
                <p
                  class="border-warning-default/30 bg-warning-dimmer text-warning-stronger mt-3 rounded-md border px-3.5 py-2.5 text-sm"
                  role="status"
                  aria-live="polite"
                >
                  {currentStepSkippedMessage}
                </p>
              {/if}

              {#if currentStepUploadError}
                <div
                  class="border-negative-default/30 bg-negative-dimmer text-negative-stronger mt-3 rounded-md border px-3.5 py-2.5 text-sm"
                  role="alert"
                  aria-live="assertive"
                >
                  <p>
                    {currentStepUploadError}{getUploadErrorHint(
                      classifyUploadError(currentStepUploadError ?? "")
                    )}
                  </p>
                  <button
                    class="text-negative-stronger mt-1.5 text-xs font-medium underline underline-offset-2 hover:no-underline"
                    onclick={() => retryUpload(currentRuntimeStep)}
                  >
                    {labels.retryUpload}
                  </button>
                </div>
              {/if}

              {#if currentStepUploadedFiles.length > 0}
                <div class="mt-3 mb-2 flex flex-col gap-1.5">
                  {#each currentStepUploadedFiles as file (file.id)}
                    <div
                      class="group bg-hover-dimmer hover:bg-hover-default flex min-h-[44px] items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors duration-100"
                    >
                      <div class="flex min-w-0 flex-col">
                        <span class="min-w-0 truncate">{file.name ?? file.id}</span>
                        {#if file.size}
                          <span class="text-muted text-xs">{formatBytes(file.size)}</span>
                        {/if}
                      </div>
                      <button
                        class="text-muted/60 hover:text-negative-default group-hover:text-muted flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-md transition-colors duration-100"
                        onclick={() => removeFile(currentRuntimeStep.step_id, file.id)}
                        aria-label="{m.delete()} {file.name ?? file.id}"
                      >
                        <IconXMark class="size-4" />
                      </button>
                    </div>
                  {/each}
                </div>
              {/if}
            </div>
          </div>
        {:else if currentPage.kind === "review"}
          <div class="flex flex-col gap-4">
            {#if reviewSummaryItems.length > 0}
              <div class="px-1 py-1">
                <h4 class="text-sm font-semibold" data-wizard-heading tabindex="-1">
                  {labels.reviewSummaryTitle}
                </h4>
                <div class="mt-3 flex flex-wrap gap-2">
                  {#each reviewSummaryItems as item (item.id)}
                    <span
                      class="border-positive-default/20 bg-positive-dimmer/30 text-positive-stronger inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium"
                    >
                      <IconCheck class="size-3.5 shrink-0" />
                      {item.label}
                    </span>
                  {/each}
                </div>
              </div>
            {/if}

            {#if runBlockers.length > 0}
              <div
                class="border-warning-default/30 bg-warning-dimmer text-warning-stronger rounded-xl border px-4 py-4"
                role="status"
                aria-live="polite"
              >
                <p class="flex items-center gap-2 text-sm font-semibold">
                  <IconInfo class="size-4 shrink-0" />
                  {labels.runBlockersTitle}
                </p>
                <div class="mt-3 flex flex-col gap-2">
                  {#each runBlockers as blocker (blocker.id)}
                    <div class="bg-primary/70 rounded-lg px-3 py-3">
                      <div class="flex flex-wrap items-center justify-between gap-3">
                        <p class="text-sm">{blocker.title}</p>
                        <Button
                          variant="outline"
                          size="sm"
                          onclick={() => goToPageById(blocker.pageId)}
                        >
                          {blocker.actionLabel}
                        </Button>
                      </div>
                    </div>
                  {/each}
                </div>
              </div>
            {:else}
              <div
                class="bg-positive-default/10 text-positive-stronger flex items-center gap-3 rounded-xl px-4 py-3.5 text-sm"
              >
                <div
                  class="bg-positive-default/15 flex size-7 shrink-0 items-center justify-center rounded-full"
                >
                  <IconCheck class="size-4 shrink-0" />
                </div>
                <span class="font-medium">{labels.reviewReady}</span>
              </div>
            {/if}

            {#if completedFormFieldSummaries.length > 0}
              <div class="px-1 py-1">
                <h4 class="text-sm font-semibold">{labels.reviewFieldsTitle}</h4>
                <div class="mt-3 grid gap-3 md:grid-cols-2">
                  {#each completedFormFieldSummaries as item (item.field.name)}
                    <div class="bg-secondary/20 rounded-lg px-3 py-3">
                      <p class="text-muted text-xs font-medium tracking-[0.12em] uppercase">
                        {item.field.name}
                      </p>
                      <p class="mt-1 text-sm leading-relaxed">{item.value}</p>
                    </div>
                  {/each}
                </div>
              </div>
            {/if}

            {#if showFreeformTextInput && inputText.trim().length > 0}
              <div class="px-1 py-1">
                <h4 class="text-sm font-semibold">{labels.reviewTextTitle}</h4>
                <pre
                  class="bg-secondary/20 mt-3 overflow-x-auto rounded-lg px-3 py-3 text-sm whitespace-pre-wrap">
{inputText.trim()}</pre>
              </div>
            {/if}

            {#if reviewFileGroups.length > 0}
              <div class="border-default rounded-xl border px-4 py-4">
                <h4 class="text-sm font-semibold">{labels.reviewFilesTitle}</h4>
                <div class="mt-3 flex flex-col gap-3">
                  {#each reviewFileGroups as group (group.step.step_id)}
                    <div class="flex flex-col gap-1.5">
                      <p class="text-muted text-xs font-medium tracking-wide uppercase">
                        {labels.runtimeReviewStep(group.step.step_order, getStepLabel(group.step))}
                      </p>
                      {#each group.files as file (file.id)}
                        <div
                          class="bg-secondary/10 flex items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-sm"
                        >
                          <span class="min-w-0 truncate">{file.name ?? file.id}</span>
                          {#if file.size}
                            <span class="text-muted shrink-0 text-xs">{formatBytes(file.size)}</span
                            >
                          {/if}
                        </div>
                      {/each}
                    </div>
                  {/each}
                </div>
              </div>
            {/if}
          </div>
        {/if}
      </div>
    {/if}

    <!-- Footer -->
    <div
      class="border-default shrink-0 border-t px-4 sm:px-6 {showCloseConfirmation
        ? 'bg-warning-dimmer/30 py-4'
        : 'py-3'}"
    >
      {#if showCloseConfirmation}
        <div
          class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
          role="alertdialog"
          aria-label={labels.closeConfirmTitle}
          aria-describedby="close-confirm-desc"
        >
          <div class="min-w-0">
            <p class="text-sm font-medium">{labels.closeConfirmTitle}</p>
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
                class="order-1 w-full min-w-[7rem] sm:order-3 sm:w-auto"
              >
                {#if isSubmitting}
                  <IconLoadingSpinner class="size-4 animate-spin" />
                {/if}
                {m.flow_run_trigger()}
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
    </div>
  </Dialog.Content>
</Dialog.Root>
