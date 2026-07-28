<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import Bug from "@lucide/svelte/icons/bug";
  import type { ChatDebugPanelState } from "./chatDebugPanelState.svelte";

  let { state: panel, open }: { state: ChatDebugPanelState; open: boolean } = $props();
</script>

<Button
  id="chat-debug-trigger"
  variant={open ? "secondary" : "outline"}
  aria-expanded={open}
  aria-controls="chat-debug-panel"
  onclick={() => panel.setOpen(!open)}
>
  <Bug data-icon="inline-start" aria-hidden="true" />
  {m.chat_debug_open()}
</Button>
