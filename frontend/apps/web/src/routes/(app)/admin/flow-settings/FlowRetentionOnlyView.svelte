<script lang="ts">
  import { beforeNavigate } from "$app/navigation";
  import { Page } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";

  import type { PageData } from "./$types";
  import FlowRetentionAccessPanel from "./FlowRetentionAccessPanel.svelte";

  // For a role with retention_manage or retention_holds but not admin: the
  // retention tab alone. The other Flow settings tabs are admin settings.
  let { data }: { data: PageData } = $props();
  let dirty = $state(false);

  beforeNavigate((navigation) => {
    if (dirty && !confirm(m.flow_settings_leave_confirm())) navigation.cancel();
  });
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.flow_settings_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.flow_settings_title()} />
    <Page.Tabbar>
      <Page.TabTrigger tab="retention">{m.flow_settings_tab_retention()}</Page.TabTrigger>
    </Page.Tabbar>
  </Page.Header>
  <Page.Main>
    <p class="text-secondary mx-auto w-full max-w-[1180px] px-6 pt-4 text-sm lg:px-4">
      {m.flow_retention_only_description()}
    </p>
    <Page.Tab id="retention">
      <FlowRetentionAccessPanel {data} onDirtyChange={(value) => (dirty = value)} />
    </Page.Tab>
  </Page.Main>
</Page.Root>
