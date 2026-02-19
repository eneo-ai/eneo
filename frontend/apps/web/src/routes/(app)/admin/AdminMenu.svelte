<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconAssistant } from "@intric/icons/assistant";
  import { IconAssistants } from "@intric/icons/assistants";
  import { IconThumb } from "@intric/icons/thumb";
  import { IconLibrary } from "@intric/icons/library";
  import { IconCPU } from "@intric/icons/CPU";
  import { IconBulb } from "@intric/icons/bulb";
  import { IconHistory } from "@intric/icons/history";
  import { page } from "$app/stores";
  import { Navigation } from "$lib/components/layout";
  import { ChartPie, LayoutTemplate, Cloud, Plug } from "lucide-svelte";
  import { IconKey } from "@intric/icons/key";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { getAppContext } from "$lib/core/AppContext.js";

  const { settings } = getAppContext();

  let currentRoute = "";
  $: currentRoute = $page.url.pathname;

  function isSelected(url: string, currentRoute: string) {
    url = url.replaceAll("/admin", "");
    currentRoute = currentRoute.replaceAll("/admin", "");
    if (url === "") return currentRoute === "";
    return currentRoute.startsWith(url);
  }
</script>

<Navigation.Menu>
  <Navigation.Link
    href={localizeHref("/admin")}
    isActive={isSelected("/admin", currentRoute)}
    icon={IconLibrary}
    label={m.organisation()}
  />

  <div class="border-default my-2 border-b-[0.5px]"></div>
  <Navigation.Link
    href={localizeHref("/admin/models")}
    isActive={isSelected("/admin/models", currentRoute)}
    icon={IconCPU}
    label={m.models()}
  />
  {#if settings?.using_templates}
    <Navigation.Link
      href={localizeHref("/admin/templates")}
      isActive={isSelected("/admin/templates", currentRoute)}
      icon={LayoutTemplate}
      label={m.templates()}
    />
  {/if}
  <Navigation.Link
    href={localizeHref("/admin/security-classifications")}
    isActive={isSelected("/admin/security-classifications", currentRoute)}
    icon={IconKey}
    label={m.security()}
  />
  <Navigation.Link
    href="/admin/mcp-servers"
    isActive={isSelected("/admin/mcp-servers", currentRoute)}
    icon={Plug}
    label={m.mcp()}
  />
  <Navigation.Link
    href="/admin/audit-logs"
    isActive={isSelected("/admin/audit-logs", currentRoute)}
    icon={IconHistory}
    label={m.audit_logs()}
  />
  <Navigation.Link
    href="/admin/integrations"
    isActive={isSelected("/admin/integrations", currentRoute)}
    icon={Cloud}
    label={m.integrations()}
  />
  <div class="border-default my-2 border-b-[0.5px]"></div>
  <Navigation.Link
    href={localizeHref("/admin/usage")}
    isActive={isSelected("/admin/usage", currentRoute)}
    icon={ChartPie}
    label={m.usage()}
  />
  <Navigation.Link
    href={localizeHref("/admin/insights")}
    isActive={isSelected("/admin/insights", currentRoute)}
    icon={IconBulb}
    label={m.insights()}
  >
    <span
      class="hidden rounded-md border border-[var(--beta-indicator)] px-1 py-0.5 text-xs font-normal !tracking-normal text-[var(--beta-indicator)] md:block"
      >{m.beta()}</span
    >
  </Navigation.Link>
  <div class="border-default my-2 border-b-[0.5px]"></div>
  <Navigation.Link
    href={localizeHref("/admin/users")}
    isActive={isSelected("/admin/users", currentRoute)}
    icon={IconAssistant}
    label={m.users()}
  />
  <Navigation.Link
    href={localizeHref("/admin/legacy/user-groups")}
    isActive={isSelected("/admin/legacy/user-groups", currentRoute)}
    icon={IconAssistants}
    label={m.user_groups()}
  />
  <Navigation.Link
    href={localizeHref("/admin/legacy/roles")}
    isActive={isSelected("/admin/legacy/roles", currentRoute)}
    icon={IconThumb}
    label={m.roles()}
  />
</Navigation.Menu>
