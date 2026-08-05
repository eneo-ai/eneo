<script lang="ts">
  import * as Resizable from "$lib/components/ui/resizable/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { Snippet } from "svelte";
  import { MediaQuery } from "svelte/reactivity";
  import type { ChatService } from "../../ChatService.svelte";
  import { ChatDebugPanelState } from "./chatDebugPanelState.svelte";
  import ChatDebugSheet from "./ChatDebugSheet.svelte";
  import ChatDebugSidebar from "./ChatDebugSidebar.svelte";
  import ChatDebugTrigger from "./ChatDebugTrigger.svelte";

  let {
    chat,
    available,
    children
  }: {
    chat: ChatService;
    available: boolean;
    children: Snippet<[Snippet]>;
  } = $props();

  // The chat service instance is stable for the lifetime of the page; only
  // its inner state is reactive.
  // svelte-ignore state_referenced_locally
  const panel = new ChatDebugPanelState(chat, () => available);
  // Below lg the split view leaves the conversation unusably narrow, so the
  // panel falls back to a full-width sheet.
  const isDesktop = new MediaQuery("(min-width: 64rem)");
  const inlineOpen = $derived(available && chat.debugPanelOpen && isDesktop.current);
</script>

{#snippet trigger()}
  {#if available}
    <ChatDebugTrigger state={panel} open={chat.debugPanelOpen} />
  {/if}
{/snippet}

<Resizable.PaneGroup direction="horizontal" autoSaveId="chat-debug-layout" class="min-w-0 flex-1">
  <Resizable.Pane order={1} defaultSize={65} minSize={35} class="flex min-w-0 flex-col">
    {@render children(trigger)}
  </Resizable.Pane>
  {#if inlineOpen}
    <Resizable.Handle
      withHandle
      aria-label={m.chat_debug_resize_handle()}
      class="hover:bg-border focus-visible:ring-ring w-1 transition-colors motion-reduce:transition-none"
    />
    <Resizable.Pane
      order={2}
      defaultSize={35}
      minSize={24}
      maxSize={55}
      class="flex min-w-0 flex-col"
    >
      <ChatDebugSidebar {chat} state={panel} />
    </Resizable.Pane>
  {/if}
</Resizable.PaneGroup>

{#if available && !isDesktop.current}
  <ChatDebugSheet {chat} state={panel} />
{/if}
