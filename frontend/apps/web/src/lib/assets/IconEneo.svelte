<script lang="ts">
  import type { SvelteHTMLElements } from "svelte/elements";
  import { m } from "$lib/paraglide/messages";
  type $$Props = SvelteHTMLElements["div"];
</script>

<div 
  role="img" 
  aria-label={m.eneo_icon()}
  class="font-bold select-none cursor-default"
  style="font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; font-size: 16px; color: #4f46e5;"
  {...$$restProps}
>
  E
</div>