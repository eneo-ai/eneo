<script lang="ts" module>
  export type AppSkillAdoptionRun = {
    status: "pending" | "running" | "completed" | "stopped" | "failed";
    provisionalTotal: number;
    advanced: number;
    concurrentChange: number;
    contextWindow: number;
  };

  export type SkillAdoptionRun = {
    status: "running" | "completed" | "stopped" | "failed";
    assistantsIncluded: boolean;
    provisionalTotal: number;
    advanced: number;
    concurrentChange: number;
    activationUnavailable: number;
    contextWindow: number;
    personalChat: "pending" | "advanced" | "failed" | "not_applicable";
    apps: AppSkillAdoptionRun | null;
    stopRequested?: boolean;
  };

  export type SkillBindingUpdateScope = {
    assistants: boolean;
    apps: boolean;
  };

  export type SkillAdoptionQuery = {
    limit: number;
    cursor: string | null;
    query?: string;
    kind?: "assistant" | "app";
    drift?: "current" | "behind";
  };

  export type SkillDetachSelection = {
    assistantIds: string[];
    appIds: string[];
  };

  export type SkillSelectedAdvanceResult = {
    advanced: number;
    concurrentChange: number;
    incompatible: number;
    // Every resource the server reported an outcome for; the rest were not
    // processed (already current, detached meanwhile, or in a failed request).
    processedIds: string[];
    // Resources whose request failed after earlier work was committed.
    failedIds: string[];
    error: string | null;
  };
</script>

<script lang="ts">
  import type { SkillAdoptionProjectionPagePublic, SkillDetachmentTotals } from "@eneo/eneo-js";
  import { AlertCircle, LoaderCircle, RefreshCw, Search, Unlink } from "lucide-svelte";
  import { resolve } from "$app/paths";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { getErrorMessage } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { tick, untrack } from "svelte";

  type AdoptionResource = SkillAdoptionProjectionPagePublic["items"][number];
  type AdoptionDrift = AdoptionResource["drift"];

  type PersonalChatPin = { revisionId: string; revisionNumber: number };

  type Props = {
    skillId: string;
    initialPage: SkillAdoptionProjectionPagePublic | null;
    initialLoading?: boolean;
    initialError?: boolean;
    getOrganizationSkillAdoption: (
      skillId: string,
      options: SkillAdoptionQuery
    ) => Promise<SkillAdoptionProjectionPagePublic>;
    onDetach?: (selection: SkillDetachSelection) => Promise<SkillDetachmentTotals>;
    onAdvanceSelected?: (selection: SkillDetachSelection) => Promise<SkillSelectedAdvanceResult>;
    onAdvancePersonalChat?: (pinned: PersonalChatPin) => void;
    publishedRevisionId?: string | null;
    onStartOutdatedBindingsUpdate?: (
      projection: SkillAdoptionProjectionPagePublic,
      scope: SkillBindingUpdateScope
    ) => void;
    run?: SkillAdoptionRun | null;
    onStop?: () => void;
    onRestart?: () => void;
  };

  let {
    skillId,
    initialPage,
    initialLoading = false,
    initialError = false,
    getOrganizationSkillAdoption,
    onDetach,
    onAdvanceSelected,
    onAdvancePersonalChat,
    publishedRevisionId = null,
    onStartOutdatedBindingsUpdate,
    run = null,
    onStop,
    onRestart
  }: Props = $props();

  let observedSkillId = untrack(() => skillId);
  let observedInitialPage = untrack(() => initialPage);
  // The parent keeps one instance and moves it between load states, so a
  // change from loading to failed carries the same (null) page.
  let observedInitialLoading = untrack(() => initialLoading);
  let observedInitialError = untrack(() => initialError);
  // A local request may outlive a reactive parent refresh even when the current route often remounts.
  let projectionGeneration = 0;
  let page = $state.raw<SkillAdoptionProjectionPagePublic | null>(untrack(() => initialPage));
  let items = $state<AdoptionResource[]>(untrack(() => [...(initialPage?.items ?? [])]));
  let nextCursor = $state<string | null>(untrack(() => initialPage?.next_cursor ?? null));
  let loadingInitial = $state(untrack(() => initialLoading));
  let initialLoadError = $state(untrack(() => initialError));
  let loadingMore = $state(false);
  let loadMoreError = $state<string | null>(null);
  let summary = $derived(page?.summary ?? null);

  // Resource filters are server-side; the summary above them stays whole-skill.
  type KindFilter = "all" | "assistant" | "app";
  type DriftFilter = "all" | "current" | "behind";
  let queryInput = $state("");
  let queryTimer: ReturnType<typeof setTimeout> | null = null;
  let query = $state("");
  let kindFilter = $state<KindFilter>("all");
  let driftFilter = $state<DriftFilter>("all");
  let filtersActive = $derived(query !== "" || kindFilter !== "all" || driftFilter !== "all");
  let matchedCount = $state(untrack(() => initialPage?.matched_count ?? 0));
  let reloading = $state(false);
  let reloadError = $state<string | null>(null);

  // Selection is bounded by the detach endpoint; select-all takes the first 100 loaded rows.
  const selectionLimit = 100;
  let selectedKeys = $state<string[]>([]);
  // Rows that stay selected even when the page they came from is no longer
  // loaded, so a retry after a partial failure still carries them.
  let retainedSelection = $state<AdoptionResource[]>([]);
  let selectableItems = $derived(items.slice(0, selectionLimit));
  let selectedResources = $derived([
    ...items.filter((resource) => selectedKeys.includes(resourceKey(resource))),
    ...retainedSelection.filter(
      (resource) =>
        selectedKeys.includes(resourceKey(resource)) &&
        !items.some((item) => resourceKey(item) === resourceKey(resource))
    )
  ]);
  let detachAvailable = $derived(onDetach !== undefined && run?.status !== "running");
  let advanceAvailable = $derived(
    onAdvanceSelected !== undefined && publishedRevisionId !== null && run?.status !== "running"
  );
  let selectionActionsAvailable = $derived(detachAvailable || advanceAvailable);
  let selectedBehind = $derived(
    selectedResources.filter((resource) => resource.drift === "behind")
  );
  // One confirmation dialog serves both selection actions.
  let pendingAction = $state<"detach" | "advance" | null>(null);
  let actionRunning = $state(false);
  let actionError = $state<string | null>(null);
  let actionReceipt = $state("");
  // A receipt that reports nothing done needs to read as an outcome, not noise.
  let receiptNeedsAttention = $state(false);
  let rolloutProcessed = $derived(
    run === null
      ? 0
      : run.advanced + run.concurrentChange + run.activationUnavailable + run.contextWindow
  );
  let rolloutTotal = $derived(run === null ? 0 : Math.max(run.provisionalTotal, rolloutProcessed));
  let appRolloutProcessed = $derived(
    run?.apps === null || run?.apps === undefined
      ? 0
      : run.apps.advanced + run.apps.concurrentChange + run.apps.contextWindow
  );
  let appRolloutTotal = $derived(
    run?.apps === null || run?.apps === undefined
      ? 0
      : Math.max(run.apps.provisionalTotal, appRolloutProcessed)
  );
  let assistantUpdateAvailable = $derived(
    publishedRevisionId !== null &&
      summary !== null &&
      summary.revision_counts.some(
        (revision) => revision.revision_id !== publishedRevisionId && revision.assistant_count > 0
      )
  );
  let personalChatUpdateAvailable = $derived(
    publishedRevisionId !== null &&
      summary?.personal_chat !== null &&
      summary?.personal_chat !== undefined &&
      summary.personal_chat.revision_id !== publishedRevisionId
  );
  let appUpdateAvailable = $derived(
    publishedRevisionId !== null &&
      summary !== null &&
      summary.revision_counts.some(
        (revision) => revision.revision_id !== publishedRevisionId && revision.app_count > 0
      )
  );
  let outdatedBindingScope = $derived<SkillBindingUpdateScope>({
    assistants: personalChatUpdateAvailable || assistantUpdateAvailable,
    apps: appUpdateAvailable
  });
  let recoveryActionAvailable = $derived(
    (assistantUpdateAvailable || appUpdateAvailable) &&
      onStartOutdatedBindingsUpdate !== undefined &&
      run?.status !== "running" &&
      run?.personalChat !== "pending"
  );

  $effect(() => {
    const nextSkillId = skillId;
    const nextInitialPage = initialPage;
    const nextInitialLoading = initialLoading;
    const nextInitialError = initialError;
    if (
      nextSkillId === observedSkillId &&
      nextInitialPage === observedInitialPage &&
      nextInitialLoading === observedInitialLoading &&
      nextInitialError === observedInitialError
    ) {
      return;
    }

    const skillChanged = nextSkillId !== observedSkillId;
    observedSkillId = nextSkillId;
    observedInitialPage = nextInitialPage;
    observedInitialLoading = nextInitialLoading;
    observedInitialError = nextInitialError;
    projectionGeneration += 1;
    loadingMore = false;
    loadMoreError = null;
    // Only a request started after this point may own the loading flag.
    reloading = false;
    reloadError = null;
    clearSelection();
    if (skillChanged) {
      untrack(() => clearFilters(false));
    }

    if (nextInitialPage === null) {
      page = null;
      items = [];
      nextCursor = null;
      matchedCount = 0;
      loadingInitial = initialLoading;
      initialLoadError = initialError;
      return;
    }

    page = nextInitialPage;
    items = [...nextInitialPage.items];
    nextCursor = nextInitialPage.next_cursor ?? null;
    matchedCount = nextInitialPage.matched_count ?? 0;
    loadingInitial = false;
    initialLoadError = false;
    untrack(() => {
      // Unpublishing hides the status control; drop its filter before deciding
      // whether the unfiltered page just handed over needs a filtered reload.
      if (publishedRevisionId === null) driftFilter = "all";
      // A parent refresh hands over an unfiltered first page; re-apply the admin's filters.
      if (filtersActive) void reload();
    });
  });

  $effect(() => {
    // The status control disappears while unpublished; its filter must not linger.
    if (publishedRevisionId === null && driftFilter !== "all") {
      driftFilter = "all";
      void untrack(() => reload());
    }
  });

  function clearSelection() {
    selectedKeys = [];
    retainedSelection = [];
  }

  function resourceKey(resource: AdoptionResource): string {
    return `${resource.kind}:${resource.resource_id}`;
  }

  function filterOptions(): Pick<SkillAdoptionQuery, "query" | "kind" | "drift"> {
    return {
      query: query || undefined,
      kind: kindFilter === "all" ? undefined : kindFilter,
      drift: driftFilter === "all" ? undefined : driftFilter
    };
  }

  function kindFilterLabel(value: KindFilter): string {
    switch (value) {
      case "all":
        return m.organization_skills_adoption_filter_kind_all();
      case "assistant":
        return m.organization_skills_adoption_resource_assistant();
      case "app":
        return m.organization_skills_adoption_resource_app();
    }
  }

  function driftFilterLabel(value: DriftFilter): string {
    switch (value) {
      case "all":
        return m.organization_skills_adoption_filter_status_all();
      case "current":
        return m.organization_skills_adoption_drift_current();
      case "behind":
        return m.organization_skills_adoption_drift_behind();
    }
  }

  // Reloads the first page with the current filters and drops every pending
  // response and the selection, so an older request cannot overwrite it.
  async function reload() {
    const generation = ++projectionGeneration;
    const requestSkillId = skillId;
    reloading = true;
    reloadError = null;
    loadingMore = false;
    loadMoreError = null;
    // The old cursor belongs to the old filters; never continue from it.
    nextCursor = null;
    clearSelection();
    try {
      const loadedPage = await getOrganizationSkillAdoption(requestSkillId, {
        limit: 25,
        cursor: null,
        ...filterOptions()
      });
      if (!isCurrentProjection(generation, requestSkillId)) return;
      page = loadedPage;
      items = [...loadedPage.items];
      nextCursor = loadedPage.next_cursor ?? null;
      matchedCount = loadedPage.matched_count ?? 0;
    } catch (error) {
      if (!isCurrentProjection(generation, requestSkillId)) return;
      reloadError = getErrorMessage(error, m.organization_skills_adoption_reload_error());
    } finally {
      if (isCurrentProjection(generation, requestSkillId)) {
        reloading = false;
      }
    }
  }

  function setQuery(value: string) {
    queryInput = value;
    if (queryTimer !== null) clearTimeout(queryTimer);
    queryTimer = setTimeout(() => {
      queryTimer = null;
      const next = value.trim();
      if (next === query) return;
      query = next;
      void reload();
    }, 250);
  }

  function setKindFilter(value: string) {
    if (value === kindFilter) return;
    kindFilter = value as KindFilter;
    void reload();
  }

  function setDriftFilter(value: string) {
    if (value === driftFilter) return;
    driftFilter = value as DriftFilter;
    void reload();
  }

  function clearFilters(reloadAfter = true) {
    if (queryTimer !== null) {
      clearTimeout(queryTimer);
      queryTimer = null;
    }
    const wasActive = filtersActive;
    queryInput = "";
    query = "";
    kindFilter = "all";
    driftFilter = "all";
    if (reloadAfter && wasActive) void reload();
  }

  function toggleResource(resource: AdoptionResource, checked: boolean) {
    if (pendingAction === null) actionError = null;
    const key = resourceKey(resource);
    selectedKeys = checked
      ? [...selectedKeys.filter((existing) => existing !== key), key].slice(0, selectionLimit)
      : selectedKeys.filter((existing) => existing !== key);
  }

  function toggleAll(checked: boolean) {
    if (!checked) {
      clearSelection();
      return;
    }
    selectedKeys = selectableItems.map(resourceKey);
  }

  function toSelection(resources: AdoptionResource[]): SkillDetachSelection {
    return {
      assistantIds: resources
        .filter((resource) => resource.kind === "assistant")
        .map((resource) => resource.resource_id),
      appIds: resources
        .filter((resource) => resource.kind === "app")
        .map((resource) => resource.resource_id)
    };
  }

  async function announce(message: string, needsAttention = false) {
    actionReceipt = "";
    await tick();
    actionReceipt = message;
    receiptNeedsAttention = needsAttention;
  }

  async function confirmAction() {
    if (pendingAction === null || actionRunning || selectedResources.length === 0) return;
    actionRunning = true;
    actionError = null;
    try {
      let message: string;
      if (pendingAction === "detach") {
        if (onDetach === undefined) return;
        const result = await onDetach(toSelection(selectedResources));
        message = m.organization_skills_adoption_detached_success({
          assistants: String(result.assistant_count),
          apps: String(result.app_count)
        });
      } else {
        if (onAdvanceSelected === undefined) return;
        // Rows already on the published version are not sent, so the server
        // only validates real targets; every selected row is still accounted
        // for against the outcomes it returns.
        const submitted = selectedResources;
        const result = await onAdvanceSelected(toSelection(selectedBehind));
        const processed = new Set(result.processedIds);
        const failed = new Set(result.failedIds);
        const unprocessed = submitted.filter(
          (resource) => !processed.has(resource.resource_id) && !failed.has(resource.resource_id)
        ).length;
        message = m.organization_skills_adoption_advanced_success({
          advanced: String(result.advanced),
          unprocessed: String(unprocessed),
          concurrent: String(result.concurrentChange),
          incompatible: String(result.incompatible)
        });
        const rejected = result.concurrentChange + result.incompatible;
        if (result.error !== null) {
          // Part of the work is committed: report it, and keep exactly the
          // rows whose request failed selected, even if the refreshed page no
          // longer lists them.
          const failedRows = submitted.filter((resource) => failed.has(resource.resource_id));
          pendingAction = null;
          await announce(message, true);
          await reload();
          retainedSelection = failedRows;
          selectedKeys = failedRows.map(resourceKey);
          actionError = result.error;
          return;
        }
        pendingAction = null;
        clearSelection();
        // Nothing moved although the server accepted the request: that is an
        // outcome the administrator has to see, not only hear.
        await announce(message, result.advanced === 0 && rejected > 0);
        await reload();
        return;
      }
      pendingAction = null;
      clearSelection();
      await announce(message);
      await reload();
    } catch (error) {
      actionError = getErrorMessage(
        error,
        pendingAction === "detach"
          ? m.organization_skills_adoption_detach_error()
          : m.organization_skills_adoption_advance_error()
      );
    } finally {
      actionRunning = false;
    }
  }

  function resourceKindLabel(kind: AdoptionResource["kind"]): string {
    return kind === "assistant"
      ? m.organization_skills_adoption_resource_assistant()
      : m.organization_skills_adoption_resource_app();
  }

  function startOutdatedBindingsUpdate(): void {
    const projection = page;
    if (projection === null || onStartOutdatedBindingsUpdate === undefined) return;
    onStartOutdatedBindingsUpdate(projection, outdatedBindingScope);
  }

  function driftLabel(drift: AdoptionDrift): string {
    switch (drift) {
      case "current":
        return m.organization_skills_adoption_drift_current();
      case "behind":
        return m.organization_skills_adoption_drift_behind();
      case "unpublished":
        return m.organization_skills_adoption_drift_unpublished();
    }
  }

  function isCurrentProjection(generation: number, requestSkillId: string): boolean {
    return generation === projectionGeneration && requestSkillId === skillId;
  }

  function rolloutStatusLabel(status: SkillAdoptionRun["status"]): string {
    switch (status) {
      case "running":
        return m.organization_skills_rollout_status_running();
      case "completed":
        return m.organization_skills_rollout_status_completed();
      case "stopped":
        return m.organization_skills_rollout_status_stopped();
      case "failed":
        return m.organization_skills_rollout_status_failed();
    }
  }

  function rolloutStatusVariant(
    status: SkillAdoptionRun["status"]
  ): "default" | "secondary" | "outline" | "destructive" {
    switch (status) {
      case "running":
        return "secondary";
      case "completed":
        return "secondary";
      case "stopped":
        return "outline";
      case "failed":
        return "destructive";
    }
  }

  function personalChatResultLabel(result: SkillAdoptionRun["personalChat"]): string {
    switch (result) {
      case "pending":
        return m.organization_skills_rollout_personal_chat_pending();
      case "advanced":
        return m.organization_skills_rollout_personal_chat_advanced();
      case "failed":
        return m.organization_skills_rollout_personal_chat_failed();
      case "not_applicable":
        return m.organization_skills_rollout_personal_chat_not_applicable();
    }
  }

  function appRolloutStatusLabel(status: AppSkillAdoptionRun["status"]): string {
    switch (status) {
      case "pending":
        return m.organization_skills_rollout_apps_status_pending();
      case "running":
        return m.organization_skills_rollout_apps_status_running();
      case "completed":
        return m.organization_skills_rollout_apps_status_completed();
      case "stopped":
        return m.organization_skills_rollout_apps_status_stopped();
      case "failed":
        return m.organization_skills_rollout_apps_status_failed();
    }
  }

  function appRolloutStatusVariant(
    status: AppSkillAdoptionRun["status"]
  ): "default" | "secondary" | "outline" | "destructive" {
    switch (status) {
      case "running":
        return "secondary";
      case "completed":
        return "secondary";
      case "pending":
      case "stopped":
        return "outline";
      case "failed":
        return "destructive";
    }
  }

  async function retryInitialLoad() {
    if (loadingInitial) return;
    const generation = projectionGeneration;
    const requestSkillId = skillId;
    loadingInitial = true;
    initialLoadError = false;
    try {
      const loadedPage = await getOrganizationSkillAdoption(requestSkillId, {
        limit: 25,
        cursor: null,
        ...filterOptions()
      });
      if (!isCurrentProjection(generation, requestSkillId)) return;
      page = loadedPage;
      items = [...loadedPage.items];
      nextCursor = loadedPage.next_cursor ?? null;
      matchedCount = loadedPage.matched_count ?? 0;
    } catch {
      if (!isCurrentProjection(generation, requestSkillId)) return;
      initialLoadError = true;
    } finally {
      if (isCurrentProjection(generation, requestSkillId)) {
        loadingInitial = false;
      }
    }
  }

  async function loadMore() {
    if (page === null || nextCursor === null || loadingMore || reloading) return;
    const generation = projectionGeneration;
    const requestSkillId = skillId;
    const cursor = nextCursor;
    const limit = page.limit;
    loadingMore = true;
    loadMoreError = null;
    try {
      const loadedPage = await getOrganizationSkillAdoption(requestSkillId, {
        limit,
        cursor,
        ...filterOptions()
      });
      if (!isCurrentProjection(generation, requestSkillId)) return;
      items = [...items, ...loadedPage.items];
      nextCursor = loadedPage.next_cursor ?? null;
    } catch (error) {
      if (!isCurrentProjection(generation, requestSkillId)) return;
      loadMoreError = getErrorMessage(error, m.organization_skills_adoption_load_more_error());
    } finally {
      if (isCurrentProjection(generation, requestSkillId)) {
        loadingMore = false;
      }
    }
  }
</script>

{#snippet driftStatus(drift: AdoptionDrift)}
  {#if drift === "current"}
    <!-- The settled state needs no pill; attention goes to rows that need action. -->
    <span class="text-muted-foreground text-sm">{driftLabel(drift)}</span>
  {:else}
    <Badge variant="outline" class="h-auto min-h-5 max-w-full whitespace-normal text-left">
      {driftLabel(drift)}
    </Badge>
  {/if}
{/snippet}

{#snippet rolloutReceipt()}
  {#if run !== null}
    <section
      aria-labelledby="organization-skill-rollout-heading"
      class="border-border flex flex-col gap-3 border-y py-4 text-sm"
    >
      <div class="flex flex-wrap items-center gap-2">
        <h3
          id="organization-skill-rollout-heading"
          class={["font-medium", run.status === "failed" && "text-destructive"]}
        >
          {m.organization_skills_rollout_title()}
        </h3>
        <Badge variant={rolloutStatusVariant(run.status)}>
          {rolloutStatusLabel(run.status)}
        </Badge>
      </div>
      {#if run.assistantsIncluded}
        <p role="status" aria-live="polite" aria-atomic="true" class="font-medium tabular-nums">
          {m.organization_skills_rollout_progress({
            updated: String(run.advanced),
            total: String(rolloutTotal)
          })}
        </p>
        <div class="border-border border-y">
          <Table.Root>
            <Table.Header>
              <Table.Row>
                <Table.Head>{m.organization_skills_rollout_outcome_column()}</Table.Head>
                <Table.Head class="w-20 text-right">
                  {m.organization_skills_rollout_count_column()}
                </Table.Head>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              <Table.Row>
                <Table.Cell>{m.organization_skills_rollout_updated()}</Table.Cell>
                <Table.Cell class="text-right tabular-nums">{run.advanced}</Table.Cell>
              </Table.Row>
              <Table.Row>
                <Table.Cell>{m.organization_skills_rollout_concurrent_change()}</Table.Cell>
                <Table.Cell class="text-right tabular-nums">{run.concurrentChange}</Table.Cell>
              </Table.Row>
              <Table.Row>
                <Table.Cell>{m.organization_skills_rollout_activation_unavailable()}</Table.Cell>
                <Table.Cell class="text-right tabular-nums">{run.activationUnavailable}</Table.Cell>
              </Table.Row>
              <Table.Row>
                <Table.Cell>{m.organization_skills_rollout_context_window()}</Table.Cell>
                <Table.Cell class="text-right tabular-nums">{run.contextWindow}</Table.Cell>
              </Table.Row>
            </Table.Body>
          </Table.Root>
        </div>
        <div class="text-muted-foreground flex flex-col gap-1 leading-6">
          <p>{m.organization_skills_rollout_exclusions()}</p>
          <p>{personalChatResultLabel(run.personalChat)}</p>
          {#if run.status === "failed" && run.apps?.status !== "failed"}
            <p class="text-destructive">{m.organization_skills_rollout_failure()}</p>
          {/if}
        </div>
      {/if}
      {#if run.apps !== null}
        <section
          class="border-border flex flex-col gap-3 border-t pt-4"
          aria-labelledby="organization-skill-app-rollout-heading"
        >
          <div class="flex flex-wrap items-center gap-2">
            <h4 id="organization-skill-app-rollout-heading" class="text-foreground font-medium">
              {m.organization_skills_rollout_apps_title()}
            </h4>
            <Badge variant={appRolloutStatusVariant(run.apps.status)}>
              {appRolloutStatusLabel(run.apps.status)}
            </Badge>
          </div>
          <p role="status" aria-live="polite" aria-atomic="true" class="font-medium tabular-nums">
            {m.organization_skills_rollout_apps_progress({
              updated: String(run.apps.advanced),
              total: String(appRolloutTotal)
            })}
          </p>
          <div class="border-border border-y">
            <Table.Root>
              <Table.Header>
                <Table.Row>
                  <Table.Head>{m.organization_skills_rollout_outcome_column()}</Table.Head>
                  <Table.Head class="w-20 text-right">
                    {m.organization_skills_rollout_count_column()}
                  </Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                <Table.Row>
                  <Table.Cell>{m.organization_skills_rollout_updated()}</Table.Cell>
                  <Table.Cell class="text-right tabular-nums">{run.apps.advanced}</Table.Cell>
                </Table.Row>
                <Table.Row>
                  <Table.Cell>{m.organization_skills_rollout_concurrent_change()}</Table.Cell>
                  <Table.Cell class="text-right tabular-nums">
                    {run.apps.concurrentChange}
                  </Table.Cell>
                </Table.Row>
                <Table.Row>
                  <Table.Cell>{m.organization_skills_rollout_context_window()}</Table.Cell>
                  <Table.Cell class="text-right tabular-nums">
                    {run.apps.contextWindow}
                  </Table.Cell>
                </Table.Row>
              </Table.Body>
            </Table.Root>
          </div>
          <div class="text-muted-foreground flex flex-col gap-1 leading-6">
            <p>{m.organization_skills_rollout_apps_exclusions()}</p>
            <p>{m.organization_skills_rollout_apps_queued_runs_unchanged()}</p>
            {#if run.apps.status === "failed"}
              <p class="text-destructive">{m.organization_skills_rollout_apps_failure()}</p>
            {/if}
          </div>
        </section>
      {/if}
      {#if run.status === "running" && onStop !== undefined}
        <div>
          <Button
            variant="outline"
            size="sm"
            disabled={run.stopRequested === true}
            onclick={onStop}
          >
            {m.organization_skills_rollout_stop()}
          </Button>
        </div>
      {:else if (run.status === "stopped" || run.status === "failed") && run.personalChat !== "pending" && onRestart !== undefined && !recoveryActionAvailable}
        <div>
          <Button variant="outline" size="sm" onclick={onRestart}>
            {m.organization_skills_rollout_restart()}
          </Button>
        </div>
      {/if}
    </section>
  {/if}
{/snippet}

<section
  class="flex flex-col gap-5"
  aria-labelledby="organization-skill-adoption-heading"
  aria-busy={loadingInitial || loadingMore || reloading}
>
  <header>
    <h2
      id="organization-skill-adoption-heading"
      class="text-foreground scroll-mt-24 text-lg font-semibold"
    >
      {m.organization_skills_adoption_heading()}
    </h2>
    <p class="text-muted-foreground mt-1 max-w-[65ch] text-sm leading-6">
      {m.organization_skills_adoption_description()}
    </p>
  </header>

  <!-- The outcome of the last action outlives the reload it triggers, so it is
       rendered for every load state instead of inside the loaded table. -->
  <p
    class={[
      "text-sm",
      actionReceipt === "" && "sr-only",
      receiptNeedsAttention ? "text-accent-default font-medium" : "text-muted-foreground"
    ]}
    role="status"
    aria-live="polite"
  >
    {actionReceipt}
  </p>

  {#if loadingInitial}
    <div
      class="flex flex-col gap-4"
      role="status"
      aria-live="polite"
      aria-label={m.organization_skills_adoption_loading()}
    >
      <span class="sr-only">{m.organization_skills_adoption_loading()}</span>
      <div class="border-border grid grid-cols-2 gap-4 border-y py-4 sm:grid-cols-4">
        {#each Array(4) as _, index (index)}
          <div class="flex flex-col gap-2">
            <Skeleton class="h-3 w-20" />
            <Skeleton class="h-7 w-12" />
          </div>
        {/each}
      </div>
      <Skeleton class="h-14 w-full" />
      <Skeleton class="h-36 w-full" />
    </div>
  {:else if initialLoadError || page === null}
    <Alert.Root>
      <AlertCircle aria-hidden="true" />
      <Alert.Title>{m.organization_skills_adoption_error_title()}</Alert.Title>
      <Alert.Description>{m.organization_skills_adoption_error()}</Alert.Description>
      <Alert.Action>
        <Button variant="outline" size="sm" onclick={retryInitialLoad}>{m.retry()}</Button>
      </Alert.Action>
    </Alert.Root>
    {@render rolloutReceipt()}
  {:else if summary !== null}
    <dl class="border-border grid grid-cols-2 gap-x-6 gap-y-5 border-y py-5 sm:grid-cols-4">
      <div>
        <dt class="text-muted-foreground text-sm">
          {m.organization_skills_adoption_assistants_label()}
        </dt>
        <dd class="mt-1 text-xl font-semibold tabular-nums">
          {summary.assistant_count}
        </dd>
      </div>
      <div>
        <dt class="text-muted-foreground text-sm">
          {m.organization_skills_adoption_apps_label()}
        </dt>
        <dd class="mt-1 text-xl font-semibold tabular-nums">{summary.app_count}</dd>
      </div>
      <div>
        <dt class="text-muted-foreground text-sm">
          {m.organization_skills_adoption_spaces_label()}
        </dt>
        <dd class="mt-1 text-xl font-semibold tabular-nums">
          {summary.distinct_space_count}
        </dd>
      </div>
      <div>
        <dt class="text-muted-foreground text-sm">
          {m.organization_skills_adoption_behind_label()}
        </dt>
        <dd
          class={[
            "mt-1 text-xl font-semibold tabular-nums",
            summary.behind_published_count > 0 && "text-accent-default"
          ]}
        >
          {summary.behind_published_count}
        </dd>
      </div>
    </dl>

    {@render rolloutReceipt()}

    {#if recoveryActionAvailable}
      <Alert.Root>
        <Alert.Title>{m.organization_skills_rollout_recovery_title()}</Alert.Title>
        <Alert.Description>
          {m.organization_skills_rollout_recovery_description()}
        </Alert.Description>
        <div class="mt-3">
          <Button variant="outline" size="sm" onclick={startOutdatedBindingsUpdate}>
            {m.organization_skills_rollout_recovery_action()}
          </Button>
        </div>
      </Alert.Root>
    {/if}

    {#if summary.assistant_count === 0 && summary.app_count === 0 && summary.personal_chat === null}
      <div class="border-border flex flex-col items-center border-y px-6 py-8 text-center">
        <h3 class="text-foreground text-base font-medium">
          {m.organization_skills_adoption_empty_title()}
        </h3>
        <p class="text-muted-foreground mt-2 max-w-lg text-sm leading-6">
          {m.organization_skills_adoption_empty_description()}
        </p>
      </div>
    {:else}
      <div class="grid gap-6 lg:grid-cols-2">
        <section aria-labelledby="organization-skill-personal-chat-heading">
          <h3
            id="organization-skill-personal-chat-heading"
            class="text-foreground text-sm font-semibold"
          >
            {m.organization_skills_adoption_personal_chat_heading()}
          </h3>
          <div
            class="border-border mt-3 flex min-h-12 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-y py-3"
          >
            {#if summary.personal_chat}
              {@const personalChat = summary.personal_chat}
              <div class="flex flex-wrap items-center gap-2">
                <span class="text-sm">
                  {m.organization_skills_adoption_personal_chat_pinned({
                    version: String(personalChat.revision_number)
                  })}
                </span>
                {@render driftStatus(personalChat.drift)}
              </div>
              {#if onAdvancePersonalChat !== undefined && personalChat.drift === "behind" && !recoveryActionAvailable}
                <Button
                  variant="outline"
                  size="sm"
                  onclick={() =>
                    onAdvancePersonalChat({
                      revisionId: personalChat.revision_id,
                      revisionNumber: personalChat.revision_number
                    })}
                >
                  {m.organization_skills_adoption_personal_chat_advance_action()}
                </Button>
              {/if}
            {:else}
              <span class="text-muted-foreground text-sm">
                {m.organization_skills_adoption_personal_chat_not_pinned()}
              </span>
            {/if}
          </div>
        </section>

        <section aria-labelledby="organization-skill-revision-breakdown-heading">
          <h3
            id="organization-skill-revision-breakdown-heading"
            class="text-foreground text-sm font-semibold"
          >
            {m.organization_skills_adoption_revision_breakdown_heading()}
          </h3>
          <p class="text-muted-foreground mt-1 text-sm leading-6">
            {m.organization_skills_adoption_revision_breakdown_description()}
          </p>
          <div class="border-border @container mt-4 border-y">
            <Table.Root class="w-full table-fixed [&_td]:py-3">
              <Table.Header>
                <Table.Row>
                  <Table.Head class="w-auto">
                    {m.organization_skills_adoption_revision_column()}
                  </Table.Head>
                  <Table.Head class="w-20 text-right">
                    {m.organization_skills_adoption_assistants_label()}
                  </Table.Head>
                  <Table.Head class="w-16 text-right">
                    {m.organization_skills_adoption_apps_label()}
                  </Table.Head>
                  <Table.Head class="hidden w-36 text-right @md:table-cell">
                    {m.organization_skills_adoption_personal_chat_heading()}
                  </Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {#each summary.revision_counts as revision (revision.revision_id)}
                  <Table.Row>
                    <Table.Cell class="font-medium">
                      {m.organization_skills_version({
                        version: String(revision.revision_number)
                      })}
                      <p class="text-muted-foreground mt-1 text-xs font-normal @md:hidden">
                        {m.organization_skills_adoption_personal_chat_heading()}:
                        {revision.personal_chat_pinned
                          ? m.organization_skills_adoption_pinned()
                          : m.organization_skills_adoption_not_pinned()}
                      </p>
                    </Table.Cell>
                    <Table.Cell class="text-right tabular-nums">
                      {revision.assistant_count}
                    </Table.Cell>
                    <Table.Cell class="text-right tabular-nums">
                      {revision.app_count}
                    </Table.Cell>
                    <Table.Cell class="hidden text-right @md:table-cell">
                      {revision.personal_chat_pinned
                        ? m.organization_skills_adoption_pinned()
                        : m.organization_skills_adoption_not_pinned()}
                    </Table.Cell>
                  </Table.Row>
                {/each}
              </Table.Body>
            </Table.Root>
          </div>
        </section>
      </div>

      <Separator />

      <section aria-labelledby="organization-skill-resources-heading">
        <h3 id="organization-skill-resources-heading" class="text-foreground text-sm font-semibold">
          {m.organization_skills_adoption_resources_heading()}
        </h3>
        <p class="text-muted-foreground mt-1 max-w-[65ch] text-sm leading-6">
          {m.organization_skills_adoption_resources_description()}
        </p>

        <div class="@container mt-4">
          <div class="flex flex-col gap-3 @2xl:flex-row @2xl:items-center">
            <InputGroup.Root class="min-w-0 @2xl:max-w-sm">
              <InputGroup.Addon>
                <Search aria-hidden="true" />
              </InputGroup.Addon>
              <InputGroup.Input
                type="search"
                value={queryInput}
                maxlength={100}
                placeholder={m.organization_skills_adoption_search_placeholder()}
                aria-label={m.organization_skills_adoption_search_placeholder()}
                oninput={(event) => setQuery(event.currentTarget.value)}
              />
            </InputGroup.Root>
            <div class="flex flex-wrap items-center gap-2">
              <Select.Root type="single" value={kindFilter} onValueChange={setKindFilter}>
                <Select.Trigger
                  class="w-40"
                  aria-label={m.organization_skills_adoption_filter_kind_label()}
                >
                  <span data-slot="select-value">{kindFilterLabel(kindFilter)}</span>
                </Select.Trigger>
                <Select.Content>
                  <Select.Group>
                    {#each ["all", "assistant", "app"] as const as value (value)}
                      <Select.Item {value} label={kindFilterLabel(value)}>
                        {kindFilterLabel(value)}
                      </Select.Item>
                    {/each}
                  </Select.Group>
                </Select.Content>
              </Select.Root>
              {#if publishedRevisionId !== null}
                <Select.Root type="single" value={driftFilter} onValueChange={setDriftFilter}>
                  <Select.Trigger
                    class="w-56"
                    aria-label={m.organization_skills_adoption_filter_status_label()}
                  >
                    <span data-slot="select-value">{driftFilterLabel(driftFilter)}</span>
                  </Select.Trigger>
                  <Select.Content>
                    <Select.Group>
                      {#each ["all", "current", "behind"] as const as value (value)}
                        <Select.Item {value} label={driftFilterLabel(value)}>
                          {driftFilterLabel(value)}
                        </Select.Item>
                      {/each}
                    </Select.Group>
                  </Select.Content>
                </Select.Root>
              {/if}
              {#if filtersActive}
                <Button variant="ghost" size="sm" onclick={() => clearFilters()}>
                  {m.organization_skills_adoption_clear_filters()}
                </Button>
              {/if}
            </div>
          </div>

          {#if selectionActionsAvailable}
            <div class="mt-3 flex min-h-8 flex-wrap items-center gap-3">
              <p
                class={["text-muted-foreground text-sm", selectedKeys.length === 0 && "sr-only"]}
                aria-live="polite"
              >
                {m.organization_skills_adoption_selection_count({
                  count: String(selectedKeys.length),
                  limit: String(selectionLimit)
                })}
              </p>
              {#if selectedKeys.length > 0}
                {#if advanceAvailable}
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={selectedBehind.length === 0}
                    onclick={() => (pendingAction = "advance")}
                  >
                    <RefreshCw
                      aria-hidden="true"
                    />{m.organization_skills_adoption_advance_selected()}
                  </Button>
                {/if}
                {#if detachAvailable}
                  <Button variant="outline" size="sm" onclick={() => (pendingAction = "detach")}>
                    <Unlink aria-hidden="true" />{m.organization_skills_adoption_detach_selected()}
                  </Button>
                {/if}
                <Button variant="ghost" size="sm" onclick={clearSelection}>
                  {m.clear()}
                </Button>
              {/if}
            </div>
          {/if}
          {#if actionError !== null && pendingAction === null}
            <p class="text-destructive mt-2 text-sm" role="alert">{actionError}</p>
          {/if}
        </div>

        {#if reloading}
          <div class="mt-4 flex flex-col gap-3" role="status" aria-live="polite">
            <span class="sr-only">{m.organization_skills_adoption_loading()}</span>
            <Skeleton class="h-10 w-full" />
            <Skeleton class="h-10 w-full" />
            <Skeleton class="h-10 w-full" />
          </div>
        {:else if reloadError}
          <Alert.Root class="mt-4">
            <AlertCircle aria-hidden="true" />
            <Alert.Title>{m.organization_skills_adoption_error_title()}</Alert.Title>
            <Alert.Description>{reloadError}</Alert.Description>
            <Alert.Action>
              <Button variant="outline" size="sm" onclick={() => reload()}>{m.retry()}</Button>
            </Alert.Action>
          </Alert.Root>
        {:else if items.length === 0}
          <p class="text-muted-foreground border-border mt-4 border-y py-5 text-sm">
            {filtersActive
              ? m.organization_skills_adoption_filtered_empty()
              : m.organization_skills_adoption_resources_empty()}
          </p>
        {:else}
          <div class="border-border @container mt-4 border-y">
            <Table.Root class="w-full table-fixed [&_td]:py-3">
              <Table.Header>
                <Table.Row>
                  {#if selectionActionsAvailable}
                    <Table.Head class="w-10">
                      <Checkbox
                        class="relative before:absolute before:-inset-1.5 before:content-['']"
                        aria-label={m.organization_skills_adoption_select_shown({
                          count: String(selectableItems.length)
                        })}
                        checked={selectableItems.length > 0 &&
                          selectableItems.every((resource) =>
                            selectedKeys.includes(resourceKey(resource))
                          )}
                        onCheckedChange={(checked) => toggleAll(checked === true)}
                      />
                    </Table.Head>
                  {/if}
                  <Table.Head class="w-auto @4xl:w-[28%]">
                    {m.organization_skills_adoption_resource_column()}
                  </Table.Head>
                  <Table.Head class="hidden w-28 @4xl:table-cell">
                    {m.organization_skills_adoption_resource_type_column()}
                  </Table.Head>
                  <Table.Head class="hidden w-[28%] @4xl:table-cell">
                    {m.organization_skills_adoption_space_column()}
                  </Table.Head>
                  <Table.Head class="hidden w-28 @4xl:table-cell">
                    {m.organization_skills_adoption_pinned_revision_column()}
                  </Table.Head>
                  <Table.Head class="hidden w-36 @md:table-cell">
                    {m.organization_skills_adoption_status_column()}
                  </Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {#each items as resource (resourceKey(resource))}
                  {@const selected = selectedKeys.includes(resourceKey(resource))}
                  {@const spaceLabel =
                    resource.owner_name !== null && resource.owner_name !== undefined
                      ? `${m.organization_skills_adoption_personal_space()} · ${resource.owner_name}`
                      : resource.space_name}
                  <!-- Half-strength highlight keeps muted text at AA on a selected row. -->
                  <Table.Row
                    data-state={selected ? "selected" : undefined}
                    class="data-[state=selected]:bg-muted/50"
                  >
                    {#if selectionActionsAvailable}
                      <Table.Cell>
                        <Checkbox
                          class="relative before:absolute before:-inset-1.5 before:content-['']"
                          aria-label={m.organization_skills_adoption_select_resource({
                            name: resource.name
                          })}
                          checked={selected}
                          disabled={!selected && selectedKeys.length >= selectionLimit}
                          onCheckedChange={(checked) => toggleResource(resource, checked === true)}
                        />
                      </Table.Cell>
                    {/if}
                    <Table.Cell class="min-w-0 max-w-64 whitespace-normal">
                      {#if resource.can_open !== false}
                        <a
                          href={resource.kind === "assistant"
                            ? resolve("/(app)/spaces/[spaceId]/assistants/[assistantId]", {
                                spaceId: resource.space_id,
                                assistantId: resource.resource_id
                              })
                            : resolve("/(app)/spaces/[spaceId]/apps/[appId]", {
                                spaceId: resource.space_id,
                                appId: resource.resource_id
                              })}
                          class="text-foreground hover:text-accent-default focus-visible:ring-ring line-clamp-2 rounded-sm font-medium hover:underline focus-visible:ring-2 focus-visible:outline-none"
                        >
                          {resource.name}
                        </a>
                      {:else}
                        <!-- Another user's personal space: the admin cannot open it, so no dead link. -->
                        <span class="text-foreground line-clamp-2 font-medium">{resource.name}</span
                        >
                      {/if}
                      <div class="mt-2 @md:hidden">
                        {@render driftStatus(resource.drift)}
                      </div>
                      <dl class="text-muted-foreground mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                        <div class="flex gap-1 @4xl:hidden">
                          <dt>{m.organization_skills_adoption_resource_type_column()}:</dt>
                          <dd>{resourceKindLabel(resource.kind)}</dd>
                        </div>
                        <div class="flex min-w-0 gap-1 @4xl:hidden">
                          <dt>{m.organization_skills_adoption_space_column()}:</dt>
                          <dd class="line-clamp-1">{spaceLabel}</dd>
                        </div>
                        <div class="flex gap-1 @4xl:hidden">
                          <dt>{m.organization_skills_adoption_pinned_revision_column()}:</dt>
                          <dd>
                            {m.organization_skills_version({
                              version: String(resource.revision_number)
                            })}
                          </dd>
                        </div>
                      </dl>
                    </Table.Cell>
                    <Table.Cell class="hidden @4xl:table-cell">
                      {resourceKindLabel(resource.kind)}
                    </Table.Cell>
                    <Table.Cell class="hidden max-w-56 whitespace-normal @4xl:table-cell">
                      <span class="line-clamp-2">{spaceLabel}</span>
                    </Table.Cell>
                    <Table.Cell class="hidden @4xl:table-cell">
                      {m.organization_skills_version({
                        version: String(resource.revision_number)
                      })}
                    </Table.Cell>
                    <Table.Cell class="hidden @md:table-cell">
                      {@render driftStatus(resource.drift)}
                    </Table.Cell>
                  </Table.Row>
                {/each}
              </Table.Body>
            </Table.Root>
          </div>
        {/if}

        {#if items.length > 0 && !reloading}
          <p class="text-muted-foreground mt-3 text-sm tabular-nums" aria-live="polite">
            {m.organization_skills_adoption_resources_shown({
              shown: String(items.length),
              total: String(matchedCount)
            })}
          </p>
        {/if}

        {#if nextCursor !== null || loadMoreError}
          <div class="flex flex-col items-center gap-3 pt-4">
            {#if loadMoreError}
              <p class="text-destructive text-sm" role="alert">{loadMoreError}</p>
            {/if}
            {#if nextCursor !== null}
              <Button variant="outline" disabled={loadingMore} onclick={loadMore}>
                {#if loadingMore}
                  <LoaderCircle data-icon="inline-start" class="animate-spin" aria-hidden="true" />
                  {m.organization_skills_adoption_loading_more()}
                {:else if loadMoreError}
                  {m.retry()}
                {:else}
                  {m.organization_skills_adoption_load_more()}
                {/if}
              </Button>
            {/if}
          </div>
        {/if}
      </section>
    {/if}
  {/if}
</section>

{#if pendingAction !== null}
  {@const detach = pendingAction === "detach"}
  <AlertDialog.Root
    open
    onOpenChange={(open) => {
      if (open || actionRunning) return;
      pendingAction = null;
      actionError = null;
    }}
  >
    <AlertDialog.Content>
      <AlertDialog.Header>
        <AlertDialog.Title>
          {detach
            ? m.organization_skills_adoption_detach_title()
            : m.organization_skills_adoption_advance_title()}
        </AlertDialog.Title>
        <AlertDialog.Description>
          {detach
            ? m.organization_skills_adoption_detach_description({
                count: String(selectedResources.length)
              })
            : m.organization_skills_adoption_advance_description({
                count: String(selectedResources.length)
              })}
        </AlertDialog.Description>
      </AlertDialog.Header>
      <ul class="divide-border max-h-64 divide-y overflow-y-auto text-sm">
        {#each selectedResources as resource (resourceKey(resource))}
          <li class="flex items-center justify-between gap-3 py-2">
            <span class="min-w-0 truncate font-medium">{resource.name}</span>
            <span class="text-muted-foreground shrink-0">
              {detach ? resourceKindLabel(resource.kind) : driftLabel(resource.drift)}
            </span>
          </li>
        {/each}
      </ul>
      {#if actionError}
        <p class="text-destructive text-sm" role="alert">{actionError}</p>
      {/if}
      <AlertDialog.Footer>
        <AlertDialog.Cancel disabled={actionRunning}>{m.cancel()}</AlertDialog.Cancel>
        <AlertDialog.Action
          variant={detach ? "destructive" : "default"}
          disabled={actionRunning}
          onclick={confirmAction}
        >
          {#if actionRunning}
            <LoaderCircle data-icon="inline-start" class="animate-spin" aria-hidden="true" />
            {detach
              ? m.organization_skills_adoption_detaching()
              : m.organization_skills_adoption_advancing()}
          {:else}
            {detach
              ? m.organization_skills_adoption_detach_selected()
              : m.organization_skills_adoption_advance_selected()}
          {/if}
        </AlertDialog.Action>
      </AlertDialog.Footer>
    </AlertDialog.Content>
  </AlertDialog.Root>
{/if}
