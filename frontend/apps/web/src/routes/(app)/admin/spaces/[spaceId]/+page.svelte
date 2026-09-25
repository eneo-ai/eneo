<!--
  One shared space as an organisation administrator sees it without being a
  member: settings, configuration, knowledge metadata, members and usage,
  never documents, questions, answers or conversations.
-->
<script lang="ts">
  import {
    BookOpen,
    Bot,
    MessageSquareCode,
    Settings2,
    TriangleAlert,
    UsersRound
  } from "@lucide/svelte";
  import { tick } from "svelte";
  import { Page } from "$lib/components/layout";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import { intlLocale } from "$lib/core/formatting/dateTime";
  import { urlTab } from "$lib/core/helpers/urlTab.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import AssistantsTab from "./AssistantsTab.svelte";
  import KnowledgeTab from "./KnowledgeTab.svelte";
  import MembersTab from "./MembersTab.svelte";
  import SettingsTab from "./SettingsTab.svelte";
  import SpaceMembershipBanner from "./SpaceMembershipBanner.svelte";
  import SpaceSummary from "./SpaceSummary.svelte";
  import WidgetsTab from "./WidgetsTab.svelte";

  let { data } = $props();

  const number = new Intl.NumberFormat(intlLocale());
  const tab = urlTab(
    ["settings", "assistants", "knowledge", "members", "widgets"] as const,
    "settings"
  );
  const listHref = localizeHref("/admin/spaces");

  const space = $derived(data.space);

  async function goToMembers() {
    tab.value = "members";
    await tick();
    document.getElementById("space-members-title")?.focus();
  }
</script>

<svelte:head>
  <title>
    Eneo.ai – {m.admin()} – {m.admin_spaces_nav()} – {space?.name ??
      m.admin_spaces_not_found_title()}
  </title>
</svelte:head>

{#snippet count(value: number)}
  <Badge variant="secondary" class="ml-1">{number.format(value)}</Badge>
{/snippet}

<Page.Root>
  <Page.Header>
    <Page.Title
      wrap
      parent={{ title: m.admin_spaces_nav(), href: listHref }}
      title={space?.name ?? m.admin_spaces_not_found_title()}
    ></Page.Title>
  </Page.Header>
  <Page.Main>
    <div class="mx-auto flex w-full max-w-[1200px] flex-col gap-6 p-4">
      {#if !space}
        <div class="flex max-w-[75ch] flex-col gap-3">
          <p>{m.admin_spaces_not_found_body()}</p>
          <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href from a fixed route -->
          <a class="text-accent-stronger w-fit underline underline-offset-2" href={listHref}>
            {m.admin_spaces_back()}
          </a>
          <!-- eslint-enable svelte/no-navigation-without-resolve -->
        </div>
      {:else}
        {#if space.description}
          <p class="text-secondary max-w-[75ch] wrap-anywhere">{space.description}</p>
        {/if}

        <SpaceMembershipBanner {space} />

        {#if space.attention.includes("no_admin")}
          <section
            aria-labelledby="space-no-admin-title"
            class="bg-warning-dimmer text-warning-stronger flex flex-col gap-3 rounded-lg p-4 @3xl:flex-row @3xl:items-center"
          >
            <div class="flex min-w-0 flex-1 gap-3">
              <TriangleAlert class="mt-0.5 size-5 shrink-0" aria-hidden="true" />
              <div class="flex min-w-0 flex-col gap-1">
                <h2 id="space-no-admin-title" class="text-base font-semibold">
                  {m.admin_spaces_no_admin_title()}
                </h2>
                <p class="max-w-[75ch] text-sm">{m.admin_spaces_no_admin_body()}</p>
              </div>
            </div>
            <Button
              variant="outline"
              class="w-fit max-md:min-h-12 @max-3xl:ml-8"
              onclick={goToMembers}
            >
              {m.admin_spaces_no_admin_action()}
            </Button>
          </section>
        {/if}

        <SpaceSummary {space} securityEnabled={data.securityEnabled} />

        <Tabs.Root bind:value={tab.value} class="gap-6">
          <Tabs.List
            class="h-auto w-full flex-wrap gap-1 p-1 sm:w-auto sm:self-start"
            aria-label={space.name}
          >
            <Tabs.Trigger value="settings" class="h-9 px-3 max-md:min-h-12">
              <Settings2 aria-hidden="true" />
              {m.settings()}
            </Tabs.Trigger>
            <Tabs.Trigger value="assistants" class="h-9 px-3 max-md:min-h-12">
              <Bot aria-hidden="true" />
              {m.admin_spaces_tab_assistants()}
              {@render count(
                space.assistants.length + space.apps.length + space.group_chats.length
              )}
            </Tabs.Trigger>
            <Tabs.Trigger value="knowledge" class="h-9 px-3 max-md:min-h-12">
              <BookOpen aria-hidden="true" />
              {m.knowledge()}
              {@render count(space.knowledge.length)}
            </Tabs.Trigger>
            <Tabs.Trigger value="members" class="h-9 px-3 max-md:min-h-12">
              <UsersRound aria-hidden="true" />
              {m.members()}
              <!-- People with access, the same count as the summary and the tab's own. -->
              {@render count(space.members.member_count)}
            </Tabs.Trigger>
            <Tabs.Trigger value="widgets" class="h-9 px-3 max-md:min-h-12">
              <MessageSquareCode aria-hidden="true" />
              {m.widget_admin_nav()}
              {@render count(space.widgets.length)}
            </Tabs.Trigger>
          </Tabs.List>

          <Tabs.Content value="settings">
            <SettingsTab settings={space.settings} />
          </Tabs.Content>
          <Tabs.Content value="assistants">
            <AssistantsTab
              assistants={space.assistants}
              apps={space.apps}
              groupChats={space.group_chats}
            />
          </Tabs.Content>
          <Tabs.Content value="knowledge">
            <KnowledgeTab
              knowledge={space.knowledge}
              inheritedCount={space.inherited_knowledge_count}
            />
          </Tabs.Content>
          <Tabs.Content value="members">
            <MembersTab {space} currentUserId={data.user.id} />
          </Tabs.Content>
          <Tabs.Content value="widgets">
            <WidgetsTab widgets={space.widgets} />
          </Tabs.Content>
        </Tabs.Root>
      {/if}
    </div>
  </Page.Main>
</Page.Root>
