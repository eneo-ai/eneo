<script lang="ts">
  import type { SvelteHTMLElements } from "svelte/elements";
  import { m } from "$lib/paraglide/messages";

  /* eslint-disable @typescript-eslint/no-unused-vars */
  type $$Props = SvelteHTMLElements["svg"];
</script>

<svg
  xmlns="http://www.w3.org/2000/svg"
  fill="currentColor"
  role="img"
  aria-label={m.intric_logo()}
  viewBox="0 0 46.51 46.51"
  {...$$restProps}
  ><path
    d="M0 31.43h15.09v15.09H0zM30.17 31.43h15.09v15.09H30.17zM33.51 16.34h4.83c4.51 0 8.17-3.66 8.17-8.17S42.85 0 38.34 0s-8.17 3.66-8.17 8.17V13a3.34 3.34 0 0 1-3.34 3.34H15.08v15.09h15.09V19.68a3.34 3.34 0 0 1 3.34-3.34Z"
  /><path d="M0 1.26h15.09v15.09H0z" /></svg
>
