<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script context="module" lang="ts">
  import type { ResourcePermission } from "@eneo/eneo-js";

  export type SpaceMenuResource =
    | "space"
    | "assistant"
    | "group_chat"
    | "app"
    | "service"
    | "collection"
    | "website"
    | "skill"
    | "member";

  export type SpaceMenuContext = {
    routeId: string;
    personal: boolean;
    organization: boolean;
    hasPermission(action: ResourcePermission, resource: SpaceMenuResource): boolean;
  };
</script>

<script lang="ts">
  import { IconApp } from "@eneo/icons/app";
  import { IconAssistants } from "@eneo/icons/assistants";
  import { IconCog } from "@eneo/icons/cog";
  import { IconKnowledge } from "@eneo/icons/knowledge";
  import { IconOverview } from "@eneo/icons/overview";
  import { IconServices } from "@eneo/icons/services";
  import { IconSpeechBubble } from "@eneo/icons/speech-bubble";
  import { page } from "$app/stores";
  import { Navigation } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { BookOpenCheck } from "lucide-svelte";

  export let space: SpaceMenuContext;

  $: section = $page.url.pathname.split("/")[3];
  $: chatPartnerIsDefined = $page.url.searchParams.get("type") !== null;
  $: isOrgSpace = space.organization === true;
</script>

<Navigation.Menu>
  {#if !isOrgSpace && space.personal}
    <!-- The personal chat is a fixed feature of the personal space: always
         shown here, like Overview. Access is gated in-page (the chat renders a
         no-access state without the personal_chat permission), so the nav stays
         consistent regardless of permissions. -->
    <Navigation.Link
      href={localizeHref(`/spaces/${space.routeId}/chat?tab=chat`)}
      isActive={section === "chat" && !chatPartnerIsDefined}
      icon={IconSpeechBubble}
      label={m.chat()}
    />
    <div class="border-default my-2 border-b-[0.5px]"></div>
  {/if}

  {#if !isOrgSpace}
    <Navigation.Link
      href={localizeHref(`/spaces/${space.routeId}/overview`)}
      isActive={section === "overview"}
      icon={IconOverview}
      label={m.overview()}
    />
  {/if}

  {#if !isOrgSpace && space.hasPermission("read", "assistant")}
    <Navigation.Link
      href={localizeHref(`/spaces/${space.routeId}/assistants`)}
      isActive={section === "assistants" || (section === "chat" && chatPartnerIsDefined)}
      icon={IconSpeechBubble}
      label={m.assistants()}
    />
  {/if}
  {#if !isOrgSpace && space.hasPermission("read", "app")}
    <Navigation.Link
      href={localizeHref(`/spaces/${space.routeId}/apps`)}
      isActive={section === "apps"}
      icon={IconApp}
      label={m.apps()}
    />
  {/if}
  {#if space.hasPermission("read", "website") || space.hasPermission("read", "collection")}
    <Navigation.Link
      href={localizeHref(`/spaces/${space.routeId}/knowledge`)}
      isActive={section === "knowledge"}
      icon={IconKnowledge}
      label={m.knowledge()}
    />
  {/if}
  {#if space.hasPermission("read", "skill")}
    <Navigation.Link
      href={localizeHref(`/spaces/${space.routeId}/skills`)}
      isActive={section === "skills"}
      icon={BookOpenCheck}
      label={m.skills()}
    />
  {/if}
  {#if space.hasPermission("read", "service")}<div
      class="border-default my-2 border-b-[0.5px]"
    ></div>
    <Navigation.Link
      href={localizeHref(`/spaces/${space.routeId}/services`)}
      isActive={section === "services"}
      icon={IconServices}
      label={m.services()}
    />
  {/if}
  {#if !isOrgSpace && space.hasPermission("read", "member")}
    <div class="border-default my-2 border-b-[0.5px]"></div>
    <Navigation.Link
      href={localizeHref(`/spaces/${space.routeId}/members`)}
      isActive={section === "members"}
      icon={IconAssistants}
      label={m.members()}
    />
  {/if}
  {#if space.hasPermission("edit", "space")}
    <Navigation.Link
      href={localizeHref(`/spaces/${space.routeId}/settings`)}
      isActive={section === "settings"}
      icon={IconCog}
      label={m.settings()}
    />
  {/if}
</Navigation.Menu>
