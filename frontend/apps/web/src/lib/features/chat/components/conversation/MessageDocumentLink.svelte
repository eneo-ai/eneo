<!-- File names open previews; explicit download controls save the file. -->
<script lang="ts">
  import {
    sanitizeLinkHref,
    type EneoFileCustomComponentProps
  } from "$lib/components/markdown/index.js";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import { getFilePreview } from "$lib/features/file-preview/FilePreview.svelte";
  import { previewKindOf } from "$lib/features/file-preview/previewKind";
  import { m } from "$lib/paraglide/messages";
  import { getChatService } from "../../ChatService.svelte";
  import { isDocument } from "../../documentVersions";
  import { getMessageContext } from "../../MessageContext.svelte";

  const { token }: EneoFileCustomComponentProps = $props();

  const chat = getChatService();
  const preview = getFilePreview();
  const attachmentUrls = getAttachmentUrlService();
  const { current } = getMessageContext();

  // The file meant: the one this answer created, else the newest document of
  // that name in the conversation.
  const file = $derived(
    current().generated_files.findLast(
      (candidate) => isDocument(candidate) && candidate.name === token.name
    ) ??
      chat.documents.documents.findLast((document) =>
        document.versions.some((version) => version.name === token.name)
      )?.latest
  );
  const kind = $derived(file ? previewKindOf(file) : null);
  // A Markdown document is read in Eneo and goes by its title.
  const label = $derived(
    kind === "markdown" ? token.name.replace(/\.(md|markdown)$/i, "") : token.name
  );
  const href = $derived(
    file ? sanitizeLinkHref(attachmentUrls.getOriginalUrl(file) ?? null) : null
  );
  const linkClass =
    "text-accent-stronger hover:text-accent-default focus-visible:ring-accent-default rounded-sm font-[inherit] underline underline-offset-2 focus-visible:ring-2 focus-visible:outline-none";
</script>

{#if file && kind && preview}
  <button
    type="button"
    class="{linkClass} text-left"
    aria-label={m.file_preview_open({ name: file.name })}
    onclick={(event) => file && preview.open(file, event.currentTarget)}>{label}</button
  >
{:else if file && href}
  <!-- eslint-disable svelte/no-navigation-without-resolve -- signed file URL -->
  <a
    {href}
    download={file.name}
    class={linkClass}
    aria-label={m.generated_file_download({ name: file.name })}>{label}</a
  >
  <!-- eslint-enable svelte/no-navigation-without-resolve -->
{:else}
  {label}
{/if}
