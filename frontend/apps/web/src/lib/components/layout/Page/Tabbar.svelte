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
  class="text-primary left-[50%] flex min-w-0 flex-grow items-center justify-center gap-2 overflow-x-auto pr-3 max-lg:order-2 max-lg:w-full max-lg:flex-none max-lg:justify-start @4xl:lg:absolute @4xl:lg:-translate-x-[50%]"
  aria-label={m.main_views_available_for_current_resource()}
>
  <slot />
</div>
