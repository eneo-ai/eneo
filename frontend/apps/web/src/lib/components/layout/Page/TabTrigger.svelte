<script lang="ts">
  import { browser } from "$app/environment";
  import { replaceState } from "$app/navigation";
  import { page } from "$app/stores";
  import { getContentTabs } from "./ctx";
  import { Button } from "@eneo/ui";

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
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic URL with mutated query params
    replaceState(url, { ...$page.state, tab });
  }
</script>

{#if asFragment}
  <slot trigger={[$trigger(tab)]} />
{:else}
  <!-- `unstyled` replaces the generic button recipe, so focus styling is set here. -->
  <Button
    is={[$trigger(tab)]}
    unstyled
    {label}
    class="text-secondary hover:text-primary focus-visible:outline-ring data-[state=active]:bg-primary data-[state=active]:text-primary inline-flex items-center justify-center gap-1.5 rounded-md {padding ===
    'icon-leading'
      ? 'py-1 pr-3 pl-1.5'
      : 'px-3 py-1'} text-sm font-medium whitespace-nowrap transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 data-[state=active]:shadow-sm"
    on:click={updateUrl}
  >
    <slot trigger={[$trigger(tab)]} />
  </Button>
{/if}
