<script lang="ts">
  import { makeEditable } from "$lib/core/editable";
  import { getIntric } from "$lib/core/Intric";
  import SelectEmbeddingModel from "$lib/features/ai-models/components/SelectEmbeddingModel.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { type Website } from "@intric/intric-js";
  import { Dialog, Button, Input, Select, Tooltip } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  const emptyWebsite = () => {
    return {
      name: null,
      url: "",
      crawl_type: "crawl",
      download_files: undefined,
      embedding_model: undefined,
      update_interval: "never"
    } as unknown as Website;
  };

  const intric = getIntric();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  export let mode: "update" | "create" = "create";
  export let website: Omit<Website, "embedding_model"> & {
    embedding_model?: { id: string } | null;
  } = emptyWebsite();
  export let showDialog: Dialog.OpenState | undefined = undefined;

  let editableWebsite = makeEditable(website);
  let websiteName = website.name ?? "";
  let isProcessing = false;
  let validUrl = false;

  // HTTP Basic Authentication state
  let httpAuthEnabled = website?.requires_http_auth ?? false;
  let httpAuthUsername = '';
  let httpAuthPassword = '';
  let showPassword = false;

  // Clear credentials when auth is disabled
  $: if (!httpAuthEnabled) {
    httpAuthUsername = '';
    httpAuthPassword = '';
  }

  function handleRemoveAuth() {
    httpAuthEnabled = false;
    httpAuthUsername = '';
    httpAuthPassword = '';
  }

  async function updateWebsite() {
    isProcessing = true;
    try {
      let edits = editableWebsite.getEdits();
      edits.name = websiteName === "" ? null : websiteName;

      // Handle HTTP auth fields
      if (httpAuthEnabled && httpAuthUsername) {
        edits.http_auth_username = httpAuthUsername;
        if (httpAuthPassword) {
          edits.http_auth_password = httpAuthPassword;
        }
      } else if (!httpAuthEnabled && website?.requires_http_auth) {
        // Remove auth if it was previously enabled
        edits.http_auth_username = null;
        edits.http_auth_password = null;
      }

      const updated = await intric.websites.update({ website: { id: website.id }, update: edits });
      editableWebsite.updateWithValue(updated);
      refreshCurrentSpace();
      $showDialog = false;
    } catch (e) {
      alert(e);
      console.error(e);
    }
    isProcessing = false;
  }

  async function createWebsite() {
    if (!validUrl) {
      return;
    }

    isProcessing = true;
    try {
      const websiteData: any = {
        spaceId: $currentSpace.id,
        ...editableWebsite,
        name: websiteName === "" ? null : websiteName
      };

      // Add HTTP auth if enabled
      if (httpAuthEnabled && httpAuthUsername && httpAuthPassword) {
        websiteData.http_auth_username = httpAuthUsername;
        websiteData.http_auth_password = httpAuthPassword;
      }

      await intric.websites.create(websiteData);
      editableWebsite.updateWithValue(emptyWebsite());
      websiteName = "";
      httpAuthEnabled = false;
      httpAuthUsername = '';
      httpAuthPassword = '';
      refreshCurrentSpace();
      $showDialog = false;
    } catch (e) {
      alert(e);
      console.error(e);
    }
    isProcessing = false;
  }

  const crawlOptions = [
    { label: m.basic_crawl(), value: "crawl" },
    { label: m.sitemap_based_crawl(), value: "sitemap" }
  ] as { label: string; value: Website["crawl_type"] }[];

  const updateOptions = [
    { label: m.never(), value: "never" },
    { label: m.every_day(), value: "daily" },
    { label: m.every_other_day(), value: "every_other_day" },
    { label: m.every_week(), value: "weekly" }
  ] as { label: string; value: Website["update_interval"] }[];
</script>

<Dialog.Root bind:isOpen={showDialog}>
  {#if mode === "create"}
    <Dialog.Trigger asFragment let:trigger>
      <Button variant="primary" is={trigger}>{m.connect_website()}</Button>
    </Dialog.Trigger>
  {/if}

  <Dialog.Content width="medium" form>
    {#if mode === "create"}
      <Dialog.Title>{m.create_website_integration()}</Dialog.Title>
    {:else}
      <Dialog.Title>{m.edit_website_integration()}</Dialog.Title>
    {/if}

    <Dialog.Section>
      {#if $currentSpace.embedding_models.length < 1 && mode === "create"}
        <p
          class="label-warning border-label-default bg-label-dimmer text-label-stronger m-4 rounded-md border px-2 py-1 text-sm"
        >
          <span class="font-bold">{m.warning()}:</span>
          {m.warning_no_embedding_models()}
        </p>
        <div class="border-default border-t"></div>
      {/if}

      <Input.Text
        bind:value={editableWebsite.url}
        label={m.url_required()}
        description={editableWebsite.crawl_type === "sitemap"
          ? m.full_url_sitemap()
          : m.url_description()}
        type="url"
        required
        placeholder={editableWebsite.crawl_type === "sitemap"
          ? "https://example.com/sitemap.xml"
          : "https://example.com"}
        class="border-default hover:bg-hover-dimmer border-b p-4"
        bind:isValid={validUrl}
      ></Input.Text>

      <Input.Text
        label={m.display_name()}
        class="border-default hover:bg-hover-dimmer border-b p-4"
        description={m.display_name_optional()}
        bind:value={websiteName}
        placeholder={editableWebsite.url.split("//")[1] ?? editableWebsite.url}
      ></Input.Text>

      <!-- HTTP Basic Authentication -->
      <Input.Switch
        bind:value={httpAuthEnabled}
        class="border-default hover:bg-hover-dimmer p-4 px-6"
      >
        {m.requires_http_auth()}
      </Input.Switch>

      {#if httpAuthEnabled}
        <div class="bg-info-dimmer border-info-default text-info-stronger m-4 rounded-md border px-3 py-2 text-sm">
          <span class="font-medium">{m.security_note()}</span>
          {m.credentials_encrypted_securely()}
        </div>

        {#if website?.requires_http_auth}
          <div class="m-4 flex items-center gap-2 text-sm text-positive-stronger">
            <svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clip-rule="evenodd" />
            </svg>
            {m.authentication_configured()}
          </div>
        {/if}

        <Input.Text
          bind:value={httpAuthUsername}
          label={m.username()}
          description={m.http_auth_username_description()}
          required={httpAuthEnabled}
          placeholder={m.enter_username()}
          autocomplete="username"
          class="border-default hover:bg-hover-dimmer border-b p-4"
        />

        <div class="relative">
          <Input.Text
            bind:value={httpAuthPassword}
            label={m.password()}
            description={website ? m.leave_blank_keep_password() : m.http_auth_password_description()}
            type={showPassword ? "text" : "password"}
            required={httpAuthEnabled && !website?.requires_http_auth}
            placeholder={m.enter_password()}
            autocomplete="current-password"
            class="border-default hover:bg-hover-dimmer border-b p-4"
          />
          <button
            type="button"
            class="absolute right-6 top-12 p-1 text-dimmer hover:text-default"
            onclick={() => showPassword = !showPassword}
            aria-label={showPassword ? m.hide_password() : m.show_password()}
          >
            {#if showPassword}
              <!-- Eye slash icon -->
              <svg class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M3.28 2.22a.75.75 0 00-1.06 1.06l14.5 14.5a.75.75 0 101.06-1.06l-1.745-1.745a10.029 10.029 0 003.3-4.38 1.651 1.651 0 000-1.185A10.004 10.004 0 009.999 3a9.956 9.956 0 00-4.744 1.194L3.28 2.22zM7.752 6.69l1.092 1.092a2.5 2.5 0 013.374 3.373l1.091 1.092a4 4 0 00-5.557-5.557z" clip-rule="evenodd" />
                <path d="M10.748 13.93l2.523 2.523a9.987 9.987 0 01-3.27.547c-4.258 0-7.894-2.66-9.337-6.41a1.651 1.651 0 010-1.186A10.007 10.007 0 012.839 6.02L6.07 9.252a4 4 0 004.678 4.678z" />
              </svg>
            {:else}
              <!-- Eye icon -->
              <svg class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                <path d="M10 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5z" />
                <path fill-rule="evenodd" d="M.664 10.59a1.651 1.651 0 010-1.186A10.004 10.004 0 0110 3c4.257 0 7.893 2.66 9.336 6.41.147.381.146.804 0 1.186A10.004 10.004 0 0110 17c-4.257 0-7.893-2.66-9.336-6.41zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clip-rule="evenodd" />
              </svg>
            {/if}
          </button>
        </div>

        {#if website?.requires_http_auth}
          <div class="m-4">
            <button
              type="button"
              class="text-sm text-negative-default hover:text-negative-stronger"
              onclick={handleRemoveAuth}
            >
              {m.remove_authentication()}
            </button>
          </div>
        {/if}
      {/if}

      <div class="flex">
        <Select.Simple
          class="border-default hover:bg-hover-dimmer w-1/2 border-b px-4 py-4"
          options={crawlOptions}
          bind:value={editableWebsite.crawl_type}>{m.crawl_type()}</Select.Simple
        >

        <Select.Simple
          class="border-default hover:bg-hover-dimmer w-1/2 border-b px-4 py-4"
          options={updateOptions}
          bind:value={editableWebsite.update_interval}>{m.automatic_updates()}</Select.Simple
        >
      </div>

      {#if editableWebsite.crawl_type !== "sitemap"}
        <Input.Switch
          bind:value={editableWebsite.download_files}
          class="border-default hover:bg-hover-dimmer p-4 px-6"
        >
          {m.download_analyse_files()}
        </Input.Switch>
      {:else}
        <Tooltip text={m.option_only_basic_crawls()}>
          <Input.Switch
            disabled
            bind:value={editableWebsite.download_files}
            class="border-default hover:bg-hover-dimmer p-4 px-6 opacity-40"
          >
            {m.download_analyse_files()}
          </Input.Switch>
        </Tooltip>
      {/if}

      {#if mode === "create"}
        <div class="border-default border-t"></div>
        <SelectEmbeddingModel
          hideWhenNoOptions
          bind:value={editableWebsite.embedding_model}
          selectableModels={$currentSpace.embedding_models}
        ></SelectEmbeddingModel>
      {/if}
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      {#if mode === "create"}
        <Button
          variant="primary"
          on:click={createWebsite}
          type="submit"
          disabled={isProcessing || $currentSpace.embedding_models.length === 0}
          >{isProcessing ? m.creating() : m.create_website()}</Button
        >
      {:else if mode === "update"}
        <Button variant="primary" on:click={updateWebsite} disabled={isProcessing}
          >{isProcessing ? m.saving() : m.save_changes()}</Button
        >
      {/if}
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
