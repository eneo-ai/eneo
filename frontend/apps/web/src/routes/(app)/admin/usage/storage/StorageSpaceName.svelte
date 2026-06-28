<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import SpaceChip from "$lib/features/spaces/components/SpaceChip.svelte";
  import type { StorageSpaceList } from "@eneo/eneo-js";

  export let space: StorageSpaceList;
</script>

<div class="flex w-full items-center justify-start gap-2">
  <SpaceChip space={{ ...space, personal: false }}></SpaceChip>

  <span class="text-primary truncate overflow-ellipsis">
    {space.name}
  </span>
</div>
