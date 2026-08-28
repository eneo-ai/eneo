<script lang="ts">
  import { getContentTabs } from "./ctx";

  let div: HTMLDivElement | undefined;

  const {
    states: { value }
  } = getContentTabs();

  const scrollPositions: Record<string, number> = {};
  function loadPersistedScroll(tabKey: string) {
    const scrollY = scrollPositions[tabKey] ?? 0;

    const scrollContainer = div;
    if (!scrollContainer) return;

    setTimeout(() => {
      scrollContainer.scrollTo({
        top: scrollY,
        behavior: "instant"
      });
    }, 1);
  }

  function persistScroll(event: Event) {
    if (event.currentTarget instanceof HTMLDivElement) {
      scrollPositions[$value] = event.currentTarget.scrollTop;
    }
  }

  $: loadPersistedScroll($value);
</script>

<div
  bind:this={div}
  id="global-page-container"
  style="container-type: size;"
  class="text-primary relative flex flex-grow flex-col overflow-y-auto pl-6 transition-colors duration-400"
  on:scroll={persistScroll}
>
  <slot />
</div>
