<script lang="ts">
  import type { Flow, FlowInputPolicy, Intric, UploadedFile } from "@intric/intric-js";
  import { Button, Dialog } from "@intric/ui";
  import { createEventDispatcher } from "svelte";
  import { writable } from "svelte/store";
  import { IntricError } from "@intric/intric-js";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import {
    getFlowFormFieldRuntimeKey,
    normalizeFlowFormFields,
    type FlowFormField,
    type NormalizedFlowFormField,
  } from "$lib/features/flows/flowFormSchema";
  import { getRuntimeFileOriginKind } from "$lib/features/flows/flowStepPresentation";

  export let open: boolean;
  export let flow: Flow;
  export let intric: Intric;
  export let lastInputPayload: Record<string, unknown> | null;

  const dispatch = createEventDispatcher<{ runCreated: void }>();
  const openController = writable(false);

  $: openController.set(open);
  $: open = $openController;

  let inputText = "";
  let isSubmitting = false;

  $: formFields = normalizeFlowFormFields(
    (((flow.metadata_json?.form_schema as { fields: FlowFormField[] })?.fields ?? []) as FlowFormField[]),
  );
  $: hasFormFields = formFields.length > 0;
  $: hasRequiredFormFields = formFields.some((field) => field.required);
  $: missingRequiredFields = formFields.filter((field) => field.required && isFieldMissing(field));
  $: missingRequiredFieldNames = missingRequiredFields
    .map((field) => field.name.trim())
    .filter((name) => name.length > 0);

  $: stepCount = flow.steps?.length ?? 0;

  let flowInputPolicy: FlowInputPolicy | null = null;
  let policyLoadError: string | null = null;
  let policyLoadedForFlowId: string | null = null;

  async function loadFlowInputPolicy(flowId: string) {
    try {
      policyLoadError = null;
      flowInputPolicy = await intric.flows.inputPolicy({ id: flowId });
    } catch (e) {
      flowInputPolicy = null;
      policyLoadError = e instanceof IntricError ? e.getReadableMessage() : String(e);
    }
  }

  $: if (open && flow?.id && policyLoadedForFlowId !== flow.id) {
    policyLoadedForFlowId = flow.id;
    void loadFlowInputPolicy(flow.id);
  }
  $: if (!open) {
    policyLoadedForFlowId = null;
  }

  // Legacy first-step fallback when policy endpoint is unavailable
  $: firstStep = flow.steps?.length > 0 ? flow.steps[0] : null;
  $: resolvedInputType = flowInputPolicy?.input_type ?? firstStep?.input_type ?? null;
  $: hasFlowInputStep = Boolean(flowInputPolicy) || firstStep?.input_source === "flow_input";
  $: isAudioUpload = resolvedInputType === "audio";
  $: needsFileUpload = flowInputPolicy
    ? flowInputPolicy.accepts_file_upload
    : resolvedInputType === "document" || resolvedInputType === "file" || isAudioUpload;
  $: runtimeFileOriginKind = getRuntimeFileOriginKind({
    needsFileUpload,
    hasFlowInputStep
  });
  const AUDIO_ACCEPT_FILTER = "audio/*,video/webm,video/mp4";
  $: fileInputAccept = flowInputPolicy?.accepted_mimetypes?.length
    ? flowInputPolicy.accepted_mimetypes.join(",")
    : isAudioUpload
      ? AUDIO_ACCEPT_FILTER
      : undefined;
  $: effectiveMaxFileSizeBytes = flowInputPolicy?.max_file_size_bytes ?? null;

  let formValues: Record<string, unknown> = {};

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

  function isFieldMissing(field: NormalizedFlowFormField): boolean {
    if (field.type === "multiselect") {
      return getFieldMultiValue(field).length === 0;
    }
    return getFieldValue(field).trim().length === 0;
  }

  // File upload state
  let uploadedFiles: UploadedFile[] = [];
  let isUploading = false;
  let uploadError: string | null = null;
  let isDragging = false;
  const FLOW_UPLOAD_TIMEOUT_MS = 120_000;

  function reuseLastInput() {
    if (lastInputPayload) {
      if (hasFormFields) {
        for (const field of formFields) {
          const key = getFlowFormFieldRuntimeKey(field.name);
          const previous = lastInputPayload[key];
          if (field.type === "multiselect") {
            formValues[key] = Array.isArray(previous)
              ? previous.map((item) => String(item))
              : typeof previous === "string"
                ? previous
                    .split(",")
                    .map((item) => item.trim())
                    .filter((item) => item.length > 0)
                : [];
          } else if (previous !== undefined) {
            formValues[key] = previous;
          } else {
            formValues[key] = "";
          }
        }
        formValues = formValues;
      } else {
        inputText = String(lastInputPayload.text ?? JSON.stringify(lastInputPayload));
      }
    }
  }

  async function handleFileSelect(event: Event) {
    const input = event.target as HTMLInputElement;
    if (input.files) await uploadFiles(Array.from(input.files));
    input.value = "";
  }

  function openFilePicker() {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    if (fileInputAccept) {
      input.accept = fileInputAccept;
    }
    input.onchange = (event) => {
      void handleFileSelect(event);
    };
    input.click();
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault();
    isDragging = false;
    if (event.dataTransfer?.files) {
      void uploadFiles(Array.from(event.dataTransfer.files));
    }
  }

  function handleDragOver(event: DragEvent) {
    event.preventDefault();
    isDragging = true;
  }

  function handleDragLeave() {
    isDragging = false;
  }

  async function uploadFileWithTimeout(file: File): Promise<UploadedFile> {
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
      const uploadPromise = intric.flows.files.upload({
        id: flow.id,
        file,
        signal: controller.signal
      });
      return await Promise.race([uploadPromise, timeoutPromise]);
    } finally {
      if (timeoutId) clearTimeout(timeoutId);
    }
  }

  async function uploadFiles(files: File[]) {
    isUploading = true;
    uploadError = null;
    if (!flow.id) {
      uploadError = m.something_went_wrong();
      isUploading = false;
      return;
    }
    for (const file of files) {
      try {
        if (effectiveMaxFileSizeBytes !== null && file.size > effectiveMaxFileSizeBytes) {
          uploadError = `${file.name}: ${m.flow_run_upload_max_size({ size: formatBytes(effectiveMaxFileSizeBytes) })}`;
          continue;
        }
        const uploaded = await uploadFileWithTimeout(file);
        uploadedFiles = [...uploadedFiles, uploaded];
      } catch (e) {
        if (e instanceof IntricError) {
          const readable = e.getReadableMessage();
          const status = e.status ? `status=${e.status}` : "status=unknown";
          const code = e.code ? ` code=${e.code}` : "";
          uploadError = `${readable} (${status}${code})`;
          console.error("Flow file upload failed", {
            status: e.status,
            code: e.code,
            stage: e.stage,
            request: e.request,
            response: e.response
          });
        } else {
          uploadError = String(e);
          console.error("Flow file upload failed (non-IntricError)", e);
        }
      }
    }
    isUploading = false;
  }

  function removeFile(fileId: string) {
    uploadedFiles = uploadedFiles.filter((f) => f.id !== fileId);
  }

  async function triggerRun() {
    if (!flow.id) return;
    if (missingRequiredFields.length > 0) {
      toast.error(m.flow_run_missing_required());
      return;
    }
    if (needsFileUpload && uploadedFiles.length === 0) {
      toast.error(
        isAudioUpload ? m.flow_run_audio_placeholder() : m.flow_run_document_placeholder()
      );
      return;
    }
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
      } else {
        payload = { text: inputText };
      }
      const fileIds = uploadedFiles.length > 0 ? uploadedFiles.map((f) => f.id) : undefined;
      await intric.flows.runs.create({
        flow: { id: flow.id },
        input_payload_json: payload,
        file_ids: fileIds
      });
      dispatch("runCreated");
      $openController = false;
      inputText = "";
      formValues = {};
      uploadedFiles = [];
      uploadError = null;
    } catch (e) {
      const message = e instanceof IntricError ? e.getReadableMessage() : String(e);
      toast.error(message);
    }
    isSubmitting = false;
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

<Dialog.Root {openController}>
  <Dialog.Content width="dynamic">
    <Dialog.Section class="relative mt-2 -mb-0.5">
      <div
        class="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 pt-6 pb-8 sm:px-6 sm:pt-8 lg:px-10"
      >
        <h3 class="text-xl font-bold">{m.flow_run_trigger()}</h3>
        <p class="text-secondary text-sm">
          {flow.name}
          {#if stepCount > 0}
            <span class="text-muted ml-1"
              >({m.flow_run_step_count({ count: String(stepCount) })})</span
            >
          {/if}
        </p>

        {#if hasFormFields}
          <div class="rounded-xl border border-default bg-secondary/20 px-4 py-3.5">
            <p class="text-sm font-semibold">{m.flow_run_fields_intro_title()}</p>
            <div class="mt-1.5 space-y-1">
              <p class="text-xs leading-relaxed text-secondary">
                {m.flow_run_fields_intro_desc()}
              </p>
              {#if hasRequiredFormFields}
                <p class="text-xs text-secondary">{m.flow_run_required_hint()}</p>
              {/if}
            </div>
          </div>

          {#if missingRequiredFields.length > 0}
            <div class="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              {#if missingRequiredFieldNames.length > 0}
                {m.flow_run_missing_required_named({ fields: missingRequiredFieldNames.join(", ") })}
              {:else}
                {m.flow_run_missing_required()}
              {/if}
            </div>
          {/if}

          {#each formFields as field, fieldIndex (field.name)}
            <div class="flex flex-col gap-1">
              <label class="text-sm font-medium" for={`flow-input-${fieldIndex}`}>
                {field.name}
                {#if field.required}
                  <span class="text-red-500">*</span>
                {/if}
              </label>
              {#if field.type === "multiselect"}
                <select
                  id={`flow-input-${fieldIndex}`}
                  class="border-default bg-primary ring-default min-h-[100px] w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
                  multiple
                  required={field.required}
                  on:change={(e) => {
                    const selected = Array.from(e.currentTarget.selectedOptions).map(
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
                  class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
                  value={getFieldValue(field)}
                  required={field.required}
                  on:change={(e) => setFieldValue(field, e.currentTarget.value)}
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
                  class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
                  value={getFieldValue(field)}
                  placeholder={field.name}
                  required={field.required}
                  on:input={(e) => setFieldValue(field, e.currentTarget.value)}
                />
              {/if}
            </div>
          {/each}
        {:else}
          <div class="flex flex-col gap-1">
            <span class="text-sm font-medium">{m.flow_run_input()}</span>
            <span class="text-xs text-secondary">{m.flow_run_input_desc()}</span>
            <textarea
              class="border-default bg-primary ring-default min-h-[120px] w-full rounded-lg border px-3 py-2 font-mono text-sm shadow focus-within:ring-2"
              bind:value={inputText}
              placeholder={needsFileUpload
                ? isAudioUpload
                  ? m.flow_run_audio_placeholder()
                  : m.flow_run_document_placeholder()
                : m.flow_run_input_placeholder()}
            ></textarea>
          </div>
        {/if}

        {#if needsFileUpload}
          <div class="flex flex-col gap-2">
            <div>
              <p class="text-sm font-medium">{m.flow_run_files_section_title()}</p>
              <p class="mt-1 text-xs leading-relaxed text-secondary">
                {#if runtimeFileOriginKind === "flow_input_runtime"}
                  {m.flow_run_file_origin_runtime()}
                {:else if runtimeFileOriginKind === "no_runtime_upload"}
                  {m.flow_run_file_origin_no_runtime_upload()}
                {:else}
                  {m.flow_run_file_origin_static_step_context()}
                {/if}
              </p>
            </div>
            <div
              class="border-default flex min-h-[80px] cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-6 transition-colors"
              class:border-accent-default={isDragging}
              class:bg-accent-dimmer={isDragging}
              on:dragover={handleDragOver}
              on:dragleave={handleDragLeave}
              on:drop={handleDrop}
              on:click={openFilePicker}
              role="button"
              tabindex="0"
              on:keydown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  openFilePicker();
                }
              }}
            >
              {#if isUploading}
                <span class="text-secondary text-sm">{m.loading()}</span>
              {:else}
                <span class="text-secondary text-sm">{m.upload_file()}</span>
                <span class="text-secondary text-xs">
                  {isAudioUpload ? m.flow_run_audio_upload_hint() : m.upload_files_description()}
                </span>
                {#if effectiveMaxFileSizeBytes}
                  <span class="text-secondary text-xs">
                    {m.flow_run_upload_max_size({ size: formatBytes(effectiveMaxFileSizeBytes) })}
                  </span>
                {/if}
              {/if}
            </div>

            {#if policyLoadError}
              <p class="text-secondary text-xs">{policyLoadError}</p>
            {/if}
            {#if uploadError}
              <p class="text-xs text-red-600">{uploadError}</p>
            {/if}

            {#if uploadedFiles.length > 0}
              <div class="flex flex-col gap-1">
                {#each uploadedFiles as file (file.id)}
                  <div
                    class="bg-hover-dimmer flex items-center justify-between rounded-md px-3 py-2 text-sm"
                  >
                    <span class="min-w-0 truncate">{file.name ?? file.id}</span>
                    <button
                      class="ml-2 shrink-0 text-xs text-red-600 hover:text-red-800"
                      on:click={() => removeFile(file.id)}
                    >
                      {m.delete()}
                    </button>
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        {/if}
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      {#if lastInputPayload}
        <Button variant="outlined" on:click={reuseLastInput}>
          {m.flow_run_reuse_last_input()}
        </Button>
      {/if}
      <div class="flex-grow"></div>
      <Button is={close}>{m.cancel()}</Button>
      <Button
        onclick={triggerRun}
        variant="primary"
        disabled={isSubmitting || isUploading || missingRequiredFields.length > 0 || (needsFileUpload && uploadedFiles.length === 0)}
      >
        {#if isSubmitting}
          <IconLoadingSpinner class="size-4 animate-spin" />
        {/if}
        {m.flow_run_trigger()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
