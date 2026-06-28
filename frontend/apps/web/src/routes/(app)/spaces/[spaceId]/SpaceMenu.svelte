<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

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
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  // TODO
  const {
    state: { currentSpace }
  } = getSpacesManager();

  $: section = $page.url.pathname.split("/")[3];
  $: chatPartnerIsDefined = $page.url.searchParams.get("type") !== null;
  $: isOrgSpace = $currentSpace.organization === true;
</script>

<Navigation.Menu>
  {#if !isOrgSpace && $currentSpace.personal}
    <!-- The personal chat is a fixed feature of the personal space: always
         shown here, like Overview. Access is gated in-page (the chat renders a
         no-access state without the personal_chat permission), so the nav stays
         consistent regardless of permissions. -->
    <Navigation.Link
      href={localizeHref(`/spaces/${$currentSpace.routeId}/chat?tab=chat`)}
      isActive={section === "chat" && !chatPartnerIsDefined}
      icon={IconSpeechBubble}
      label={m.chat()}
    />
    <div class="border-default my-2 border-b-[0.5px]"></div>
  {/if}

  {#if !isOrgSpace}
    <Navigation.Link
      href={localizeHref(`/spaces/${$currentSpace.routeId}/overview`)}
      isActive={section === "overview"}
      icon={IconOverview}
      label={m.overview()}
    />
  {/if}

  {#if !isOrgSpace && $currentSpace.hasPermission("read", "assistant")}
    <Navigation.Link
      href={localizeHref(`/spaces/${$currentSpace.routeId}/assistants`)}
      isActive={section === "assistants" || (section === "chat" && chatPartnerIsDefined)}
      icon={IconSpeechBubble}
      label={m.assistants()}
    />
  {/if}
  {#if !isOrgSpace && $currentSpace.hasPermission("read", "app")}
    <Navigation.Link
      href={localizeHref(`/spaces/${$currentSpace.routeId}/apps`)}
      isActive={section === "apps"}
      icon={IconApp}
      label={m.apps()}
    />
  {/if}
  {#if $currentSpace.hasPermission("read", "website") || $currentSpace.hasPermission("read", "collection")}
    <Navigation.Link
      href={localizeHref(`/spaces/${$currentSpace.routeId}/knowledge`)}
      isActive={section === "knowledge"}
      icon={IconKnowledge}
      label={m.knowledge()}
    />
  {/if}
  {#if $currentSpace.hasPermission("read", "service")}<div
      class="border-default my-2 border-b-[0.5px]"
    ></div>
    <Navigation.Link
      href={localizeHref(`/spaces/${$currentSpace.routeId}/services`)}
      isActive={section === "services"}
      icon={IconServices}
      label={m.services()}
    />
  {/if}
  {#if !isOrgSpace && $currentSpace.hasPermission("read", "member")}
    <div class="border-default my-2 border-b-[0.5px]"></div>
    <Navigation.Link
      href={localizeHref(`/spaces/${$currentSpace.routeId}/members`)}
      isActive={section === "members"}
      icon={IconAssistants}
      label={m.members()}
    />
  {/if}
  {#if $currentSpace.hasPermission("edit", "space")}
    <Navigation.Link
      href={localizeHref(`/spaces/${$currentSpace.routeId}/settings`)}
      isActive={section === "settings"}
      icon={IconCog}
      label={m.settings()}
    />
  {/if}
</Navigation.Menu>
