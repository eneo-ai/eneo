<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import Check from "@lucide/svelte/icons/check";
  import Copy from "@lucide/svelte/icons/copy";

  let { label, value }: { label: string; value: string } = $props();
  let copied = $state(false);

  async function copyValue() {
    if (!navigator.clipboard) return;
    await navigator.clipboard.writeText(value);
    copied = true;
  }
</script>

<div class="min-w-0">
  <dt class="text-muted-foreground text-xs">{label}</dt>
  <dd class="mt-0.5 flex min-w-0 items-start gap-1">
    <code class="min-w-0 flex-1 break-all text-xs leading-5 font-medium">{value}</code>
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label={m.chat_debug_copy_value({ label })}
      onclick={copyValue}
    >
      {#if copied}
        <Check aria-hidden="true" />
      {:else}
        <Copy aria-hidden="true" />
      {/if}
    </Button>
  </dd>
</div>
