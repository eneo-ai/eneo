<script lang="ts">
  import { Button } from "@eneo/ui";
  import { onMount } from "svelte";
  import { quadInOut } from "svelte/easing";
  import { fly } from "svelte/transition";

  export let parent: { title?: string; href: string } | null = null;
  export let title: string | undefined = undefined;
  export let truncate = false;

  let titleContainer: HTMLDivElement;
  let originalTitleWidth: number | null = null;
  // When truncating always start in overflow state, it's better to have a too small component expand than
  // a too large one shrink when the value is computed for the first time
  let isOverflowing = truncate;

  function setThreshold() {
    if (titleContainer && titleContainer.parentElement && truncate) {
      const fullWidth = titleContainer.parentElement.getBoundingClientRect().width;

      originalTitleWidth = Math.max(
        originalTitleWidth ?? 0,
        titleContainer.getBoundingClientRect().width,
        titleContainer.scrollWidth
      );

      // As the titleContainer has a maxWidth of 40% we want to switch views slight before that
      isOverflowing = originalTitleWidth > fullWidth * 0.35;
    }
  }

  onMount(() => {
    if (truncate) setThreshold();
    // When switching between assistants in the assistant switcher, the size of the slot will change
    // we also need to detect these size changes, not only window resizes (which we need also to observe)
    const observer = new ResizeObserver(setThreshold);
    observer.observe(titleContainer);
    return () => observer.disconnect();
  });
</script>

<svelte:window on:resize={setThreshold} />

<div
  bind:this={titleContainer}
  class:max-w-[40%]={isOverflowing}
  class="grid translate-y-[0.02rem] flex-col overflow-hidden transition-all"
>
  <div class="overflow-hidden pl-2 text-[1.4rem]">
    <div class="flex w-full items-baseline gap-2">
      {#if parent}
        <Button
          unstyled
          href={parent.href}
          class="text-muted hover:border-dimmer hover:bg-hover-default hover:text-primary -mx-2 inline-block rounded-lg border border-transparent px-2 py-0.5 text-[1.35rem] tracking-[-0.01rem] whitespace-nowrap"
          >←
          {#if parent.title}
            <span class:sr-only={isOverflowing}>
              &nbsp;{parent.title}
            </span>
          {/if}
        </Button>
        {#if parent.title}
          <div class="text-muted" class:hidden={isOverflowing}>/</div>
        {/if}
      {/if}

      {#if title}
        <h1
          in:fly|global={{ x: -5, duration: parent ? 300 : 0, easing: quadInOut, opacity: 0.3 }}
          class:pl-2={isOverflowing}
          class="text-primary inline-block w-full items-center gap-2 truncate pr-4 text-[1.45rem] leading-normal font-extrabold"
        >
          {title}
        </h1>
      {:else}
        <slot></slot>
      {/if}
    </div>
  </div>
</div>
