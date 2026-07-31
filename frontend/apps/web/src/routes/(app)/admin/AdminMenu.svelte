<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { ComponentType } from "svelte";
  import BookOpenCheck from "lucide-svelte/icons/book-open-check";
  import BookText from "lucide-svelte/icons/book-text";
  import ChartPie from "lucide-svelte/icons/chart-pie";
  import Cloud from "lucide-svelte/icons/cloud";
  import Cpu from "lucide-svelte/icons/cpu";
  import Database from "lucide-svelte/icons/database";
  import Fingerprint from "lucide-svelte/icons/fingerprint";
  import HardDrive from "lucide-svelte/icons/hard-drive";
  import History from "lucide-svelte/icons/history";
  import KeyRound from "lucide-svelte/icons/key-round";
  import Landmark from "lucide-svelte/icons/landmark";
  import LayoutTemplate from "lucide-svelte/icons/layout-template";
  import Lightbulb from "lucide-svelte/icons/lightbulb";
  import MessageSquareText from "lucide-svelte/icons/message-square-text";
  import Plug from "lucide-svelte/icons/plug";
  import ShieldCheck from "lucide-svelte/icons/shield-check";
  import SlidersHorizontal from "lucide-svelte/icons/sliders-horizontal";
  import Sparkles from "lucide-svelte/icons/sparkles";
  import UserRound from "lucide-svelte/icons/user-round";
  import UsersRound from "lucide-svelte/icons/users-round";
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

  type NavItem = { route: string; href: string; icon: ComponentType; label: string };
  type NavGroup = { label: string; items: NavItem[] };

  function navItem(route: string, icon: ComponentType, label: string): NavItem {
    return { route, href: localizeHref(route), icon, label };
  }

  const groups = $derived<NavGroup[]>([
    {
      label: m.admin_section_overview(),
      items: [navItem("/admin", Landmark, m.overview())]
    },
    {
      label: m.admin_section_governance(),
      items: [
        navItem("/admin/personal-assistant", MessageSquareText, m.governance_title()),
        navItem("/admin/prompt-library", BookText, m.governance_tab_prompts()),
        navItem("/admin/flow-data-retention", Database, m.flow_retention_title()),
        navItem("/admin/security-classifications", ShieldCheck, m.security_classifications())
      ]
    },
    {
      label: m.admin_section_configuration(),
      items: [
        navItem("/admin/models", Cpu, m.models()),
        ...(settings?.using_templates
          ? [navItem("/admin/templates", LayoutTemplate, m.templates())]
          : []),
        navItem("/admin/flow-input-limits", SlidersHorizontal, m.flow_input_limits_title()),
        navItem(
          "/admin/flow-knowledge-evidence",
          SlidersHorizontal,
          m.flow_knowledge_evidence_title()
        ),
        navItem("/admin/skills", BookOpenCheck, m.admin_skills_nav_label()),
        navItem("/admin/help-assistants", Sparkles, m.admin_help_assistants_nav_label()),
        navItem("/admin/mcp-servers", Plug, m.mcp()),
        navItem("/admin/integrations", Cloud, m.integrations()),
        navItem("/admin/storage", HardDrive, m.storage_settings_nav())
      ]
    },
    {
      label: m.admin_section_analytics_logs(),
      items: [
        navItem("/admin/usage", ChartPie, m.usage()),
        navItem("/admin/insights", Lightbulb, m.insights()),
        navItem("/admin/audit-logs", History, m.audit_logs())
      ]
    },
    {
      label: m.admin_section_access(),
      items: [
        navItem("/admin/users", UserRound, m.users()),
        navItem("/admin/legacy/user-groups", UsersRound, m.user_groups()),
        navItem("/admin/legacy/roles", Fingerprint, m.roles()),
        navItem("/admin/api-keys", KeyRound, m.api_keys())
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
            <Sidebar.MenuButton isActive={active} class="[&_svg]:size-4.5">
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
