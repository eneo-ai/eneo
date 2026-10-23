<script lang="ts">
  import { untrack } from "svelte";
  import { get, writable, type Writable } from "svelte/store";
  import { Tabs } from "bits-ui";
  import { page } from "$app/state";
  import { createContentTabs, selectPageTab } from "./ctx";

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

  function selectTab(next: string) {
    const curr = $tabController;
    selectPageTab(tabController, onTabChange ? onTabChange({ curr, next }) : next);
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
