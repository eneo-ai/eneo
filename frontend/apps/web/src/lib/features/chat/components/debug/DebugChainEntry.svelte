<!--
  Copyright (c) 2026 Sundsvalls Kommun

  Licensed under the MIT License.

  One entry of the debug panel's message chain: a role-badged card that shows
  a one-line preview when collapsed and the full content when expanded. Tool
  results without inline content are lazily fetched on first expand.
-->

<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { ChevronRight } from "lucide-svelte";

  let {
    role,
    label = null,
    content = null,
    onLoadResult = undefined
  }: {
    role: string;
    /** Extra context next to the badge, e.g. the tool name. */
    label?: string | null;
    content?: string | null;
    /** Lazy source for content that is not inline (persisted tool results). */
    onLoadResult?: () => Promise<string | null>;
  } = $props();

  let open = $state(false);
  let loadedResult = $state<string | null>(null);
  let loading = $state(false);
  let loadAttempted = $state(false);

  const text = $derived(content ?? loadedResult ?? "");
  const preview = $derived(text.replace(/\s+/g, " ").trim());

  const ROLE_STYLES: Record<string, string> = {
    system: "bg-secondary text-secondary border-default",
    user: "bg-accent-dimmer text-accent-stronger border-accent-default/30",
    assistant: "bg-positive-dimmer text-positive-stronger border-positive-default/30",
    tool: "bg-warning-dimmer text-warning-stronger border-warning-default/30"
  };

  async function toggle() {
    open = !open;
    if (!open || content !== null || !onLoadResult || loadAttempted || loading) return;
    loading = true;
    try {
      loadedResult = (await onLoadResult()) ?? "";
    } catch (error) {
      toastError(error, m.mcp_tool_response_load_error());
    } finally {
      loadAttempted = true;
      loading = false;
    }
  }
</script>

<div class="border-dimmer rounded-md border">
  <button
    type="button"
    class="flex w-full items-center gap-1.5 px-2 py-1.5 text-left"
    onclick={toggle}
    aria-expanded={open}
  >
    <ChevronRight
      class="text-muted h-3 w-3 shrink-0 transition-transform {open ? 'rotate-90' : ''}"
    />
    <span
      class="shrink-0 rounded-full border px-1.5 py-0.5 font-mono text-[10px] leading-none {ROLE_STYLES[
        role
      ] ?? 'bg-secondary text-secondary border-default'}"
    >
      {role}
    </span>
    {#if label}
      <span class="text-default shrink-0 truncate text-xs font-medium">{label}</span>
    {/if}
    {#if !open && preview}
      <span class="text-muted min-w-0 truncate text-xs">{preview}</span>
    {/if}
  </button>
  {#if open}
    <div class="border-dimmer border-t px-2 py-1.5">
      {#if loading}
        <p class="text-muted text-xs">{m.debug_panel_result_loading()}</p>
      {:else if text}
        <pre
          class="bg-secondary/40 max-h-96 overflow-auto rounded-md p-2 text-xs break-words whitespace-pre-wrap">{text}</pre>
      {:else}
        <p class="text-muted text-xs">{m.debug_panel_empty_section()}</p>
      {/if}
    </div>
  {/if}
</div>
