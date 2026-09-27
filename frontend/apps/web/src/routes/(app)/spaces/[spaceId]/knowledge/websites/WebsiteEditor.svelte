<script lang="ts">
  import { makeEditable } from "$lib/core/editable";
  import { getEneo } from "$lib/core/Eneo";
  import SelectEmbeddingModel from "$lib/features/ai-models/components/SelectEmbeddingModel.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { type Website } from "@eneo/eneo-js";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { useId } from "bits-ui";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { tick } from "svelte";
  import { writable, type Writable } from "svelte/store";

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

  const eneo = getEneo();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  export let mode: "update" | "create" = "create";
  export let website: Omit<Website, "embedding_model"> & {
    embedding_model?: { id: string } | null;
  } = emptyWebsite();
  export let showDialog: Writable<boolean> = writable(false);

  let editableWebsite = makeEditable(website);
  let websiteName = website.name ?? "";
  let isProcessing = false;
  let validUrl = false;

  const urlId = useId();
  const nameId = useId();
  const httpAuthId = useId();
  const usernameId = useId();
  const passwordId = useId();
  const downloadFilesId = useId();
  const crawlTypeId = useId();
  const updateIntervalId = useId();

  // HTTP Basic Authentication state
  let httpAuthEnabled = website?.requires_http_auth ?? false;
  let httpAuthUsername = "";
  let httpAuthPassword = "";
  let showPassword = false;

  // Duplicate URL warning state
  type ExistingWebsite = {
    website_id: string;
    space_id: string;
    space_name: string;
    url: string;
    name: string | null;
    update_interval: string;
    last_crawled_at: string | null;
    pages_crawled: number | null;
    pages_failed: number | null;
    files_downloaded: number | null;
    files_failed: number | null;
    crawl_status: string | null;
  };
  let existingOnOrg: ExistingWebsite | null = null;
  let showDuplicateWarning: Writable<boolean> = writable(false);
  let duplicateCheckPending = false;

  async function checkUrlBeforeCreate() {
    console.log("=== checkUrlBeforeCreate START ===");
    console.log("validUrl:", validUrl);
    console.log("organization:", $currentSpace.organization);
    console.log("url:", editableWebsite.url);

    if (!validUrl) {
      console.log("URL is not valid, skipping");
      return;
    }

    if ($currentSpace.organization) {
      // Skip check on organization space
      console.log("On organization space, creating directly");
      await createWebsite();
      return;
    }

    duplicateCheckPending = true;
    try {
      console.log("Checking URL:", editableWebsite.url);
      existingOnOrg = (await eneo.websites.checkUrl(
        editableWebsite.url
      )) as unknown as ExistingWebsite | null;
      console.log("Check result:", existingOnOrg);
      if (existingOnOrg) {
        // Show warning modal on top of the main dialog
        console.log("Duplicate found, showing warning modal");
        showDuplicateWarning.set(true);
        await tick();
      } else {
        // No duplicate, proceed with creation
        console.log("No duplicate, creating website");
        await createWebsite();
      }
    } catch (e) {
      // On error, just proceed with creation
      console.error("Failed to check URL:", e);
      await createWebsite();
    } finally {
      duplicateCheckPending = false;
    }
  }

  function formatUpdateInterval(interval: string): string {
    switch (interval) {
      case "daily":
        return m.every_day();
      case "every_other_day":
        return m.every_other_day();
      case "weekly":
        return m.every_week();
      default:
        return m.never();
    }
  }

  function formatDateTime(dateString: string | null): string {
    if (!dateString) return m.website_not_yet_crawled();
    const date = new Date(dateString);
    return `${date.toLocaleDateString()} ${date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}`;
  }

  function formatCrawlResult(
    website: ExistingWebsite
  ): { text: string; hasFailures: boolean } | null {
    // If crawl is in progress
    if (website.crawl_status === "in progress" || website.crawl_status === "queued") {
      return { text: m.website_crawl_in_progress(), hasFailures: false };
    }

    // pages_crawled and files_downloaded are TOTAL counts (successful + failed)
    const totalPages = website.pages_crawled ?? 0;
    const pagesFailed = website.pages_failed ?? 0;
    const pagesSuccess = totalPages - pagesFailed;

    const totalFiles = website.files_downloaded ?? 0;
    const filesFailed = website.files_failed ?? 0;
    const filesSuccess = totalFiles - filesFailed;

    // No data available
    if (totalPages === 0 && totalFiles === 0) {
      return null;
    }

    const hasFailures = pagesFailed > 0 || filesFailed > 0;

    // Only pages, no files
    if (totalFiles === 0) {
      if (pagesFailed === 0) {
        return {
          text: m.website_all_pages_indexed({ count: pagesSuccess.toString() }),
          hasFailures: false
        };
      }
      return {
        text: m.website_pages_indexed({
          success: pagesSuccess.toString(),
          total: totalPages.toString()
        }),
        hasFailures: true
      };
    }

    // Both pages and files
    return {
      text: m.website_pages_indexed_with_files({
        successPages: pagesSuccess.toString(),
        totalPages: totalPages.toString(),
        successFiles: filesSuccess.toString(),
        totalFiles: totalFiles.toString()
      }),
      hasFailures
    };
  }

  // Clear credentials when auth is disabled
  $: if (!httpAuthEnabled) {
    httpAuthUsername = "";
    httpAuthPassword = "";
  }

  function handleRemoveAuth() {
    httpAuthEnabled = false;
    httpAuthUsername = "";
    httpAuthPassword = "";
  }

  async function updateWebsite() {
    isProcessing = true;
    try {
      let edits = editableWebsite.getEdits();
      edits.name = websiteName === "" ? null : websiteName;

      // Handle HTTP auth fields
      const editsAny = edits as Record<string, unknown>;
      if (httpAuthEnabled && httpAuthUsername) {
        editsAny.http_auth_username = httpAuthUsername;
        if (httpAuthPassword) {
          editsAny.http_auth_password = httpAuthPassword;
        }
      } else if (!httpAuthEnabled && website?.requires_http_auth) {
        // Remove auth if it was previously enabled
        editsAny.http_auth_username = null;
        editsAny.http_auth_password = null;
      }

      const updated = await eneo.websites.update({ website: { id: website.id }, update: edits });
      editableWebsite.updateWithValue(updated);
      refreshCurrentSpace();
      $showDialog = false;
    } catch (e) {
      toastError(e);
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
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
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

      await eneo.websites.create(websiteData);
      editableWebsite.updateWithValue(emptyWebsite());
      websiteName = "";
      httpAuthEnabled = false;
      httpAuthUsername = "";
      httpAuthPassword = "";
      refreshCurrentSpace();
      $showDialog = false;
    } catch (e) {
      toastError(e);
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

<Dialog.Root bind:open={$showDialog}>
  {#if mode === "create"}
    <Dialog.Trigger>
      {#snippet child({ props })}
        <Button {...props}>{m.connect_website()}</Button>
      {/snippet}
    </Dialog.Trigger>
  {/if}

  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <form
      class="contents"
      onsubmit={(event) => {
        event.preventDefault();
        if (mode === "create") checkUrlBeforeCreate();
        else updateWebsite();
      }}
    >
      <Dialog.Header class={dialogLayout.header}>
        {#if mode === "create"}
          <Dialog.Title>{m.create_website_integration()}</Dialog.Title>
        {:else}
          <Dialog.Title>{m.edit_website_integration()}</Dialog.Title>
        {/if}
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <div class={dialogLayout.section}>
          {#if $currentSpace.embedding_models.length < 1 && mode === "create"}
            <p
              class="label-warning border-label-default bg-label-dimmer text-label-stronger m-4 rounded-md border px-2 py-1 text-sm"
            >
              <span class="font-bold">{m.warning()}:</span>
              {m.warning_no_embedding_models()}
            </p>
            <div class="border-default border-t"></div>
          {/if}

          <Field.Field class="border-default hover:bg-hover-dimmer border-b p-4">
            <Field.Label for={urlId}>{m.url_required()}</Field.Label>
            <Input
              id={urlId}
              bind:value={editableWebsite.url}
              type="url"
              required
              placeholder={editableWebsite.crawl_type === "sitemap"
                ? "https://example.com/sitemap.xml"
                : "https://example.com"}
              aria-describedby={`${urlId}-description`}
              oninput={(e) => (validUrl = e.currentTarget.validity.valid)}
            />
            <Field.Description id={`${urlId}-description`}>
              {editableWebsite.crawl_type === "sitemap"
                ? m.full_url_sitemap()
                : m.url_description()}
            </Field.Description>
          </Field.Field>

          <Field.Field class="border-default hover:bg-hover-dimmer border-b p-4">
            <Field.Label for={nameId}>{m.display_name()}</Field.Label>
            <Input
              id={nameId}
              bind:value={websiteName}
              placeholder={editableWebsite.url.split("//")[1] ?? editableWebsite.url}
              aria-describedby={`${nameId}-description`}
            />
            <Field.Description id={`${nameId}-description`}>
              {m.display_name_optional()}
            </Field.Description>
          </Field.Field>

          <!-- HTTP Basic Authentication -->
          <Field.Field
            orientation="horizontal"
            class="border-default hover:bg-hover-dimmer p-4 px-6"
          >
            <Field.Label for={httpAuthId}>{m.requires_http_auth()}</Field.Label>
            <Switch id={httpAuthId} bind:checked={httpAuthEnabled} />
          </Field.Field>

          {#if httpAuthEnabled}
            <div
              class="label-info border-label-default bg-label-dimmer text-label-stronger m-4 rounded-md border px-3 py-2 text-sm"
            >
              <span class="font-medium">{m.security_note()}</span>
              {m.credentials_encrypted_securely()}
            </div>

            {#if website?.requires_http_auth}
              <div class="text-positive-stronger m-4 flex items-center gap-2 text-sm">
                <svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                  <path
                    fill-rule="evenodd"
                    d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z"
                    clip-rule="evenodd"
                  />
                </svg>
                {m.authentication_configured()}
              </div>
            {/if}

            <Field.Field class="border-default hover:bg-hover-dimmer border-b p-4">
              <Field.Label for={usernameId}>
                {m.username()}
                {#if httpAuthEnabled && !website?.requires_http_auth}
                  <span class="text-muted font-normal" aria-hidden="true">({m.required()})</span>
                {/if}
              </Field.Label>
              <Input
                id={usernameId}
                bind:value={httpAuthUsername}
                required={httpAuthEnabled && !website?.requires_http_auth}
                placeholder={m.enter_username()}
                autocomplete="username"
                aria-describedby={`${usernameId}-description`}
              />
              <Field.Description id={`${usernameId}-description`}>
                {m.http_auth_username_description()}
              </Field.Description>
            </Field.Field>

            <div class="relative">
              <Field.Field class="border-default hover:bg-hover-dimmer border-b p-4">
                <Field.Label for={passwordId}>
                  {m.password()}
                  {#if httpAuthEnabled && !website?.requires_http_auth}
                    <span class="text-muted font-normal" aria-hidden="true">({m.required()})</span>
                  {/if}
                </Field.Label>
                <Input
                  id={passwordId}
                  bind:value={httpAuthPassword}
                  type={showPassword ? "text" : "password"}
                  required={httpAuthEnabled && !website?.requires_http_auth}
                  placeholder={m.enter_password()}
                  autocomplete="current-password"
                  aria-describedby={`${passwordId}-description`}
                />
                <Field.Description id={`${passwordId}-description`}>
                  {website ? m.leave_blank_keep_password() : m.http_auth_password_description()}
                </Field.Description>
              </Field.Field>
              <button
                type="button"
                class="text-muted hover:text-default absolute top-11 right-6 p-1"
                onclick={() => (showPassword = !showPassword)}
                aria-label={showPassword ? m.hide_password() : m.show_password()}
              >
                {#if showPassword}
                  <!-- Eye slash icon -->
                  <svg class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                    <path
                      fill-rule="evenodd"
                      d="M3.28 2.22a.75.75 0 00-1.06 1.06l14.5 14.5a.75.75 0 101.06-1.06l-1.745-1.745a10.029 10.029 0 003.3-4.38 1.651 1.651 0 000-1.185A10.004 10.004 0 009.999 3a9.956 9.956 0 00-4.744 1.194L3.28 2.22zM7.752 6.69l1.092 1.092a2.5 2.5 0 013.374 3.373l1.091 1.092a4 4 0 00-5.557-5.557z"
                      clip-rule="evenodd"
                    />
                    <path
                      d="M10.748 13.93l2.523 2.523a9.987 9.987 0 01-3.27.547c-4.258 0-7.894-2.66-9.337-6.41a1.651 1.651 0 010-1.186A10.007 10.007 0 012.839 6.02L6.07 9.252a4 4 0 004.678 4.678z"
                    />
                  </svg>
                {:else}
                  <!-- Eye icon -->
                  <svg class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                    <path d="M10 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5z" />
                    <path
                      fill-rule="evenodd"
                      d="M.664 10.59a1.651 1.651 0 010-1.186A10.004 10.004 0 0110 3c4.257 0 7.893 2.66 9.336 6.41.147.381.146.804 0 1.186A10.004 10.004 0 0110 17c-4.257 0-7.893-2.66-9.336-6.41zM14 10a4 4 0 11-8 0 4 4 0 018 0z"
                      clip-rule="evenodd"
                    />
                  </svg>
                {/if}
              </button>
            </div>

            {#if website?.requires_http_auth}
              <div class="m-4">
                <button
                  type="button"
                  class="text-negative-default hover:text-negative-stronger text-sm"
                  onclick={handleRemoveAuth}
                >
                  {m.remove_authentication()}
                </button>
              </div>
            {/if}
          {/if}

          <div class="flex">
            <Field.Field class="border-default hover:bg-hover-dimmer w-1/2 border-b px-4 py-4">
              <Field.Label for={crawlTypeId}>{m.crawl_type()}</Field.Label>
              <Select.Root
                type="single"
                value={editableWebsite.crawl_type}
                onValueChange={(key) =>
                  (editableWebsite.crawl_type =
                    crawlOptions.find((option) => option.value === key)?.value ??
                    editableWebsite.crawl_type)}
              >
                <Select.Trigger id={crawlTypeId} class="w-full">
                  {crawlOptions.find((option) => option.value === editableWebsite.crawl_type)
                    ?.label ?? m.ui_select_placeholder()}
                </Select.Trigger>
                <Select.Content>
                  {#each crawlOptions as option (option.value)}
                    <Select.Item value={option.value} label={option.label}
                      >{option.label}</Select.Item
                    >
                  {/each}
                </Select.Content>
              </Select.Root>
            </Field.Field>

            <Field.Field class="border-default hover:bg-hover-dimmer w-1/2 border-b px-4 py-4">
              <Field.Label for={updateIntervalId}>{m.automatic_updates()}</Field.Label>
              <Select.Root
                type="single"
                value={editableWebsite.update_interval}
                onValueChange={(key) =>
                  (editableWebsite.update_interval =
                    updateOptions.find((option) => option.value === key)?.value ??
                    editableWebsite.update_interval)}
              >
                <Select.Trigger id={updateIntervalId} class="w-full">
                  {updateOptions.find((option) => option.value === editableWebsite.update_interval)
                    ?.label ?? m.ui_select_placeholder()}
                </Select.Trigger>
                <Select.Content>
                  {#each updateOptions as option (option.value)}
                    <Select.Item value={option.value} label={option.label}
                      >{option.label}</Select.Item
                    >
                  {/each}
                </Select.Content>
              </Select.Root>
            </Field.Field>
          </div>

          {#if editableWebsite.crawl_type !== "sitemap"}
            <Field.Field
              orientation="horizontal"
              class="border-default hover:bg-hover-dimmer p-4 px-6"
            >
              <Field.Label for={downloadFilesId}>{m.download_analyse_files()}</Field.Label>
              <Switch
                id={downloadFilesId}
                checked={editableWebsite.download_files ?? false}
                onCheckedChange={(next) => (editableWebsite.download_files = next)}
              />
            </Field.Field>
          {:else}
            <Tooltip.Root>
              <Tooltip.Trigger>
                {#snippet child({ props })}
                  <div {...props}>
                    <Field.Field
                      orientation="horizontal"
                      class="border-default hover:bg-hover-dimmer p-4 px-6 opacity-40"
                    >
                      <Field.Label for={downloadFilesId}>{m.download_analyse_files()}</Field.Label>
                      <Switch
                        id={downloadFilesId}
                        disabled
                        checked={editableWebsite.download_files ?? false}
                      />
                    </Field.Field>
                  </div>
                {/snippet}
              </Tooltip.Trigger>
              <Tooltip.Content>{m.option_only_basic_crawls()}</Tooltip.Content>
            </Tooltip.Root>
          {/if}

          {#if mode === "create"}
            <div class="border-default border-t"></div>
            <SelectEmbeddingModel
              hideWhenNoOptions
              bind:value={editableWebsite.embedding_model}
              selectableModels={$currentSpace.embedding_models}
            ></SelectEmbeddingModel>
          {/if}
        </div>
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
        {#if mode === "create"}
          <Button
            type="submit"
            disabled={isProcessing ||
              duplicateCheckPending ||
              $currentSpace.embedding_models.length === 0}
            >{isProcessing || duplicateCheckPending ? m.creating() : m.create_website()}</Button
          >
        {:else if mode === "update"}
          <Button type="submit" disabled={isProcessing}
            >{isProcessing ? m.saving() : m.save_changes()}</Button
          >
        {/if}
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>

<!-- Duplicate URL Warning Modal -->
<ConfirmDialog
  bind:open={$showDuplicateWarning}
  title={m.website_exists_on_org()}
  description={existingOnOrg
    ? m.website_exists_on_org_description({ spaceName: existingOnOrg.space_name })
    : undefined}
  confirmLabel={m.create_anyway()}
  pendingLabel={m.creating()}
  cancelLabel={m.go_back()}
  variant="default"
  onConfirm={createWebsite}
>
  {#if existingOnOrg}
    {@const crawlResult = formatCrawlResult(existingOnOrg)}
    <div class="{dialogLayout.section} p-4">
      <div class="bg-hover-dimmer border-default rounded-lg border p-4">
        <div class="flex items-start gap-3">
          <div class="text-warning-default mt-0.5 flex-shrink-0">
            <svg class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path
                fill-rule="evenodd"
                d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z"
                clip-rule="evenodd"
              />
            </svg>
          </div>
          <div class="flex-1">
            <div class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <span class="text-muted">{m.website_last_crawled()}:</span>
              <span>{formatDateTime(existingOnOrg.last_crawled_at)}</span>

              {#if crawlResult}
                <span class="text-muted">{m.website_crawl_result()}:</span>
                <span
                  class={crawlResult.hasFailures
                    ? "text-warning-stronger"
                    : "text-positive-stronger"}
                >
                  {crawlResult.text}
                </span>
              {/if}

              <span class="text-muted">{m.website_sync_interval()}:</span>
              <span>{formatUpdateInterval(existingOnOrg.update_interval)}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  {/if}
</ConfirmDialog>
