<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconStar } from "@intric/icons/star";
  import { getAppContext } from "$lib/core/AppContext";
  import { dynamicColour } from "$lib/core/colours";

  export let space: {
    id: string;
    name: string;
    personal: boolean;
    icon_id?: string | null;
  };

  const { user, environment } = getAppContext();

  // Generate icon URL from icon_id
  $: iconUrl = space.icon_id
    ? `${environment.baseUrl}/api/v1/icons/${space.icon_id}/`
    : null;
</script>

{#if space.personal}
  <div {...dynamicColour({ basedOn: user.id })} class="star" aria-hidden="true">
    <IconStar size="sm" />
  </div>
{:else if iconUrl}
  <div class="chip overflow-hidden !p-0" aria-hidden="true">
    <img src={iconUrl} alt="" class="h-[1.6rem] w-[1.6rem] object-cover" />
  </div>
{:else}
  <div {...dynamicColour({ basedOn: space.id })} class="chip capitalize" aria-hidden="true">
    {[...space.name][0]}
  </div>
{/if}

<style lang="postcss">
  @reference "@intric/ui/styles";
  .chip {
    @apply bg-dynamic-default text-on-fill flex min-h-[1.6rem] min-w-[1.6rem] items-center justify-center rounded-md;
  }
  .star {
    @apply bg-dynamic-dimmer text-dynamic-stronger flex min-h-[1.6rem] min-w-[1.6rem] items-center justify-center rounded-md;
  }
</style>
