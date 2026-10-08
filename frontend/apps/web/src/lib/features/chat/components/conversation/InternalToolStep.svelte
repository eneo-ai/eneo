<!--
  Copyright (c) 2026 Sundsvalls Kommun

  A call to one of Eneo's built-in loopback tools, rendered with a thinking-
  like footprint instead of a tool card: a shimmer line while running
  ("Söker kunskap…"), collapsing to a muted past-tense line when done
  ("Sökte i kunskap"). Both states expand to the call's parameters on click;
  the result joins the panel once the call completes. External MCP tools keep
  their ReasoningToolStep cards.

  A call that created a document names it instead ("Skapade Införandeplan")
  and opens it beside the conversation: the step is the document's place in
  the chat, so an answer carries no file card for it.
-->
<script lang="ts">
  import { sanitizeLinkHref } from "$lib/components/markdown/index.js";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import { getFilePreview } from "$lib/features/file-preview/FilePreview.svelte";
  import { previewKindOf } from "$lib/features/file-preview/previewKind";
  import { m } from "$lib/paraglide/messages";
  import { ChevronRight, Download, FileText, X } from "@lucide/svelte";
  import type { GeneratedDocument } from "../../documentVersions";
  import ShimmerText from "./ShimmerText.svelte";
  import ToolCallDetailsPanel from "./ToolCallDetailsPanel.svelte";

  type Status = "preparing" | "running" | "complete" | "failed" | "denied";

  let {
    runningLabel,
    doneLabel,
    serverName,
    detail = null,
    args,
    toolCallId,
    onLoadResult,
    status,
    previousAttempt = false,
    document = null
  }: {
    /** Present-tense label without ellipsis, e.g. "Söker kunskap". */
    runningLabel: string;
    /** Past-tense label, e.g. "Sökte i kunskap". */
    doneLabel: string;
    /** Localized server label ("Kunskap"), used in the result heading. */
    serverName: string;
    /** Extra context for the call, e.g. a filename or search query. */
    detail?: string | null;
    args?: Record<string, unknown>;
    toolCallId?: string;
    onLoadResult?: () => Promise<string | null>;
    status: Status;
    /** An earlier failed call followed by a success from this tool. */
    previousAttempt?: boolean;
    /**
     * The document the call created. `label` is the step's text around the
     * document's name ("Skapade {name}"); without one the name follows
     * `doneLabel` as its detail.
     */
    document?: { file: GeneratedDocument; label?: (name: string) => string } | null;
  } = $props();

  const preview = getFilePreview();
  const attachmentUrls = getAttachmentUrlService();

  let open = $state(false);
  const isActive = $derived(status === "preparing" || status === "running");
  const isPreviousAttempt = $derived(status === "failed" && previousAttempt);
  const isNegative = $derived((status === "failed" && !isPreviousAttempt) || status === "denied");
  const hasArgs = $derived(args != null && Object.keys(args).length > 0);
  const canViewResult = $derived(
    !!toolCallId && !!onLoadResult && (status === "complete" || status === "failed")
  );
  // The parameters are known as soon as the model has written them, so a
  // running call (a long image generation, say) already opens to its prompt.
  const canExpand = $derived(hasArgs || canViewResult);

  const file = $derived(status === "complete" ? (document?.file ?? null) : null);
  const kind = $derived(file ? previewKindOf(file) : null);
  const previewable = $derived(!!preview && kind !== null);
  const previewing = $derived(!!file && (preview?.isOpen(file) ?? false));
  // A Markdown document is read in Eneo and shown by its title; any other
  // file keeps its full name and offers the download it was made for.
  const fileName = $derived(
    file ? (kind === "markdown" ? file.name.replace(/\.(md|markdown)$/i, "") : file.name) : ""
  );
  const downloads = $derived(!!file && (!previewable || kind !== "markdown"));
  const href = $derived(
    file && downloads ? sanitizeLinkHref(attachmentUrls.getOriginalUrl(file) ?? null) : null
  );
  // The words around the name, split so the name can be set apart.
  const NAME = "\u0000";
  const [beforeName, afterName] = $derived(
    document?.label ? document.label(NAME).split(NAME) : [`${doneLabel} `, ""]
  );
</script>

{#snippet documentLine()}
  <FileText
    class="h-3.5 w-3.5 shrink-0 {previewing ? 'text-accent-stronger' : ''}"
    aria-hidden="true"
  />
  <span class="truncate">
    {beforeName}<span class="font-medium {previewing ? 'text-accent-stronger' : 'text-default'}"
      >{fileName}</span
    >{afterName}
  </span>
{/snippet}

{#if file}
  {#if detail}
    <p class="text-muted text-left text-sm">{doneLabel} · {detail}</p>
  {/if}
  <!-- eslint-disable svelte/no-navigation-without-resolve -- signed file URL -->
  <div class="flex max-w-full items-center gap-2 text-sm leading-tight">
    {#if previewable}
      <button
        type="button"
        class="text-muted hover:text-secondary focus-visible:ring-accent-default flex w-fit min-w-0 items-center gap-1.5 rounded-sm text-left transition-colors focus-visible:ring-2 focus-visible:outline-none"
        aria-expanded={previewing}
        onclick={(event) => preview?.toggle(file, event.currentTarget)}
      >
        {@render documentLine()}
      </button>
      {#if downloads}
        <a
          href={href ?? undefined}
          download={file.name}
          aria-label={m.generated_file_download({ name: file.name })}
          aria-disabled={href ? undefined : "true"}
          class="border-default text-secondary hover:bg-secondary hover:text-default focus-visible:ring-accent-default flex h-6 shrink-0 items-center gap-1 rounded-md border px-2 text-xs font-medium no-underline transition-colors focus-visible:ring-2 focus-visible:outline-none {href
            ? ''
            : 'pointer-events-none opacity-60'}"
        >
          <Download class="size-3" aria-hidden="true" />
          {m.download()}
        </a>
      {/if}
    {:else}
      <!-- Nothing to preview (or no panel to preview in): the step is the download. -->
      <a
        href={href ?? undefined}
        download={file.name}
        aria-label={m.generated_file_download({ name: file.name })}
        aria-disabled={href ? undefined : "true"}
        class="text-muted hover:text-secondary focus-visible:ring-accent-default flex w-fit min-w-0 items-center gap-1.5 rounded-sm no-underline transition-colors focus-visible:ring-2 focus-visible:outline-none {href
          ? ''
          : 'pointer-events-none opacity-60'}"
      >
        {@render documentLine()}
        <Download class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      </a>
    {/if}
  </div>
  <!-- eslint-enable svelte/no-navigation-without-resolve -->
{:else}
  <div role={isActive ? "status" : undefined} aria-label={isActive ? runningLabel : undefined}>
    <button
      type="button"
      class="group flex w-fit max-w-full items-start justify-start gap-1.5 text-left text-sm leading-tight transition-colors {isActive
        ? ''
        : 'text-muted hover:text-secondary'} {canExpand ? 'cursor-pointer' : 'cursor-default'}"
      onclick={() => {
        if (canExpand) open = !open;
      }}
      disabled={!canExpand}
      aria-expanded={open}
    >
      {#if isNegative}
        <X class="text-negative-default mt-0.5 h-3.5 w-3.5 shrink-0" />
      {/if}
      <span class="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span class="min-w-0 max-w-full text-left">
          {#if isActive}
            <ShimmerText text={`${runningLabel}…`} />
          {:else}
            {isPreviousAttempt
              ? m.chat_tool_previous_attempt({ tool: serverName })
              : isNegative
                ? runningLabel
                : doneLabel}
          {/if}
        </span>
        {#if detail}
          <span
            class="text-muted min-w-0 max-w-full truncate text-xs {isActive ? '' : 'opacity-70'}"
            title={detail}>{detail}</span
          >
        {/if}
        {#if isNegative}
          <span class="text-negative-default text-xs">
            {status === "denied" ? m.tool_rejected_by_user() : m.chat_tool_status_failed()}
          </span>
        {/if}
      </span>
      {#if canExpand}
        <ChevronRight
          class="text-muted mt-0.5 h-3.5 w-3.5 shrink-0 transition-transform {open
            ? 'rotate-90 opacity-100'
            : 'opacity-0 group-hover:opacity-100'}"
        />
      {/if}
    </button>

    <ToolCallDetailsPanel
      {open}
      toolName={serverName}
      {args}
      {toolCallId}
      {onLoadResult}
      {status}
      containerClass="border-dimmer bg-secondary/40 mt-1 mb-1 rounded-lg border px-3 py-2.5"
    />
  </div>
{/if}
