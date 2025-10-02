<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { SpaceSparse } from "@intric/intric-js";
  import { IconEdit } from "@intric/icons/edit";
  import { IconEllipsis } from "@intric/icons/ellipsis";
  import { Button, Dropdown } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  export let space: SpaceSparse;
</script>

{#if space.permissions?.includes("edit")}
  <Dropdown.Root>
    <Dropdown.Trigger let:trigger asFragment>
      <Button is={trigger} disabled={false} padding="icon">
        <IconEllipsis></IconEllipsis>
      </Button>
    </Dropdown.Trigger>
    <Dropdown.Menu let:item>
      <Button is={item} href="/spaces/{space.id}/settings" padding="icon-leading">
        <IconEdit size="sm" />
        {m.edit()}</Button
      >
    </Dropdown.Menu>
  </Dropdown.Root>
{/if}
