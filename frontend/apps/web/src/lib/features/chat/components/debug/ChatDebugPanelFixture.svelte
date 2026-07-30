<script lang="ts">
  import type { ChatService } from "../../ChatService.svelte";
  import ChatDebugPanel from "./ChatDebugPanel.svelte";

  // Test-only fixture: mirrors how the chat page composes the debug panel
  // around its content (trigger in the header, conversation in the pane).
  let { chat, available }: { chat: ChatService; available: boolean } = $props();
</script>

<div class="flex h-svh w-full">
  <ChatDebugPanel {chat} {available}>
    {#snippet children(debugTrigger)}
      <div class="flex min-w-0 flex-1 flex-col">
        <header class="flex justify-end p-2">
          {@render debugTrigger()}
        </header>
        <!-- eslint-disable eneo/no-hardcoded-text -- test-only fixture -->
        <main class="flex-1">
          conversation
          <label>
            composer
            <input type="text" />
          </label>
        </main>
        <!-- eslint-enable eneo/no-hardcoded-text -->
      </div>
    {/snippet}
  </ChatDebugPanel>
</div>
