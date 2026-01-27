<script lang="ts">
  import { IconUpload } from "@intric/icons/upload";
  import type { App } from "@intric/intric-js";
  import { getAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import { getExplicitAttachmentRules } from "$lib/features/attachments/getAttachmentRules";
  import AttachmentItem from "$lib/features/attachments/components/AttachmentItem.svelte";
  import { m } from "$lib/paraglide/messages";

  export let input: App["input_fields"][number];
  export let description: string | undefined = undefined;

  const attachmentRules = getExplicitAttachmentRules(input);
  let fileInput: HTMLInputElement;
  let isDragging = false;

  const {
    queueValidUploads,
    state: { attachments }
  } = getAttachmentManager();

  // Use provided description or fall back to translated default
  $: displayDescription = description ?? m.upload_files_description();

  function uploadFiles() {
    if (!fileInput.files) return;

    const errors = queueValidUploads([...fileInput.files], attachmentRules);

    if (errors) {
      alert(errors.join("\n"));
    }

    fileInput.value = "";
  }

  function handleDragEnter(e: DragEvent) {
    e.preventDefault();
    isDragging = true;
  }

  function handleDragLeave(e: DragEvent) {
    const target = e.currentTarget as HTMLElement;
    if (!target.contains(e.relatedTarget as Node)) {
      isDragging = false;
    }
  }

  function handleDrop() {
    isDragging = false;
  }

  // Map MIME types to human-friendly labels
  // Based on backend: intric/files/text.py, audio.py, image.py
  const mimeToFriendly: Record<string, string> = {
    // Text types (from TextMimeTypes)
    "text/plain": "TXT",
    "text/markdown": "Markdown",
    "text/csv": "CSV",
    "application/csv": "CSV",
    "application/pdf": "PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint",
    "application/msword": "Word",
    "application/vnd.ms-excel": "Excel",
    "application/vnd.ms-powerpoint": "PowerPoint",
    // Image types (from ImageMimeTypes)
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    // Audio types (from AudioMimeTypes)
    "audio/mpeg": "MP3",
    "audio/mp3": "MP3",
    "audio/wav": "WAV",
    "audio/ogg": "OGG",
    "audio/webm": "WebM",
    "audio/mp4": "M4A",
    "audio/x-m4a": "M4A",
    "video/webm": "WebM",
    "video/mp4": "MP4"
  };

  function formatMimeType(mime: string): string {
    const trimmed = mime.trim().toLowerCase();
    // Check exact match first
    if (mimeToFriendly[trimmed]) {
      return mimeToFriendly[trimmed];
    }
    // Handle file extensions (e.g., ".pdf", ".docx")
    if (trimmed.startsWith(".")) {
      return trimmed.slice(1).toUpperCase();
    }
    // Extract subtype from MIME (e.g., "application/pdf" -> "PDF")
    const parts = trimmed.split("/");
    if (parts.length === 2) {
      const subtype = parts[1].split(";")[0]; // Remove charset etc.
      // Handle common patterns
      if (subtype.includes("word")) return "Word";
      if (subtype.includes("excel") || subtype.includes("spreadsheet")) return "Excel";
      if (subtype.includes("powerpoint") || subtype.includes("presentation")) return "PowerPoint";
      return subtype.toUpperCase();
    }
    return trimmed.toUpperCase();
  }

  // Format accepted types for display with friendly names
  $: acceptedTypesLabel = attachmentRules.acceptString
    ? attachmentRules.acceptString
        .split(",")
        .map((t) => formatMimeType(t))
        .filter((v, i, a) => a.indexOf(v) === i) // Remove duplicates
        .slice(0, 6)
        .join(", ") +
      (attachmentRules.acceptString.split(",").length > 6 ? ", ..." : "")
    : null;
</script>

{#if $attachments.length > 0}
  <div class="border-default bg-primary w-[60ch] rounded-lg border p-2">
    <div class="flex flex-col">
      {#each $attachments as attachment (attachment.id)}
        <AttachmentItem {attachment}></AttachmentItem>
      {/each}
    </div>
  </div>
{/if}

{#if attachmentRules.maxTotalCount ? $attachments.length < attachmentRules.maxTotalCount : true}
  <label
    for="fileInput"
    class="upload-target"
    class:is-dragging={isDragging}
    on:dragenter={handleDragEnter}
    on:dragleave={handleDragLeave}
    on:drop={handleDrop}
  >
    <IconUpload class="text-secondary"></IconUpload>
    <span class="font-medium">{displayDescription}</span>
    {#if acceptedTypesLabel}
      <span class="file-types">{acceptedTypesLabel}</span>
    {/if}
  </label>
  <input
    type="file"
    bind:this={fileInput}
    id="fileInput"
    accept={attachmentRules.acceptString}
    multiple={true}
    on:change={uploadFiles}
    class="pointer-events-none absolute h-11 w-11 rounded-lg file:border-none file:bg-transparent file:text-transparent"
  />
{/if}

<style lang="postcss">
  @reference "@intric/ui/styles";

  /* Upload target with dashed border pattern */
  .upload-target {
    @apply flex cursor-pointer flex-col items-center gap-2 rounded-xl p-6;
    @apply border-2 border-dashed border-gray-300;
    @apply bg-gray-50 transition-all duration-200;
  }

  :global(.dark) .upload-target {
    @apply border-gray-600 bg-gray-800/50;
  }

  .upload-target:hover {
    @apply border-blue-400 bg-blue-50 shadow-md;
    transform: translateY(-1px);
  }

  :global(.dark) .upload-target:hover {
    @apply border-blue-500 bg-blue-900/20;
  }

  .upload-target.is-dragging {
    @apply border-blue-500 bg-blue-100;
    @apply ring-4 ring-blue-500/20;
  }

  :global(.dark) .upload-target.is-dragging {
    @apply border-blue-400 bg-blue-900/30;
    @apply ring-blue-400/20;
  }

  @media (prefers-reduced-motion: reduce) {
    .upload-target {
      transition: none;
    }
    .upload-target:hover {
      transform: none;
    }
  }

  /* File types label - subtle, readable */
  .file-types {
    @apply mt-2 text-xs text-gray-500;
    @apply max-w-[40ch] text-center leading-relaxed;
  }

  :global(.dark) .file-types {
    @apply text-gray-400;
  }
</style>
