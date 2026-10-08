<!--
  What a conversation has to show in the panel, as one list: interactive tool
  views, documents created in the chat and uploaded files. The panel
  overview and the switcher in the panel's title both show it.
-->
<script lang="ts">
  import { sanitizeLinkHref } from "$lib/components/markdown/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { pickFileIcon } from "$lib/core/formatting/pickFileIcon";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import type { ConversationDocument } from "$lib/features/chat/documentVersions";
  import { m } from "$lib/paraglide/messages";
  import AppWindow from "@lucide/svelte/icons/app-window";
  import Check from "@lucide/svelte/icons/check";
  import Download from "@lucide/svelte/icons/download";
  import type { FilePreview } from "../FilePreview.svelte";
  import type { PanelView } from "../panelContents";
  import { previewKindOf, type PreviewFile } from "../previewKind";

  let {
    preview,
    documents,
    uploads = [],
    views = [],
    fullHeight = false,
    onfile,
    onview
  }: {
    preview: FilePreview;
    documents: ConversationDocument[];
    uploads?: PreviewFile[];
    views?: PanelView[];
    fullHeight?: boolean;
    onfile: (file: PreviewFile) => void;
    onview?: (view: PanelView) => void;
  } = $props();

  const attachmentUrls = getAttachmentUrlService();

  // A Markdown document is read in Eneo and listed by its title.
  const displayName = (file: { name: string; mimetype: string }) =>
    previewKindOf(file) === "markdown" ? file.name.replace(/\.(md|markdown)$/i, "") : file.name;
  const description = (latest: PreviewFile, versionCount: number) => {
    const extension = latest.name.includes(".")
      ? (latest.name.split(".").pop() ?? "").toUpperCase()
      : "";
    const bytes = latest.original_size ?? latest.size;
    return [
      extension,
      bytes > 0 ? formatBytes(bytes) : "",
      versionCount > 1 ? m.conversation_document_versions({ count: versionCount }) : ""
    ]
      .filter(Boolean)
      .join(" · ");
  };

  // A row is a ghost button that holds two lines, with the hover of a row
  // instead of the button's; the one on show is marked as the selection.
  const rowClass =
    "hover:bg-hover-default h-auto min-w-0 flex-1 justify-start gap-2.5 px-2 py-1.5 text-left font-normal";
  const currentClass = "bg-accent-dimmer hover:bg-accent-dimmer";
</script>

{#snippet row(Icon: typeof AppWindow, name: string, detail: string, current: boolean)}
  <span
    class={[
      "text-accent-stronger flex size-8 shrink-0 items-center justify-center rounded-md",
      current ? "bg-background" : "bg-accent-dimmer"
    ]}
  >
    <Icon class="size-4" aria-hidden="true" />
  </span>
  <span class="flex min-w-0 flex-1 flex-col leading-tight">
    <span class="text-foreground truncate text-sm font-medium">{name}</span>
    <span class="text-muted-foreground truncate text-xs tabular-nums">{detail}</span>
  </span>
  {#if current}
    <Check class="text-accent-stronger size-4 shrink-0" aria-hidden="true" />
  {/if}
{/snippet}

<!-- `versions` are every file of the entry; the panel may show an earlier one. -->
{#snippet entry(file: PreviewFile, versions: PreviewFile[])}
  {@const href = sanitizeLinkHref(attachmentUrls.getOriginalUrl(file) ?? null)}
  {@const current = versions.some((version) => preview.isOpen(version))}
  {@const Icon = pickFileIcon(file.mimetype)}
  <li class="flex items-center gap-1">
    {#if preview.canPreview(file)}
      <Button
        variant="ghost"
        class={[rowClass, current && currentClass]}
        aria-label={m.file_preview_open({ name: file.name })}
        aria-current={current ? "true" : undefined}
        onclick={() => onfile(file)}
      >
        {@render row(Icon, displayName(file), description(file, versions.length), current)}
      </Button>
    {:else}
      <div class="flex min-w-0 flex-1 items-center gap-2.5 px-2 py-1.5">
        {@render row(Icon, displayName(file), description(file, versions.length), false)}
      </div>
    {/if}
    <Button
      variant="ghost"
      size="icon-sm"
      class="hover:bg-hover-default"
      {href}
      download={file.name}
      disabled={!href}
      aria-label={m.generated_file_download({ name: file.name })}
      title={m.download()}
    >
      <Download aria-hidden="true" />
    </Button>
  </li>
{/snippet}

{#snippet heading(text: string)}
  <h3 class="text-muted-foreground px-2 pt-2 pb-1 text-xs font-medium">{text}</h3>
{/snippet}

<div class={["p-1", !fullHeight && "max-h-80 overflow-y-auto"]}>
  {#if views.length > 0}
    <section aria-label={m.conversation_documents_views()}>
      {@render heading(m.conversation_documents_views())}
      <ul class="flex flex-col">
        {#each views as view (view.id)}
          <li class="flex">
            <Button
              variant="ghost"
              class={[rowClass, view.shown && currentClass]}
              aria-current={view.shown ? "true" : undefined}
              onclick={() => onview?.(view)}
            >
              {@render row(
                AppWindow,
                view.title,
                view.subject ?? m.mcp_app_view_title(),
                view.shown
              )}
            </Button>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
  {#if documents.length > 0}
    <section aria-label={m.conversation_documents_created()}>
      {@render heading(m.conversation_documents_created())}
      <ul class="flex flex-col">
        {#each documents as document (document.latest.id)}
          {@render entry(document.latest, document.versions)}
        {/each}
      </ul>
    </section>
  {/if}
  {#if uploads.length > 0}
    <section aria-label={m.conversation_documents_uploads()}>
      {@render heading(m.conversation_documents_uploads())}
      <ul class="flex flex-col">
        {#each uploads as file (file.id)}
          {@render entry(file, [file])}
        {/each}
      </ul>
    </section>
  {/if}
</div>
