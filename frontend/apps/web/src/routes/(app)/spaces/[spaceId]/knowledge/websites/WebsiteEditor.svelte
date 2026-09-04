<script lang="ts">
  import { getEneo } from "$lib/core/Eneo";
  import { toastError } from "$lib/core/errors";
  import SelectEmbeddingModel from "$lib/features/ai-models/components/SelectEmbeddingModel.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { Website } from "@eneo/eneo-js";
  import { AlertCircle, Eye, EyeOff, Info, LockKeyhole } from "lucide-svelte";
  import { untrack } from "svelte";
  import { isSupportedWebsiteUrl } from "./websiteForm";

  type EditableWebsite = Omit<Website, "embedding_model"> & {
    embedding_model?: { id: string } | null;
  };

  type ExistingWebsite = {
    space_name: string;
  };

  const emptyWebsite = (): EditableWebsite =>
    ({
      id: "",
      name: null,
      url: "",
      crawl_type: "crawl",
      download_files: false,
      embedding_model: undefined,
      update_interval: "never",
      requires_http_auth: false
    }) as EditableWebsite;

  const eneo = getEneo();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  type WebsiteCreateInput = Parameters<typeof eneo.websites.create>[0];
  type WebsiteUpdateInput = Parameters<typeof eneo.websites.update>[0]["update"];

  let {
    mode = "create",
    website = emptyWebsite(),
    showDialog = $bindable(false)
  }: {
    mode?: "update" | "create";
    website?: EditableWebsite;
    showDialog?: boolean;
  } = $props();

  const initialWebsite = untrack(() => website);
  let url = $state(initialWebsite.url);
  let websiteName = $state(initialWebsite.name ?? "");
  let crawlType = $state<Website["crawl_type"]>(initialWebsite.crawl_type);
  let updateInterval = $state<Website["update_interval"]>(initialWebsite.update_interval);
  let downloadFiles = $state(initialWebsite.download_files ?? false);
  let embeddingModel = $state(initialWebsite.embedding_model);
  let httpAuthEnabled = $state(initialWebsite.requires_http_auth ?? false);
  let httpAuthUsername = $state("");
  let httpAuthPassword = $state("");
  let showPassword = $state(false);
  let isProcessing = $state(false);
  let duplicateCheckPending = $state(false);
  let urlTouched = $state(false);
  let formError = $state("");
  let existingOnOrg = $state<ExistingWebsite | null>(null);
  let showDuplicateWarning = $state(false);

  let urlInvalid = $derived(urlTouched && !isSupportedWebsiteUrl(url));
  let authInvalid = $derived.by(credentialsAreInvalid);

  function setCrawlType(value: string) {
    crawlType = value as Website["crawl_type"];
    if (crawlType === "sitemap") downloadFiles = false;
  }

  function credentialsAreInvalid(): boolean {
    if (!httpAuthEnabled) return false;
    const hasUsername = httpAuthUsername.trim().length > 0;
    const hasPassword = httpAuthPassword.length > 0;
    const canKeepExisting = mode === "update" && website.requires_http_auth;
    if (canKeepExisting && !hasUsername && !hasPassword) return false;
    return hasUsername !== hasPassword || (!hasUsername && !hasPassword);
  }

  function closeDialog() {
    showDialog = false;
    formError = "";
    urlTouched = false;
  }

  function resetCreateForm() {
    url = "";
    websiteName = "";
    crawlType = "crawl";
    updateInterval = "never";
    downloadFiles = false;
    embeddingModel = undefined;
    httpAuthEnabled = false;
    httpAuthUsername = "";
    httpAuthPassword = "";
    showPassword = false;
    existingOnOrg = null;
  }

  function authFields(): Pick<WebsiteUpdateInput, "http_auth_username" | "http_auth_password"> {
    if (!httpAuthEnabled && website.requires_http_auth) {
      return { http_auth_username: null, http_auth_password: null };
    }
    if (httpAuthEnabled && httpAuthUsername.trim() && httpAuthPassword) {
      return {
        http_auth_username: httpAuthUsername.trim(),
        http_auth_password: httpAuthPassword
      };
    }
    return {};
  }

  function validateForm(): boolean {
    urlTouched = true;
    formError = "";
    return isSupportedWebsiteUrl(url) && !authInvalid;
  }

  async function submitForm() {
    if (!validateForm()) return;
    if (mode === "update") {
      await updateWebsite();
    } else {
      await checkUrlBeforeCreate();
    }
  }

  async function checkUrlBeforeCreate() {
    if ($currentSpace.organization) {
      await createWebsite();
      return;
    }
    duplicateCheckPending = true;
    try {
      existingOnOrg = (await eneo.websites.checkUrl(url)) as ExistingWebsite | null;
      if (existingOnOrg) showDuplicateWarning = true;
      else await createWebsite();
    } catch {
      await createWebsite();
    } finally {
      duplicateCheckPending = false;
    }
  }

  async function createWebsite() {
    const selectedEmbeddingModel = embeddingModel ?? $currentSpace.embedding_models[0];
    if (!selectedEmbeddingModel) {
      formError = m.warning_no_embedding_models();
      return;
    }

    isProcessing = true;
    formError = "";
    try {
      const payload: WebsiteCreateInput = {
        spaceId: $currentSpace.id,
        url,
        name: websiteName.trim() || null,
        crawl_type: crawlType,
        update_interval: updateInterval,
        download_files: downloadFiles,
        embedding_model: { id: selectedEmbeddingModel.id },
        ...authFields()
      };
      await eneo.websites.create(payload);
      showDuplicateWarning = false;
      resetCreateForm();
      closeDialog();
      await refreshCurrentSpace("knowledge");
    } catch (error) {
      formError = m.website_form_create_failed();
      toastError(error, formError);
    } finally {
      isProcessing = false;
    }
  }

  async function updateWebsite() {
    isProcessing = true;
    formError = "";
    try {
      const update: WebsiteUpdateInput = {
        url,
        name: websiteName.trim() || null,
        crawl_type: crawlType,
        update_interval: updateInterval,
        download_files: downloadFiles,
        ...authFields()
      };
      await eneo.websites.update({ website: { id: website.id }, update });
      closeDialog();
      await refreshCurrentSpace("knowledge");
    } catch (error) {
      formError = m.website_form_update_failed();
      toastError(error, formError);
    } finally {
      isProcessing = false;
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
</script>

<Dialog.Root bind:open={showDialog}>
  {#if mode === "create"}
    <Dialog.Trigger>
      {#snippet child({ props })}
        <Button {...props}>{m.connect_website()}</Button>
      {/snippet}
    </Dialog.Trigger>
  {/if}

  <Dialog.Content
    class="flex max-h-[calc(100dvh-2rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl"
    showCloseButton={!isProcessing}
    closeLabel={m.close()}
  >
    <Dialog.Header class="border-b px-6 py-5 pr-12">
      <Dialog.Title>
        {mode === "create" ? m.create_website_integration() : m.edit_website_integration()}
      </Dialog.Title>
      <Dialog.Description>{m.website_crawl_type_description()}</Dialog.Description>
    </Dialog.Header>

    <form
      class="flex min-h-0 flex-1 flex-col"
      onsubmit={(event) => {
        event.preventDefault();
        void submitForm();
      }}
    >
      <div class="min-h-0 flex-1 overflow-y-auto px-6 py-5 [scrollbar-gutter:stable]">
        <div class="flex flex-col gap-5">
          {#if formError}
            <Alert.Root variant="destructive" aria-live="assertive">
              <AlertCircle aria-hidden="true" />
              <Alert.Description>{formError}</Alert.Description>
            </Alert.Root>
          {/if}
          {#if $currentSpace.embedding_models.length < 1 && mode === "create"}
            <Alert.Root>
              <Info aria-hidden="true" />
              <Alert.Title>{m.warning()}</Alert.Title>
              <Alert.Description>{m.warning_no_embedding_models()}</Alert.Description>
            </Alert.Root>
          {/if}

          <Field.Group class="grid gap-5">
            <Field.Field data-invalid={urlInvalid}>
              <Field.Label for="website-url">{m.url_required()}</Field.Label>
              <Input
                id="website-url"
                name="url"
                type="url"
                required
                bind:value={url}
                placeholder={crawlType === "sitemap"
                  ? m.website_sitemap_url_placeholder()
                  : m.website_url_placeholder()}
                aria-invalid={urlInvalid}
                aria-describedby="website-url-description"
                onblur={() => (urlTouched = true)}
              />
              <Field.Description id="website-url-description">
                {crawlType === "sitemap"
                  ? m.website_sitemap_crawl_description()
                  : m.website_basic_crawl_description()}
              </Field.Description>
              {#if urlInvalid}<Field.Error>{m.website_url_invalid()}</Field.Error>{/if}
            </Field.Field>

            <Field.Field>
              <Field.Label for="website-name">{m.display_name()}</Field.Label>
              <Input
                id="website-name"
                name="name"
                bind:value={websiteName}
                placeholder={url.split("//")[1] ?? url}
              />
              <Field.Description>{m.display_name_optional()}</Field.Description>
            </Field.Field>

            <div class="grid gap-5 sm:grid-cols-2">
              <Field.Field>
                <Field.Label for="website-crawl-type">{m.crawl_type()}</Field.Label>
                <Select.Root type="single" value={crawlType} onValueChange={setCrawlType}>
                  <Select.Trigger id="website-crawl-type" class="w-full">
                    <span data-slot="select-value">
                      {crawlType === "sitemap" ? m.sitemap_based_crawl() : m.basic_crawl()}
                    </span>
                  </Select.Trigger>
                  <Select.Content>
                    <Select.Item value="crawl" label={m.basic_crawl()}
                      >{m.basic_crawl()}</Select.Item
                    >
                    <Select.Item value="sitemap" label={m.sitemap_based_crawl()}>
                      {m.sitemap_based_crawl()}
                    </Select.Item>
                  </Select.Content>
                </Select.Root>
                <Field.Description>{m.website_crawl_type_description()}</Field.Description>
              </Field.Field>

              <Field.Field>
                <Field.Label for="website-update-interval">{m.automatic_updates()}</Field.Label>
                <Select.Root type="single" bind:value={updateInterval}>
                  <Select.Trigger id="website-update-interval" class="w-full">
                    <span data-slot="select-value">{formatUpdateInterval(updateInterval)}</span>
                  </Select.Trigger>
                  <Select.Content>
                    <Select.Item value="never" label={m.never()}>{m.never()}</Select.Item>
                    <Select.Item value="daily" label={m.every_day()}>{m.every_day()}</Select.Item>
                    <Select.Item value="every_other_day" label={m.every_other_day()}>
                      {m.every_other_day()}
                    </Select.Item>
                    <Select.Item value="weekly" label={m.every_week()}>{m.every_week()}</Select.Item
                    >
                  </Select.Content>
                </Select.Root>
                <Field.Description>{m.website_automatic_updates_description()}</Field.Description>
              </Field.Field>
            </div>

            <Field.Field orientation="horizontal" class="rounded-lg border p-3">
              <Field.Content>
                <Field.Label for="website-http-auth">{m.requires_http_auth()}</Field.Label>
                <Field.Description id="website-http-auth-description">
                  {website.requires_http_auth
                    ? m.website_http_auth_replace_description()
                    : m.website_http_auth_description()}
                </Field.Description>
              </Field.Content>
              <Switch
                id="website-http-auth"
                bind:checked={httpAuthEnabled}
                aria-describedby="website-http-auth-description"
              />
            </Field.Field>

            {#if httpAuthEnabled}
              <Alert.Root role="note">
                <LockKeyhole aria-hidden="true" />
                <Alert.Title>
                  {website.requires_http_auth ? m.authentication_configured() : m.security_note()}
                </Alert.Title>
                <Alert.Description>{m.credentials_encrypted_securely()}</Alert.Description>
              </Alert.Root>
              <div class="grid gap-5 sm:grid-cols-2">
                <Field.Field data-invalid={authInvalid}>
                  <Field.Label for="website-auth-username">{m.username()}</Field.Label>
                  <Input
                    id="website-auth-username"
                    name="username"
                    autocomplete="username"
                    bind:value={httpAuthUsername}
                    placeholder={m.enter_username()}
                    aria-invalid={authInvalid}
                  />
                </Field.Field>
                <Field.Field data-invalid={authInvalid}>
                  <Field.Label for="website-auth-password">{m.password()}</Field.Label>
                  <div class="relative">
                    <Input
                      id="website-auth-password"
                      name="password"
                      type={showPassword ? "text" : "password"}
                      autocomplete="current-password"
                      bind:value={httpAuthPassword}
                      placeholder={m.enter_password()}
                      aria-invalid={authInvalid}
                      class="pr-10"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      class="absolute top-1/2 right-1 -translate-y-1/2"
                      onclick={() => (showPassword = !showPassword)}
                      aria-label={showPassword ? m.hide_password() : m.show_password()}
                    >
                      {#if showPassword}<EyeOff aria-hidden="true" />{:else}<Eye
                          aria-hidden="true"
                        />{/if}
                    </Button>
                  </div>
                </Field.Field>
              </div>
              {#if authInvalid}<Field.Error
                  >{m.website_http_auth_credentials_required()}</Field.Error
                >{/if}
            {/if}

            <Field.Field orientation="horizontal" class="rounded-lg border p-3">
              <Field.Content>
                <Field.Label for="website-download-files">{m.download_analyse_files()}</Field.Label>
                <Field.Description id="website-download-files-description">
                  {crawlType === "sitemap"
                    ? m.option_only_basic_crawls()
                    : m.website_download_files_description()}
                </Field.Description>
              </Field.Content>
              <Switch
                id="website-download-files"
                bind:checked={downloadFiles}
                disabled={crawlType === "sitemap"}
                aria-describedby="website-download-files-description"
              />
            </Field.Field>

            {#if mode === "create"}
              <SelectEmbeddingModel
                hideWhenNoOptions
                bind:value={embeddingModel}
                selectableModels={$currentSpace.embedding_models}
              />
            {/if}
          </Field.Group>
        </div>
      </div>

      <Dialog.Footer class="mx-0 mb-0 shrink-0 border-t px-6 py-4">
        <Dialog.Close>
          {#snippet child({ props })}
            <Button {...props} type="button" variant="outline" disabled={isProcessing}>
              {m.cancel()}
            </Button>
          {/snippet}
        </Dialog.Close>
        <Button
          type="submit"
          disabled={isProcessing ||
            duplicateCheckPending ||
            (mode === "create" && $currentSpace.embedding_models.length === 0)}
          aria-busy={isProcessing || duplicateCheckPending}
        >
          {#if mode === "create"}
            {isProcessing || duplicateCheckPending ? m.creating() : m.create_website()}
          {:else}
            {isProcessing ? m.saving() : m.save_changes()}
          {/if}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>

<AlertDialog.Root bind:open={showDuplicateWarning}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.website_exists_on_org()}</AlertDialog.Title>
      <AlertDialog.Description>
        {#if existingOnOrg}
          {m.website_exists_on_org_description({ spaceName: existingOnOrg.space_name })}
        {/if}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={isProcessing}>{m.go_back()}</AlertDialog.Cancel>
      <AlertDialog.Action disabled={isProcessing} onclick={() => void createWebsite()}>
        {isProcessing ? m.creating() : m.create_anyway()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
