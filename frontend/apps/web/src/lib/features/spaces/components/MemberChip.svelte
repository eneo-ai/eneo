<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { dynamicColour } from "$lib/core/colours";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";

  export let member:
    | {
        id: string;
        email: string;
      }
    | {
        label: string;
      };
</script>

<div aria-hidden="true">
  {#if "email" in member}
    <Tooltip.Root>
      <Tooltip.Trigger>
        {#snippet child({ props })}
          <!-- Not a tab stop: the chip sits in an aria-hidden subtree. -->
          {@const { tabindex: _tabindex, ...triggerProps } = props}
          <div
            {...triggerProps}
            {...dynamicColour({ basedOn: member.email })}
            class="chip bg-dynamic-default text-on-fill capitalize"
          >
            {member.email.slice(0, 1)}
          </div>
        {/snippet}
      </Tooltip.Trigger>
      <Tooltip.Content>{member.email}</Tooltip.Content>
    </Tooltip.Root>
  {:else}
    <div class="fallback chip">{member.label}</div>
  {/if}
</div>

<style lang="postcss">
  @reference "@eneo/ui/styles";
  .chip {
    @apply border-on-fill -ml-2 flex h-9 w-9 items-center justify-center rounded-full border-2 shadow hover:z-30 hover:shadow-lg;
  }
  .fallback {
    @apply bg-accent-default text-on-fill text-center text-sm;
  }
</style>
