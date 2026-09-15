<script lang="ts">
  import { onDestroy } from "svelte";
  import { Check, Copy } from "lucide-svelte";
  import { Button } from "$lib/components/ui/button";
  import { m } from "$lib/paraglide/messages";

  let { correlationId }: { correlationId: string } = $props();

  let copied = $state(false);
  let resetTimer: ReturnType<typeof setTimeout> | undefined;

  async function copy() {
    try {
      await navigator.clipboard.writeText(correlationId);
    } catch {
      // Clipboard API unavailable (insecure context / permissions): the ID stays selectable.
      return;
    }
    copied = true;
    clearTimeout(resetTimer);
    resetTimer = setTimeout(() => (copied = false), 2000);
  }

  onDestroy(() => clearTimeout(resetTimer));
</script>

<div class="mt-3 border-t border-current/25 pt-3 text-xs">
  <p>{m.oidc_correlation_hint()}</p>
  <div class="mt-1 flex items-center gap-2">
    <code class="font-mono break-all select-all">{correlationId}</code>
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      class="shrink-0 text-current hover:bg-current/10 hover:text-current"
      aria-label={m.copy_correlation_id()}
      onclick={copy}
    >
      {#if copied}
        <Check aria-hidden="true" />
      {:else}
        <Copy aria-hidden="true" />
      {/if}
    </Button>
    <span class="sr-only" aria-live="polite">{copied ? m.copied_to_clipboard() : ""}</span>
  </div>
</div>
