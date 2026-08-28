<script lang="ts">
  import { onMount } from "svelte";
  import { SvelteMap } from "svelte/reactivity";
  import { resolve } from "$app/paths";
  import { EneoError, type ApiKeyV2, type ModuleInstallation } from "@eneo/eneo-js";
  import AlertCircle from "lucide-svelte/icons/alert-circle";
  import CheckCircle2 from "lucide-svelte/icons/check-circle-2";
  import Loader2 from "lucide-svelte/icons/loader-2";
  import Pencil from "lucide-svelte/icons/pencil";
  import Plus from "lucide-svelte/icons/plus";
  import Trash2 from "lucide-svelte/icons/trash-2";
  import { Page, Settings } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "svelte-sonner";

  const eneo = getEneo();
  const UNBOUND_SERVICE_KEY = "__unbound__";
  const SERVICE_KEY_PAGE_SIZE = 50;

  let installations = $state<ModuleInstallation[]>([]);
  let serviceKeys = $state<ApiKeyV2[]>([]);
  let serviceKeyCursor = $state<string | null>(null);
  let serviceKeySearchInput = $state("");
  let appliedServiceKeySearch = "";
  let serviceKeysLoading = $state(false);
  let boundKeyLoading = $state(false);
  let serviceKeyRequestId = 0;
  let boundKeyRequestId = 0;
  let loading = $state(true);
  let saving = $state(false);
  let removing = $state(false);
  let errorMessage = $state<string | null>(null);
  let removalError = $state<string | null>(null);
  let moduleKey = $state("");
  let redirectUrisInput = $state("");
  let serviceKeyId = $state("");
  let boundKeyMissing = $state(false);
  let editingModuleKey = $state<string | null>(null);
  let pendingRemoval = $state<ModuleInstallation | null>(null);
  let removalDialogOpen = $state(false);

  const selectedServiceKey = $derived(serviceKeys.find((key) => key.id === serviceKeyId));
  const formTitle = $derived(
    editingModuleKey ? m.module_admin_edit_title() : m.module_admin_add_title()
  );

  function serviceKeyLabel(key: ApiKeyV2): string {
    return `${key.name} · ${key.key_prefix}••••${key.key_suffix}`;
  }

  function parseRedirectUris(): string[] {
    return [
      ...new Set(
        redirectUrisInput
          .split(/\r?\n/)
          .map((uri) => uri.trim())
          .filter(Boolean)
      )
    ];
  }

  function mergeServiceKeys(current: ApiKeyV2[], incoming: ApiKeyV2[]): ApiKeyV2[] {
    const byId = new SvelteMap(current.map((key) => [key.id, key]));
    for (const key of incoming) byId.set(key.id, key);
    return [...byId.values()];
  }

  async function loadServiceKeys({
    cursor = null,
    append = false,
    search = appliedServiceKeySearch
  }: {
    cursor?: string | null;
    append?: boolean;
    search?: string;
  } = {}) {
    const requestId = ++serviceKeyRequestId;
    serviceKeysLoading = true;
    errorMessage = null;
    try {
      const normalizedSearch = search.trim();
      const page = await eneo.modules.listServiceKeys({
        limit: SERVICE_KEY_PAGE_SIZE,
        ...(cursor && { cursor }),
        ...(normalizedSearch && { search: normalizedSearch })
      });
      if (requestId !== serviceKeyRequestId) return;

      const selected = serviceKeys.find((key) => key.id === serviceKeyId);
      const retained = append ? serviceKeys : selected ? [selected] : [];
      serviceKeys = mergeServiceKeys(retained, page.items);
      appliedServiceKeySearch = normalizedSearch;
      serviceKeyCursor = page.next_cursor ?? null;
    } catch (error) {
      if (requestId !== serviceKeyRequestId) return;
      console.error(error);
      errorMessage = getErrorMessage(error);
    } finally {
      if (requestId === serviceKeyRequestId) serviceKeysLoading = false;
    }
  }

  function searchServiceKeys() {
    void loadServiceKeys({ search: serviceKeySearchInput });
  }

  function handleServiceKeySearchKeydown(event: KeyboardEvent) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    searchServiceKeys();
  }

  async function refreshInstallations() {
    errorMessage = null;
    try {
      installations = (await eneo.modules.list()).items;
    } catch (error) {
      console.error(error);
      errorMessage = getErrorMessage(error);
    }
  }

  async function loadPage() {
    loading = true;
    errorMessage = null;
    try {
      const [modulePage] = await Promise.all([
        eneo.modules.list(),
        loadServiceKeys({ search: "" })
      ]);
      installations = modulePage.items;
    } catch (error) {
      console.error(error);
      errorMessage = getErrorMessage(error);
    } finally {
      loading = false;
    }
  }

  function resetForm() {
    boundKeyRequestId += 1;
    boundKeyLoading = false;
    moduleKey = "";
    redirectUrisInput = "";
    serviceKeyId = "";
    boundKeyMissing = false;
    editingModuleKey = null;
  }

  async function editInstallation(installation: ModuleInstallation) {
    const requestId = ++boundKeyRequestId;
    moduleKey = installation.module_key;
    redirectUrisInput = (installation.redirect_uris ?? []).join("\n");
    const boundKeyId = installation.service_key_id ?? "";
    editingModuleKey = installation.module_key;
    errorMessage = null;
    boundKeyMissing = false;
    boundKeyLoading = false;

    if (boundKeyId === "") {
      serviceKeyId = UNBOUND_SERVICE_KEY;
    } else if (serviceKeys.some((key) => key.id === boundKeyId)) {
      serviceKeyId = boundKeyId;
    } else {
      serviceKeyId = "";
      boundKeyLoading = true;
      try {
        const boundKey = await eneo.modules.getServiceKey({ serviceKeyId: boundKeyId });
        if (requestId !== boundKeyRequestId) return;
        serviceKeys = mergeServiceKeys(serviceKeys, [boundKey]);
        serviceKeyId = boundKey.id;
      } catch (error) {
        if (requestId !== boundKeyRequestId) return;
        if (error instanceof EneoError && error.status === 404) {
          // Missing, cross-tenant and no-longer-eligible keys intentionally share 404.
          boundKeyMissing = true;
        } else {
          errorMessage = getErrorMessage(error);
        }
      } finally {
        if (requestId === boundKeyRequestId) boundKeyLoading = false;
      }
    }

    document.getElementById("module-installation-form")?.scrollIntoView({
      behavior: "smooth",
      block: "start"
    });
  }

  async function saveInstallation(event: SubmitEvent) {
    event.preventDefault();
    const normalizedModuleKey = moduleKey.trim();
    const redirectUris = parseRedirectUris();
    if (!normalizedModuleKey || redirectUris.length === 0 || !serviceKeyId) return;

    saving = true;
    errorMessage = null;
    try {
      await eneo.modules.install({
        moduleKey: normalizedModuleKey,
        config: {
          redirect_uris: redirectUris,
          service_key_id: serviceKeyId === UNBOUND_SERVICE_KEY ? null : serviceKeyId
        }
      });
      toast.success(m.module_admin_saved());
      resetForm();
      await refreshInstallations();
    } catch (error) {
      console.error(error);
      errorMessage = getErrorMessage(error);
    } finally {
      saving = false;
    }
  }

  function confirmRemoval(installation: ModuleInstallation) {
    pendingRemoval = installation;
    removalError = null;
    removalDialogOpen = true;
  }

  async function removeInstallation() {
    if (!pendingRemoval) return;
    removing = true;
    removalError = null;
    try {
      await eneo.modules.uninstall({ moduleKey: pendingRemoval.module_key });
      toast.success(m.module_admin_removed());
      if (editingModuleKey === pendingRemoval.module_key) resetForm();
      removalDialogOpen = false;
      pendingRemoval = null;
      removalError = null;
      await refreshInstallations();
    } catch (error) {
      console.error(error);
      removalError = getErrorMessage(error);
    } finally {
      removing = false;
    }
  }

  onMount(() => void loadPage());
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.module_admin_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.module_admin_title()} />
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      {#if errorMessage}
        <Alert.Root variant="destructive" role="alert">
          <AlertCircle />
          <Alert.Description>{errorMessage}</Alert.Description>
        </Alert.Root>
      {/if}

      <Settings.Group title={m.module_admin_installed_title()}>
        <p class="text-muted mb-4 text-sm">{m.module_admin_description()}</p>
        {#if loading}
          <div class="flex flex-col gap-3" aria-label={m.loading()}>
            <Skeleton class="h-12 w-full" />
            <Skeleton class="h-12 w-full" />
          </div>
        {:else if installations.length === 0}
          <div class="border-default rounded-lg border border-dashed px-6 py-10 text-center">
            <p class="font-medium">{m.module_admin_empty_title()}</p>
            <p class="text-muted mt-1 text-sm">{m.module_admin_empty_description()}</p>
          </div>
        {:else}
          <div class="border-default overflow-hidden rounded-lg border">
            <Table.Root>
              <Table.Header>
                <Table.Row>
                  <Table.Head>{m.module_admin_module_key()}</Table.Head>
                  <Table.Head>{m.module_admin_callback_urls()}</Table.Head>
                  <Table.Head>{m.module_admin_service_key()}</Table.Head>
                  <Table.Head>{m.module_admin_status()}</Table.Head>
                  <Table.Head class="text-right">{m.module_admin_actions()}</Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {#each installations as installation (installation.module_id)}
                  <Table.Row>
                    <Table.Cell class="font-mono text-sm">{installation.module_key}</Table.Cell>
                    <Table.Cell>
                      <div class="flex max-w-xl flex-col gap-1">
                        {#each installation.redirect_uris ?? [] as uri (uri)}
                          <span class="truncate text-sm" title={uri}>{uri}</span>
                        {:else}
                          <span class="text-muted text-sm">—</span>
                        {/each}
                      </div>
                    </Table.Cell>
                    <Table.Cell>
                      {#if installation.service_key_id}
                        {@const boundKey = serviceKeys.find(
                          (key) => key.id === installation.service_key_id
                        )}
                        {#if boundKey}
                          <span class="text-sm">{serviceKeyLabel(boundKey)}</span>
                        {:else}
                          <span
                            class="text-muted font-mono text-sm"
                            title={installation.service_key_id}
                          >
                            {installation.service_key_id.slice(0, 8)}…
                          </span>
                        {/if}
                      {:else}
                        <span class="text-muted text-sm">—</span>
                      {/if}
                    </Table.Cell>
                    <Table.Cell>
                      <Badge variant={installation.configured ? "default" : "destructive"}>
                        {installation.configured
                          ? m.module_admin_configured()
                          : m.module_admin_incomplete()}
                      </Badge>
                    </Table.Cell>
                    <Table.Cell>
                      <div class="flex justify-end gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onclick={() => void editInstallation(installation)}
                        >
                          <Pencil />
                          {m.edit()}
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          onclick={() => confirmRemoval(installation)}
                        >
                          <Trash2 />
                          {m.remove()}
                        </Button>
                      </div>
                    </Table.Cell>
                  </Table.Row>
                {/each}
              </Table.Body>
            </Table.Root>
          </div>
        {/if}
      </Settings.Group>

      <Settings.Group title={formTitle}>
        <form
          id="module-installation-form"
          class="flex max-w-2xl flex-col gap-5"
          onsubmit={saveInstallation}
        >
          <Field.Field>
            <Field.Label for="module-key">{m.module_admin_module_key()}</Field.Label>
            <Input
              id="module-key"
              bind:value={moduleKey}
              required
              disabled={editingModuleKey !== null || saving}
              pattern="[A-Za-z0-9][A-Za-z0-9._-]*"
              autocomplete="off"
              placeholder={m.module_admin_module_key_placeholder()}
            />
            <Field.Description>{m.module_admin_module_key_help()}</Field.Description>
          </Field.Field>

          <Field.Field>
            <Field.Label for="redirect-uris">{m.module_admin_callback_urls()}</Field.Label>
            <Textarea
              id="redirect-uris"
              bind:value={redirectUrisInput}
              required
              disabled={saving}
              rows={4}
              placeholder={m.module_admin_callback_urls_placeholder()}
            />
            <Field.Description>{m.module_admin_callback_urls_help()}</Field.Description>
          </Field.Field>

          <Field.Field>
            <Field.Label for="service-key">{m.module_admin_service_key()}</Field.Label>
            <div class="flex gap-2">
              <Input
                type="search"
                bind:value={serviceKeySearchInput}
                aria-label={`${m.module_admin_service_key()} ${m.search()}`}
                placeholder={m.search()}
                disabled={saving || serviceKeysLoading}
                onkeydown={handleServiceKeySearchKeydown}
              />
              <Button
                type="button"
                variant="outline"
                disabled={saving || serviceKeysLoading}
                onclick={searchServiceKeys}
              >
                {m.search()}
              </Button>
            </div>
            <Select.Root
              type="single"
              bind:value={serviceKeyId}
              disabled={saving || serviceKeysLoading || boundKeyLoading}
            >
              <Select.Trigger
                id="service-key"
                class="w-full"
                aria-label={m.module_admin_service_key()}
              >
                <span class="truncate">
                  {serviceKeyId === UNBOUND_SERVICE_KEY
                    ? m.module_admin_service_key_unbound()
                    : selectedServiceKey
                      ? serviceKeyLabel(selectedServiceKey)
                      : m.module_admin_service_key_placeholder()}
                </span>
              </Select.Trigger>
              <Select.Content>
                <Select.Item value={UNBOUND_SERVICE_KEY}>
                  {m.module_admin_service_key_unbound()}
                </Select.Item>
                {#each serviceKeys as key (key.id)}
                  <Select.Item value={key.id}>{serviceKeyLabel(key)}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
            {#if serviceKeyCursor}
              <Button
                type="button"
                variant="outline"
                class="self-start"
                disabled={saving || serviceKeysLoading}
                onclick={() =>
                  void loadServiceKeys({
                    cursor: serviceKeyCursor,
                    append: true,
                    search: appliedServiceKeySearch
                  })}
              >
                {m.load_more()}
              </Button>
            {/if}
            <Field.Description>{m.module_admin_service_key_help()}</Field.Description>
            {#if boundKeyMissing && !boundKeyLoading && !serviceKeyId}
              <Alert.Root variant="destructive" role="alert">
                <AlertCircle />
                <Alert.Description>{m.module_admin_bound_key_missing()}</Alert.Description>
              </Alert.Root>
            {/if}
          </Field.Field>

          {#if !loading && serviceKeys.length === 0}
            <Alert.Root>
              <AlertCircle />
              <Alert.Title>{m.module_admin_no_service_keys_title()}</Alert.Title>
              <Alert.Description>
                {m.module_admin_no_service_keys_description()}
                <a class="ml-1 underline" href={resolve("/admin/api-keys")}>
                  {m.module_admin_manage_service_keys()}
                </a>
              </Alert.Description>
            </Alert.Root>
          {/if}

          <div class="flex gap-2">
            <Button
              type="submit"
              disabled={saving ||
                !moduleKey.trim() ||
                parseRedirectUris().length === 0 ||
                !serviceKeyId}
            >
              {#if saving}
                <Loader2 class="animate-spin" />
              {:else if editingModuleKey}
                <CheckCircle2 />
              {:else}
                <Plus />
              {/if}
              {editingModuleKey ? m.module_admin_update() : m.module_admin_install()}
            </Button>
            {#if editingModuleKey}
              <Button type="button" variant="outline" disabled={saving} onclick={resetForm}>
                {m.cancel()}
              </Button>
            {/if}
          </div>
        </form>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>

<AlertDialog.Root bind:open={removalDialogOpen}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.module_admin_remove_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.module_admin_remove_description({ moduleKey: pendingRemoval?.module_key ?? "" })}
      </AlertDialog.Description>
    </AlertDialog.Header>
    {#if removalError}
      <Alert.Root variant="destructive" role="alert">
        <AlertCircle />
        <Alert.Description>{removalError}</Alert.Description>
      </Alert.Root>
    {/if}
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={removing}>{m.cancel()}</AlertDialog.Cancel>
      <Button
        type="button"
        variant="destructive"
        disabled={removing}
        onclick={() => void removeInstallation()}
      >
        {#if removing}<Loader2 class="animate-spin" />{/if}
        {m.remove()}
      </Button>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
