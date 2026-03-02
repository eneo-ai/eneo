<script lang="ts">
  import type { Flow, Intric, UploadedFile } from "@intric/intric-js";
  import { Button, Dialog } from "@intric/ui";
  import { createEventDispatcher } from "svelte";
  import { writable } from "svelte/store";
  import { IntricError } from "@intric/intric-js";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";

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

  type FormField = { name: string; type: string; required?: boolean };
  $: formFields = ((flow.metadata_json?.form_schema as { fields: FormField[] })?.fields ?? []) as FormField[];
  $: hasFormFields = formFields.length > 0;

  $: stepCount = flow.steps?.length ?? 0;

  // Detect if first step expects file/document input
  $: firstStep = flow.steps?.length > 0 ? flow.steps[0] : null;
  $: needsFileUpload = firstStep?.input_type === "document" || firstStep?.input_type === "file";

  let formValues: Record<string, string> = {};

  // File upload state
  let uploadedFiles: UploadedFile[] = [];
  let isUploading = false;
  let uploadError: string | null = null;
  let isDragging = false;

  function reuseLastInput() {
    if (lastInputPayload) {
      if (hasFormFields) {
        for (const field of formFields) {
          formValues[field.name] = String(lastInputPayload[field.name] ?? "");
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

  async function uploadFiles(files: File[]) {
    isUploading = true;
    uploadError = null;
    for (const file of files) {
      try {
        const uploaded = await intric.files.upload({ file });
        uploadedFiles = [...uploadedFiles, uploaded];
      } catch (e) {
        uploadError = e instanceof IntricError ? e.getReadableMessage() : String(e);
      }
    }
    isUploading = false;
  }

  function removeFile(fileId: string) {
    uploadedFiles = uploadedFiles.filter((f) => f.id !== fileId);
  }

  async function triggerRun() {
    if (!flow.id) return;
    isSubmitting = true;
    try {
      let payload: Record<string, unknown>;
      if (hasFormFields) {
        payload = { ...formValues };
      } else {
        payload = { text: inputText };
      }
      const fileIds = uploadedFiles.length > 0
        ? uploadedFiles.map((f) => f.id)
        : undefined;
      await intric.flows.runs.create({
        flow: { id: flow.id },
        input_payload_json: payload,
        file_ids: fileIds,
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
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="dynamic">
    <Dialog.Section class="relative mt-2 -mb-0.5">
      <div class="flex w-full flex-col gap-6 px-10 pt-8 pb-8">
        <h3 class="text-xl font-bold">{m.flow_run_trigger()}</h3>
        <p class="text-secondary text-sm">
          {flow.name}
          {#if stepCount > 0}
            <span class="text-muted ml-1">({m.flow_run_step_count({ count: String(stepCount) })})</span>
          {/if}
        </p>

        {#if hasFormFields}
          {#each formFields as field}
            <div class="flex flex-col gap-1">
              <label class="text-sm font-medium">
                {field.name}
                {#if field.required}
                  <span class="text-red-500">*</span>
                {/if}
              </label>
              {#if field.type === "textarea"}
                <textarea
                  class="border-default bg-primary ring-default min-h-[80px] w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
                  bind:value={formValues[field.name]}
                  placeholder={field.name}
                  required={field.required}
                ></textarea>
              {:else}
                <input
                  type={field.type === "number" ? "number" : field.type === "email" ? "email" : "text"}
                  class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
                  bind:value={formValues[field.name]}
                  placeholder={field.name}
                  required={field.required}
                />
              {/if}
            </div>
          {/each}
        {:else}
          <div class="flex flex-col gap-1">
            <span class="text-sm font-medium">{m.flow_run_input()}</span>
            <textarea
              class="border-default bg-primary ring-default min-h-[120px] w-full rounded-lg border px-3 py-2 font-mono text-sm shadow focus-within:ring-2"
              bind:value={inputText}
              placeholder={needsFileUpload ? m.flow_run_document_placeholder() : m.flow_run_input_placeholder()}
            ></textarea>
          </div>
        {/if}

        {#if needsFileUpload}
          <div class="flex flex-col gap-2">
            <span class="text-sm font-medium">{m.flow_attachments()}</span>
            <!-- svelte-ignore a11y-no-static-element-interactions -->
            <div
              class="border-default flex min-h-[80px] cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-6 transition-colors"
              class:border-blue-400={isDragging}
              class:bg-blue-50={isDragging}
              on:dragover={handleDragOver}
              on:dragleave={handleDragLeave}
              on:drop={handleDrop}
              on:click={() => {
                const input = document.createElement("input");
                input.type = "file";
                input.multiple = true;
                input.onchange = (e) => handleFileSelect(e);
                input.click();
              }}
              role="button"
              tabindex="0"
              on:keydown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  const input = document.createElement("input");
                  input.type = "file";
                  input.multiple = true;
                  input.onchange = (ev) => handleFileSelect(ev);
                  input.click();
                }
              }}
            >
              {#if isUploading}
                <span class="text-secondary text-sm">{m.uploading()}</span>
              {:else}
                <span class="text-secondary text-sm">{m.upload_files()}</span>
                <span class="text-xs text-secondary">{m.upload_files_description()}</span>
              {/if}
            </div>

            {#if uploadError}
              <p class="text-xs text-red-600">{uploadError}</p>
            {/if}

            {#if uploadedFiles.length > 0}
              <div class="flex flex-col gap-1">
                {#each uploadedFiles as file (file.id)}
                  <div class="bg-hover-dimmer flex items-center justify-between rounded-md px-3 py-2 text-sm">
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
        disabled={isSubmitting || isUploading}
      >
        {#if isSubmitting}
          <IconLoadingSpinner class="size-4 animate-spin" />
        {/if}
        {m.flow_run_trigger()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
