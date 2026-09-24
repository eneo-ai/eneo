<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import SpaceChip from "$lib/features/spaces/components/SpaceChip.svelte";
  import type { SpaceSparse } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { localizeHref } from "$lib/paraglide/runtime";

  export let space: SpaceSparse;
</script>

<div class="flex w-full items-center justify-start">
  <Button variant="ghost" href={localizeHref(`/spaces/${space.id}/overview`)} class="max-w-full">
    <SpaceChip {space}></SpaceChip>

    <span class="text-primary truncate overflow-ellipsis">
      {space.name}
    </span>
  </Button>
</div>
