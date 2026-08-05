<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import Bug from "@lucide/svelte/icons/bug";
  import X from "@lucide/svelte/icons/x";
  import type { ChatService } from "../../ChatService.svelte";
  import type { ChatDebugPanelState } from "./chatDebugPanelState.svelte";
  import ChatDebugPanelContent from "./ChatDebugPanelContent.svelte";

  let { chat, state: panel }: { chat: ChatService; state: ChatDebugPanelState } = $props();

  let container = $state<HTMLElement | null>(null);

  $effect(() => {
    // Move focus into the panel when it opens so keyboard users land where
    // the new content is; the trigger keeps focus via close().
    container?.focus();
  });

  function close() {
    panel.setOpen(false);
    document.getElementById("chat-debug-trigger")?.focus();
  }

  function onDocumentKeydown(event: KeyboardEvent) {
    // Mirror dialog dismissal: Escape closes the panel when focus is inside
    // it, or when no control holds focus (for example after a clicked button
    // unmounted). Open popovers and menus consume Escape first and prevent
    // default, and Escape pressed inside the chat composer stays there.
    if (event.key !== "Escape" || event.defaultPrevented) return;
    const active = document.activeElement;
    const insidePanel = container?.contains(active) ?? false;
    const unfocused = !active || active === document.body;
    if (!insidePanel && !unfocused) return;
    event.preventDefault();
    close();
  }
</script>

<svelte:document onkeydown={onDocumentKeydown} />

<aside
  bind:this={container}
  id="chat-debug-panel"
  aria-label={m.chat_debug_title()}
  tabindex="-1"
  class="bg-background flex h-full min-h-0 flex-col focus-visible:outline-none"
>
  <header class="border-border flex items-start justify-between gap-3 border-b px-5 py-4">
    <div class="flex min-w-0 flex-col gap-1">
      <h2 class="flex items-center gap-2 text-base font-semibold">
        <Bug aria-hidden="true" class="size-4" />
        {m.chat_debug_title()}
      </h2>
      <p class="text-muted-foreground max-w-[54ch] text-sm leading-5">
        {m.chat_debug_description()}
      </p>
    </div>
    <Button variant="ghost" size="icon-sm" aria-label={m.close()} onclick={close}>
      <X aria-hidden="true" />
    </Button>
  </header>

  <ChatDebugPanelContent {chat} state={panel} idPrefix="chat-debug-sidebar" />
</aside>
