<script lang="ts">
  import type { Snippet } from "svelte";
  import { dynamicColour } from "$lib/core/colours";

  type Props = {
    href: string;
    name: string;
    /** Seeds the tile's colour. */
    id: string;
    icon: Snippet;
    actions: Snippet;
  };

  let { href, name, id, icon, actions }: Props = $props();
</script>

<!-- eslint-disable svelte/no-navigation-without-resolve -- callers build the dynamic href -->
<a
  aria-label={name}
  {...dynamicColour({ basedOn: id })}
  {href}
  class="group border-dynamic-default bg-dynamic-dimmer text-dynamic-stronger hover:bg-dynamic-default hover:text-on-fill relative flex aspect-square flex-col items-start gap-2 border-t p-2 px-4"
>
  <h2 class="line-clamp-2 pt-1 font-mono text-sm">
    {name}
  </h2>

  <div class="hover:text-primary absolute right-2 bottom-2">
    {@render actions()}
  </div>

  <span
    class="group-hover:text-on-fill pointer-events-none absolute inset-0 flex items-center justify-center font-mono text-[4.5rem]"
  >
    {@render icon()}
  </span>

  <div class="flex-grow"></div>
</a>
<!-- eslint-enable svelte/no-navigation-without-resolve -->
