<!--
  A security classification as static text: name and level, readable without
  the icon or colour. Not a live region.
-->
<script lang="ts">
  import { ShieldCheck } from "@lucide/svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils.js";

  type Props = {
    classification: { name: string; security_level: number };
    /**
     * Prefix "Säkerhetsklassificering:" for screen readers, where no column
     * header or term already says what the badge is.
     */
    labelled?: boolean;
    class?: string;
  };

  let { classification, labelled = false, class: className }: Props = $props();
</script>

<Badge
  variant="outline"
  class={cn("h-auto min-h-5 max-w-full text-left whitespace-normal", className)}
>
  <ShieldCheck class="shrink-0" aria-hidden="true" />
  <span class="min-w-0 break-words">
    {#if labelled}<span class="sr-only">{m.security_classification()}:</span>{/if}
    {classification.name}
    <span aria-hidden="true">·</span>
    <span class="text-secondary"
      >{m.security_classification_badge_level({ level: classification.security_level })}</span
    >
  </span>
</Badge>
