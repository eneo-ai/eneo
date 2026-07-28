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
  };

  let {
    skillId,
    initialPage,
    initialLoading = false,
    initialError = false,
    getOrganizationSkillAdoption,
    onAdvancePersonalChat
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

<section
  class="flex flex-col gap-5"
  aria-labelledby="organization-skill-adoption-heading"
  aria-busy={loadingInitial || loadingMore}
>
  <header>
    <h2 id="organization-skill-adoption-heading" class="text-foreground text-lg font-semibold">
      {m.organization_skills_adoption_heading()}
    </h2>
    <p class="text-muted-foreground mt-1 max-w-[70ch] text-sm leading-6">
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
  {:else if summary !== null}
    <dl class="grid grid-cols-2 gap-x-4 gap-y-5 border-y py-4 sm:grid-cols-4">
      <div>
        <dt class="text-muted-foreground text-xs font-medium">
          {m.organization_skills_adoption_assistants_label()}
        </dt>
        <dd class="mt-1 text-xl font-semibold tabular-nums">
          {summary.assistant_count}
        </dd>
      </div>
      <div>
        <dt class="text-muted-foreground text-xs font-medium">
          {m.organization_skills_adoption_apps_label()}
        </dt>
        <dd class="mt-1 text-xl font-semibold tabular-nums">{summary.app_count}</dd>
      </div>
      <div>
        <dt class="text-muted-foreground text-xs font-medium">
          {m.organization_skills_adoption_spaces_label()}
        </dt>
        <dd class="mt-1 text-xl font-semibold tabular-nums">
          {summary.distinct_space_count}
        </dd>
      </div>
      <div>
        <dt class="text-muted-foreground text-xs font-medium">
          {m.organization_skills_adoption_behind_label()}
        </dt>
        <dd class="mt-1 text-xl font-semibold tabular-nums">
          {summary.behind_published_count}
        </dd>
      </div>
    </dl>

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
          <div class="mt-3 flex min-h-10 flex-wrap items-center gap-2 border-y py-3">
            {#if summary.personal_chat}
              {@const personalChat = summary.personal_chat}
              <span class="text-sm">
                {m.organization_skills_adoption_personal_chat_pinned({
                  version: String(personalChat.revision_number)
                })}
              </span>
              <Badge variant={driftVariant(personalChat.drift)}>
                {driftLabel(personalChat.drift)}
              </Badge>
              {#if onAdvancePersonalChat !== undefined && personalChat.drift === "behind"}
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
          <p class="text-muted-foreground mt-1 text-xs leading-5">
            {m.organization_skills_adoption_revision_breakdown_description()}
          </p>
          <div class="border-border @container mt-3 border-y">
            <Table.Root class="w-full table-fixed">
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
            <Table.Root class="w-full table-fixed">
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
