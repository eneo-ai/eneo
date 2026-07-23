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

  type Props = {
    skillId: string;
    initialPage: SkillAdoptionProjectionPagePublic | null;
    initialLoading?: boolean;
    initialError?: boolean;
    getOrganizationSkillAdoption: (
      skillId: string,
      options: { limit: number; cursor: string | null }
    ) => Promise<SkillAdoptionProjectionPagePublic>;
  };

  let {
    skillId,
    initialPage,
    initialLoading = false,
    initialError = false,
    getOrganizationSkillAdoption
  }: Props = $props();

  let sourcePage = $state.raw(untrack(() => initialPage));
  let page = $state.raw<SkillAdoptionProjectionPagePublic | null>(untrack(() => initialPage));
  let summary = $state.raw(untrack(() => initialPage?.summary ?? null));
  let items = $state<AdoptionResource[]>(untrack(() => [...(initialPage?.items ?? [])]));
  let nextCursor = $state<string | null>(untrack(() => initialPage?.next_cursor ?? null));
  let loadingInitial = $state(untrack(() => initialLoading));
  let initialLoadError = $state(untrack(() => initialError));
  let loadingMore = $state(false);
  let loadMoreError = $state<string | null>(null);
  let resourceTotal = $derived(summary === null ? 0 : summary.assistant_count + summary.app_count);

  $effect(() => {
    if (initialPage === null || initialPage === sourcePage) return;
    sourcePage = initialPage;
    page = initialPage;
    summary = initialPage.summary;
    items = [...initialPage.items];
    nextCursor = initialPage.next_cursor ?? null;
    loadingInitial = false;
    initialLoadError = false;
    loadMoreError = null;
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

  async function retryInitialLoad() {
    if (loadingInitial) return;
    loadingInitial = true;
    initialLoadError = false;
    try {
      const loadedPage = await getOrganizationSkillAdoption(skillId, {
        limit: 25,
        cursor: null
      });
      sourcePage = loadedPage;
      page = loadedPage;
      summary = loadedPage.summary;
      items = [...loadedPage.items];
      nextCursor = loadedPage.next_cursor ?? null;
    } catch {
      initialLoadError = true;
    } finally {
      loadingInitial = false;
    }
  }

  async function loadMore() {
    if (page === null || nextCursor === null || loadingMore) return;
    const cursor = nextCursor;
    loadingMore = true;
    loadMoreError = null;
    try {
      const loadedPage = await getOrganizationSkillAdoption(skillId, {
        limit: page.limit,
        cursor
      });
      items = [...items, ...loadedPage.items];
      nextCursor = loadedPage.next_cursor ?? null;
    } catch (error) {
      loadMoreError = getErrorMessage(error) || m.organization_skills_adoption_load_more_error();
    } finally {
      loadingMore = false;
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
              <span class="text-sm">
                {m.organization_skills_adoption_personal_chat_pinned({
                  version: String(summary.personal_chat.revision_number)
                })}
              </span>
              <Badge variant={driftVariant(summary.personal_chat.drift)}>
                {driftLabel(summary.personal_chat.drift)}
              </Badge>
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
          <!-- svelte-ignore a11y_no_noninteractive_tabindex (overflow region must be keyboard-scrollable) -->
          <div
            class="border-border focus-visible:ring-ring mt-3 overflow-x-auto border-y outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
            role="group"
            aria-labelledby="organization-skill-revision-breakdown-heading"
            tabindex="0"
          >
            <div class="min-w-[32rem]">
              <Table.Root>
                <Table.Header>
                  <Table.Row>
                    <Table.Head>
                      {m.organization_skills_adoption_revision_column()}
                    </Table.Head>
                    <Table.Head class="text-right">
                      {m.organization_skills_adoption_assistants_label()}
                    </Table.Head>
                    <Table.Head class="text-right">
                      {m.organization_skills_adoption_apps_label()}
                    </Table.Head>
                    <Table.Head class="text-right">
                      <span class="sr-only">
                        {m.organization_skills_adoption_personal_chat_column()}
                      </span>
                      <span aria-hidden="true"
                        >{m.organization_skills_adoption_personal_chat_heading()}</span
                      >
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
                      </Table.Cell>
                      <Table.Cell class="text-right tabular-nums">
                        {revision.assistant_count}
                      </Table.Cell>
                      <Table.Cell class="text-right tabular-nums">
                        {revision.app_count}
                      </Table.Cell>
                      <Table.Cell class="text-right">
                        {revision.personal_chat_pinned
                          ? m.organization_skills_adoption_pinned()
                          : m.organization_skills_adoption_not_pinned()}
                      </Table.Cell>
                    </Table.Row>
                  {/each}
                </Table.Body>
              </Table.Root>
            </div>
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
          <!-- svelte-ignore a11y_no_noninteractive_tabindex (overflow region must be keyboard-scrollable) -->
          <div
            class="border-border focus-visible:ring-ring mt-4 overflow-x-auto border-y outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
            role="region"
            aria-label={m.organization_skills_adoption_table_scroll_region_label({
              count: String(items.length)
            })}
            tabindex="0"
          >
            <div class="min-w-[44rem]">
              <Table.Root>
                <Table.Header>
                  <Table.Row>
                    <Table.Head>{m.organization_skills_adoption_resource_column()}</Table.Head>
                    <Table.Head>
                      {m.organization_skills_adoption_resource_type_column()}
                    </Table.Head>
                    <Table.Head>{m.organization_skills_adoption_space_column()}</Table.Head>
                    <Table.Head>
                      {m.organization_skills_adoption_pinned_revision_column()}
                    </Table.Head>
                    <Table.Head>{m.organization_skills_adoption_status_column()}</Table.Head>
                  </Table.Row>
                </Table.Header>
                <Table.Body>
                  {#each items as resource (`${resource.kind}:${resource.resource_id}`)}
                    <Table.Row>
                      <Table.Cell class="max-w-64 whitespace-normal">
                        <span class="line-clamp-2 font-medium">{resource.name}</span>
                      </Table.Cell>
                      <Table.Cell>{resourceKindLabel(resource.kind)}</Table.Cell>
                      <Table.Cell class="max-w-56 whitespace-normal">
                        <span class="line-clamp-2">{resource.space_name}</span>
                      </Table.Cell>
                      <Table.Cell>
                        {m.organization_skills_version({
                          version: String(resource.revision_number)
                        })}
                      </Table.Cell>
                      <Table.Cell>
                        <Badge variant={driftVariant(resource.drift)}>
                          {driftLabel(resource.drift)}
                        </Badge>
                      </Table.Cell>
                    </Table.Row>
                  {/each}
                </Table.Body>
              </Table.Root>
            </div>
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
