<script lang="ts">
  import { invalidateAll } from "$app/navigation";
  import { Page } from "$lib/components/layout";
  import { getAppContext } from "$lib/core/AppContext.js";
  import { getIntric } from "$lib/core/Intric";
  import { Button, Dialog } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  const {
    user,
    state: { userInfo }
  } = getAppContext();
  const intric = getIntric();

  let apiKey: string | null = null;
  let showCopiedMessage = false;

  async function generateApiKey() {
    apiKey = (await intric.users.generateApiKey()).key;
    invalidateAll();
  }
</script>

<svelte:head>
  <title>Eneo.ai – Account – {$userInfo.firstName}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.my_api_keys()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <div
      class="border-default hover:bg-hover-dimmer flex items-center gap-1 border-b py-4 pr-4 pl-2"
    >
      <div class="flex flex-grow flex-col gap-1">
        <h3 class="font-medium">{m.api_key()}</h3>
        <pre class="">{apiKey
            ? apiKey
            : user.truncated_api_key
              ? `****${user.truncated_api_key}`
              : m.no_active_key()}</pre>
      </div>
      {#if apiKey}
        <Button
          on:click={() => {
            if (!apiKey) {
              alert(m.no_api_key_found_generate());
              return;
            }
            navigator.clipboard.writeText(apiKey);
            showCopiedMessage = true;
            setTimeout(() => {
              showCopiedMessage = false;
            }, 2000);
          }}
          variant="outlined"
          class="w-24"
        >
          <span>{showCopiedMessage ? m.copied() : m.copy_key()}</span>
        </Button>
      {/if}
      <Dialog.Root alert>
        <Dialog.Trigger asFragment let:trigger>
          <Button variant="outlined" is={trigger}>{m.generate_api_key()}</Button>
        </Dialog.Trigger>

        <Dialog.Content>
          <Dialog.Title>{m.generate_new_api_key_title()}</Dialog.Title>
          <Dialog.Description>{@html m.generate_api_key_warning()}</Dialog.Description>

          <Dialog.Controls let:close>
            <Button is={close}>{m.cancel()}</Button>
            <Button is={close} variant="destructive" on:click={generateApiKey}
              >{m.generate_new_key()}</Button
            >
          </Dialog.Controls>
        </Dialog.Content>
      </Dialog.Root>
    </div>
  </Page.Main>
</Page.Root>
