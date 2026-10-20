<!--
  Copyright (c) 2026 Sundsvalls Kommun

  A call to one of Eneo's built-in tools, rendered with a thinking-like
  footprint instead of a tool card: a shimmer line while running ("Söker
  kunskap…"), collapsing to a muted past-tense line when done ("Sökte i
  kunskap"). Both states expand to the call's parameters on click; the result
  joins the panel once the call completes. External MCP tools keep their
  ReasoningToolStep cards.

  A function step (a capability call: chart, file analysis, web search) carries
  the function's icon on a chip, so it reads as work done rather than as a
  lookup; a context step (knowledge, files) carries none.

  A call that created a document names it instead ("Skapade Införandeplan")
  and opens it beside the conversation: the step is the document's place in
  the chat, so an answer carries no file card for it. A call whose result has
  a view the panel can show names that view the same way and opens it.
-->
<script lang="ts">
  import { sanitizeLinkHref } from "$lib/components/markdown/index.js";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import { getFilePreview, type PreviewDraft } from "$lib/features/file-preview/FilePreview.svelte";
  import { previewKindOf } from "$lib/features/file-preview/previewKind";
  import type { CapabilityDescriptor } from "$lib/features/mcp/capabilities";
  import { m } from "$lib/paraglide/messages";
  import { AppWindow, ChevronRight, Download, FileText, X } from "@lucide/svelte";
  import type { GeneratedDocument } from "../../documentVersions";
  import ShimmerText from "./ShimmerText.svelte";
  import ToolCallDetailsPanel from "./ToolCallDetailsPanel.svelte";
  import ToolStepIcon from "./ToolStepIcon.svelte";

  import type { ToolStepStatus as Status } from "../../toolStepStatus";

  let {
    runningLabel,
    doneLabel,
    serverName,
    identity = null,
    detail = null,
    args,
    toolCallId,
    onLoadResult,
    status,
    previousAttempt = false,
    document = null,
    icon = null,
    view = null,
    draft = null
  }: {
    /** Present-tense label without ellipsis, e.g. "Söker kunskap". */
    runningLabel: string;
    /** Past-tense label, e.g. "Sökte i kunskap". */
    doneLabel: string;
    /** Localized server label ("Kunskap"), used in the result heading. */
    serverName: string;
    /** The call as the model made it, "server · tool", shown in the expanded panel. */
    identity?: string | null;
    /** Extra context for the call, e.g. a filename or search query. */
    detail?: string | null;
    args?: Record<string, unknown>;
    toolCallId?: string;
    onLoadResult?: () => Promise<string | null>;
    status: Status;
    /** A failed call the reply may still correct, or one a later success from this tool followed. */
    previousAttempt?: boolean;
    /**
     * The document the call created. `label` is the step's text around the
     * document's name ("Skapade {name}"); without one the name follows
     * `doneLabel` as its detail.
     */
    document?: { file: GeneratedDocument; label?: (name: string) => string } | null;
    /** The function's icon for a function step; null for a context step. */
    icon?: CapabilityDescriptor["icon"] | null;
    /** The view of the call's result that the panel can show, named and opened from the step. */
    view?: { name: string; open: () => void } | null;
    /** The document the running call is writing, which the step shows in the panel on click. */
    draft?: PreviewDraft | null;
  } = $props();

  const preview = getFilePreview();
  const attachmentUrls = getAttachmentUrlService();

  let open = $state(false);
  const isActive = $derived(
    status === "preparing" || status === "awaiting" || status === "running"
  );
  const isPreviousAttempt = $derived(status === "failed" && previousAttempt);
  const isNegative = $derived((status === "failed" && !isPreviousAttempt) || status === "denied");
  const hasArgs = $derived(args != null && Object.keys(args).length > 0);
  const canViewResult = $derived(
    !!toolCallId && !!onLoadResult && (status === "complete" || status === "failed")
  );
  // A document being written is shown in the panel instead of as parameters.
  const writing = $derived(isActive && !!preview && draft ? draft : null);
  // The parameters are known as soon as the model has written them, so a
  // running call (a long image generation, say) already opens to its prompt.
  const canExpand = $derived(!writing && (hasArgs || canViewResult));

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
  // A finished call with a view is shown by that view, like a document.
  const shownView = $derived(!file && status === "complete" ? view : null);
</script>

{#snippet documentLine()}
  <ToolStepIcon icon={FileText} class={previewing ? "text-accent-stronger" : ""} />
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
        class="text-muted hover:text-secondary focus-visible:ring-accent-default flex w-fit min-w-0 items-center gap-2 rounded-sm text-left transition-colors focus-visible:ring-2 focus-visible:outline-none"
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
        class="text-muted hover:text-secondary focus-visible:ring-accent-default flex w-fit min-w-0 items-center gap-2 rounded-sm no-underline transition-colors focus-visible:ring-2 focus-visible:outline-none {href
          ? ''
          : 'pointer-events-none opacity-60'}"
      >
        {@render documentLine()}
        <Download class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      </a>
    {/if}
  </div>
  <!-- eslint-enable svelte/no-navigation-without-resolve -->
{:else if shownView}
  <!-- The step is the view's place in the chat: its name opens the view beside the conversation. -->
  <button
    type="button"
    class="text-muted hover:text-secondary focus-visible:ring-accent-default flex w-fit max-w-full items-center gap-2 rounded-sm text-left text-sm leading-tight transition-colors focus-visible:ring-2 focus-visible:outline-none"
    aria-label={m.tool_step_open_view({ name: shownView.name })}
    onclick={shownView.open}
  >
    {#if icon}
      <ToolStepIcon {icon} />
    {/if}
    <span class="truncate">
      {doneLabel} <span class="text-default font-medium">{shownView.name}</span>
    </span>
    {#if detail}
      <span class="text-muted min-w-0 max-w-full truncate text-xs opacity-70" title={detail}
        >{detail}</span
      >
    {/if}
    <AppWindow class="text-muted h-3.5 w-3.5 shrink-0" aria-hidden="true" />
  </button>
{:else}
  <div role={isActive ? "status" : undefined} aria-label={isActive ? runningLabel : undefined}>
    <button
      type="button"
      class="group focus-visible:ring-accent-default flex w-fit max-w-full items-start justify-start gap-2 rounded-sm text-left text-sm leading-tight transition-colors focus-visible:ring-2 focus-visible:outline-none {isActive
        ? ''
        : 'text-muted hover:text-secondary'} {canExpand || writing
        ? 'cursor-pointer'
        : 'cursor-default'}"
      onclick={() => {
        if (writing) preview?.showDraft(writing);
        else if (canExpand) open = !open;
      }}
      disabled={!canExpand && !writing}
      aria-expanded={writing ? undefined : open}
      aria-label={writing
        ? m.tool_step_show_draft({ name: writing.title || runningLabel })
        : undefined}
    >
      {#if icon}
        <!-- The chip carries the failure, so no bare cross precedes the text. -->
        <ToolStepIcon {icon} tone={isNegative ? "negative" : "default"} class="-mt-px" />
      {:else if isNegative}
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
      {identity}
      {args}
      {toolCallId}
      {onLoadResult}
      {status}
      containerClass="border-dimmer bg-secondary/40 mt-1 mb-1 rounded-lg border px-3 py-2.5"
    />
  </div>
{/if}
