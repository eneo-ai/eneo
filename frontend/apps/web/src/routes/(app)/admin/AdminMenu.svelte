<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { Icon } from "@intric/icons";
  import type { ComponentType } from "svelte";
  import { IconAssistant } from "@intric/icons/assistant";
  import { IconAssistants } from "@intric/icons/assistants";
  import { IconThumb } from "@intric/icons/thumb";
  import { IconLibrary } from "@intric/icons/library";
  import { IconCPU } from "@intric/icons/CPU";
  import { IconBulb } from "@intric/icons/bulb";
  import { IconHistory } from "@intric/icons/history";
  import { IconSpeechBubble } from "@intric/icons/speech-bubble";
  import { IconSparkles } from "@intric/icons/sparkles";
  import { IconKey } from "@intric/icons/key";
  import { BookText, ChartPie, LayoutTemplate, Cloud, Plug, ShieldCheck } from "lucide-svelte";
  import { page } from "$app/stores";
  import * as Sidebar from "$lib/components/ui/sidebar/index.js";
  import { m } from "$lib/paraglide/messages";
  import { deLocalizeHref, localizeHref } from "$lib/paraglide/runtime";
  import { getAppContext } from "$lib/core/AppContext.js";

  const { settings } = getAppContext();

  const currentRoute = $derived(deLocalizeHref($page.url.pathname));

  function isSelected(url: string, route: string) {
    const normalizedUrl = url.replace(/\/$/, "");
    const normalizedRoute = route.replace(/\/$/, "");
    if (normalizedUrl === "/admin") return normalizedRoute === "/admin";
    return normalizedRoute === normalizedUrl || normalizedRoute.startsWith(`${normalizedUrl}/`);
  }

  type NavItem = { route: string; href: string; icon: Icon | ComponentType; label: string };
  type NavGroup = { label: string; items: NavItem[] };

  function navItem(route: string, icon: Icon | ComponentType, label: string): NavItem {
    return { route, href: localizeHref(route), icon, label };
  }

  const groups = $derived<NavGroup[]>([
    {
      label: m.admin_section_overview(),
      items: [navItem("/admin", IconLibrary, m.organisation())]
    },
    {
      label: m.admin_section_governance(),
      items: [
        navItem("/admin/personal-assistant", IconSpeechBubble, m.governance_title()),
        navItem("/admin/prompt-library", BookText, m.governance_tab_prompts()),
        navItem("/admin/security-classifications", ShieldCheck, m.security_classifications())
      ]
    },
    {
      label: m.admin_section_configuration(),
      items: [
        navItem("/admin/models", IconCPU, m.models()),
        ...(settings?.using_templates
          ? [navItem("/admin/templates", LayoutTemplate, m.templates())]
          : []),
        navItem("/admin/help-assistants", IconSparkles, m.admin_help_assistants_nav_label()),
        navItem("/admin/mcp-servers", Plug, m.mcp()),
        navItem("/admin/integrations", Cloud, m.integrations())
      ]
    },
    {
      label: m.admin_section_analytics_logs(),
      items: [
        navItem("/admin/usage", ChartPie, m.usage()),
        navItem("/admin/insights", IconBulb, m.insights()),
        navItem("/admin/audit-logs", IconHistory, m.audit_logs())
      ]
    },
    {
      label: m.admin_section_access(),
      items: [
        navItem("/admin/users", IconAssistant, m.users()),
        navItem("/admin/legacy/user-groups", IconAssistants, m.user_groups()),
        navItem("/admin/legacy/roles", IconThumb, m.roles()),
        navItem("/admin/api-keys", IconKey, m.api_keys())
      ]
    }
  ]);
</script>

{#each groups as group (group.label)}
  <Sidebar.Group>
    <Sidebar.GroupLabel>{group.label}</Sidebar.GroupLabel>
    <Sidebar.GroupContent>
      <Sidebar.Menu>
        {#each group.items as item (item.href)}
          {@const active = isSelected(item.route, currentRoute)}
          <Sidebar.MenuItem>
            <Sidebar.MenuButton isActive={active}>
              {#snippet child({ props })}
                <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- localized hrefs built from typed route literals -->
                <a href={item.href} {...props} aria-current={active ? "page" : undefined}>
                  <item.icon class="size-4" />
                  <span>{item.label}</span>
                </a>
              {/snippet}
            </Sidebar.MenuButton>
          </Sidebar.MenuItem>
        {/each}
      </Sidebar.Menu>
    </Sidebar.GroupContent>
  </Sidebar.Group>
{/each}
