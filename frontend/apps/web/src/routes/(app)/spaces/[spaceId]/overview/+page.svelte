<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import MembersList from "../members/MembersList.svelte";
  import { getAppContext } from "$lib/core/AppContext";
  import { Page } from "$lib/components/layout";

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const {
    state: { userInfo }
  } = getAppContext();

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
    (g: any) => ownerSpaceId(g) === $currentSpace?.id
  );
  $: localWebsites = ($currentSpace?.knowledge?.websites ?? []).filter(
    (w: any) => ownerSpaceId(w) === $currentSpace?.id
  );

</script>


<svelte:head>
  <title>Eneo.ai – {$currentSpace.personal ? "Personal" : $currentSpace.name} – Overview</title>
</svelte:head>

{#snippet tile(params: { title: string; count: number; link: string })}
  <a
    href="/spaces/{$currentSpace.routeId}{params.link}"
    class="border-default bg-hover-dimmer hover:bg-hover-default flex min-h-64 cursor-pointer flex-col border-t px-4 py-2"
  >
    <h3 class="text-primary font-mono text-sm uppercase">{params.title}</h3>
    <div class="flex-grow"></div>

    <div class="text-primary self-end text-[4rem] font-bold">
      {params.count}
    </div>
  </a>
{/snippet}

<Page.Root>
  <Page.Header>
    <Page.Title title="Overview"></Page.Title>
    <MembersList></MembersList>
  </Page.Header>

  <Page.Main>
    <div class="flex flex-grow flex-col overflow-y-auto pt-4 pr-4 pl-2">
      <div class="flex items-center justify-start gap-4 pb-4">
        <h1 class="text-primary text-[2rem] font-extrabold">
          {$currentSpace.personal ? `Hi, ${$userInfo.firstName}!` : $currentSpace.name}
        </h1>
      </div>
      {#if $currentSpace.personal}
        <p class="text-primary min-h-20 max-w-[70ch]">
          You can build and experiment with your own AI applications in your personal space.
        </p>
      {:else}
        <p class="min-h-20">{$currentSpace.description ?? `Welcome to ${$currentSpace.name}`}</p>
      {/if}
      <!-- <div class="flex-grow"></div> -->

      <div class="grid gap-4 pt-4 pb-4 md:grid-cols-3">
        {#if $currentSpace.hasPermission("read", "assistant")}
          {@render tile({
            title: "Assistants",
            count: $currentSpace.applications.chat.length,
            link: "/assistants"
          })}
        {/if}
        {#if $currentSpace.hasPermission("read", "app")}
          {@render tile({
            title: "Apps",
            count: $currentSpace.applications.apps.length,
            link: "/apps"
          })}
        {/if}
        {#if $currentSpace.hasPermission("read", "service")}
          {@render tile({
            title: "Services",
            count: $currentSpace.applications.services.length,
            link: "/services"
          })}
        {/if}
        {#if $currentSpace.hasPermission("read", "collection")}
          {@render tile({
            title: "Collections",
            count: localCollections.length,
            link: "/knowledge?tab=collections"
          })}
        {/if}
        {#if $currentSpace.hasPermission("read", "website")}
          {@render tile({
            title: "Websites",
            count: localWebsites.length,
            link: "/knowledge?tab=websites"
          })}
        {/if}
        {#if $currentSpace.hasPermission("read", "member")}
          {@render tile({
            title: "Members",
            count: $currentSpace.members.length,
            link: "/members"
          })}
        {/if}
      </div>
    </div>
  </Page.Main>
</Page.Root>
