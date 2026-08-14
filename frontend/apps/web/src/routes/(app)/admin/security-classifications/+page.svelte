<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import SecurityClassificationEnabledSetting from "$lib/features/security-classifications/components/SecurityClassificationEnabledSetting.svelte";
  import SecurityClassificationListSetting from "$lib/features/security-classifications/components/SecurityClassificationListSetting.svelte";
  import { initSecurityClassificationService } from "$lib/features/security-classifications/SecurityClassificationsService.svelte.js";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";

  const { data } = $props();

  untrack(() => initSecurityClassificationService(data.eneo, data.securityClassifications));
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.security_classifications()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.security()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.general()}>
        <SecurityClassificationEnabledSetting></SecurityClassificationEnabledSetting>
      </Settings.Group>
      <Settings.Group title={m.configuration()}>
        <SecurityClassificationListSetting></SecurityClassificationListSetting>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>
