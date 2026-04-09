<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button } from "@intric/ui";
  import { Page } from "$lib/components/layout/index.js";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import AssistantTemplatesTable from "./AssistantTemplatesTable.svelte";
  import AppTemplatesTable from "./AppTemplatesTable.svelte";
  import DeletedTemplatesTable from "./DeletedTemplatesTable.svelte";
  import { LayoutTemplate } from "lucide-svelte";
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { page } from "$app/state";

  let { data } = $props();

  // Get active tab: prefer page.state.tab (set by TabTrigger via replaceState),
  // fallback to URL param (for direct navigation), default to assistant_templates
  let activeTab = $derived(
    (page.state as Record<string, unknown>)?.tab ??
      page.url.searchParams.get("tab") ??
      "assistant_templates"
  );

  function handleCreateTemplate() {
    if (activeTab === "app_templates") {
      goto(resolve("/admin/templates/new/app"));
    } else {
      goto(resolve("/admin/templates/new/assistant"));
    }
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.templates()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.templates()}></Page.Title>

    <Button variant="primary" padding="icon-leading" onclick={handleCreateTemplate}>
      <LayoutTemplate size={16} />
      {m.create_template()}
    </Button>

    <Page.Tabbar>
      <Page.TabTrigger tab="assistant_templates">{m.assistant_templates()}</Page.TabTrigger>
      <Page.TabTrigger tab="app_templates">{m.app_templates()}</Page.TabTrigger>
      <Page.TabTrigger tab="deleted_templates">{m.deleted_templates()}</Page.TabTrigger>
    </Page.Tabbar>
  </Page.Header>
  <Page.Main>
    <Page.Tab id="assistant_templates">
      {#if data.assistantTemplates.length === 0}
        <div class="flex flex-col items-center justify-center gap-4 py-24">
          <div class="bg-accent-dimmer rounded-full p-6">
            <LayoutTemplate size={48} class="text-accent-default" />
          </div>

          <div class="flex flex-col items-center gap-2 text-center">
            <h3 class="text-default text-lg font-semibold">
              {m.no_templates_yet()}
            </h3>
            <p class="text-dimmer max-w-md text-sm">
              {m.templates_empty_state_description()}
            </p>
          </div>

          <Button
            variant="primary"
            padding="icon-leading"
            href={localizeHref("/admin/templates/new/assistant")}
          >
            <LayoutTemplate size={16} />
            {m.create_first_template()}
          </Button>
        </div>
      {:else}
        <AssistantTemplatesTable templates={data.assistantTemplates} />
      {/if}
    </Page.Tab>
    <Page.Tab id="app_templates">
      {#if data.appTemplates.length === 0}
        <div class="flex flex-col items-center justify-center gap-4 py-24">
          <div class="bg-accent-dimmer rounded-full p-6">
            <LayoutTemplate size={48} class="text-accent-default" />
          </div>

          <div class="flex flex-col items-center gap-2 text-center">
            <h3 class="text-default text-lg font-semibold">
              {m.no_templates_yet()}
            </h3>
            <p class="text-dimmer max-w-md text-sm">
              {m.templates_empty_state_description()}
            </p>
          </div>

          <Button
            variant="primary"
            padding="icon-leading"
            href={localizeHref("/admin/templates/new/app")}
          >
            <LayoutTemplate size={16} />
            {m.create_first_template()}
          </Button>
        </div>
      {:else}
        <AppTemplatesTable templates={data.appTemplates} />
      {/if}
    </Page.Tab>
    <Page.Tab id="deleted_templates">
      {#if data.deletedTemplates.length === 0}
        <div class="flex flex-col items-center justify-center gap-4 py-24">
          <div class="bg-accent-dimmer rounded-full p-6">
            <LayoutTemplate size={48} class="text-accent-default" />
          </div>

          <div class="flex flex-col items-center gap-2 text-center">
            <h3 class="text-default text-lg font-semibold">
              {m.no_templates_yet()}
            </h3>
            <p class="text-dimmer max-w-md text-sm">
              {m.templates_empty_state_description()}
            </p>
          </div>
        </div>
      {:else}
        <DeletedTemplatesTable templates={data.deletedTemplates} />
      {/if}
    </Page.Tab>
  </Page.Main>
</Page.Root>
