<script lang="ts">
  import type { SvelteHTMLElements } from "svelte/elements";
  import { m } from "$lib/paraglide/messages";
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- $$Props is a Svelte compiler convention for typing $$restProps
  type $$Props = SvelteHTMLElements["div"];
</script>

<div
  role="img"
  aria-label={m.eneo_icon()}
  class="cursor-default font-bold select-none"
  style="font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; font-size: 16px; color: #4f46e5;"
  {...$$restProps}
>
  E
</div>
