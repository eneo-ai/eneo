<svelte:options runes={false} />

<script lang="ts">
  import type {
    Flow,
    FlowRunContract,
    FlowRunContractStepInput,
    FlowRunContractTemplateReadiness,
    Intric,
    UploadedFile
  } from "@intric/intric-js";
  import { Button, Dialog } from "@intric/ui";
  import { createEventDispatcher } from "svelte";
  import { writable } from "svelte/store";
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

  export let open: boolean;
  export let flow: Flow;
  export let intric: Intric;
  export let lastInputPayload: Record<string, unknown> | null;

  const dispatch = createEventDispatcher<{ runCreated: { runId: string } }>();
  const openController = writable(false);

  $: openController.set(open);
  $: open = $openController;

  let inputText = "";
  let isSubmitting = false;
  let runContract: FlowRunContract | null = null;
  let runContractError: string | null = null;
  let runContractLoadedForFlowId: string | null = null;

  let formValues: Record<string, unknown> = {};
  let runtimeFilesByStepId: Record<string, UploadedFile[]> = {};
  let uploadErrorsByStepId: Record<string, string | null> = {};
  let skippedMessagesByStepId: Record<string, string | null> = {};
  let uploadingStepIds: string[] = [];
  let draggingStepId: string | null = null;
  let currentPageIndex = 0;

  const FLOW_UPLOAD_TIMEOUT_MS = 120_000;
  const AUDIO_ACCEPT_FILTER = "audio/*,video/webm,video/mp4";
  const locale = (getLocale() === "en" ? "en" : "sv") as FlowLocale;
  const labels = getRunDialogLabels(locale);

  $: formFields = normalizeFlowFormFields(
    ((runContract?.form_fields as { fields?: FlowFormField[] } | undefined)?.fields ??
      runContract?.form_fields ??
      []) as FlowFormField[]
  );
  $: hasFormFields = formFields.length > 0;
  $: hasRequiredFormFields = formFields.some((field) => field.required);
  $: missingRequiredFields = formFields.filter((field) => {
    if (!field.required) return false;
    const value = formValues[getFlowFormFieldRuntimeKey(field.name)];
    if (field.type === "multiselect") {
      return !Array.isArray(value) || value.length === 0;
    }
    if (value === null || value === undefined) return true;
    return String(value).trim().length === 0;
  });
  $: missingRequiredFieldNames = missingRequiredFields
    .map((field) => field.name.trim())
    .filter((name) => name.length > 0);

  $: stepCount = flow.steps?.length ?? 0;
  $: stepsRequiringInput = runContract?.steps_requiring_input ?? [];
  $: templateReadinessItems = normalizeTemplateReadiness(runContract?.template_readiness);
  $: hasRuntimeFileInputs = stepsRequiringInput.length > 0;
  $: showFreeformTextInput = !hasFormFields && !hasRuntimeFileInputs;
  $: hasTemplateOverview = templateReadinessItems.length > 0;
  $: wizardPages = buildFlowRunWizardPages({
    locale,
    hasTemplateOverview,
    hasFormFields,
    hasFreeformTextInput: showFreeformTextInput,
    stepsRequiringInput
  });
  $: currentPage = wizardPages[currentPageIndex] ?? wizardPages[0] ?? null;
  $: runBlockers = buildFlowRunBlockers({
    locale,
    missingRequiredFieldNames,
    stepsRequiringInput,
    runtimeFilesByStepId,
    templateReadinessItems,
    uploadingStepIds
  });
  $: currentPageProgressBlockers = currentPage
    ? runBlockers.filter((blocker) => blocker.pageId === currentPage.id && blocker.blocksProgress)
    : [];
  $: reviewBlockers = runBlockers;
  $: currentRuntimeStep =
    currentPage?.kind === "runtime-step"
      ? (stepsRequiringInput.find((step) => step.step_id === currentPage.stepId) ?? null)
      : null;
  $: currentTemplateBlockers =
    currentPage?.kind === "overview"
      ? reviewBlockers.filter((blocker) => blocker.pageId === "overview")
      : [];
  $: reviewFileGroups = stepsRequiringInput
    .map((step) => ({
      step,
      files: getUploadedFiles(step.step_id)
    }))
    .filter((group) => group.files.length > 0);
  $: uploadedFileCount = reviewFileGroups.reduce((count, group) => count + group.files.length, 0);
  $: templateReadyCount = templateReadinessItems.filter((item) => item.status === "ready").length;
  $: completedFormFieldSummaries = formFields
    .map((field) => ({
      field,
      value: getReviewFieldValue(field)
    }))
    .filter((item) => item.value.length > 0);
  $: reviewSummaryItems = buildFlowRunReviewSummary({
    locale,
    templateCount: templateReadyCount,
    filledFieldCount: completedFormFieldSummaries.length,
    runtimeStepCountWithFiles: reviewFileGroups.length,
    uploadedFileCount
  });
  $: progressLabel =
    wizardPages.length > 0 ? labels.progress(currentPageIndex + 1, wizardPages.length) : "";
  $: progressPercent =
    wizardPages.length > 0 ? ((currentPageIndex + 1) / wizardPages.length) * 100 : 0;
  $: canGoNext =
    currentPageIndex < wizardPages.length - 1 &&
    currentPageProgressBlockers.length === 0 &&
    !isSubmitting;
  $: canSubmitRun =
    runContract !== null && !runContractError && !isSubmitting && reviewBlockers.length === 0;

  $: if (wizardPages.length > 0 && currentPageIndex > wizardPages.length - 1) {
    currentPageIndex = wizardPages.length - 1;
  }

  async function loadRunContract(flowId: string) {
    try {
      runContractError = null;
      runContract = await intric.flows.runContract.get({ id: flowId });
    } catch (error) {
      runContract = null;
      runContractError = error instanceof IntricError ? error.getReadableMessage() : String(error);
    }
  }

  $: if (open && flow?.id && runContractLoadedForFlowId !== flow.id) {
    runContractLoadedForFlowId = flow.id;
    currentPageIndex = 0;
    void loadRunContract(flow.id);
  }

  $: if (!open) {
    runContractLoadedForFlowId = null;
    runContract = null;
    runContractError = null;
    runtimeFilesByStepId = {};
    uploadErrorsByStepId = {};
    skippedMessagesByStepId = {};
    uploadingStepIds = [];
    draggingStepId = null;
    currentPageIndex = 0;
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
    draggingStepId = stepId;
  }

  function handleDragLeave(stepId: string) {
    if (draggingStepId === stepId) {
      draggingStepId = null;
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

  let pageContentEl: HTMLElement | null = null;

  function focusPageHeading() {
    requestAnimationFrame(() => {
      const heading = pageContentEl?.querySelector<HTMLElement>("[data-wizard-heading]");
      if (heading) {
        heading.focus();
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
    if (!flow.id || !runContract || reviewBlockers.length > 0) return;

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

      dispatch("runCreated", { runId: createdRun.id });
      toast.success(m.flow_run_started_toast());
      $openController = false;
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
        reviewBlockersTitle: "Det här behöver lösas innan du kan köra flödet",
        reviewReady: "Allt som krävs är klart. Du kan köra flödet nu.",
        reviewSummaryTitle: "Det här följer med i körningen",
        reviewFieldsTitle: "Fält som skickas med",
        reviewTextTitle: "Text som skickas in",
        reviewFilesTitle: "Uppladdade filer",
        runtimeReviewStep: (stepOrder: number, stepLabel: string) =>
          `Steg ${stepOrder}: ${stepLabel}`
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
      reviewBlockersTitle: "This still needs to be resolved before you can run the flow",
      reviewReady: "Everything required is ready. You can run the flow now.",
      reviewSummaryTitle: "Included in this run",
      reviewFieldsTitle: "Fields that will be sent",
      reviewTextTitle: "Text that will be sent",
      reviewFilesTitle: "Uploaded files",
      runtimeReviewStep: (stepOrder: number, stepLabel: string) => `Step ${stepOrder}: ${stepLabel}`
    };
  }
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="dynamic">
    <Dialog.Section class="relative mt-2 -mb-0.5 overflow-hidden">
      <div
        class="mx-auto flex max-h-[82vh] min-h-[24rem] w-full max-w-5xl flex-col overflow-hidden px-4 pt-5 pb-4 sm:min-h-[30rem] sm:px-6 sm:pt-7 lg:px-8"
      >
        <Dialog.Title class="text-xl font-bold">{m.flow_run_trigger()}</Dialog.Title>
        <p class="text-secondary mt-1 text-sm">
          {flow.name}
          {#if stepCount > 0}
            <span class="text-muted ml-1"
              >({m.flow_run_step_count({ count: String(stepCount) })})</span
            >
          {/if}
        </p>

        {#if runContract === null && !runContractError}
          <div class="mt-6 flex flex-col gap-4">
            <div class="border-default bg-secondary/10 h-[7rem] animate-pulse rounded-[1.75rem] border"></div>
            <div class="bg-secondary/10 h-[10rem] animate-pulse rounded-xl"></div>
          </div>
        {:else if runContractError}
          <div
            class="border-negative-default/20 bg-negative-dimmer text-negative-stronger mt-6 rounded-lg border px-4 py-3 text-sm"
            role="alert"
          >
            <p>{runContractError}</p>
            <button
              class="text-negative-stronger mt-2 text-xs font-medium underline underline-offset-2 hover:no-underline"
              on:click={() => { runContractLoadedForFlowId = null; }}
            >
              {labels.retryUpload}
            </button>
          </div>
        {:else if currentPage}
          <div
            class="border-default bg-secondary/10 mt-5 rounded-[1.75rem] border px-4 py-4 sm:px-5"
          >
            <div class="grid gap-4 md:grid-cols-[minmax(0,1fr)_18rem] md:items-start">
              <div class="min-w-0">
                <p class="sr-only">{progressLabel}</p>
                <p class="mt-0 text-lg font-semibold" data-wizard-heading tabindex="-1">{currentPage.title}</p>
                <p class="text-secondary mt-1 text-sm leading-relaxed">
                  {currentPage.description}
                </p>
              </div>
              <div
                class="flex items-center gap-1.5 md:pt-3"
                role="progressbar"
                aria-valuenow={progressPercent}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={progressLabel}
              >
                {#each wizardPages as page, pageIndex (page.id)}
                  {@const isCompleted = pageIndex < currentPageIndex}
                  {@const isCurrent = pageIndex === currentPageIndex}
                  {@const isClickable = isCompleted}
                  <button
                    title={page.title}
                    class="h-1.5 flex-1 rounded-full transition-all duration-200 focus-visible:ring-2 focus-visible:ring-accent-default focus-visible:ring-offset-2 {isCompleted ? 'bg-accent-default' : isCurrent ? 'bg-accent-default/60' : 'bg-hover-dimmer'}"
                    aria-label={page.title}
                    aria-current={isCurrent ? "step" : undefined}
                    disabled={!isClickable}
                    class:cursor-pointer={isClickable}
                    class:cursor-default={!isClickable}
                    on:click={() => { if (isClickable) goToPageById(page.id); }}
                  ></button>
                {/each}
              </div>
            </div>
          </div>

          <div class="mt-5 min-h-0 flex-1 overflow-y-auto overscroll-contain pr-0.5 sm:pr-1" bind:this={pageContentEl}>
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
                      class="border-default text-secondary rounded-full border px-2.5 py-1 text-[11px] font-medium"
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
                            class={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${getTemplateStatusClasses(item.status)}`}
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
                    <p class="font-medium">{labels.reviewBlockersTitle}</p>
                    <ul class="mt-2 space-y-1.5">
                      {#each currentTemplateBlockers as blocker (blocker.id)}
                        <li>{blocker.title}</li>
                      {/each}
                    </ul>
                  </div>
                {/if}
              </div>
            {:else if currentPage.kind === "form"}
              <div class="flex flex-col gap-4">
                <div class="border-default bg-primary rounded-xl border px-4 py-3.5">
                  <p class="text-sm font-semibold">{labels.formIntroTitle}</p>
                  <div class="mt-1.5 space-y-1">
                    <p class="text-secondary text-sm leading-relaxed">
                      {labels.formIntroDescription}
                    </p>
                    {#if hasRequiredFormFields}
                      <p class="text-secondary text-xs">{m.flow_run_required_hint()}</p>
                    {/if}
                  </div>
                </div>

                {#if missingRequiredFields.length > 0}
                  <div
                    id="form-validation-banner"
                    class="border-warning-default/30 bg-warning-dimmer text-warning-stronger rounded-lg border px-3 py-2 text-xs"
                    role="alert"
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
                        class="border-default bg-primary ring-default min-h-[120px] w-full rounded-lg border px-3 py-2 shadow focus-visible:ring-2 focus-visible:ring-accent-default"
                        multiple
                        required={field.required}
                        aria-required={field.required}
                        aria-describedby={missingRequiredFields.includes(field) ? "form-validation-banner" : undefined}
                        on:change={(event) => {
                          const selected = Array.from(event.currentTarget.selectedOptions).map(
                            (option) => option.value
                          );
                          setFieldValue(field, selected);
                        }}
                      >
                        {#each field.options ?? [] as option (option)}
                          <option
                            value={option}
                            selected={getFieldMultiValue(field).includes(option)}
                          >
                            {option}
                          </option>
                        {/each}
                      </select>
                    {:else if field.type === "select"}
                      <select
                        id={`flow-input-${fieldIndex}`}
                        class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-visible:ring-2 focus-visible:ring-accent-default"
                        value={getFieldValue(field)}
                        required={field.required}
                        aria-required={field.required}
                        aria-describedby={missingRequiredFields.includes(field) ? "form-validation-banner" : undefined}
                        on:change={(event) => setFieldValue(field, event.currentTarget.value)}
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
                        class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-visible:ring-2 focus-visible:ring-accent-default"
                        value={getFieldValue(field)}
                        autocomplete="off"
                        required={field.required}
                        aria-required={field.required}
                        aria-describedby={missingRequiredFields.includes(field) ? "form-validation-banner" : undefined}
                        on:input={(event) => setFieldValue(field, event.currentTarget.value)}
                      />
                    {/if}
                  </div>
                {/each}
              </div>
            {:else if currentPage.kind === "freeform"}
              <div class="flex flex-col gap-2">
                <span class="text-sm font-medium">{m.flow_run_input()}</span>
                <span class="text-secondary text-sm leading-relaxed">{m.flow_run_input_desc()}</span
                >
                <textarea
                  class="border-default bg-primary ring-default min-h-[220px] w-full rounded-xl border px-3 py-2 font-mono text-sm shadow focus-within:ring-2"
                  bind:value={inputText}
                  placeholder={m.flow_run_input_placeholder()}
                ></textarea>
              </div>
            {:else if currentPage.kind === "runtime-step" && currentRuntimeStep}
              <div class="flex flex-col gap-4">
                <div class="border-default bg-primary rounded-xl border px-4 py-4">
                  <div class="flex flex-wrap items-start justify-between gap-3">
                    <div class="min-w-0">
                      <div class="flex flex-wrap items-center gap-2">
                        <p class="text-muted text-xs font-medium tracking-[0.14em] uppercase">
                          {labels.runtimeStepUploadTitle}
                        </p>
                        {#if currentRuntimeStep.required}
                          <span
                            class="border-default bg-secondary/15 text-secondary rounded-full border px-2 py-0.5 text-[11px] font-medium"
                          >
                            {labels.requiredBadge}
                          </span>
                        {/if}
                        {#if getStepFileCount(currentRuntimeStep) > 0}
                          <span
                            class="border-default text-secondary rounded-full border px-2 py-0.5 text-[11px] font-medium"
                          >
                            {labels.selectedFiles(getStepFileCount(currentRuntimeStep))}
                          </span>
                        {/if}
                      </div>
                      <p class="mt-2 text-base font-semibold">{getStepLabel(currentRuntimeStep)}</p>
                      {#if currentRuntimeStep.description}
                        <p class="text-secondary mt-1 text-sm leading-relaxed">
                          {currentRuntimeStep.description}
                        </p>
                      {/if}
                      <p class="text-secondary mt-2 text-xs leading-relaxed">
                        {labels.runtimeScopeHint(currentRuntimeStep.step_order)}
                      </p>
                    </div>
                    <div class="text-secondary flex flex-wrap gap-2 text-[11px]">
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
                          Max {formatBytes(currentRuntimeStep.max_file_size_bytes)}/fil
                        </span>
                      {/if}
                    </div>
                  </div>

                  {#if getCurrentStepBlockerSummary(currentRuntimeStep.step_id).length > 0}
                    <div
                      class="border-warning-default/30 bg-warning-dimmer text-warning-stronger mt-4 rounded-lg border px-3 py-2 text-sm"
                      role="alert"
                      aria-live="polite"
                    >
                      {getCurrentStepBlockerSummary(currentRuntimeStep.step_id)[0]?.title}
                    </div>
                  {/if}

                  {#if isStepUploading(currentRuntimeStep.step_id)}
                    <div
                      class="border-accent-default/20 bg-accent-dimmer/40 text-accent-stronger mt-4 rounded-lg border px-3 py-2 text-sm"
                    >
                      {labels.runtimeUploadingHint}
                    </div>
                  {/if}

                  <div
                    class="border-default bg-secondary/10 mt-4 flex min-h-[132px] cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-6 text-center transition-all duration-150 sm:min-h-[100px] {draggingStepId === currentRuntimeStep.step_id ? 'border-accent-default bg-accent-dimmer scale-[1.01]' : ''} {getRemainingFileSlots(currentRuntimeStep) > 0 && draggingStepId !== currentRuntimeStep.step_id ? 'hover:border-accent-default hover:bg-secondary/20' : ''} {getRemainingFileSlots(currentRuntimeStep) <= 0 ? 'pointer-events-none opacity-50' : ''}"
                    on:dragover={(event) => handleDragOver(currentRuntimeStep.step_id, event)}
                    on:dragleave={() => handleDragLeave(currentRuntimeStep.step_id)}
                    on:drop={(event) => handleDrop(currentRuntimeStep, event)}
                    on:click={() => openFilePicker(currentRuntimeStep)}
                    role="button"
                    tabindex="0"
                    aria-label="{m.upload_file()} — {getStepLabel(currentRuntimeStep)}"
                    on:keydown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openFilePicker(currentRuntimeStep);
                      }
                    }}
                  >
                    {#if isStepUploading(currentRuntimeStep.step_id)}
                      <IconLoadingSpinner class="text-secondary size-6 animate-spin" />
                      <span class="text-secondary text-sm">{m.loading()}</span>
                    {:else}
                      <IconUploadCloud class="text-muted size-7" />
                      <span class="text-secondary text-sm">{m.upload_file()}</span>
                      <span class="text-muted text-xs">{labels.runtimeUploadHint}</span>
                    {/if}
                  </div>

                  {#if getRemainingFileSlots(currentRuntimeStep) <= 0}
                    <p class="text-secondary mt-2 text-xs">{labels.maxFilesReached}</p>
                  {/if}

                  {#if currentRuntimeStep.accepted_mimetypes.length > 0}
                    <details
                      class="border-default bg-secondary/10 mt-3 rounded-lg border px-3 py-2"
                    >
                      <summary class="cursor-pointer text-sm font-medium">
                        {labels.allowedTypesToggle}
                      </summary>
                      <p class="text-secondary mt-2 text-xs leading-relaxed">
                        {friendlyMimeNames(currentRuntimeStep.accepted_mimetypes).join(", ")}
                      </p>
                      <p class="text-muted mt-1 text-[10px] leading-relaxed" title={currentRuntimeStep.accepted_mimetypes.join(", ")}>
                        {currentRuntimeStep.accepted_mimetypes.join(", ")}
                      </p>
                    </details>
                  {/if}

                  {#if currentRuntimeStep.max_files != null}
                    <span
                      class="mt-3 inline-flex text-xs"
                      class:text-warning-stronger={getRemainingFileSlots(currentRuntimeStep) <= 0}
                      class:text-secondary={getRemainingFileSlots(currentRuntimeStep) > 0}
                    >
                      {m.flow_run_files_count({
                        current: String(getStepFileCount(currentRuntimeStep)),
                        limit: String(currentRuntimeStep.max_files)
                      })}
                    </span>
                  {/if}

                  {#if getSkippedMessage(currentRuntimeStep.step_id)}
                    <p
                      class="border-warning-default/30 bg-warning-dimmer text-warning-stronger mt-2 rounded-md border px-3 py-2 text-xs"
                      role="status"
                      aria-live="polite"
                    >
                      {getSkippedMessage(currentRuntimeStep.step_id)}
                    </p>
                  {/if}

                  {#if getUploadError(currentRuntimeStep.step_id)}
                    <div
                      class="border-negative-default/30 bg-negative-dimmer text-negative-stronger mt-2 rounded-md border px-3 py-2 text-xs"
                      role="alert"
                      aria-live="assertive"
                    >
                      <p>
                        {getUploadError(currentRuntimeStep.step_id)}{getUploadErrorHint(classifyUploadError(getUploadError(currentRuntimeStep.step_id) ?? ""))}
                      </p>
                      <button
                        class="text-negative-stronger mt-1.5 text-xs font-medium underline underline-offset-2 hover:no-underline"
                        on:click={() => retryUpload(currentRuntimeStep)}
                      >
                        {labels.retryUpload}
                      </button>
                    </div>
                  {/if}

                  {#if getUploadedFiles(currentRuntimeStep.step_id).length > 0}
                    <div class="mt-4 flex flex-col gap-2">
                      {#each getUploadedFiles(currentRuntimeStep.step_id) as file (file.id)}
                        <div
                          class="bg-hover-dimmer flex min-h-[44px] items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm"
                        >
                          <div class="flex min-w-0 flex-col">
                            <span class="min-w-0 truncate">{file.name ?? file.id}</span>
                            {#if file.size}
                              <span class="text-muted text-[11px]">{formatBytes(file.size)}</span>
                            {/if}
                          </div>
                          <button
                            class="text-muted hover:text-negative-default flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-md transition-colors"
                            on:click={() => removeFile(currentRuntimeStep.step_id, file.id)}
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
                  <div class="border-default bg-primary rounded-xl border px-4 py-4">
                    <p class="text-sm font-semibold" data-wizard-heading tabindex="-1">{labels.reviewSummaryTitle}</p>
                    <div class="mt-3 flex flex-wrap gap-2">
                      {#each reviewSummaryItems as item (item.id)}
                        <span
                          class="border-default bg-secondary/15 text-secondary inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium"
                        >
                          <IconCheck class="text-positive-default size-3.5 shrink-0" />
                          {item.label}
                        </span>
                      {/each}
                    </div>
                  </div>
                {/if}

                {#if reviewBlockers.length > 0}
                  <div
                    class="border-warning-default/30 bg-warning-dimmer text-warning-stronger rounded-xl border px-4 py-4"
                    role="alert"
                    aria-live="polite"
                  >
                    <p class="flex items-center gap-2 text-sm font-semibold">
                      <IconInfo class="size-4 shrink-0" />
                      {labels.reviewBlockersTitle}
                    </p>
                    <div class="mt-3 flex flex-col gap-2">
                      {#each reviewBlockers as blocker (blocker.id)}
                        <div class="bg-primary/70 rounded-lg px-3 py-3">
                          <div class="flex flex-wrap items-center justify-between gap-3">
                            <p class="text-sm">{blocker.title}</p>
                            <Button
                              variant="outlined"
                              size="small"
                              on:click={() => goToPageById(blocker.pageId)}
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
                    class="border-positive-default/30 bg-positive-default/10 text-positive-stronger flex items-center gap-2.5 rounded-xl border px-4 py-3 text-sm"
                  >
                    <IconCheck class="size-4.5 shrink-0" />
                    {labels.reviewReady}
                  </div>
                {/if}

                {#if completedFormFieldSummaries.length > 0}
                  <div class="border-default bg-primary rounded-xl border px-4 py-4">
                    <p class="text-sm font-semibold">{labels.reviewFieldsTitle}</p>
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
                  <div class="border-default bg-primary rounded-xl border px-4 py-4">
                    <p class="text-sm font-semibold">{labels.reviewTextTitle}</p>
                    <pre
                      class="bg-secondary/20 mt-3 overflow-x-auto rounded-lg px-3 py-3 text-sm whitespace-pre-wrap">
{inputText.trim()}</pre>
                  </div>
                {/if}

                {#if reviewFileGroups.length > 0}
                  <div class="border-default bg-primary rounded-xl border px-4 py-4">
                    <p class="text-sm font-semibold">{labels.reviewFilesTitle}</p>
                    <div class="mt-3 flex flex-col gap-3">
                      {#each reviewFileGroups as group (group.step.step_id)}
                        <div class="bg-secondary/20 rounded-lg px-3 py-3">
                          <p class="text-sm font-medium">
                            {labels.runtimeReviewStep(
                              group.step.step_order,
                              getStepLabel(group.step)
                            )}
                          </p>
                          <div class="mt-2 flex flex-col gap-2">
                            {#each group.files as file (file.id)}
                              <div class="bg-primary flex items-center justify-between gap-3 rounded-md px-3 py-2 text-sm">
                                <span class="min-w-0 truncate">{file.name ?? file.id}</span>
                                {#if file.size}
                                  <span class="text-muted shrink-0 text-[11px]">{formatBytes(file.size)}</span>
                                {/if}
                              </div>
                            {/each}
                          </div>
                        </div>
                      {/each}
                    </div>
                  </div>
                {/if}
              </div>
            {/if}
          </div>
        {/if}
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <div
        class="flex w-full flex-col gap-3 px-4 pt-3 pb-1 sm:px-6"
      >
        <div class="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
          <!-- Left: contextual actions -->
          <div class="order-2 flex gap-2 sm:order-1">
            {#if lastInputPayload && (currentPage?.kind === "form" || currentPage?.kind === "freeform")}
              <Button variant="outlined" on:click={reuseLastInput} class="w-full sm:w-auto">
                {m.flow_run_reuse_last_input()}
              </Button>
            {/if}
          </div>

          <div class="hidden flex-grow sm:order-2 sm:block"></div>

          <!-- Right: Back | Cancel | Primary (primary first on mobile for thumb reach) -->
          <div class="order-1 flex w-full flex-col gap-2 sm:order-3 sm:w-auto sm:flex-row sm:items-center">
            {#if currentPage && currentPage.kind === "review"}
              <Button
                on:click={triggerRun}
                variant="primary"
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
                on:click={goToNextPage}
                variant="primary"
                disabled={!canGoNext}
                title={!canGoNext ? getDisabledNextReason() : undefined}
                class="order-1 w-full min-w-[7rem] sm:order-3 sm:w-auto"
              >
                {labels.next}
              </Button>
            {/if}

            <Button is={close} class="order-3 w-full sm:order-2 sm:w-auto">{m.cancel()}</Button>

            {#if currentPageIndex > 0}
              <Button variant="outlined" on:click={goToPreviousPage} class="order-2 w-full sm:order-1 sm:w-auto">
                {labels.previous}
              </Button>
            {/if}
          </div>
        </div>
      </div>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
