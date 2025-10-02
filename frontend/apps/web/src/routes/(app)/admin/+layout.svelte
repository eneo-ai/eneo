<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getAppContext } from "$lib/core/AppContext";
  import { dynamicColour } from "$lib/core/colours";
  import SpaceChip from "$lib/features/spaces/components/SpaceChip.svelte";
  import AdminMenu from "./AdminMenu.svelte";
  import { m } from "$lib/paraglide/messages";

  const { tenant } = getAppContext();
</script>

<div {...dynamicColour({ basedOn: "1" })} class="absolute inset-0 flex flex-grow justify-stretch">
  <div class="border-default flex flex-col border-r-[0.5px] md:max-w-[17rem] md:min-w-[17rem]">
    <div
      class="group border-default relative flex h-[4.25rem] w-full items-center justify-start gap-3 border-b-[0.5px] pt-0.5 pr-5 pl-[1.4rem] font-medium"
    >
      <SpaceChip
        space={{
          id: "1",
          name: tenant.display_name ?? m.your_organisation(),
          personal: false
        }}
      ></SpaceChip>
      <span class="text-primary flex-grow truncate pl-0.5 text-left">
        {tenant.display_name ?? m.your_organisation()}
      </span>
    </div>
    <AdminMenu></AdminMenu>
  </div>
  <slot />
  <div
    class="pointer-events-none absolute inset-0 -z-0 flex flex-grow shadow-xl md:left-[17rem]"
  ></div>
</div>
