<script lang="ts">
  import { makeEditable } from "$lib/core/editable";
  import { getIntric } from "$lib/core/Intric";
  import SelectEmbeddingModel from "$lib/features/ai-models/components/SelectEmbeddingModel.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { type Website } from "@intric/intric-js";
  import { Dialog, Button, Input, Select, Tooltip } from "@intric/ui";

  const emptyWebsite = () => {
    return {
      name: null,
      url: "",
      crawl_type: "crawl",
      download_files: undefined,
      embedding_model: undefined,
      update_interval: "never",
      requires_auth: false,
      auth_username: "",
      auth_password: ""
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
  let authFieldsValid = true;

  // Validate auth fields when they change
  $: authFieldsValid = !editableWebsite.requires_auth || 
    (editableWebsite.auth_username?.trim() && editableWebsite.auth_password?.trim());

  async function updateWebsite() {
    isProcessing = true;
    try {
      let edits = editableWebsite.getEdits();
      edits.name = websiteName === "" ? null : websiteName;
      
      // Only send auth fields if authentication is required
      if (!editableWebsite.requires_auth) {
        edits.auth_username = null;
        edits.auth_password = null;
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
      const websiteData = {
        spaceId: $currentSpace.id,
        ...editableWebsite,
        name: websiteName === "" ? null : websiteName
      };
      
      // Only send auth fields if authentication is required
      if (!editableWebsite.requires_auth) {
        delete websiteData.auth_username;
        delete websiteData.auth_password;
      }
      
      await intric.websites.create(websiteData);
      editableWebsite.updateWithValue(emptyWebsite());
      websiteName = "";
      refreshCurrentSpace();
      $showDialog = false;
    } catch (e) {
      alert(e);
      console.error(e);
    }
    isProcessing = false;
  }

  const crawlOptions = [
    { label: "Basic crawl", value: "crawl" },
    { label: "Sitemap based crawl", value: "sitemap" }
  ] as { label: string; value: Website["crawl_type"] }[];

  const updateOptions = [
    { label: "Never", value: "never" },
    { label: "Daily", value: "daily" },
    { label: "Every other day", value: "every_other_day" },
    { label: "Weekly", value: "weekly" }
  ] as { label: string; value: Website["update_interval"] }[];
</script>

<Dialog.Root bind:isOpen={showDialog}>
  {#if mode === "create"}
    <Dialog.Trigger asFragment let:trigger>
      <Button variant="primary" is={trigger}>Connect website</Button>
    </Dialog.Trigger>
  {/if}

  <Dialog.Content width="medium" form>
    {#if mode === "create"}
      <Dialog.Title>Create a website integration</Dialog.Title>
    {:else}
      <Dialog.Title>Edit website integration</Dialog.Title>
    {/if}

    <Dialog.Section>
      {#if $currentSpace.embedding_models.length < 1 && mode === "create"}
        <p
          class="label-warning border-label-default bg-label-dimmer text-label-stronger m-4 rounded-md border px-2 py-1 text-sm"
        >
          <span class="font-bold">Warning:</span>
          This space does currently not have any embedding models enabled. Enable at least one embedding
          model to be able to connect to a website.
        </p>
        <div class="border-default border-t"></div>
      {/if}

      <Input.Text
        bind:value={editableWebsite.url}
        label="URL"
        description={editableWebsite.crawl_type === "sitemap"
          ? "Full URL to your sitemap.xml file"
          : "URL from where to start indexing (including https://)"}
        type="url"
        required
        placeholder={editableWebsite.crawl_type === "sitemap"
          ? "https://example.com/sitemap.xml"
          : "https://example.com"}
        class="border-default hover:bg-hover-dimmer border-b p-4"
        bind:isValid={validUrl}
      ></Input.Text>

      <Input.Text
        label="Display name"
        class="border-default hover:bg-hover-dimmer border-b p-4"
        description="Optional, will default to the website's URL"
        bind:value={websiteName}
        placeholder={editableWebsite.url.split("//")[1] ?? editableWebsite.url}
      ></Input.Text>

      <Input.Switch
        bind:value={editableWebsite.requires_auth}
        class="border-default hover:bg-hover-dimmer p-4 px-6"
      >
        Requires basic authentication
      </Input.Switch>

      {#if editableWebsite.requires_auth}
        <div class="bg-info-dimmer border-info-default text-info-stronger m-4 rounded-md border px-3 py-2 text-sm">
          <span class="font-medium">Security Note:</span>
          Credentials are encrypted and stored securely. They will only be used for crawling this website.
        </div>
        
        <Input.Text
          bind:value={editableWebsite.auth_username}
          label="Username"
          description="Username for basic authentication"
          required={editableWebsite.requires_auth}
          placeholder="Enter username"
          class="border-default hover:bg-hover-dimmer border-b p-4"
        ></Input.Text>

        <Input.Text
          bind:value={editableWebsite.auth_password}
          label="Password"
          description="Password for basic authentication"
          type="password"
          required={editableWebsite.requires_auth}
          placeholder="Enter password"
          class="border-default hover:bg-hover-dimmer border-b p-4"
        ></Input.Text>
      {/if}

      <div class="flex">
        <Select.Simple
          class="border-default hover:bg-hover-dimmer w-1/2 border-b px-4 py-4"
          options={crawlOptions}
          bind:value={editableWebsite.crawl_type}>Crawl type</Select.Simple
        >

        <Select.Simple
          class="border-default hover:bg-hover-dimmer w-1/2 border-b px-4 py-4"
          options={updateOptions}
          bind:value={editableWebsite.update_interval}>Automatic updates</Select.Simple
        >
      </div>

      {#if editableWebsite.crawl_type !== "sitemap"}
        <Input.Switch
          bind:value={editableWebsite.download_files}
          class="border-default hover:bg-hover-dimmer p-4 px-6"
        >
          Download and analyse compatible files
        </Input.Switch>
      {:else}
        <Tooltip text="This option is only available for basic crawls">
          <Input.Switch
            disabled
            bind:value={editableWebsite.download_files}
            class="border-default hover:bg-hover-dimmer p-4 px-6 opacity-40"
          >
            Download and analyse compatible files
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
      <Button is={close}>Cancel</Button>
      {#if mode === "create"}
        <Button
          variant="primary"
          on:click={createWebsite}
          type="submit"
          disabled={isProcessing || $currentSpace.embedding_models.length === 0 || !authFieldsValid}
          >{isProcessing ? "Creating..." : "Create website"}</Button
        >
      {:else if mode === "update"}
        <Button variant="primary" on:click={updateWebsite} disabled={isProcessing || !authFieldsValid}
          >{isProcessing ? "Saving..." : "Save changes"}</Button
        >
      {/if}
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
