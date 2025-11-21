<script lang="ts">
  import { browser } from "$app/environment";
  import { goto } from "$app/navigation";
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

  // Replace pushState with goto to trigger proper SvelteKit navigation
  // This ensures the load function re-runs with new tab parameter
  function updateUrl() {
    if (!browser) return;

    // CRITICAL: Create new URL object (don't mutate $page.url)
    const url = new URL($page.url);
    url.searchParams.set("tab", tab);
    // Reset to page 1 when switching tabs to avoid empty results
    url.searchParams.delete("page");

    // goto() triggers real navigation, re-running load function
    goto(url.toString(), {
      replaceState: true,  // Don't add to browser history
      noScroll: true,      // Keep scroll position
      keepFocus: true      // Maintain focus state
    });
  }
</script>

{#if asFragment}
  <slot trigger={[$trigger(tab)]} />
{:else}
  <Button is={[$trigger(tab)]} {padding} {label} on:click={updateUrl} displayActiveState>
    <slot trigger={[$trigger(tab)]} />
  </Button>
{/if}
