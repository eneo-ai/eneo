<script lang="ts">
  import { browser } from "$app/environment";
  import { replaceState } from "$app/navigation";
  import { page } from "$app/stores";
  import { getContentTabs } from "./ctx";
  import { Button } from "@intric/ui";

  export let tab: string;
  export let padding: "icon-leading" | "text" = "text";
  export let label: string | undefined = undefined;
  export let asFragment = false;

  const {
    elements: { trigger }
  } = getContentTabs();

  function updateUrl() {
    if (!browser) return;

    // Create new URL object (don't mutate $page.url)
    const url = new URL($page.url);
    url.searchParams.set("tab", tab);
    // Reset to page 1 when switching tabs to avoid empty results
    url.searchParams.delete("page");

    // replaceState updates the URL without triggering SvelteKit navigation,
    // so tab switching is instant (no load functions re-run)
    replaceState(url, { ...$page.state, tab });
  }
</script>

{#if asFragment}
  <slot trigger={[$trigger(tab)]} />
{:else}
  <Button is={[$trigger(tab)]} {padding} {label} on:click={updateUrl} displayActiveState>
    <slot trigger={[$trigger(tab)]} />
  </Button>
{/if}
