<script lang="ts">
  import { dynamicColour } from "$lib/core/colours";
  import { getAppContext } from "$lib/core/AppContext";

  export let app: { id: string; name: string; icon_id?: string | null };
  export let size: "medium" | "large" = "large";

  const { environment } = getAppContext();

  // Generate icon URL from icon_id
  $: iconUrl = app.icon_id
    ? `${environment.baseUrl}/api/v1/icons/${app.icon_id}/`
    : null;
</script>

<div
  {...dynamicColour({ basedOn: app.id })}
  class="{size} app-icon border-dynamic-default text-dynamic-stronger pointer-events-none w-fit rounded-[2rem] border"
>
  <div class="flex items-center justify-center overflow-hidden" class:bg-[var(--dynamic-transparent)]={!iconUrl} class:font-mono={!iconUrl} class:font-bold={!iconUrl}>
    {#if iconUrl}
      <img src={iconUrl} alt={app.name} class="h-full w-full rounded-xl object-cover" />
    {:else}
      {[...app.name][0]}
    {/if}
  </div>
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";
  div {
    --dynamic-transparent: oklch(from var(--dynamic-default) l c h / 8%);
  }
  .large {
    @apply mx-4 rounded-[2rem] border-b-4 p-2;
  }
  .large div {
    @apply h-24 w-24 min-h-24 min-w-24 max-h-24 max-w-24 rounded-[1.5rem] text-[2.6rem];
  }
  .medium {
    @apply rounded-[0.9rem] border-b-4 p-1;
  }
  .medium div {
    @apply h-12 w-12 min-h-12 min-w-12 max-h-12 max-w-12 rounded-[0.7rem] text-[1.8rem];
  }
  .app-icon {
    box-shadow:
      0px 8px 30px -5px rgb(from var(--dynamic-default) r g b / 20%),
      0px 8px 20px -10px rgb(from var(--dynamic-default) r g b / 50%);
    background: linear-gradient(
      0deg,
      var(--background-primary) 0%,
      var(--dynamic-transparent) 100%
    );
  }
</style>
