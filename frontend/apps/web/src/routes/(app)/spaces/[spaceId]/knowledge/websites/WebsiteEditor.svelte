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

  async function updateWebsite() {
    isProcessing = true;
    try {
      let edits = editableWebsite.getEdits();
      edits.name = websiteName === "" ? null : websiteName;
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
      await intric.websites.create({
        spaceId: $currentSpace.id,
        ...editableWebsite,
        name: websiteName === "" ? null : websiteName
      });
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
    { label: m.basic_crawl(), value: "crawl" },
    { label: m.sitemap_based_crawl(), value: "sitemap" }
  ] as { label: string; value: Website["crawl_type"] }[];

  const updateOptions = [
    { label: m.never(), value: "never" },
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
