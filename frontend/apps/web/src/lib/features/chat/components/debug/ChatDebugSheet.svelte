<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Sheet from "$lib/components/ui/sheet/index.js";
  import { m } from "$lib/paraglide/messages";
  import Bug from "@lucide/svelte/icons/bug";
  import X from "@lucide/svelte/icons/x";
  import type { ChatService } from "../../ChatService.svelte";
  import type { ChatDebugPanelState } from "./chatDebugPanelState.svelte";
  import ChatDebugPanelContent from "./ChatDebugPanelContent.svelte";

  let { chat, state: panel }: { chat: ChatService; state: ChatDebugPanelState } = $props();
</script>

<Sheet.Root open={chat.debugPanelOpen} onOpenChange={(open) => panel.setOpen(open)}>
  <Sheet.Content
    id="chat-debug-panel"
    class="w-full max-w-full gap-0 p-0 sm:max-w-[36rem]"
    showCloseButton={false}
  >
    <Sheet.Header class="border-border gap-1 border-b px-5 py-4 pr-14">
      <Sheet.Title class="flex items-center gap-2 text-base font-semibold">
        <Bug aria-hidden="true" class="size-4" />
        {m.chat_debug_title()}
      </Sheet.Title>
      <Sheet.Description class="max-w-[54ch] leading-5">
        {m.chat_debug_description()}
      </Sheet.Description>
      <Sheet.Close>
        {#snippet child({ props })}
          <Button
            {...props}
            class="absolute top-3 right-3"
            variant="ghost"
            size="icon-sm"
            aria-label={m.close()}
          >
            <X aria-hidden="true" />
          </Button>
        {/snippet}
      </Sheet.Close>
    </Sheet.Header>

    <ChatDebugPanelContent {chat} state={panel} idPrefix="chat-debug-sheet" />
  </Sheet.Content>
</Sheet.Root>
