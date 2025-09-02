<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconApp } from "@intric/icons/app";
  import { IconAssistants } from "@intric/icons/assistants";
  import { IconCog } from "@intric/icons/cog";
  import { IconKnowledge } from "@intric/icons/knowledge";
  import { IconOverview } from "@intric/icons/overview";
  import { IconServices } from "@intric/icons/services";
  import { IconSpeechBubble } from "@intric/icons/speech-bubble";
  import { page } from "$app/stores";
  import { Navigation } from "$lib/components/layout";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  // TODO
  const {
    state: { currentSpace }
  } = getSpacesManager();

  $: section = $page.url.pathname.split("/")[3];
  $: chatPartnerIsDefined = $page.url.searchParams.get("type") !== null;
  $: isOrgSpace = $currentSpace.organization === true;
</script>

<Navigation.Menu>
  {#if !isOrgSpace && $currentSpace.hasPermission("read", "default_assistant") && $currentSpace.personal}
    <Navigation.Link
      href="/spaces/{$currentSpace.routeId}/chat?tab=chat"
      isActive={section === "chat" && !chatPartnerIsDefined}
      icon={IconSpeechBubble}
      label="Chat"
    />
    <div class="border-default my-2 border-b-[0.5px]"></div>
  {/if}

  {#if !isOrgSpace}
    <Navigation.Link
      href="/spaces/{$currentSpace.routeId}/overview"
      isActive={section === "overview"}
      icon={IconOverview}
      label="Overview"
    />
  {/if}

  {#if !isOrgSpace && $currentSpace.hasPermission("read", "assistant")}
    <Navigation.Link
      href="/spaces/{$currentSpace.routeId}/assistants"
      isActive={section === "assistants" || (section === "chat" && chatPartnerIsDefined)}
      icon={IconSpeechBubble}
      label="Assistants"
    />
  {/if}
  {#if !isOrgSpace && $currentSpace.hasPermission("read", "app")}
    <Navigation.Link
      href="/spaces/{$currentSpace.routeId}/apps"
      isActive={section === "apps"}
      icon={IconApp}
      label="Apps"
    />
  {/if}
  {#if $currentSpace.hasPermission("read", "website") || $currentSpace.hasPermission("read", "collection")}
    <Navigation.Link
      href="/spaces/{$currentSpace.routeId}/knowledge"
      isActive={section === "knowledge"}
      icon={IconKnowledge}
      label="Knowledge"
    />
  {/if}
  {#if $currentSpace.hasPermission("read", "service")}<div
      class="border-default my-2 border-b-[0.5px]"
    ></div>
    <Navigation.Link
      href="/spaces/{$currentSpace.routeId}/services"
      isActive={section === "services"}
      icon={IconServices}
      label="Services"
    />
  {/if}
  {#if !isOrgSpace && $currentSpace.hasPermission("read", "member")}
    <div class="border-default my-2 border-b-[0.5px]"></div>
    <Navigation.Link
      href="/spaces/{$currentSpace.routeId}/members"
      isActive={section === "members"}
      icon={IconAssistants}
      label="Members"
    />
  {/if}
  {#if $currentSpace.hasPermission("edit", "space")}
    <Navigation.Link
      href="/spaces/{$currentSpace.routeId}/settings"
      isActive={section === "settings"}
      icon={IconCog}
      label="Settings"
    />
  {/if}
</Navigation.Menu>
