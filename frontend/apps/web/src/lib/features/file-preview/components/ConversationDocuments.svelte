<!--
  The documents the assistant created in the conversation, behind one button
  in the chat header. Answers carry no file card for a document, so this list
  is the way back to one whose panel was closed.
-->
<script lang="ts">
  import { sanitizeLinkHref } from "$lib/components/markdown/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { pickFileIcon } from "$lib/core/formatting/pickFileIcon";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import type { ConversationDocument } from "$lib/features/chat/documentVersions";
  import { m } from "$lib/paraglide/messages";
  import Download from "@lucide/svelte/icons/download";
  import FileText from "@lucide/svelte/icons/file-text";
  import type { FilePreview } from "../FilePreview.svelte";
  import { previewKindOf } from "../previewKind";

  let { preview, documents }: { preview: FilePreview; documents: ConversationDocument[] } =
    $props();

  const attachmentUrls = getAttachmentUrlService();

  let open = $state(false);
  let trigger = $state<HTMLElement | null>(null);

  // A Markdown document is read in Eneo and listed by its title.
  const displayName = (file: { name: string; mimetype: string }) =>
    previewKindOf(file) === "markdown" ? file.name.replace(/\.(md|markdown)$/i, "") : file.name;
  const description = ({ latest, versions }: ConversationDocument) => {
    const extension = latest.name.includes(".")
      ? (latest.name.split(".").pop() ?? "").toUpperCase()
      : "";
    const bytes = latest.original_size ?? latest.size;
    return [
      extension,
      bytes > 0 ? formatBytes(bytes) : "",
      versions.length > 1 ? m.conversation_document_versions({ count: versions.length }) : ""
    ]
      .filter(Boolean)
      .join(" · ");
  };
</script>

{#snippet row(document: ConversationDocument)}
  {@const Icon = pickFileIcon(document.latest.mimetype)}
  <span
    class="bg-accent-dimmer text-accent-stronger flex size-8 shrink-0 items-center justify-center rounded-md"
  >
    <Icon class="size-4" aria-hidden="true" />
  </span>
  <span class="flex min-w-0 flex-1 flex-col leading-tight">
    <span class="text-foreground truncate text-sm font-medium">{displayName(document.latest)}</span>
    <span class="text-muted-foreground truncate text-xs tabular-nums">
      {description(document)}
    </span>
  </span>
{/snippet}

{#if documents.length > 0}
  <Popover.Root bind:open>
    <Popover.Trigger
      bind:ref={trigger}
      class={buttonVariants({ variant: preview.shown ? "secondary" : "ghost" }) + " gap-1.5"}
      aria-label={m.conversation_documents_count_aria({ count: documents.length })}
    >
      <FileText class="size-4" aria-hidden="true" />
      <span class="hidden sm:inline">{m.documents()}</span>
      <Badge variant="secondary" class="px-1.5 tabular-nums" aria-hidden="true">
        {documents.length}
      </Badge>
    </Popover.Trigger>

    <Popover.Content align="end" class="w-80 gap-0 p-0">
      <div class="border-b px-3 py-2.5">
        <Popover.Title class="text-sm">{m.conversation_documents_heading()}</Popover.Title>
      </div>
      <ul class="flex max-h-80 flex-col overflow-y-auto p-1">
        {#each documents as document (document.latest.id)}
          {@const file = document.latest}
          {@const href = sanitizeLinkHref(attachmentUrls.getOriginalUrl(file) ?? null)}
          {@const previewable = preview.canPreview(file)}
          <!-- eslint-disable svelte/no-navigation-without-resolve -- signed file URL -->
          <li class="flex items-center gap-1">
            {#if previewable}
              <button
                type="button"
                class="hover:bg-muted focus-visible:ring-accent-default flex min-w-0 flex-1 items-center gap-2.5 rounded-md px-2 py-1.5 text-left focus-visible:ring-2 focus-visible:outline-none {preview.isOpen(
                  file
                )
                  ? 'bg-muted'
                  : ''}"
                aria-label={m.file_preview_open({ name: file.name })}
                onclick={() => {
                  open = false;
                  preview.open(file, trigger);
                }}
              >
                {@render row(document)}
              </button>
            {:else}
              <div class="flex min-w-0 flex-1 items-center gap-2.5 px-2 py-1.5">
                {@render row(document)}
              </div>
            {/if}
            <a
              href={href ?? undefined}
              download={file.name}
              aria-label={m.generated_file_download({ name: file.name })}
              aria-disabled={href ? undefined : "true"}
              title={m.download()}
              class="text-secondary hover:bg-muted hover:text-default focus-visible:ring-accent-default flex size-8 shrink-0 items-center justify-center rounded-md transition-colors focus-visible:ring-2 focus-visible:outline-none {href
                ? ''
                : 'pointer-events-none opacity-60'}"
            >
              <Download class="size-4" aria-hidden="true" />
            </a>
          </li>
          <!-- eslint-enable svelte/no-navigation-without-resolve -->
        {/each}
      </ul>
    </Popover.Content>
  </Popover.Root>
{/if}
