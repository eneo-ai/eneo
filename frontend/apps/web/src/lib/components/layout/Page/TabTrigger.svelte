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
      <Button
        {...props}
        variant="ghost"
        aria-label={label}
        class="data-[state=active]:bg-accent-dimmer data-[state=active]:text-accent-stronger tracking-[0.01rem] data-[state=active]:font-medium data-[state=active]:tracking-normal"
      >
        {@render children?.({ trigger: props })}
      </Button>
    {/if}
  {/snippet}
</Tabs.Trigger>
