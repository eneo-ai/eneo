<script lang="ts">
  import { Page } from "$lib/components/layout";
  import CollectionEditor from "./collections/CollectionEditor.svelte";
  import CollectionTable from "./collections/CollectionTable.svelte";
  import WebsiteEditor from "./websites/WebsiteEditor.svelte";
  import WebsiteTable from "./websites/WebsiteTable.svelte";
  import { writable } from "svelte/store";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getEneo } from "$lib/core/Eneo";
  import { Button as LegacyButton, Tooltip } from "@eneo/ui";
  import { resolve } from "$app/paths";
  import { IconInfo } from "@eneo/icons/info";
  import { IconLinkExternal } from "@eneo/icons/link-external";
  import { IconRefresh } from "@eneo/icons/refresh";
  import { IconStop } from "@eneo/icons/stop";
  import { IconTrash } from "@eneo/icons/trash";
  import IntegrationsTable from "./integrations/IntegrationsTable.svelte";
  import SyncHistoryDialog from "./integrations/SyncHistoryDialog.svelte";
  import ImportKnowledgeDialog from "$lib/features/integrations/components/import/ImportKnowledgeDialog.svelte";
  import SharePointFixtureLauncher from "$lib/features/integrations/sharepoint/SharePointFixtureLauncher.svelte";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { toastError } from "$lib/core/errors";
  import type { IntegrationKnowledge, WebsiteSparse } from "@eneo/eneo-js";
  import { jobCompletionEvents } from "$lib/features/jobs/JobManager";
  import { untrack } from "svelte";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { canRequestCrawlStop } from "$lib/features/knowledge/crawlRunState";
  import {
    bulkDeletionWaitsForCrawlerCleanup,
    bulkFailureWebsiteIds,
    deleteWebsiteBatches,
    runWebsiteBatches,
    stopWebsiteBatches
  } from "./bulkWebsiteActions";

  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- page data type inferred from layout chain
  let { data } = $props<{ data: any }>();

  const eneo = getEneo();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  // Listen for job completion events and refresh knowledge
  $effect(() => {
    const event = $jobCompletionEvents;
    if (event) {
      console.log("Knowledge page: Job completion event received, refreshing knowledge");
      refreshCurrentSpace("knowledge");
    }
  });

  let selectedTab = writable<string>();
  let showIntegrationsNotice = $state(
    untrack(() => data.environment.integrationRequestFormUrl !== undefined)
  );
  let selectedIntegrationForSyncHistory: IntegrationKnowledge | null = $state(null);
  let showSyncHistoryDialog = $state(false);
  let isOrgSpace = $currentSpace.organization;
  let isPersonalSpace = $currentSpace.personal;

  // Check if user has admin permission
  let isAdmin = untrack(
    () =>
      data.user?.roles?.some((role: { permissions?: string[] }) =>
        role.permissions?.includes("admin")
      ) ?? false
  );

  function handleSelectIntegration(integration: IntegrationKnowledge) {
    selectedIntegrationForSyncHistory = integration;
    showSyncHistoryDialog = true;
  }

  // Website selection state (shared with WebsiteTable)
  let selectedWebsiteIds = $state.raw(writable<Set<string>>(new Set()));
  let isBulkRecrawling = $state(false);
  let isBulkStopping = $state(false);
  let isBulkDeleting = $state(false);
  let stopDialogOpen = $state(false);
  let stopTargetIds = $state<string[]>([]);
  let deleteDialogOpen = $state(false);
  let deleteTargetIds = $state<string[]>([]);
  let bulkActionPending = $derived(isBulkRecrawling || isBulkStopping || isBulkDeleting);

  async function refreshWebsiteData() {
    try {
      await refreshCurrentSpace("knowledge");
    } catch (error) {
      console.error("Failed to refresh website data after a bulk action", error);
    }
  }

  function canStopWebsite(website: WebsiteSparse): boolean {
    return (
      website.space_id === $currentSpace.id &&
      website.latest_crawl !== null &&
      canRequestCrawlStop(website.latest_crawl)
    );
  }

  let stoppableWebsiteIds = $derived(
    $currentSpace.knowledge.websites.filter(canStopWebsite).map((website) => website.id)
  );
  let selectedStoppableWebsiteIds = $derived(
    stoppableWebsiteIds.filter((websiteId) => $selectedWebsiteIds.has(websiteId))
  );
  let selectedDeletableWebsiteIds = $derived(
    $currentSpace.knowledge.websites
      .filter(
        (website) =>
          website.space_id === $currentSpace.id &&
          website.permissions?.includes("delete") &&
          $selectedWebsiteIds.has(website.id)
      )
      .map((website) => website.id)
  );

  // Bulk recrawl handler
  async function bulkRecrawl() {
    if ($selectedWebsiteIds.size === 0) return;

    isBulkRecrawling = true;
    try {
      const result = await runWebsiteBatches(Array.from($selectedWebsiteIds), (websiteIds) =>
        eneo.websites.bulkRun({ website_ids: websiteIds })
      );

      if (result.failed > 0) {
        toast.error(
          result.queued > 0
            ? m.bulk_crawl_partial({ queued: result.queued, failed: result.failed })
            : m.bulk_crawl_failed()
        );
        const failedWebsiteIds = bulkFailureWebsiteIds(result.errors);
        if (failedWebsiteIds.length > 0) {
          $selectedWebsiteIds = new Set(failedWebsiteIds);
        }
      } else {
        toast.success(m.bulk_crawl_started({ count: result.queued }));
        $selectedWebsiteIds = new Set();
      }
    } catch (error) {
      toastError(error, m.bulk_crawl_failed());
      console.error(error);
    } finally {
      isBulkRecrawling = false;
      await refreshWebsiteData();
    }
  }

  function confirmBulkStop(websiteIds: string[]) {
    stopTargetIds = [...websiteIds];
    stopDialogOpen = true;
  }

  async function bulkStop() {
    if (stopTargetIds.length === 0) return;

    isBulkStopping = true;
    try {
      const result = await stopWebsiteBatches(stopTargetIds, (websiteIds) =>
        eneo.websites.bulkStop({ website_ids: websiteIds })
      );

      stopDialogOpen = false;
      const failedWebsiteIds = bulkFailureWebsiteIds(result.errors);
      $selectedWebsiteIds = result.failed > 0 ? new Set(failedWebsiteIds) : new Set();

      if (result.failed > 0) {
        toast.error(
          result.stopped > 0
            ? m.crawls_stop_partial({ stopped: result.stopped, failed: result.failed })
            : m.bulk_crawl_stop_failed()
        );
      } else if (result.stopped > 0) {
        toast.success(m.crawls_stop_requested({ count: result.stopped }));
      } else {
        toast.info(m.crawls_not_running());
      }
    } catch (error) {
      toastError(error, m.bulk_crawl_stop_failed());
      console.error(error);
    } finally {
      isBulkStopping = false;
      await refreshWebsiteData();
    }
  }

  function confirmBulkDelete(websiteIds: string[]) {
    deleteTargetIds = [...websiteIds];
    deleteDialogOpen = true;
  }

  async function bulkDelete() {
    if (deleteTargetIds.length === 0) return;

    isBulkDeleting = true;
    try {
      const result = await deleteWebsiteBatches(deleteTargetIds, (websiteIds) =>
        eneo.websites.bulkDelete({ website_ids: websiteIds })
      );

      deleteDialogOpen = false;
      if (result.failed > 0) {
        if (bulkDeletionWaitsForCrawlerCleanup(result.errors)) {
          const cleanupPending = result.errors.some(
            (error) => error.error === "crawl_cleanup_pending"
          );
          toast.info(
            cleanupPending
              ? m.websites_remove_cleanup_pending()
              : result.deleted > 0
                ? m.websites_remove_partial_stopping()
                : m.websites_remove_stopping()
          );
        } else {
          toast.error(
            result.deleted > 0
              ? m.websites_remove_partial({ deleted: result.deleted, failed: result.failed })
              : m.bulk_website_remove_failed()
          );
        }
        const failedWebsiteIds = bulkFailureWebsiteIds(result.errors);
        $selectedWebsiteIds = new Set(
          failedWebsiteIds.length > 0 ? failedWebsiteIds : deleteTargetIds
        );
      } else {
        if (result.deleted > 0) {
          toast.success(m.websites_removed({ count: result.deleted }));
        } else {
          toast.info(m.websites_already_removed());
        }
        $selectedWebsiteIds = new Set();
      }
    } catch (error) {
      toastError(error, m.bulk_website_remove_failed());
      console.error(error);
    } finally {
      isBulkDeleting = false;
      await refreshWebsiteData();
    }
  }

  let userCanSeeCollections = $derived($currentSpace.hasPermission("read", "collection"));
  let userCanSeeWebsites = $derived($currentSpace.hasPermission("read", "website"));
  let userCanSeeIntegrations = $derived(
    $currentSpace.hasPermission("read", "integrationKnowledge")
  );

  // Reset selected integration when dialog closes
  $effect(() => {
    if (!showSyncHistoryDialog) {
      selectedIntegrationForSyncHistory = null;
    }
  });
</script>

<svelte:head>
  <title
    >Eneo.ai – {data.currentSpace.personal ? m.personal() : data.currentSpace.name} – {m.knowledge()}</title
  >
</svelte:head>

{#snippet noCreatePermission(resourceType: string)}
  {@const message = m.knowledge_create_no_permission({ resourceType })}
  <!-- Sits where the create button would be, so the header layout stays
       consistent whether or not the user can create. A real <button> trigger
       keeps it keyboard-focusable (tabbable), and aria-label exposes the reason
       to screen readers rather than relying on hover alone. -->
  <Tooltip text={message} placement="bottom" asFragment let:trigger>
    {@const tip = trigger[0]}
    <button
      {...tip}
      use:tip.action
      type="button"
      aria-label={message}
      class="text-secondary hover:text-primary hover:bg-hover-default focus-visible:ring-accent-default flex cursor-help items-center rounded-md p-1.5 focus:outline-none focus-visible:ring-2"
    >
      <IconInfo />
    </button>
  </Tooltip>
{/snippet}

<Page.Root tabController={selectedTab}>
  <Page.Header>
    <Page.Title title={m.knowledge()}></Page.Title>
    <Page.Tabbar>
      {#if userCanSeeCollections}
        <Page.TabTrigger tab="collections">{m.collections()}</Page.TabTrigger>
      {/if}
      {#if userCanSeeWebsites}
        <Page.TabTrigger tab="websites">{m.websites()}</Page.TabTrigger>
      {/if}
      {#if userCanSeeIntegrations}
        <Page.TabTrigger tab="integrations">{m.integrations()}</Page.TabTrigger>
      {/if}
    </Page.Tabbar>
    <div class="flex-grow"></div>
    <Page.Flex>
      {#if $selectedTab === "collections" && $currentSpace.hasPermission("create", "collection")}
        <CollectionEditor mode="create" collection={undefined}></CollectionEditor>
      {:else if $selectedTab === "collections"}
        {@render noCreatePermission(m.collections().toLowerCase())}
      {:else if $selectedTab === "websites"}
        {#if $selectedWebsiteIds.size > 0}
          {#if $currentSpace.hasPermission("create", "website")}
            {#if selectedStoppableWebsiteIds.length > 0}
              <Button
                variant="outline"
                disabled={bulkActionPending}
                aria-busy={isBulkStopping}
                onclick={() => confirmBulkStop(selectedStoppableWebsiteIds)}
              >
                <IconStop data-icon="inline-start" />
                {isBulkStopping
                  ? m.stopping_crawls()
                  : m.stop_selected_crawls({ count: selectedStoppableWebsiteIds.length })}
              </Button>
            {/if}
          {/if}
          {#if selectedDeletableWebsiteIds.length > 0}
            <Button
              variant="destructive"
              disabled={bulkActionPending}
              aria-busy={isBulkDeleting}
              onclick={() => confirmBulkDelete(selectedDeletableWebsiteIds)}
            >
              <IconTrash data-icon="inline-start" />
              {isBulkDeleting
                ? m.removing_websites()
                : m.remove_selected_websites({ count: selectedDeletableWebsiteIds.length })}
            </Button>
          {/if}
          {#if $currentSpace.hasPermission("create", "website")}
            <Button onclick={bulkRecrawl} disabled={bulkActionPending} aria-busy={isBulkRecrawling}>
              <IconRefresh data-icon="inline-start" />
              {isBulkRecrawling
                ? m.syncing()
                : m.sync_selected({ count: $selectedWebsiteIds.size })}
            </Button>
          {/if}
        {:else}
          {#if $currentSpace.hasPermission("create", "website")}
            {#if stoppableWebsiteIds.length > 0}
              <Button
                variant="outline"
                disabled={bulkActionPending}
                aria-busy={isBulkStopping}
                onclick={() => confirmBulkStop(stoppableWebsiteIds)}
              >
                <IconStop data-icon="inline-start" />
                {isBulkStopping
                  ? m.stopping_crawls()
                  : m.stop_all_crawls({ count: stoppableWebsiteIds.length })}
              </Button>
            {/if}
            <WebsiteEditor mode="create"></WebsiteEditor>
          {:else}
            {@render noCreatePermission(m.websites().toLowerCase())}
          {/if}
        {/if}
      {:else if $selectedTab === "integrations" && $currentSpace.hasPermission("create", "integrationKnowledge")}
        {#if data.settings.sharepoint_fixture_mode_available}
          <SharePointFixtureLauncher authType={isPersonalSpace ? "user_oauth" : "tenant_app"}
          ></SharePointFixtureLauncher>
        {/if}
        {#if data.availableIntegrations.length > 0}
          <ImportKnowledgeDialog></ImportKnowledgeDialog>
        {:else if isPersonalSpace}
          <LegacyButton
            variant="primary"
            onclick={() => (window.location.href = resolve("/account/integrations?tab=providers"))}
          >
            {m.configure_integrations()}
          </LegacyButton>
        {:else if isAdmin}
          <LegacyButton
            variant="primary"
            onclick={() => (window.location.href = resolve("/admin/integrations?tab=providers"))}
          >
            {m.configure_integrations()}
          </LegacyButton>
        {:else}
          <p class="text-secondary max-w-72 text-right text-xs">
            {isOrgSpace
              ? m.org_integrations_require_admin()
              : m.shared_integrations_require_admin()}
          </p>
        {/if}
      {:else if $selectedTab === "integrations"}
        {@render noCreatePermission(m.integrations().toLowerCase())}
      {/if}
    </Page.Flex>
  </Page.Header>
  <Page.Main>
    {#if userCanSeeCollections}
      <Page.Tab id="collections">
        <CollectionTable></CollectionTable>
      </Page.Tab>
    {/if}
    {#if userCanSeeWebsites}
      <Page.Tab id="websites">
        <WebsiteTable bind:selectedWebsiteIds></WebsiteTable>
      </Page.Tab>
    {/if}
    {#if userCanSeeIntegrations}
      <Page.Tab id="integrations">
        {#if showIntegrationsNotice}
          <div class="border-dimmer hidden border-b py-3 pr-3 lg:block">
            <div
              class="label-neutral border-label-default bg-label-dimmer text-label-stronger flex items-center gap-8 rounded-lg border px-4 py-3 shadow"
            >
              <div class="flex flex-col">
                <span class="font-mono text-xs uppercase">{m.beta_version()}</span>
                <span class="text-xl font-extrabold">{m.integrations()}</span>
              </div>
              <p class="-mt-[0.1rem] max-w-[85ch] pl-6 leading-[1.3rem]">
                {m.integrations_beta_notice()}
                <!-- eslint-disable svelte/no-navigation-without-resolve -- external URL -->
                <a
                  target="_blank"
                  rel="noreferrer"
                  class="hover:bg-label-stronger hover:text-label-dimmer inline items-center gap-1 underline"
                  href={data.environment.integrationRequestFormUrl}
                  >{m.request_integrations_feedback()}
                </a>
                <!-- eslint-enable svelte/no-navigation-without-resolve -->
                <IconLinkExternal class="-mt-0.5 inline" size="sm"></IconLinkExternal>
              </p>
              <div class="flex-grow"></div>
              <LegacyButton
                variant="outlined"
                class="min-w-24"
                on:click={() => {
                  showIntegrationsNotice = false;
                }}>{m.dismiss()}</LegacyButton
              >
            </div>
          </div>
        {/if}
        <IntegrationsTable onSelectIntegrationForSyncHistory={handleSelectIntegration}
        ></IntegrationsTable>
        <SyncHistoryDialog
          knowledge={selectedIntegrationForSyncHistory}
          bind:open={showSyncHistoryDialog}
        ></SyncHistoryDialog>
      </Page.Tab>
    {/if}
  </Page.Main>
</Page.Root>

<AlertDialog.Root bind:open={stopDialogOpen}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>
        {m.stop_crawls_title({ count: stopTargetIds.length })}
      </AlertDialog.Title>
      <AlertDialog.Description>{m.stop_crawls_description()}</AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={isBulkStopping}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" disabled={isBulkStopping} onclick={bulkStop}>
        {isBulkStopping ? m.stopping_crawls() : m.stop_crawl()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root bind:open={deleteDialogOpen}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>
        {m.remove_websites_title({ count: deleteTargetIds.length })}
      </AlertDialog.Title>
      <AlertDialog.Description>{m.remove_websites_description()}</AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={isBulkDeleting}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" disabled={isBulkDeleting} onclick={bulkDelete}>
        {isBulkDeleting ? m.removing_websites() : m.remove_websites_confirm()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
