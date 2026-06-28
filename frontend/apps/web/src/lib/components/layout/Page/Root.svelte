<script lang="ts">
  import { untrack } from "svelte";
  import { writable, type Writable } from "svelte/store";
  import { createContentTabs } from "./ctx";
  import { page } from "$app/state";

  type Props = {
    tabController?: Writable<string> | undefined;
    onTabChange?: ((args: { curr: string; next: string }) => string) | undefined;
    children?: import("svelte").Snippet;
  };

  let { tabController = writable(), onTabChange = undefined, children }: Props = $props();

  const {
    elements: { root }
  } = untrack(() =>
    createContentTabs(page.url.searchParams.get("tab") ?? undefined, tabController, onTabChange)
  );

  $effect(() => {
    const stateTab = page.state.tab;
    const searchTab = page.url.searchParams.get("tab");
    const desiredTab = stateTab ?? searchTab;

    if (!desiredTab) return;
    if (desiredTab === $tabController) return;

    $tabController = desiredTab;
  });
</script>

<div {...$root} use:root class="bg-primary flex flex-grow flex-col overflow-x-auto" id="content">
  {@render children?.()}
</div>
