<script lang="ts">
  import { untrack } from "svelte";
  import { get, writable, type Writable } from "svelte/store";
  import { Tabs } from "bits-ui";
  import { browser } from "$app/environment";
  import { replaceState } from "$app/navigation";
  import { page } from "$app/state";
  import { createContentTabs } from "./ctx";

  type Props = {
    tabController?: Writable<string> | undefined;
    onTabChange?: ((args: { curr: string; next: string }) => string) | undefined;
    children?: import("svelte").Snippet;
  };

  let { tabController = writable(), onTabChange = undefined, children }: Props = $props();

  untrack(() => {
    const initialTab = page.state.tab ?? page.url.searchParams.get("tab");
    if (initialTab && !get(tabController)) tabController.set(initialTab);
    createContentTabs(tabController);
  });

  // Follow the URL (back/forward, links with ?tab=) without undoing tab changes made in code.
  $effect(() => {
    const desiredTab = page.state.tab ?? page.url.searchParams.get("tab");
    if (!desiredTab) return;
    untrack(() => {
      if (desiredTab !== $tabController) $tabController = desiredTab;
    });
  });

  function syncUrl(tab: string) {
    if (!browser) return;
    const url = new URL(page.url);
    url.searchParams.set("tab", tab);
    // Reset to page 1 when switching tabs to avoid empty results
    url.searchParams.delete("page");
    // replaceState updates the URL without triggering SvelteKit navigation,
    // so tab switching is instant (no load functions re-run)
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic URL with mutated query params
    replaceState(url, { ...page.state, tab });
  }

  function selectTab(next: string) {
    const curr = $tabController;
    const accepted = onTabChange ? onTabChange({ curr, next }) : next;
    $tabController = accepted;
    syncUrl(accepted);
  }
</script>

<Tabs.Root
  bind:value={() => $tabController ?? "", selectTab}
  activationMode="manual"
  class="bg-primary flex flex-grow flex-col overflow-x-auto"
  id="content"
>
  {@render children?.()}
</Tabs.Root>
