<script lang="ts">
  import { untrack, type Snippet } from "svelte";
  import { Tabs } from "bits-ui";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getContentTabs } from "./ctx";

  type Props = {
    tab: string;
    label?: string;
    /** Render only the snippet, which receives the trigger props to spread on its own element. */
    asFragment?: boolean;
    children?: Snippet<[{ trigger: Record<string, unknown> }]>;
  };

  let { tab, label, asFragment = false, children }: Props = $props();

  untrack(() => getContentTabs().registerTab(tab));
</script>

<Tabs.Trigger value={tab}>
  {#snippet child({ props })}
    {#if asFragment}
      {@render children?.({ trigger: props })}
    {:else}
      <!-- A segment of the Tabbar's strip; the outline replaces the button's ring so
           focus keeps its contrast on the segmented background. -->
      <Button
        {...props}
        variant="ghost"
        aria-label={label}
        class="text-secondary hover:text-primary focus-visible:outline-ring data-[state=active]:bg-primary data-[state=active]:text-primary h-auto gap-1.5 rounded-md px-3 py-1 text-sm font-medium whitespace-nowrap transition-colors hover:bg-transparent focus-visible:border-transparent focus-visible:ring-0 focus-visible:outline-2 focus-visible:outline-offset-2 data-[state=active]:shadow-sm"
      >
        {@render children?.({ trigger: props })}
      </Button>
    {/if}
  {/snippet}
</Tabs.Trigger>
