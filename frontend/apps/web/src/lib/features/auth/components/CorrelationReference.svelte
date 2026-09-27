<script lang="ts">
  import CopyButton from "$lib/components/CopyButton.svelte";
  import { m } from "$lib/paraglide/messages";

  let { correlationId }: { correlationId: string } = $props();
</script>

<div class="mt-3 border-t border-current/25 pt-3 text-xs">
  <p>{m.oidc_correlation_hint()}</p>
  <div class="mt-1 flex items-center gap-2">
    <code class="font-mono break-all select-all">{correlationId}</code>
    <CopyButton
      text={correlationId}
      label={m.copy_correlation_id()}
      size="icon-sm"
      class="shrink-0 text-current hover:bg-current/10 hover:text-current"
    />
  </div>
</div>
