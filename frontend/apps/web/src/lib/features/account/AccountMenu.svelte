<script lang="ts">
  import { IconAssistant } from "@eneo/icons/assistant";
  import { IconKey } from "@eneo/icons/key";
  import { IconLink } from "@eneo/icons/link";
  import { page } from "$app/stores";
  import type { ComponentType } from "svelte";
  import { Navigation } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { deLocalizeUrl, localizeHref } from "$lib/paraglide/runtime";
  import { Sparkles } from "@lucide/svelte";
  import { getWhatsNewStore } from "$lib/features/whats-new/whatsNewStore";

  const { enabled, hasUnseen } = getWhatsNewStore();

  let currentRoute = "";
  $: currentRoute = deLocalizeUrl($page.url).pathname;

  const menuItems: {
    icon: ComponentType;
    label: string;
    url: string;
  }[] = [
    {
      icon: IconAssistant,
      label: m.my_account(),
      url: "/account"
    },
    {
      icon: IconLink,
      label: m.integrations(),
      url: "/account/integrations"
    },
    {
      icon: IconKey,
      label: m.api_keys(),
      url: "/account/api-keys"
    }
  ];
</script>

<Navigation.Menu ariaLabel={m.account_and_settings()}>
  {#each menuItems as item (item.url)}
    <Navigation.Link
      href={localizeHref(item.url)}
      icon={item.icon}
      isActive={currentRoute === item.url}
      label={item.label}
    ></Navigation.Link>
  {/each}
  {#if $enabled}
    <Navigation.Link
      href={localizeHref("/news")}
      icon={Sparkles}
      isActive={currentRoute === "/news"}
      label={m.whats_new()}
    >
      {#if $hasUnseen}
        <span aria-hidden="true" class="bg-positive-default ml-auto size-2 self-center rounded-full"
        ></span>
        <span class="sr-only">{m.whats_new_unseen()}</span>
      {/if}
    </Navigation.Link>
  {/if}
</Navigation.Menu>
