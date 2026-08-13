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
</script>

<script lang="ts">
  import type { SkillAdoptionProjectionPagePublic } from "@eneo/eneo-js";
  import { AlertCircle, LoaderCircle } from "lucide-svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { getErrorMessage } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";

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
      options: { limit: number; cursor: string | null }
    ) => Promise<SkillAdoptionProjectionPagePublic>;
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
    onAdvancePersonalChat,
    publishedRevisionId = null,
    onStartOutdatedBindingsUpdate,
    run = null,
    onStop,
    onRestart
  }: Props = $props();

  let observedSkillId = untrack(() => skillId);
  let observedInitialPage = untrack(() => initialPage);
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
  let resourceTotal = $derived(summary === null ? 0 : summary.assistant_count + summary.app_count);
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
    if (nextSkillId === observedSkillId && nextInitialPage === observedInitialPage) return;

    observedSkillId = nextSkillId;
    observedInitialPage = nextInitialPage;
    projectionGeneration += 1;
    loadingMore = false;
    loadMoreError = null;

    if (nextInitialPage === null) {
      page = null;
      items = [];
      nextCursor = null;
      loadingInitial = initialLoading;
      initialLoadError = initialError;
      return;
    }

    page = nextInitialPage;
    items = [...nextInitialPage.items];
    nextCursor = nextInitialPage.next_cursor ?? null;
    loadingInitial = false;
    initialLoadError = false;
  });

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

  function driftVariant(drift: AdoptionDrift): "default" | "secondary" | "outline" {
    switch (drift) {
      case "current":
        return "secondary";
      case "behind":
        return "default";
      case "unpublished":
        return "outline";
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
        return "default";
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
        return "default";
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
        cursor: null
      });
      if (!isCurrentProjection(generation, requestSkillId)) return;
      page = loadedPage;
      items = [...loadedPage.items];
      nextCursor = loadedPage.next_cursor ?? null;
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
    if (page === null || nextCursor === null || loadingMore) return;
    const generation = projectionGeneration;
    const requestSkillId = skillId;
    const cursor = nextCursor;
    const limit = page.limit;
    loadingMore = true;
    loadMoreError = null;
    try {
      const loadedPage = await getOrganizationSkillAdoption(requestSkillId, {
        limit,
        cursor
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

{#snippet rolloutReceipt()}
  {#if run !== null}
    <Alert.Root
      role="region"
      aria-labelledby="organization-skill-rollout-heading"
      variant={run.status === "failed" ? "destructive" : "default"}
    >
      <Alert.Title>
        <div class="flex flex-wrap items-center gap-2">
          <span id="organization-skill-rollout-heading">
            {m.organization_skills_rollout_title()}
          </span>
          <Badge variant={rolloutStatusVariant(run.status)}>
            {rolloutStatusLabel(run.status)}
          </Badge>
        </div>
      </Alert.Title>
      <Alert.Description class="mt-2 flex flex-col gap-3 text-balance">
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
                  <Table.Cell class="text-right tabular-nums"
                    >{run.activationUnavailable}</Table.Cell
                  >
                </Table.Row>
                <Table.Row>
                  <Table.Cell>{m.organization_skills_rollout_context_window()}</Table.Cell>
                  <Table.Cell class="text-right tabular-nums">{run.contextWindow}</Table.Cell>
                </Table.Row>
              </Table.Body>
            </Table.Root>
          </div>
          <p>{m.organization_skills_rollout_exclusions()}</p>
          <p>{personalChatResultLabel(run.personalChat)}</p>
          {#if run.status === "failed" && run.apps?.status !== "failed"}
            <p>{m.organization_skills_rollout_failure()}</p>
          {/if}
        {/if}
        {#if run.apps !== null}
          <section
            class="border-border bg-muted/30 rounded-md border p-3"
            aria-labelledby="organization-skill-app-rollout-heading"
          >
            <div class="flex flex-wrap items-center justify-between gap-2">
              <h3 id="organization-skill-app-rollout-heading" class="text-foreground font-medium">
                {m.organization_skills_rollout_apps_title()}
              </h3>
              <Badge variant={appRolloutStatusVariant(run.apps.status)}>
                {appRolloutStatusLabel(run.apps.status)}
              </Badge>
            </div>
            <p
              role="status"
              aria-live="polite"
              aria-atomic="true"
              class="mt-3 font-medium tabular-nums"
            >
              {m.organization_skills_rollout_apps_progress({
                updated: String(run.apps.advanced),
                total: String(appRolloutTotal)
              })}
            </p>
            <div class="border-border mt-3 border-y">
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
            <div class="text-muted-foreground mt-3 space-y-2 text-sm leading-5">
              <p>{m.organization_skills_rollout_apps_exclusions()}</p>
              <p>{m.organization_skills_rollout_apps_queued_runs_unchanged()}</p>
              {#if run.apps.status === "failed"}
                <p>{m.organization_skills_rollout_apps_failure()}</p>
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
      </Alert.Description>
    </Alert.Root>
  {/if}
{/snippet}

<section
  class="flex flex-col gap-5"
  aria-labelledby="organization-skill-adoption-heading"
  aria-busy={loadingInitial || loadingMore}
>
  <header>
    <h2 id="organization-skill-adoption-heading" class="text-foreground text-lg font-semibold">
      {m.organization_skills_adoption_heading()}
    </h2>
    <p class="text-muted-foreground mt-1 max-w-[65ch] text-sm leading-6">
      {m.organization_skills_adoption_description()}
    </p>
  </header>

  {#if loadingInitial}
    <div
      class="flex flex-col gap-4"
      role="status"
      aria-live="polite"
      aria-label={m.organization_skills_adoption_loading()}
    >
      <span class="sr-only">{m.organization_skills_adoption_loading()}</span>
      <div class="grid grid-cols-2 gap-4 border-y py-4 sm:grid-cols-4">
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
    <dl class="grid grid-cols-2 gap-x-6 gap-y-5 border-y py-5 sm:grid-cols-4">
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
            class="mt-3 flex min-h-12 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-y py-3"
          >
            {#if summary.personal_chat}
              {@const personalChat = summary.personal_chat}
              <div class="flex flex-wrap items-center gap-2">
                <span class="text-sm">
                  {m.organization_skills_adoption_personal_chat_pinned({
                    version: String(personalChat.revision_number)
                  })}
                </span>
                <Badge variant={driftVariant(personalChat.drift)}>
                  {driftLabel(personalChat.drift)}
                </Badge>
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

        {#if items.length === 0}
          <p class="text-muted-foreground border-y py-5 text-sm">
            {m.organization_skills_adoption_resources_empty()}
          </p>
        {:else}
          <div class="border-border @container mt-4 border-y">
            <Table.Root class="w-full table-fixed [&_td]:py-3">
              <Table.Header>
                <Table.Row>
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
                {#each items as resource (`${resource.kind}:${resource.resource_id}`)}
                  <Table.Row>
                    <Table.Cell class="min-w-0 max-w-64 whitespace-normal">
                      <span class="line-clamp-2 font-medium">{resource.name}</span>
                      <div class="mt-2 @md:hidden">
                        <Badge variant={driftVariant(resource.drift)}>
                          {driftLabel(resource.drift)}
                        </Badge>
                      </div>
                      <dl class="text-muted-foreground mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                        <div class="flex gap-1 @4xl:hidden">
                          <dt>{m.organization_skills_adoption_resource_type_column()}:</dt>
                          <dd>{resourceKindLabel(resource.kind)}</dd>
                        </div>
                        <div class="flex min-w-0 gap-1 @4xl:hidden">
                          <dt>{m.organization_skills_adoption_space_column()}:</dt>
                          <dd class="line-clamp-1">{resource.space_name}</dd>
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
                      <span class="line-clamp-2">{resource.space_name}</span>
                    </Table.Cell>
                    <Table.Cell class="hidden @4xl:table-cell">
                      {m.organization_skills_version({
                        version: String(resource.revision_number)
                      })}
                    </Table.Cell>
                    <Table.Cell class="hidden @md:table-cell">
                      <Badge variant={driftVariant(resource.drift)}>
                        {driftLabel(resource.drift)}
                      </Badge>
                    </Table.Cell>
                  </Table.Row>
                {/each}
              </Table.Body>
            </Table.Root>
          </div>
        {/if}

        <span class="sr-only" aria-live="polite">
          {m.organization_skills_adoption_resources_shown({
            shown: String(items.length),
            total: String(resourceTotal)
          })}
        </span>

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
