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

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const {
    state: { userInfo }
  } = getAppContext();
</script>

<svelte:head>
  <title>{m.app_name()} – {$currentSpace.personal ? m.personal() : $currentSpace.name} – {m.overview()}</title>
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
    <Page.Title title={m.overview()}></Page.Title>
    <MembersList></MembersList>
  </Page.Header>

  <Page.Main>
    <div class="flex flex-grow flex-col overflow-y-auto pt-4 pr-4 pl-2">
      <div class="flex items-center justify-start gap-4 pb-4">
        <h1 class="text-primary text-[2rem] font-extrabold">
          {$currentSpace.personal ? m.hi_user_personal({ firstName: $userInfo.firstName }) : $currentSpace.name}
        </h1>
      </div>
      {#if $currentSpace.personal}
        <p class="text-primary min-h-20 max-w-[70ch]">
          {m.personal_space_description()}
        </p>
      {:else}
        <p class="min-h-20">{$currentSpace.description ?? m.welcome_to_space({ space: $currentSpace.name })}</p>
      {/if}
      <!-- <div class="flex-grow"></div> -->

      <div class="grid gap-4 pt-4 pb-4 md:grid-cols-3">
        {#if $currentSpace.hasPermission("read", "assistant")}
          {@render tile({
            title: m.assistants(),
            count: $currentSpace.applications.chat.length,
            link: "/assistants"
          })}
        {/if}
        {#if $currentSpace.hasPermission("read", "app")}
          {@render tile({
            title: m.apps(),
            count: $currentSpace.applications.apps.length,
            link: "/apps"
          })}
        {/if}
        {#if $currentSpace.hasPermission("read", "service")}
          {@render tile({
            title: m.services(),
            count: $currentSpace.applications.services.length,
            link: "/services"
          })}
        {/if}
        {#if $currentSpace.hasPermission("read", "collection")}
          {@render tile({
            title: m.collections(),
            count: $currentSpace.knowledge.groups.length,
            link: "/knowledge?tab=collections"
          })}
        {/if}
        {#if $currentSpace.hasPermission("read", "website")}
          {@render tile({
            title: m.websites(),
            count: $currentSpace.knowledge.websites.length,
            link: "/knowledge?tab=websites"
          })}
        {/if}
        {#if $currentSpace.hasPermission("read", "member")}
          {@render tile({
            title: m.members(),
            count: $currentSpace.members.length,
            link: "/members"
          })}
        {/if}
      </div>
    </div>
  </Page.Main>
</Page.Root>
