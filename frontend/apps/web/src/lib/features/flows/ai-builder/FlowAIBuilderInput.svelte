<script lang="ts">
  /* eslint-disable eneo/no-raw-color -- composer styles derive colors from the
     accent token via relative oklch() syntax; the rest are near-transparent
     shadow overlays with no token equivalent */
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { getAppContext } from "$lib/core/AppContext";
  import { getEneo } from "$lib/core/Eneo";
  import { initAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import AttachmentPreview from "$lib/features/attachments/components/AttachmentPreview.svelte";
  import UploadedFileIcon from "$lib/features/attachments/components/UploadedFileIcon.svelte";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { formatFileType } from "$lib/core/formatting/formatFileType";
  import { IconAttachment } from "@eneo/icons/attachment";
  import { IconCancel } from "@eneo/icons/cancel";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconCheck } from "@eneo/icons/check";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import { getAIBuilderAttachmentRules } from "./builderAttachmentRules";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import type { AIBuilderPlanEditContext } from "./protocol";

  interface Props {
    editContext?: AIBuilderPlanEditContext | null;
    oncleareditcontext?: () => void;
  }

  let { editContext = null, oncleareditcontext }: Props = $props();

  const service = getAIBuilderService();
  const userMode = getFlowUserMode();
  const { limits } = getAppContext();
  const attachmentRules = getAIBuilderAttachmentRules(limits);
  const {
    state: { attachments, isUploading, attachmentRules: managerRules },
    queueValidUploads,
    clearUploads
  } = initAttachmentManager({
    eneo: getEneo(),
    options: { rules: attachmentRules }
  });

  let inputValue = $state("");
  let textareaEl: HTMLTextAreaElement | undefined = $state();
  let fileInputEl: HTMLInputElement | undefined = $state();
  let activePlaceholder = $state<string | null>(null);
  let isDragging = $state(false);

  const currentPlaceholder = $derived(activePlaceholder ?? m.ai_builder_input_placeholder());
  const completedUploads = $derived(
    $attachments.filter((attachment) => attachment.status === "completed")
  );
  const persistedAttachments = $derived(service.session?.attachments ?? []);
  const hasAttachments = $derived(persistedAttachments.length > 0 || $attachments.length > 0);
  const hasMultipleModels = $derived(service.availableModels.length > 1);
  const selectedModelName = $derived(
    service.availableModels.find((model) => model.id === service.selectedModelId)?.name ?? null
  );
  const selectedOrDefaultModelName = $derived(selectedModelName ?? m.ai_builder_model_default());
  const modelPillAccessibleLabel = $derived(
    `${m.ai_builder_model_label()}: ${selectedOrDefaultModelName}`
  );
  const canSubmit = $derived(
    (inputValue.trim().length > 0 || completedUploads.length > 0) &&
      service.canSendMessage &&
      !$isUploading
  );
  const editContextLabel = $derived.by(() => {
    if (!editContext) return null;
    if (editContext.scope === "whole_plan") {
      return m.ai_builder_edit_context_plan();
    }
    const stepNumber = editContext.target_step_number ?? null;
    const name = editContext.target_step_name ?? m.ai_builder_edit_context_step_fallback();
    return stepNumber
      ? m.ai_builder_edit_context_step({ step: stepNumber, name })
      : m.ai_builder_edit_context_step_without_number({ name });
  });

  export function focus(options?: string | { placeholder?: string; prefill?: string }) {
    // Support both legacy string signature (treated as placeholder) and options object
    if (typeof options === "string") {
      activePlaceholder = options;
    } else if (options) {
      if (options.prefill) inputValue = options.prefill;
      if (options.placeholder) activePlaceholder = options.placeholder;
    }
    requestAnimationFrame(() => {
      textareaEl?.focus();
      autosizeTextarea();
    });
  }

  export function clearActivePlaceholder() {
    activePlaceholder = null;
  }

  async function handleSubmit() {
    const trimmed = inputValue.trim();
    const uploadedFileIds = completedUploads
      .map((attachment) => attachment.fileRef?.id)
      .filter((value): value is string => Boolean(value));
    if ((!trimmed && uploadedFileIds.length === 0) || !service.canSendMessage || $isUploading) {
      return;
    }
    inputValue = "";
    activePlaceholder = null;
    resetTextareaHeight();
    await service.sendMessage(
      trimmed || m.ai_builder_attachment_only_message(),
      undefined,
      uploadedFileIds,
      editContext
    );
    clearUploads();
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSubmit();
    }
  }

  function autosizeTextarea() {
    if (!textareaEl) return;
    textareaEl.style.height = "auto";
    textareaEl.style.height = Math.min(textareaEl.scrollHeight, 300) + "px";
  }

  function resetTextareaHeight() {
    if (textareaEl) textareaEl.style.height = "auto";
  }

  function handlePaste(event: ClipboardEvent) {
    if (!event.clipboardData?.files || event.clipboardData.files.length === 0) return;
    queueValidUploads([...event.clipboardData.files]);
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault();
    isDragging = false;
    const files = event.dataTransfer?.files;
    if (!files || files.length === 0) return;
    queueValidUploads([...files]);
  }

  function handleFileInputChange() {
    if (!fileInputEl?.files) return;
    queueValidUploads([...fileInputEl.files]);
    // Reset so selecting the same file twice in a row re-triggers change
    fileInputEl.value = "";
  }

  /** Friendly chip label — prefers extension-based mapping over raw mime subtype. */
  function fileTypeLabel(mimetype: string, name?: string): string {
    const ext = name?.split(".").pop()?.toLowerCase() ?? "";
    const byExt: Record<string, string> = {
      md: "Markdown",
      txt: "Text",
      json: "JSON",
      csv: "CSV",
      pdf: "PDF",
      doc: "Word",
      docx: "Word",
      xls: "Excel",
      xlsx: "Excel",
      ppt: "PowerPoint",
      pptx: "PowerPoint"
    };
    if (byExt[ext]) return byExt[ext];
    const byMime: Record<string, string> = {
      "application/pdf": "PDF",
      "application/json": "JSON",
      "application/msword": "Word",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
      "application/vnd.ms-excel": "Excel",
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel",
      "application/vnd.ms-powerpoint": "PowerPoint",
      "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint",
      "text/plain": "Text",
      "text/markdown": "Markdown",
      "text/csv": "CSV"
    };
    return byMime[mimetype] ?? formatFileType(mimetype).toLowerCase();
  }

  /** Quiet byte formatter — short "B" suffix matches Linear/Vercel density. */
  function compactBytes(bytes: number): string {
    return formatBytes(bytes).replace(/\bBytes\b/, "B");
  }
</script>

<div class="relative mx-auto w-full max-w-[71ch]">
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="composer"
    class:composer-dragging={isDragging}
    ondragenter={(event) => {
      event.preventDefault();
      isDragging = true;
    }}
    ondragover={(event) => event.preventDefault()}
    ondragleave={(event) => {
      event.preventDefault();
      // Only clear when leaving the composer itself, not child nodes
      if (event.currentTarget === event.target) isDragging = false;
    }}
    ondrop={handleDrop}
  >
    {#if hasAttachments}
      <ul class="composer-chips" aria-label={m.ai_builder_reference_material()}>
        {#each persistedAttachments as file (file.id)}
          <li class="chip">
            <span class="chip-icon" aria-hidden="true">
              <UploadedFileIcon {file} />
            </span>
            <div class="chip-body">
              <AttachmentPreview {file} isTableView={true}>
                {#snippet children({ showFile }: { showFile: () => void })}
                  <button type="button" onclick={showFile} class="chip-name" title={file.name}>
                    {file.name}
                  </button>
                {/snippet}
              </AttachmentPreview>
              <div class="chip-meta">
                <span>{fileTypeLabel(file.mimetype, file.name)}</span>
                <span aria-hidden="true">·</span>
                <span>{compactBytes(file.size)}</span>
              </div>
            </div>
            <button
              type="button"
              class="chip-action"
              aria-label={m.remove_attachment()}
              onclick={() => service.removeAttachment(file.id)}
            >
              <IconTrash />
            </button>
          </li>
        {/each}

        {#each $attachments as upload (upload.id)}
          {@const isDone = upload.status === "completed"}
          <li class="chip" class:chip-uploading={!isDone}>
            <span class="chip-icon" aria-hidden="true">
              <UploadedFileIcon file={{ mimetype: upload.file.type }} />
            </span>
            <div class="chip-body">
              {#if isDone && upload.fileRef}
                <AttachmentPreview file={upload.fileRef} isTableView={true}>
                  {#snippet children({ showFile }: { showFile: () => void })}
                    <button
                      type="button"
                      onclick={showFile}
                      class="chip-name"
                      title={upload.file.name}
                    >
                      {upload.file.name}
                    </button>
                  {/snippet}
                </AttachmentPreview>
              {:else}
                <div class="chip-name chip-name-static" title={upload.file.name}>
                  {upload.file.name}
                </div>
              {/if}
              <div class="chip-meta">
                <span>
                  {isDone ? fileTypeLabel(upload.file.type, upload.file.name) : m.uploading()}
                </span>
                <span aria-hidden="true">·</span>
                <span>{compactBytes(upload.file.size)}</span>
              </div>
            </div>
            <button
              type="button"
              class="chip-action"
              aria-label={m.remove_attachment()}
              onclick={() => upload.remove()}
            >
              {#if isDone}
                <IconTrash />
              {:else}
                <IconCancel />
              {/if}
            </button>
            {#if !isDone}
              <span
                class="chip-progress"
                style={`--chip-progress:${upload.progress / 100}`}
                aria-hidden="true"
              ></span>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}

    {#if editContextLabel}
      <div class="composer-edit-context" role="status" aria-live="polite">
        <span class="composer-edit-context-dot" aria-hidden="true"></span>
        <span class="composer-edit-context-text">{editContextLabel}</span>
        <button
          type="button"
          class="composer-edit-context-clear"
          aria-label={m.ai_builder_edit_context_clear()}
          onclick={oncleareditcontext}
        >
          {m.ai_builder_edit_context_clear_short()}
        </button>
      </div>
    {/if}

    <label class="composer-textarea-wrap">
      <span class="sr-only">{m.ai_builder_input_placeholder()}</span>
      <textarea
        bind:this={textareaEl}
        bind:value={inputValue}
        onkeydown={handleKeydown}
        oninput={autosizeTextarea}
        onpaste={handlePaste}
        placeholder={currentPlaceholder}
        disabled={!service.canSendMessage || $isUploading}
        rows="1"
        class="composer-textarea"></textarea>
    </label>

    <div class="composer-actions">
      <div class="composer-actions-left">
        <input
          bind:this={fileInputEl}
          type="file"
          accept={$managerRules.acceptString}
          multiple
          aria-label={m.attach_files()}
          class="sr-only"
          onchange={handleFileInputChange}
          disabled={!service.canSendMessage || $isUploading}
        />
        <button
          type="button"
          class="composer-attach"
          aria-label={m.attach_files()}
          disabled={!service.canSendMessage || $isUploading}
          onclick={() => fileInputEl?.click()}
        >
          <IconAttachment class="composer-attach-icon" />
          <span class="composer-attach-label">{m.attach_files()}</span>
        </button>

        <!-- Model choice is a technical control: visible only in Avancerad. -->
        {#if service.modelsLoaded && $userMode === "power_user"}
          {#if hasMultipleModels}
            <DropdownMenu.Root>
              <DropdownMenu.Trigger>
                {#snippet child({ props })}
                  <button
                    {...props}
                    type="button"
                    class="model-pill"
                    aria-label={modelPillAccessibleLabel}
                    title={m.ai_builder_model_usage_hint()}
                    disabled={service.isCreating}
                  >
                    <span class="model-pill-dot" aria-hidden="true"></span>
                    <span class="model-pill-name">{selectedOrDefaultModelName}</span>
                    <svg
                      class="model-pill-chevron"
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 16 16"
                      fill="currentColor"
                      aria-hidden="true"
                    >
                      <path
                        fill-rule="evenodd"
                        d="M4.22 6.22a.75.75 0 0 1 1.06 0L8 8.94l2.72-2.72a.75.75 0 1 1 1.06 1.06l-3.25 3.25a.75.75 0 0 1-1.06 0L4.22 7.28a.75.75 0 0 1 0-1.06Z"
                        clip-rule="evenodd"
                      />
                    </svg>
                  </button>
                {/snippet}
              </DropdownMenu.Trigger>
              <DropdownMenu.Content align="start" sideOffset={8}>
                {#each service.availableModels as model (model.id)}
                  <DropdownMenu.Item
                    onmousedown={() => service.selectModel(model.id)}
                    class="!justify-start !gap-2 !px-2.5 !py-1.5 !text-[0.8125rem]"
                  >
                    <span class="flex-1 text-left">{model.name}</span>
                    {#if model.id === service.selectedModelId}
                      <IconCheck class="text-accent-default size-3.5" />
                    {/if}
                  </DropdownMenu.Item>
                {/each}
              </DropdownMenu.Content>
            </DropdownMenu.Root>
          {:else}
            <Tooltip.Root>
              <Tooltip.Trigger>
                {#snippet child({ props })}
                  <button
                    {...props}
                    type="button"
                    aria-disabled="true"
                    aria-label={modelPillAccessibleLabel}
                    class="model-pill model-pill-static"
                    onclick={(event) => event.preventDefault()}
                  >
                    <span class="model-pill-dot" aria-hidden="true"></span>
                    <span class="model-pill-name">{selectedOrDefaultModelName}</span>
                  </button>
                {/snippet}
              </Tooltip.Trigger>
              <Tooltip.Content side="top" sideOffset={6}>
                <div class="flex max-w-64 flex-col gap-1">
                  <span>{m.ai_builder_model_only_one()}</span>
                  <span class="text-muted">{m.ai_builder_model_usage_hint()}</span>
                </div>
              </Tooltip.Content>
            </Tooltip.Root>
          {/if}
        {/if}
      </div>

      <Button
        variant="default"
        size="sm"
        class="composer-send"
        onclick={handleSubmit}
        disabled={!canSubmit}
        aria-label={m.ai_builder_send()}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          class="size-3.5"
          aria-hidden="true"
        >
          <path
            d="M3.105 2.288a.75.75 0 0 0-.826.95l1.414 4.926A1.5 1.5 0 0 0 5.135 9.25h6.115a.75.75 0 0 1 0 1.5H5.135a1.5 1.5 0 0 0-1.442 1.086l-1.414 4.926a.75.75 0 0 0 .826.95 28.897 28.897 0 0 0 15.293-7.155.75.75 0 0 0 0-1.114A28.897 28.897 0 0 0 3.105 2.288Z"
          />
        </svg>
        <span class="composer-send-label">{m.ai_builder_send()}</span>
      </Button>
    </div>

    {#if isDragging}
      <div
        class="composer-drop-overlay"
        role="region"
        aria-live="polite"
        aria-label={m.drop_files_here_to_upload()}
      >
        <div class="composer-drop-inner">
          <IconAttachment class="composer-drop-icon" />
          <div class="composer-drop-title">
            {m.drop_files_here_to_upload()}
          </div>
          <div class="composer-drop-hint">
            {m.ai_builder_attachment_drop_hint()}
          </div>
        </div>
      </div>
    {/if}
  </div>
</div>

<style lang="postcss">
  .composer {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 0;
    border: 1px solid var(--border-default);
    background: var(--background-primary);
    border-radius: 1rem;
    box-shadow: 0 1px 2px oklch(0% 0 0 / 0.04);
    transition:
      border-color 160ms cubic-bezier(0.22, 1, 0.36, 1),
      box-shadow 160ms cubic-bezier(0.22, 1, 0.36, 1);
  }

  .composer:focus-within {
    border-color: oklch(from var(--accent-default) l c h / 0.5);
    box-shadow:
      0 0 0 3px oklch(from var(--accent-default) l c h / 0.12),
      0 1px 2px oklch(0% 0 0 / 0.04),
      0 6px 18px -8px oklch(0% 0 0 / 0.1);
  }

  .composer-dragging {
    border-color: var(--accent-default);
    box-shadow:
      0 0 0 3px oklch(from var(--accent-default) l c h / 0.18),
      0 8px 24px -10px oklch(from var(--accent-default) l c h / 0.35);
  }

  /* ------------------------------------------------------------------ */
  /* Attachment chip row                                                 */
  /* ------------------------------------------------------------------ */

  .composer-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
    margin: 0;
    padding: 0.625rem 0.625rem 0;
    list-style: none;
  }

  .chip {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    max-width: min(100%, 20rem);
    padding: 0.375rem 0.375rem 0.375rem 0.625rem;
    background: var(--background-secondary);
    border: 1px solid var(--border-default);
    border-radius: 0.625rem;
    overflow: hidden;
  }

  .chip-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.25rem;
    height: 1.25rem;
    flex-shrink: 0;
    color: var(--text-secondary);
  }

  .chip-body {
    display: flex;
    flex-direction: column;
    gap: 0.0625rem;
    min-width: 0;
    flex: 1 1 auto;
  }

  .chip-name,
  .chip-name-static {
    display: block;
    max-width: 100%;
    font-size: 0.8125rem;
    font-weight: 500;
    line-height: 1.2;
    color: var(--text-primary);
    background: transparent;
    border: 0;
    padding: 0;
    text-align: left;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .chip-name {
    cursor: pointer;
  }

  .chip-name:hover {
    text-decoration: underline;
    text-underline-offset: 0.15em;
  }

  .chip-meta {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    font-size: 0.6875rem;
    line-height: 1.2;
    color: var(--text-secondary);
    font-variant-numeric: tabular-nums;
  }

  .chip-action {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 1.75rem;
    height: 1.75rem;
    border-radius: 0.375rem;
    color: var(--text-secondary);
    background: transparent;
    border: 0;
    cursor: pointer;
    transition:
      color 120ms ease,
      background 120ms ease;
  }

  .chip-action:hover {
    color: var(--text-primary);
    background: var(--background-hover-default);
  }

  .chip-action :global(svg) {
    width: 0.875rem;
    height: 0.875rem;
  }

  .chip-progress {
    position: absolute;
    left: 0;
    bottom: 0;
    height: 2px;
    width: 100%;
    transform: scaleX(var(--chip-progress, 0));
    transform-origin: left center;
    background: var(--accent-default);
    transition: transform 200ms linear;
  }

  .chip-uploading .chip-body {
    opacity: 0.85;
  }

  .composer-edit-context {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0.625rem 0.625rem 0;
    padding: 0.5rem 0.625rem;
    background: var(--background-secondary);
    border: 1px solid var(--border-default);
    border-radius: 0.75rem;
    color: var(--text-secondary);
    font-size: 0.8125rem;
    line-height: 1.25;
  }

  .composer-edit-context-dot {
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 999px;
    background: var(--accent-default);
    flex: 0 0 auto;
  }

  .composer-edit-context-text {
    min-width: 0;
    flex: 1 1 auto;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .composer-edit-context-clear {
    flex: 0 0 auto;
    border: 0;
    background: transparent;
    color: var(--text-muted);
    font-size: 0.75rem;
    font-weight: 600;
    cursor: pointer;
    padding: 0.125rem 0.25rem;
    border-radius: 0.375rem;
  }

  .composer-edit-context-clear:hover {
    color: var(--text-primary);
    background: var(--background-hover-default);
  }

  .composer-textarea-wrap {
    display: block;
  }

  .composer-textarea {
    display: block;
    width: 100%;
    min-height: 5rem;
    max-height: 18.75rem;
    padding: 1rem 1rem 0.5rem;
    color: var(--text-primary);
    background: transparent;
    border: 0;
    outline: none;
    resize: none;
    font-size: 0.9375rem;
    line-height: 1.5;
    font-family: inherit;
  }

  @media (max-width: 640px) {
    .composer-textarea {
      min-height: 3.75rem;
      padding: 0.875rem 0.875rem 0.5rem;
    }
  }

  .composer-textarea::placeholder {
    color: var(--text-muted);
  }

  .composer-textarea:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .composer-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    padding: 0.5rem 0.5rem 0.5rem 0.625rem;
    flex-wrap: wrap;
  }

  .composer-actions-left {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    flex: 1 1 auto;
    min-width: 0;
    flex-wrap: wrap;
  }

  .composer-attach {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    height: 1.75rem;
    padding: 0 0.5rem;
    border-radius: 0.5rem;
    color: var(--text-secondary);
    background: transparent;
    cursor: pointer;
    border: 0;
    font-size: 0.8125rem;
    font-weight: 500;
    line-height: 1;
    transition:
      color 120ms ease,
      background 120ms ease;
  }

  .composer-attach:hover {
    color: var(--text-primary);
    background: var(--background-hover-default);
  }

  .composer-attach:focus-visible {
    outline: 2px solid var(--accent-default);
    outline-offset: 2px;
  }

  .composer-attach:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }

  .composer-attach :global(.composer-attach-icon) {
    width: 1rem;
    height: 1rem;
    flex-shrink: 0;
  }

  /* Compact mobile controls keep the composer usable above the keyboard. */
  @media (max-width: 639px) {
    .composer-attach,
    .model-pill,
    .composer :global(.composer-send) {
      min-height: 2.75rem;
    }

    .composer-attach-label {
      display: none;
    }

    .composer-attach {
      width: 2.75rem;
      justify-content: center;
      padding: 0;
    }
  }

  /* --- Model pill --- */

  .model-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    height: 1.75rem;
    padding: 0 0.625rem;
    border-radius: 999px;
    color: var(--text-secondary);
    background: var(--background-secondary);
    border: 1px solid transparent;
    font-size: 0.75rem;
    font-weight: 500;
    line-height: 1;
    cursor: pointer;
    max-width: min(100%, 16rem);
    transition:
      color 120ms ease,
      background 120ms ease,
      border-color 120ms ease;
  }

  .model-pill:hover,
  .model-pill[aria-expanded="true"] {
    color: var(--text-primary);
    background: var(--background-hover-default);
  }

  .model-pill:focus-visible {
    outline: 2px solid var(--accent-default);
    outline-offset: 2px;
  }

  .model-pill-static {
    cursor: default;
  }

  .model-pill-static:hover {
    background: var(--background-secondary);
    color: var(--text-secondary);
  }

  .model-pill-dot {
    width: 0.4375rem;
    height: 0.4375rem;
    border-radius: 50%;
    background: var(--accent-default);
    box-shadow: 0 0 0 2px oklch(from var(--accent-default) l c h / 0.15);
    flex-shrink: 0;
  }

  .model-pill-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .model-pill-chevron {
    width: 0.625rem;
    height: 0.625rem;
    flex-shrink: 0;
    opacity: 0.6;
  }

  .composer :global(.composer-send) {
    height: 1.75rem;
    border-radius: 999px;
    padding: 0 0.75rem;
    gap: 0.375rem;
  }

  @media (max-width: 639px) {
    .composer :global(.composer-send) {
      padding: 0;
      width: 2.75rem;
    }

    .composer-send-label {
      display: none;
    }
  }

  .composer-drop-overlay {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0.5rem;
    background: var(--background-primary);
    border-radius: inherit;
    pointer-events: none;
  }

  .composer-drop-inner {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    width: 100%;
    height: 100%;
    min-height: 7rem;
    border: 1.5px dashed var(--accent-default);
    border-radius: 0.75rem;
    padding: 1rem 1.25rem;
    background: color-mix(in oklch, var(--accent-default) 6%, var(--background-primary));
    color: var(--text-primary);
    text-align: center;
    justify-content: center;
  }

  .composer-drop-inner :global(.composer-drop-icon) {
    width: 1.75rem;
    height: 1.75rem;
    color: var(--accent-default);
  }

  .composer-drop-title {
    font-size: 0.8125rem;
    font-weight: 600;
    line-height: 1.3;
    color: var(--text-primary);
  }

  .composer-drop-hint {
    font-size: 0.75rem;
    line-height: 1.3;
    color: var(--text-secondary);
    max-width: 36ch;
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
</style>
