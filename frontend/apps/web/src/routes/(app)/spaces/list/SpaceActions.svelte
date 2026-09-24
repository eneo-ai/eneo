<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { SpaceSparse } from "@eneo/eneo-js";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  export let space: SpaceSparse;
</script>

{#if space.permissions?.includes("edit")}
  <DropdownMenu.Root>
    <DropdownMenu.Trigger>
      {#snippet child({ props })}
        <Button {...props} variant="ghost" size="icon" aria-label={m.actions()}>
          <IconEllipsis></IconEllipsis>
        </Button>
      {/snippet}
    </DropdownMenu.Trigger>
    <DropdownMenu.Content align="end">
      <DropdownMenu.Item>
        {#snippet child({ props })}
          <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing -->
          <a {...props} href={localizeHref(`/spaces/${space.id}/settings`)}>
            <IconEdit size="sm" />
            {m.edit()}
          </a>
          <!-- eslint-enable svelte/no-navigation-without-resolve -->
        {/snippet}
      </DropdownMenu.Item>
    </DropdownMenu.Content>
  </DropdownMenu.Root>
{/if}
