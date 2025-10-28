<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page, Settings } from "$lib/components/layout/index.js";
  import { Input } from "@intric/ui";
  import { getAppContext } from "$lib/core/AppContext.js";
  import { getIntric } from "$lib/core/Intric.js";
  import StorageOverviewBar from "./usage/storage/StorageOverviewBar.svelte";
  import TokenOverviewBar from "./usage/tokens/TokenOverviewBar.svelte";
  import { m } from "$lib/paraglide/messages";
  import { invalidate } from "$app/navigation";

  const { tenant, settings } = getAppContext();
  const intric = getIntric();
  let { data } = $props();

  let usingTemplates = $state(settings.using_templates);

  async function handleToggleTemplates() {
    const previousValue = usingTemplates;
    try {
      const updatedSettings = await intric.settings.updateTemplates(usingTemplates);
      settings.using_templates = updatedSettings.using_templates;
      await invalidate("app:layout");
    } catch (error) {
      usingTemplates = previousValue;
      console.error("Error updating templates setting:", error);
    }
  }
</script>

<svelte:head>
  <title>Eneo.ai - {tenant.display_name}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.organisation()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.usage()}>
        <StorageOverviewBar storageStats={data.storageStats}></StorageOverviewBar>
        <TokenOverviewBar tokenStats={data.tokenStats}></TokenOverviewBar>
      </Settings.Group>

      <Settings.Group title={m.features()}>
        <Settings.Row title={m.enable_templates()} description={m.enable_templates_description()}>
          <Input.Switch bind:value={usingTemplates} sideEffect={handleToggleTemplates} />
        </Settings.Row>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>
