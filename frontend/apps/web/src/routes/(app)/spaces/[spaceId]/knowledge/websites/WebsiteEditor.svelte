<script lang="ts">
  import { makeEditable } from "$lib/core/editable";
  import { getIntric } from "$lib/core/Intric";
  import SelectEmbeddingModel from "$lib/features/ai-models/components/SelectEmbeddingModel.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { type Website, type JSONRequestBody } from "@intric/intric-js";
  import { Dialog, Button, Input, Select, Tooltip } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { tick } from "svelte";
  import { writable, type Writable } from "svelte/store";

  type WebsiteCreatePayload = Omit<JSONRequestBody<"post", "/api/v1/websites/">, "space_id"> & {
    spaceId?: string;
  };

  const emptyWebsite = () => {
    return {
      name: null,
      url: "",
      crawl_type: "crawl",
      download_files: undefined,
      embedding_model: undefined,
      update_interval: "never",
      integration: undefined
    } as unknown as Website;
  };

  const intric = getIntric();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  type WebsiteEditorProps = {
    mode?: "update" | "create";
    website?: Omit<Website, "embedding_model"> & {
      embedding_model?: { id: string } | null;
      integration?: {
        sync_url: string;
        sitemap_url: string;
        markdown_endpoint_url?: string | null;
        markdown_endpoint_method: "get" | "post";
        markdown_endpoint_url_location: "query" | "body";
        markdown_endpoint_url_param_name: string;
        headers: Array<{ key: string; value: string }>;
        sync_status: string;
      } | null;
    };
    showDialog?: Dialog.OpenState;
  };

  let {
    mode = "create",
    website = emptyWebsite(),
    showDialog = $bindable(undefined)
  }: WebsiteEditorProps = $props();

  let editableWebsite = makeEditable(website);
  let websiteName = website.name ?? "";
  let isProcessing = false;
  let validUrl = false;

  // HTTP Basic Authentication state
  let httpAuthEnabled = website?.requires_http_auth ?? false;
  let httpAuthUsername = "";
  let httpAuthPassword = "";
  let showPassword = false;
  let integrationSitemapUrl = $state(website?.integration?.sitemap_url ?? "");
  let integrationMarkdownEndpointUrl = $state(website?.integration?.markdown_endpoint_url ?? "");
  let integrationMarkdownEndpointMethod = $state<"get" | "post">(
    website?.integration?.markdown_endpoint_method ?? "get"
  );
  let integrationMarkdownEndpointLocation = $state<"query" | "body">(
    website?.integration?.markdown_endpoint_url_location ?? "query"
  );
  let integrationMarkdownEndpointParamName = $state(
    website?.integration?.markdown_endpoint_url_param_name ?? "url"
  );
  let integrationHeaders = $state<Array<{ key: string; value: string }>>(
    website?.integration?.headers?.length
      ? website.integration.headers.map((header) => ({ ...header }))
      : [{ key: "", value: "" }]
  );
  let isWebsiteIntegration = $derived(Boolean(website?.integration));
  let createSourceType = $state<"crawl" | "integration">("crawl");
  let isCreatingIntegration = $derived(mode === "create" && createSourceType === "integration");

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

  function syncIntegrationEditorState() {
    integrationSitemapUrl = website?.integration?.sitemap_url ?? "";
    integrationMarkdownEndpointUrl = website?.integration?.markdown_endpoint_url ?? "";
    integrationMarkdownEndpointMethod = website?.integration?.markdown_endpoint_method ?? "get";
    integrationMarkdownEndpointLocation =
      website?.integration?.markdown_endpoint_url_location ?? "query";
    integrationMarkdownEndpointParamName =
      website?.integration?.markdown_endpoint_url_param_name ?? "url";
    integrationHeaders = website?.integration?.headers?.length
      ? website.integration.headers.map((header) => ({ ...header }))
      : [{ key: "", value: "" }];
  }

  async function checkUrlBeforeCreate() {
    if (!validUrl) {
      return;
    }

    if ($currentSpace.organization) {
      await createWebsite();
      return;
    }

    duplicateCheckPending = true;
    try {
      existingOnOrg = (await intric.websites.checkUrl(
        editableWebsite.url
      )) as unknown as ExistingWebsite | null;
      if (existingOnOrg) {
        showDuplicateWarning.set(true);
        await tick();
      } else {
        await createWebsite();
      }
    } catch (e) {
      console.error(e);
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
  $effect(() => {
    if (!httpAuthEnabled) {
      httpAuthUsername = "";
      httpAuthPassword = "";
    }
  });

  $effect(() => {
    if (website) {
      editableWebsite = makeEditable(website);
      websiteName = website.name ?? "";
      httpAuthEnabled = website.requires_http_auth ?? false;
      syncIntegrationEditorState();
    }
  });

  function handleRemoveAuth() {
    httpAuthEnabled = false;
    httpAuthUsername = "";
    httpAuthPassword = "";
  }

  function absoluteSyncUrl(syncUrl: string) {
    return new URL(syncUrl, intric.client.baseUrl).toString();
  }

  async function copySyncUrl(syncUrl: string) {
    try {
      await navigator.clipboard.writeText(absoluteSyncUrl(syncUrl));
    } catch (e) {
      toastError(e);
    }
  }

  async function syncWebsiteIntegration(syncUrl: string) {
    try {
      const response = await fetch(absoluteSyncUrl(syncUrl), {
        method: "POST",
        credentials: "include"
      });
      if (!response.ok) {
        throw new Error(m.sync_failed_with_status({ status: response.status.toString() }));
      }
      refreshCurrentSpace();
    } catch (e) {
      toastError(e);
    }
  }

  function addIntegrationHeaderRow() {
    integrationHeaders = [...integrationHeaders, { key: "", value: "" }];
  }

  function removeIntegrationHeaderRow(index: number) {
    integrationHeaders = integrationHeaders.filter((_, currentIndex) => currentIndex !== index);
    if (integrationHeaders.length === 0) {
      integrationHeaders = [{ key: "", value: "" }];
    }
  }

  function updateIntegrationHeader(index: number, field: "key" | "value", value: string) {
    integrationHeaders = integrationHeaders.map((header, currentIndex) =>
      currentIndex === index ? { ...header, [field]: value } : header
    );
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

      if (website?.integration) {
        editsAny.sitemap_url = integrationSitemapUrl;
        editsAny.markdown_endpoint_url =
          integrationMarkdownEndpointUrl.trim() === "" ? null : integrationMarkdownEndpointUrl;
        editsAny.markdown_endpoint_method = integrationMarkdownEndpointMethod;
        editsAny.markdown_endpoint_url_location = integrationMarkdownEndpointLocation;
        editsAny.markdown_endpoint_url_param_name = integrationMarkdownEndpointParamName;
        editsAny.headers = integrationHeaders
          .map((header) => ({
            key: header.key.trim(),
            value: header.value.trim()
          }))
          .filter((header) => header.key.length > 0);
      }

      const updated = await intric.websites.update({ website: { id: website.id }, update: edits });
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

      await intric.websites.create(websiteData);
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

  async function createWebsiteIntegration() {
    if (!$currentSpace.embedding_models.length || !editableWebsite.embedding_model) {
      return;
    }

    if (integrationSitemapUrl.trim() === "") {
      return;
    }

    isProcessing = true;
    try {
      const websiteIntegrationPayload: WebsiteCreatePayload = {
        spaceId: $currentSpace.id,
        name: websiteName === "" ? null : websiteName,
        sitemap_url: integrationSitemapUrl.trim(),
        markdown_endpoint_url:
          integrationMarkdownEndpointUrl.trim() === ""
            ? null
            : integrationMarkdownEndpointUrl.trim(),
        markdown_endpoint_method: integrationMarkdownEndpointMethod,
        markdown_endpoint_url_location: integrationMarkdownEndpointLocation,
        markdown_endpoint_url_param_name: integrationMarkdownEndpointParamName.trim() || "url",
        headers: integrationHeaders
          .map((header) => ({
            key: header.key.trim(),
            value: header.value.trim()
          }))
          .filter((header) => header.key.length > 0),
        embedding_model: editableWebsite.embedding_model
      };

      await intric.websites.create(websiteIntegrationPayload);

      editableWebsite.updateWithValue(emptyWebsite());
      websiteName = "";
      integrationSitemapUrl = "";
      integrationMarkdownEndpointUrl = "";
      integrationMarkdownEndpointMethod = "get";
      integrationMarkdownEndpointLocation = "query";
      integrationMarkdownEndpointParamName = "url";
      integrationHeaders = [{ key: "", value: "" }];
      createSourceType = "crawl";
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

  const markdownMethodOptions = [
    { label: m.get_method(), value: "get" },
    { label: m.post_method(), value: "post" }
  ] as const;

  const markdownLocationOptions = [
    { label: m.query_parameter(), value: "query" },
    { label: m.request_body(), value: "body" }
  ] as const;

  $effect(() => {
    if (
      integrationMarkdownEndpointMethod === "get" &&
      integrationMarkdownEndpointLocation !== "query"
    ) {
      integrationMarkdownEndpointLocation = "query";
    }
  });
</script>

<Dialog.Root bind:isOpen={showDialog}>
  {#if mode === "create"}
    <Dialog.Trigger asFragment let:trigger>
      <Button variant="primary" is={trigger}>{m.connect_website()}</Button>
    </Dialog.Trigger>
  {/if}

  <Dialog.Content width="medium" form>
    {#if mode === "create"}
      <Dialog.Title>{m.create_website_source()}</Dialog.Title>
    {:else}
      <Dialog.Title>{m.edit_website_source()}</Dialog.Title>
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

      {#if mode === "create"}
        <Select.Simple
          class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
          bind:value={createSourceType}
          options={[
            { label: m.crawl_website(), value: "crawl" },
            { label: m.website_integration_sitemap(), value: "integration" }
          ]}
        >
          {m.source_type()}
        </Select.Simple>
      {/if}

      <Input.Text
        label={m.display_name()}
        class="border-default hover:bg-hover-dimmer border-b p-4"
        description={m.display_name_optional()}
        bind:value={websiteName}
        placeholder={isCreatingIntegration
          ? m.marketing_website()
          : (editableWebsite.url.split("//")[1] ?? editableWebsite.url)}
      ></Input.Text>

      {#if isCreatingIntegration}
        <Input.Text
          bind:value={integrationSitemapUrl}
          label={m.sitemap_url()}
          type="url"
          required
          placeholder={m.example_sitemap_url()}
          class="border-default hover:bg-hover-dimmer border-b p-4"
        />
        <Input.Text
          bind:value={integrationMarkdownEndpointUrl}
          label={m.markdown_endpoint_url()}
          description={m.markdown_endpoint_description()}
          class="border-default hover:bg-hover-dimmer border-b p-4"
        />

        {#if integrationMarkdownEndpointUrl.trim() !== ""}
          <div class="flex">
            <Select.Simple
              class="border-default hover:bg-hover-dimmer w-1/2 border-b px-4 py-4"
              options={markdownMethodOptions}
              bind:value={integrationMarkdownEndpointMethod}
            >
              {m.method()}
            </Select.Simple>
            <Select.Simple
              class="border-default hover:bg-hover-dimmer w-1/2 border-b px-4 py-4"
              options={markdownLocationOptions}
              bind:value={integrationMarkdownEndpointLocation}
              disabled={integrationMarkdownEndpointMethod === "get"}
            >
              {m.send_url_in()}
            </Select.Simple>
          </div>
          <Input.Text
            bind:value={integrationMarkdownEndpointParamName}
            label={m.url_parameter_name()}
            class="border-default hover:bg-hover-dimmer border-b p-4"
          />
        {/if}

        <div class="p-4">
          <div class="mb-3 flex items-center justify-between">
            <div>
              <div class="text-sm font-semibold">{m.headers()}</div>
              <div class="text-secondary text-xs">
                {m.headers_description()}
              </div>
            </div>
            <Button variant="outlined" type="button" onclick={addIntegrationHeaderRow}>
              {m.add_header()}
            </Button>
          </div>
          <div class="space-y-2">
            {#each integrationHeaders as header, index (index)}
              <div class="grid grid-cols-[1fr_1fr_auto] gap-2">
                <Input.Text
                  value={header.key}
                  placeholder={m.header_key()}
                  oninput={(event) =>
                    updateIntegrationHeader(index, "key", event.currentTarget.value)}
                />
                <Input.Text
                  value={header.value}
                  placeholder={m.header_value()}
                  oninput={(event) =>
                    updateIntegrationHeader(index, "value", event.currentTarget.value)}
                />
                <Button
                  variant="outlined"
                  type="button"
                  onclick={() => removeIntegrationHeaderRow(index)}
                >
                  {m.remove()}
                </Button>
              </div>
            {/each}
          </div>
        </div>
      {:else}
        <Input.Text
          bind:value={editableWebsite.url}
          label={m.url_required()}
          description={editableWebsite.crawl_type === "sitemap"
            ? m.full_url_sitemap()
            : m.url_description()}
          type="url"
          required
          placeholder={editableWebsite.crawl_type === "sitemap"
            ? m.example_sitemap_url()
            : m.example_website_url()}
          class="border-default hover:bg-hover-dimmer border-b p-4"
          bind:isValid={validUrl}
        ></Input.Text>

        <!-- HTTP Basic Authentication -->
        <Input.Switch
          bind:value={httpAuthEnabled}
          class="border-default hover:bg-hover-dimmer p-4 px-6"
        >
          {m.requires_http_auth()}
        </Input.Switch>

        {#if httpAuthEnabled}
          <div
            class="bg-info-dimmer border-info-default text-info-stronger m-4 rounded-md border px-3 py-2 text-sm"
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
              description={website
                ? m.leave_blank_keep_password()
                : m.http_auth_password_description()}
              type={showPassword ? "text" : "password"}
              required={httpAuthEnabled && !website?.requires_http_auth}
              placeholder={m.enter_password()}
              autocomplete="current-password"
              class="border-default hover:bg-hover-dimmer border-b p-4"
            />
            <button
              type="button"
              class="text-dimmer hover:text-default absolute top-12 right-6 p-1"
              onclick={() => (showPassword = !showPassword)}
              aria-label={showPassword ? m.hide_password() : m.show_password()}
            >
              {#if showPassword}
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
      {/if}

      {#if mode === "update" && website?.integration}
        <div class="border-default border-t"></div>
        <div class="p-4">
          <div class="mb-3 flex items-center justify-between gap-3">
            <div>
              <div class="text-sm font-semibold">{m.website_integration_label()}</div>
              <div class="text-secondary text-xs">
                {m.sync_status_value({ status: website.integration.sync_status })}
              </div>
            </div>
            <div class="flex gap-2">
              <Button
                variant="outlined"
                type="button"
                onclick={() => copySyncUrl(website.integration.sync_url)}
              >
                {m.copy_sync_url()}
              </Button>
              <Button
                variant="outlined"
                type="button"
                onclick={() => syncWebsiteIntegration(website.integration.sync_url)}
              >
                {m.sync_now()}
              </Button>
            </div>
          </div>
          <div class="text-secondary text-xs break-all">
            {absoluteSyncUrl(website.integration.sync_url)}
          </div>
        </div>

        <Input.Text
          bind:value={integrationSitemapUrl}
          label={m.sitemap_url()}
          type="url"
          required
          class="border-default hover:bg-hover-dimmer border-b p-4"
        />
        <Input.Text
          bind:value={integrationMarkdownEndpointUrl}
          label={m.markdown_endpoint_url()}
          description={m.markdown_endpoint_description()}
          class="border-default hover:bg-hover-dimmer border-b p-4"
        />

        {#if integrationMarkdownEndpointUrl.trim() !== ""}
          <div class="flex">
            <Select.Simple
              class="border-default hover:bg-hover-dimmer w-1/2 border-b px-4 py-4"
              options={markdownMethodOptions}
              bind:value={integrationMarkdownEndpointMethod}
            >
              {m.method()}
            </Select.Simple>
            <Select.Simple
              class="border-default hover:bg-hover-dimmer w-1/2 border-b px-4 py-4"
              options={markdownLocationOptions}
              bind:value={integrationMarkdownEndpointLocation}
              disabled={integrationMarkdownEndpointMethod === "get"}
            >
              {m.send_url_in()}
            </Select.Simple>
          </div>
          <Input.Text
            bind:value={integrationMarkdownEndpointParamName}
            label={m.url_parameter_name()}
            class="border-default hover:bg-hover-dimmer border-b p-4"
          />
        {/if}

        <div class="p-4">
          <div class="mb-3 flex items-center justify-between">
            <div class="text-sm font-semibold">{m.headers()}</div>
            <Button variant="outlined" type="button" onclick={addIntegrationHeaderRow}>
              {m.add_header()}
            </Button>
          </div>
          <div class="space-y-2">
            {#each integrationHeaders as header, index (index)}
              <div class="grid grid-cols-[1fr_1fr_auto] gap-2">
                <Input.Text
                  value={header.key}
                  placeholder={m.header_key()}
                  oninput={(event) =>
                    updateIntegrationHeader(index, "key", event.currentTarget.value)}
                />
                <Input.Text
                  value={header.value}
                  placeholder={m.header_value()}
                  oninput={(event) =>
                    updateIntegrationHeader(index, "value", event.currentTarget.value)}
                />
                <Button
                  variant="outlined"
                  type="button"
                  onclick={() => removeIntegrationHeaderRow(index)}
                >
                  {m.remove()}
                </Button>
              </div>
            {/each}
          </div>
        </div>
      {/if}

      {#if !isWebsiteIntegration && !isCreatingIntegration}
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
          type="button"
          on:click={isCreatingIntegration ? createWebsiteIntegration : checkUrlBeforeCreate}
          disabled={isProcessing ||
            duplicateCheckPending ||
            $currentSpace.embedding_models.length === 0 ||
            (isCreatingIntegration
              ? integrationSitemapUrl.trim() === "" || !editableWebsite.embedding_model
              : false)}
          >{isProcessing || duplicateCheckPending ? m.creating() : m.create_website()}</Button
        >
      {:else if mode === "update"}
        <Button variant="primary" on:click={updateWebsite} disabled={isProcessing}
          >{isProcessing ? m.saving() : m.save_changes()}</Button
        >
      {/if}
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<!-- Duplicate URL Warning Modal -->
<Dialog.Root openController={showDuplicateWarning} alert>
  <Dialog.Content width="small">
    <Dialog.Title>{m.website_exists_on_org()}</Dialog.Title>
    <Dialog.Description>
      {#if existingOnOrg}
        {m.website_exists_on_org_description({ spaceName: existingOnOrg.space_name })}
      {/if}
    </Dialog.Description>

    {#if existingOnOrg}
      {@const crawlResult = formatCrawlResult(existingOnOrg)}
      <Dialog.Section class="p-4">
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
                <span class="text-dimmer">{m.website_last_crawled()}:</span>
                <span>{formatDateTime(existingOnOrg.last_crawled_at)}</span>

                {#if crawlResult}
                  <span class="text-dimmer">{m.website_crawl_result()}:</span>
                  <span
                    class={crawlResult.hasFailures
                      ? "text-warning-stronger"
                      : "text-positive-stronger"}
                  >
                    {crawlResult.text}
                  </span>
                {/if}

                <span class="text-dimmer">{m.website_sync_interval()}:</span>
                <span>{formatUpdateInterval(existingOnOrg.update_interval)}</span>
              </div>
            </div>
          </div>
        </div>
      </Dialog.Section>
    {/if}

    <Dialog.Controls let:close>
      <Button is={close}>{m.go_back()}</Button>
      <Button
        variant="primary"
        on:click={async () => {
          showDuplicateWarning.set(false);
          await createWebsite();
        }}
        disabled={isProcessing}
      >
        {isProcessing ? m.creating() : m.create_anyway()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
