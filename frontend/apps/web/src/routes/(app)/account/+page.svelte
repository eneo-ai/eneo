<script lang="ts">
  import { Page } from "$lib/components/layout";
  import SelectLanguage from "$lib/components/SelectLanguage.svelte";
  import { getAppContext } from "$lib/core/AppContext.js";
  import { getEneo } from "$lib/core/Eneo";
  import { toast } from "$lib/components/toast";
  import { toastError } from "$lib/core/errors";
  import {
    getPreferredAssistantCopyFormat,
    setPreferredAssistantCopyFormat
  } from "$lib/features/chat/copyAssistantAnswer";
  import UpdateUserName from "./UpdateUserName.svelte";
  import ChangePasswordDialog from "./ChangePasswordDialog.svelte";
  import { m } from "$lib/paraglide/messages";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import type { PageData } from "./$types";

  let { data } = $props<{ data: PageData }>();
  const uid = $props.id();
  const {
    user,
    settings,
    updateSettings,
    versions,
    featureFlags,
    state: { userInfo }
  } = getAppContext();
  const eneo = getEneo();

  let savingPreferredTextFormat = $state(false);
  let preferRichText = $state(getPreferredAssistantCopyFormat(settings) === "richtext");

  async function savePreferredTextFormat(next: boolean) {
    if (savingPreferredTextFormat) return;

    const nextFormat = next ? "richtext" : "markdown";
    if (getPreferredAssistantCopyFormat(settings) === nextFormat) return;

    savingPreferredTextFormat = true;
    try {
      const updatedSettings = await eneo.settings.update({
        ...settings,
        chatbot_widget: setPreferredAssistantCopyFormat(settings, nextFormat)
      });
      updateSettings(updatedSettings);
      preferRichText = getPreferredAssistantCopyFormat(updatedSettings) === "richtext";
      toast.success(m.preferred_copy_format_updated());
    } catch (error) {
      preferRichText = getPreferredAssistantCopyFormat(settings) === "richtext";
      toastError(error, m.preferred_copy_format_update_failed());
    } finally {
      savingPreferredTextFormat = false;
    }
  }
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
      <div class="border-dimmer hover:bg-hover-dimmer flex flex-col gap-1 border-b py-4 pr-4 pl-2">
        <h3 class="font-medium">{m.username()}</h3>
        <pre class="">{user.username}</pre>
      </div>
    {/if}
    <div class="border-dimmer hover:bg-hover-dimmer flex flex-col gap-1 border-b py-4 pr-4 pl-2">
      <h3 class="font-medium">{m.email()}</h3>
      <pre class="">{user.email}</pre>
    </div>
    <div
      data-tour="account-password"
      class="border-dimmer hover:bg-hover-dimmer flex flex-col items-start gap-4 border-b py-4 pr-4 pl-2 sm:flex-row sm:items-center"
    >
      <div class="min-w-0 flex-1">
        <h3 class="font-medium">{m.password()}</h3>
        <p class="text-secondary text-sm">
          {#if data.passwordChangeCapability.source === "external"}
            {m.password_managed_externally()}
          {:else if data.passwordChangeCapability.source === "unavailable"}
            {m.password_capability_unavailable()}
          {:else}
            {m.password_settings_description()}
          {/if}
        </p>
      </div>
      {#if data.passwordChangeCapability.source === "eneo" || data.passwordChangeCapability.source === "zitadel"}
        <ChangePasswordDialog
          capability={data.passwordChangeCapability}
          username={user.username ?? user.email}
        />
      {/if}
    </div>
    <div
      class="border-dimmer hover:bg-hover-dimmer flex flex-col gap-2 border-b pt-4 pr-4 pb-2 pl-2"
    >
      <span class="font-medium" aria-hidden="true">{m.language()}</span>
      <SelectLanguage></SelectLanguage>
    </div>
    <div
      data-tour="account-copy-format"
      class="border-dimmer hover:bg-hover-dimmer flex flex-col gap-3 border-b pt-4 pr-4 pb-4 pl-2"
    >
      <div class="flex flex-col gap-1">
        <h3 id={`${uid}-copy-format`} class="font-medium">{m.preferred_copy_format()}</h3>
        <p id={`${uid}-copy-format-description`} class="text-secondary text-sm">
          {m.preferred_copy_format_description()}
        </p>
      </div>
      <RadioGroup.Root
        value={preferRichText ? "on" : "off"}
        onValueChange={(v) => {
          const next = v === "on";
          void savePreferredTextFormat(next);
          preferRichText = next;
        }}
        disabled={savingPreferredTextFormat}
        class="grid w-full grid-cols-2 gap-2"
        aria-labelledby={`${uid}-copy-format`}
        aria-describedby={`${uid}-copy-format-description`}
      >
        <Field.Label for={`${uid}-copy-format-on`} class="font-normal">
          <Field.Field orientation="horizontal">
            <RadioGroup.Item value="on" id={`${uid}-copy-format-on`} />
            <span>{m.copy_format_richtext()}</span>
          </Field.Field>
        </Field.Label>
        <Field.Label for={`${uid}-copy-format-off`} class="font-normal">
          <Field.Field orientation="horizontal">
            <RadioGroup.Item value="off" id={`${uid}-copy-format-off`} />
            <span>{m.copy_format_markdown()}</span>
          </Field.Field>
        </Field.Label>
      </RadioGroup.Root>
    </div>
    <div class="border-dimmer hover:bg-hover-dimmer flex flex-col gap-1 border-b py-4 pr-4 pl-2">
      <h3 class="font-medium">{m.version()}</h3>
      <pre
        class="">{m.account_version_frontend()} {versions.frontend} {m.account_version_client()} {versions.client} {m.account_version_backend()} {versions.backend}</pre>
    </div>
    {#if versions.preview}
      <div class="border-dimmer hover:bg-hover-dimmer flex flex-col gap-1 border-b py-4 pr-4 pl-2">
        <h3 class="font-medium">{m.preview()}</h3>
        <pre class="">{m.branch()}: {versions.preview.branch}<br />{m.commit()}: {versions.preview
            .commit}</pre>
      </div>
    {/if}
  </Page.Main>
</Page.Root>
