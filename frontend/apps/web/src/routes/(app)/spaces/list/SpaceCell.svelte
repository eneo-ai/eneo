<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import SpaceChip from "$lib/features/spaces/components/SpaceChip.svelte";
  import type { SpaceSparse } from "@eneo/eneo-js";
  import { Button } from "@eneo/ui";
  import { localizeHref } from "$lib/paraglide/runtime";

  export let space: SpaceSparse;
</script>

<div class="flex w-full items-center justify-start">
  <Button
    href={localizeHref(`/spaces/${space.id}/overview`)}
    padding="icon-leading"
    class="'-ml-1' max-w-full"
  >
    <SpaceChip {space}></SpaceChip>

    <span class="text-primary truncate overflow-ellipsis">
      {space.name}
    </span>
  </Button>
</div>
