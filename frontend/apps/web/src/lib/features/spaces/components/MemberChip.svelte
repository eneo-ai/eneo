<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { dynamicColour } from "$lib/core/colours";
  import { Tooltip } from "@eneo/ui";

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
    <Tooltip text={member.email} placement="top">
      <div
        {...dynamicColour({ basedOn: member.email })}
        class="chip bg-dynamic-default text-on-fill capitalize"
      >
        {member.email.slice(0, 1)}
      </div>
    </Tooltip>
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
    @apply bg-brand-eneo text-on-fill text-center text-sm;
  }
</style>
