<script lang="ts">
  import { getContentTabs } from "./ctx";
  import { m } from "$lib/paraglide/messages";

  const {
    elements: { list }
  } = getContentTabs();
</script>

<div
  {...$list}
  use:list
  class="text-primary flex min-w-0 shrink flex-grow items-center justify-center gap-2 pr-3"
  aria-label={m.main_views_available_for_current_resource()}
>
  <slot />
</div>
