<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import ArrowLeft from "@lucide/svelte/icons/arrow-left";

  let { onclick }: { onclick: () => void } = $props();
</script>

<Button
  variant="ghost"
  size="icon"
  aria-label={m.conversation_panel_back()}
  title={m.conversation_panel_back()}
  {onclick}
>
  <ArrowLeft class="size-4" aria-hidden="true" />
</Button>
