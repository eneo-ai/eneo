<script lang="ts">
  import CopyButton from "$lib/components/CopyButton.svelte";
  import { m } from "$lib/paraglide/messages";

  let { label, value }: { label: string; value: string } = $props();
</script>

<div class="min-w-0">
  <dt class="text-muted-foreground text-xs">{label}</dt>
  <dd class="mt-0.5 flex min-w-0 items-center gap-1">
    <code class="min-w-0 flex-1 truncate font-mono text-sm leading-5 font-medium" title={value}>
      {value}
    </code>
    <CopyButton text={value} label={m.chat_debug_copy_value({ label })} size="icon-sm" />
  </dd>
</div>
