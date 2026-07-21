<script lang="ts">
  import { Menu } from "lucide-svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Sheet from "$lib/components/ui/sheet/index.js";
  import { getAppContext } from "$lib/core/AppContext";
  import { dynamicColour } from "$lib/core/colours";
  import SpaceSelector from "$lib/features/spaces/components/SpaceSelector.svelte";
  import { m } from "$lib/paraglide/messages";
  import SpaceMenu, { type SpaceMenuContext } from "../../[spaceId]/SpaceMenu.svelte";
  import {
    hasOrganizationNavigationPermission,
    resolveOrganizationSkillsAccess
  } from "./organizationSkillsAccess";

  const { user } = getAppContext();
  const access = resolveOrganizationSkillsAccess({
    admin: user.hasPermission("admin"),
    skills: user.hasPermission("skills"),
    skillsManagement: user.hasPermission("skills_management")
  });
  let mobileNavigationOpen = false;

  const organizationSpace = {
    id: "organization",
    name: m.organization_space(),
    personal: false,
    organization: true,
    routeId: "organization",
    hasPermission: (action, resource) =>
      hasOrganizationNavigationPermission(access, action, resource)
  } satisfies SpaceMenuContext & { id: string; name: string };
</script>

<div
  {...dynamicColour({ basedOn: organizationSpace.id })}
  class="absolute inset-0 flex min-w-0 flex-grow flex-col justify-stretch md:flex-row"
>
  <aside class="border-default hidden w-[17rem] min-w-[17rem] flex-col border-r-[0.5px] md:flex">
    <SpaceSelector space={organizationSpace} />
    <SpaceMenu space={organizationSpace} />
  </aside>

  <div class="border-default flex min-h-12 items-center border-b-[0.5px] px-2 md:hidden">
    <Button
      variant="ghost"
      class="h-11 min-w-11 justify-start px-3"
      aria-haspopup="dialog"
      aria-expanded={mobileNavigationOpen}
      onclick={() => (mobileNavigationOpen = true)}
    >
      <Menu data-icon="inline-start" aria-hidden="true" />
      {m.organization_space()}
    </Button>
  </div>

  <Sheet.Root open={mobileNavigationOpen} onOpenChange={(open) => (mobileNavigationOpen = open)}>
    <Sheet.Content
      side="left"
      class="w-[min(20rem,calc(100vw-2rem))] gap-0 p-0 [&_[data-slot=sheet-close]]:size-11"
    >
      <Sheet.Header class="sr-only">
        <Sheet.Title>{m.organization_space()}</Sheet.Title>
        <Sheet.Description>{m.organization_skills_open_navigation()}</Sheet.Description>
      </Sheet.Header>
      <div class="flex h-full flex-col">
        <SpaceSelector space={organizationSpace} />
        <SpaceMenu space={organizationSpace} />
      </div>
    </Sheet.Content>
  </Sheet.Root>

  <div class="relative flex min-h-0 min-w-0 flex-1">
    <slot />
  </div>

  <div
    class="pointer-events-none absolute inset-0 -z-0 flex flex-grow shadow-xl md:left-[17rem]"
  ></div>
</div>
