<script lang="ts">
  import { Page } from "$lib/components/layout";
  import SelectTheme from "$lib/components/SelectTheme.svelte";
  import SelectLanguage from "$lib/components/SelectLanguage.svelte";
  import { getAppContext } from "$lib/core/AppContext.js";
  import UpdateUserName from "./UpdateUserName.svelte";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  const {
    user,
    versions,
    featureFlags,
    state: { userInfo }
  } = getAppContext();

  const currentLocale = getLocale();
</script>

<svelte:head>
  <title>{m.app_name()} – {m.account()} – {$userInfo.firstName}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.account()}></Page.Title>
  </Page.Header>
  <Page.Main>
    {#if featureFlags.newAuth}
      <div
        class="border-dimmer hover:bg-hover-dimmer flex items-center gap-12 border-b py-4 pr-4 pl-2"
      >
        <div class="flex flex-col gap-1">
          <h3 class="font-medium">{m.first_name()}</h3>
          <pre class="">{$userInfo.firstName}</pre>
        </div>
        <div class="flex flex-col gap-1">
          <h3 class="font-medium">{m.last_name()}</h3>
          <pre class="">{$userInfo.lastName}</pre>
        </div>
        <div class="flex flex-col gap-1">
          <h3 class="font-medium">{m.full_name()}</h3>
          <pre class="">{$userInfo.displayName}</pre>
        </div>
        <!-- Changing name only supported for username/password users -->
        {#if !$userInfo.usesIdp}
          <div class="flex-grow"></div>
          <UpdateUserName
            firstName={$userInfo.firstName}
            lastName={$userInfo.lastName}
            displayName={$userInfo.displayName}
          ></UpdateUserName>
        {/if}
      </div>
    {:else}
      <div class="border-dimmer hover:bg-hover-dimmer flex flex-col gap-1 border-b py-4 pl-2 pr-4">
        <h3 class="font-medium">{m.username()}</h3>
        <pre class="">{user.username}</pre>
      </div>
    {/if}
    <div class="border-dimmer hover:bg-hover-dimmer flex flex-col gap-1 border-b py-4 pl-2 pr-4">
      <h3 class="font-medium">{m.email()}</h3>
      <pre class="">{user.email}</pre>
    </div>
    <div
      class="border-dimmer hover:bg-hover-dimmer flex flex-col gap-2 border-b pt-4 pr-4 pb-2 pl-2"
    >
      <span class="font-medium" aria-hidden="true">{m.theme()}</span>
      <SelectTheme></SelectTheme>
    </div>
    <div
      class="border-dimmer hover:bg-hover-dimmer flex flex-col gap-2 border-b pb-2 pl-2 pr-4 pt-4"
    >
      <span class="font-medium" aria-hidden="true">{m.language()}</span>
      <SelectLanguage></SelectLanguage>
    </div>
    <div class="border-dimmer hover:bg-hover-dimmer flex flex-col gap-1 border-b py-4 pl-2 pr-4">
      <h3 class="font-medium">{m.version()}</h3>
      <pre
        class="">Frontend: {versions.frontend} · Client: {versions.client} · Backend: {versions.backend}</pre>
    </div>
    {#if versions.preview}
      <div class="border-dimmer hover:bg-hover-dimmer flex flex-col gap-1 border-b py-4 pl-2 pr-4">
        <h3 class="font-medium">{m.preview()}</h3>
        <pre class="">{m.branch()}: {versions.preview.branch}<br />{m.commit()}: {versions.preview.commit}</pre>
      </div>
    {/if}
  </Page.Main>
</Page.Root>
