<script lang="ts">
  import { IconAssistant } from "@intric/icons/assistant";
  import { IconKey } from "@intric/icons/key";
  import { page } from "$app/stores";
  import type { ComponentType } from "svelte";
  import { Navigation } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  // import { IconIntegrations } from "@intric/icons/integrations";

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
    // {
    //   icon: IconIntegrations,
    //   label: "My integrations",
    //   url: "/account/integrations"
    // },
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
