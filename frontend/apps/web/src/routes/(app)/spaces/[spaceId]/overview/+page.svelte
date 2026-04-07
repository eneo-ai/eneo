<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import MembersList from "../members/MembersList.svelte";
  import { getAppContext } from "$lib/core/AppContext";
  import { Page } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import OverviewTile from "./OverviewTile.svelte";

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const {
    state: { userInfo }
  } = getAppContext();

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function ownerSpaceId(item: any): string | undefined {
    return (
      item?.space_id ??
      item?.spaceId ??
      item?.space?.id ??
      item?.metadata?.space_id ??
      item?.metadata?.spaceId
    );
  }

  $: localCollections = ($currentSpace?.knowledge?.groups ?? []).filter(
    (g) => ownerSpaceId(g) === $currentSpace?.id
  );
  $: localWebsites = ($currentSpace?.knowledge?.websites ?? []).filter(
    (w) => ownerSpaceId(w) === $currentSpace?.id
  );
</script>

<svelte:head>
  <title
    >{m.app_name()} – {$currentSpace.personal ? m.personal() : $currentSpace.name} – {m.overview()}</title
  >
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.overview()}></Page.Title>
    <MembersList></MembersList>
  </Page.Header>

  <Page.Main>
    <div class="flex flex-grow flex-col overflow-y-auto pt-4 pr-4 pl-2">
      <div class="flex items-center justify-start gap-4 pb-4">
        <h1 class="text-primary text-[2rem] font-extrabold">
          {$currentSpace.personal
            ? m.hi_user_personal({ firstName: $userInfo.firstName })
            : $currentSpace.name}
        </h1>
      </div>
      {#if $currentSpace.personal}
        <p class="text-primary min-h-20 max-w-[70ch]">
          {m.personal_space_description()}
        </p>
      {:else}
        <p class="min-h-20">
          {$currentSpace.description ?? m.welcome_to_space({ space: $currentSpace.name })}
        </p>
      {/if}

      <div class="grid gap-4 pt-4 pb-4 md:grid-cols-3">
        {#if $currentSpace.hasPermission("read", "assistant")}
          <OverviewTile
            title={m.assistants()}
            count={$currentSpace.applications.chat.length}
            href="/spaces/{$currentSpace.routeId}/assistants"
          />
        {/if}
        {#if $currentSpace.hasPermission("read", "app")}
          <OverviewTile
            title={m.apps()}
            count={$currentSpace.applications.apps.length}
            href="/spaces/{$currentSpace.routeId}/apps"
          />
        {/if}
        {#if $currentSpace.hasPermission("read", "service")}
          <OverviewTile
            title={m.services()}
            count={$currentSpace.applications.services.length}
            href="/spaces/{$currentSpace.routeId}/services"
          />
        {/if}
        {#if $currentSpace.hasPermission("read", "collection")}
          <OverviewTile
            title={m.collections()}
            count={localCollections.length}
            href="/spaces/{$currentSpace.routeId}/knowledge?tab=collections"
          />
        {/if}
        {#if $currentSpace.hasPermission("read", "website")}
          <OverviewTile
            title={m.websites()}
            count={localWebsites.length}
            href="/spaces/{$currentSpace.routeId}/knowledge?tab=websites"
          />
        {/if}
        {#if $currentSpace.hasPermission("read", "member")}
          <OverviewTile
            title={m.members()}
            count={$currentSpace.members.length}
            href="/spaces/{$currentSpace.routeId}/members"
          />
        {/if}
      </div>
    </div>
  </Page.Main>
</Page.Root>
