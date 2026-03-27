<script lang="ts">
  import { IconAssistant } from "@eneo/icons/assistant";
  import { IconKey } from "@eneo/icons/key";
  import { IconLink } from "@eneo/icons/link";
  import { page } from "$app/stores";
  import type { ComponentType } from "svelte";
  import { Navigation } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";

  let currentRoute = "";
  $: currentRoute = $page.url.pathname;

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

<Navigation.Menu>
  {#each menuItems as item (item.url)}
    <Navigation.Link
      href={item.url}
      icon={item.icon}
      isActive={currentRoute === item.url}
      label={item.label}
    ></Navigation.Link>
  {/each}
</Navigation.Menu>
