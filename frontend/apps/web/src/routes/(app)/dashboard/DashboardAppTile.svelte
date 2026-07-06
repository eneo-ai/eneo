<script lang="ts">
  import { IconApp } from "@eneo/icons/app";
  import type { AppSparse } from "@eneo/eneo-js";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { m } from "$lib/paraglide/messages";

  export let app: AppSparse;
</script>

<!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing -->
<a
  aria-label={app.name}
  href={localizeHref(`/dashboard/app/${app.id}`)}
  class="group border-default bg-dimmer text-stronger hover:bg-default hover:text-on-fill relative flex aspect-square flex-col items-start gap-2 border-t p-2 px-4"
>
  <h2 class="line-clamp-2 pt-1 font-mono text-sm">
    {m.dashboard_app_tile_label({ name: app.name })}
  </h2>

  <span
    class="group-hover:text-on-fill pointer-events-none absolute inset-0 flex items-center justify-center"
  >
    <IconApp class="h-16 w-16" />
  </span>

  <div class="flex-grow"></div>
</a>
<!-- eslint-enable svelte/no-navigation-without-resolve -->
