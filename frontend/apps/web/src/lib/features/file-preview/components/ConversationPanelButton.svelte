<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import PanelRightOpen from "@lucide/svelte/icons/panel-right-open";
  let {
    panelId,
    ref = $bindable(null),
    onopen
  }: {
    panelId: string;
    ref?: HTMLButtonElement | null;
    onopen: () => void;
  } = $props();
</script>

<Button
  bind:ref
  variant="ghost"
  class="text-muted-foreground hover:text-foreground gap-2"
  aria-label={m.conversation_panel_open()}
  aria-expanded={false}
  aria-controls={panelId}
  onclick={onopen}
>
  <PanelRightOpen class="size-4" aria-hidden="true" />
  <span>{m.conversation_panel_title()}</span>
</Button>
