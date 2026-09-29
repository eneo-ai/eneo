<script lang="ts">
  import { intlLocale } from "$lib/core/formatting/dateTime";
  import type { OrganizationSkillSummaryPublic, SkillRemovalResult } from "@eneo/eneo-js";
  import { invalidate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { Page } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import SkillRemovalDialog from "$lib/features/skills/SkillRemovalDialog.svelte";
  import { formatSkillUsage, removalAnnouncement } from "$lib/features/skills/skillUsage";
  import { getErrorMessage } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import {
    Info,
    LoaderCircle,
    Plus,
    RefreshCw,
    Search,
    ShieldAlert,
    Trash2,
    X,
    BookOpenCheck
  } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { SvelteURLSearchParams } from "svelte/reactivity";

  let { data } = $props();

  let serverPage = $state.raw(untrack(() => data.page));
  let items = $state<OrganizationSkillSummaryPublic[]>(untrack(() => [...serverPage.items]));
  let nextCursor = $state(untrack(() => serverPage.next_cursor ?? null));
  let loadingMore = $state(false);
  let loadError = $state<string | null>(null);
  const selectionLimit = 100;
  let selectedIds = $state<string[]>([]);
  let removalTargets = $state<OrganizationSkillSummaryPublic[]>([]);
  let announcement = $state("");
  let refreshWarning = $state(false);
  const selectedSkills = $derived(items.filter((skill) => selectedIds.includes(skill.id)));
  const selectableItems = $derived(items.slice(0, selectionLimit));

  function select(skillId: string, checked: boolean) {
    selectedIds = checked
      ? [...selectedIds, skillId].slice(0, selectionLimit)
      : selectedIds.filter((id) => id !== skillId);
  }

  $effect(() => {
    const refreshedPage = data.page;
    if (refreshedPage === serverPage) return;
    serverPage = refreshedPage;
    items = [...refreshedPage.items];
    nextCursor = refreshedPage.next_cursor ?? null;
    loadError = null;
    loadingMore = false;
    selectedIds = [];
    removalTargets = [];
  });

  function formatDate(value: string): string {
    return new Date(value).toLocaleString(intlLocale(), {
      dateStyle: "short",
      timeStyle: "short"
    });
  }

  function statusLabel(skill: OrganizationSkillSummaryPublic): string {
    if (skill.removed_at) return m.organization_skills_removed_status();
    if (skill.execution_blocked) return m.organization_skills_status_blocked();
    switch (skill.publication_state) {
      case "draft":
        return m.organization_skills_status_draft();
      case "published":
        return m.organization_skills_status_published();
      case "update_pending":
        return m.organization_skills_status_update_pending();
      case "unpublished":
        return m.organization_skills_status_unpublished();
    }
  }

  function statusVariant(
    skill: OrganizationSkillSummaryPublic
  ): "default" | "destructive" | "secondary" | "outline" {
    if (skill.removed_at) return "outline";
    if (skill.execution_blocked) return "outline";
    if (skill.publication_state === "published") return "secondary";
    if (skill.publication_state === "update_pending") return "outline";
    return "outline";
  }

  async function refreshOrganizationSkills() {
    try {
      await invalidate("organization:skills");
      refreshWarning = false;
    } catch {
      refreshWarning = true;
    }
  }

  async function loadMore() {
    if (nextCursor === null || loadingMore) return;
    loadingMore = true;
    loadError = null;
    const requestPage = data.page;
    try {
      const page = await data.eneo.skills.organization.list({
        cursor: nextCursor,
        search: data.search || undefined,
        removed: data.removed
      });
      if (data.page !== requestPage) return;
      items = [...items, ...page.items];
      nextCursor = page.next_cursor ?? null;
    } catch (error) {
      if (data.page === requestPage) {
        loadError = getErrorMessage(error, m.organization_skills_load_more_error());
      }
    } finally {
      if (data.page === requestPage) loadingMore = false;
    }
  }

  async function removedSkills(result: SkillRemovalResult) {
    const ids = result.removed_ids;
    if (!data.removed) items = items.filter((skill) => !ids.includes(skill.id));
    selectedIds = [];
    announcement = removalAnnouncement(result);
    await refreshOrganizationSkills();
  }

  function filterLink(removed: boolean): string {
    const query = new SvelteURLSearchParams();
    if (data.search) query.set("search", data.search);
    if (removed) query.set("removed", "true");
    return resolve("/spaces/organization/skills") + (query.size ? `?${query}` : "");
  }
</script>

<svelte:head>
  <title>{m.organization_skills_page_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.skills()}></Page.Title>
    {#if items.length > 0 || data.search}
      <Button href={resolve("/spaces/organization/skills/new")}>
        <Plus data-icon="inline-start" aria-hidden="true" />
        {m.skills_library_create()}
      </Button>
    {/if}
  </Page.Header>
  <Page.Main>
    <div class="mx-auto flex w-full max-w-[1100px] flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8">
      {#if refreshWarning}
        <Alert.Root>
          <Info aria-hidden="true" />
          <Alert.Title>{m.skills_form_saved_status()}</Alert.Title>
          <Alert.Description>
            {m.organization_skills_refresh_after_mutation_warning()}
          </Alert.Description>
          <Alert.Action>
            <Button
              variant="ghost"
              size="icon-sm"
              title={m.reload()}
              aria-label={m.reload()}
              onclick={() => window.location.reload()}
            >
              <RefreshCw aria-hidden="true" />
            </Button>
          </Alert.Action>
        </Alert.Root>
      {/if}
      <p class="text-muted-foreground max-w-[65ch] text-sm leading-6">
        {m.organization_skills_manage_intro()}
      </p>

      <nav class="flex flex-wrap gap-2" aria-label={m.organization_skills_filter_label()}>
        <Button
          data-skill-removal-focus
          href={filterLink(false)}
          variant={data.removed ? "ghost" : "secondary"}
          aria-current={!data.removed ? "page" : undefined}
          >{m.organization_skills_current_filter()}</Button
        >
        <Button
          href={filterLink(true)}
          variant={data.removed ? "secondary" : "ghost"}
          aria-current={data.removed ? "page" : undefined}
          >{m.organization_skills_removed_filter()}</Button
        >
      </nav>
      {#if data.removed}
        <p class="text-muted-foreground max-w-[65ch] text-sm">
          {m.organization_skills_removed_description()}
        </p>
      {/if}
      <p class={announcement ? "text-sm" : "sr-only"} role="status">{announcement}</p>

      {#if items.length > 0 || data.search}
        <form
          method="GET"
          action={resolve("/spaces/organization/skills")}
          class="grid max-w-xl grid-cols-[minmax(0,1fr)_auto] gap-2"
          role="search"
        >
          {#if data.removed}<input type="hidden" name="removed" value="true" />{/if}
          <InputGroup.Root class="min-w-0">
            <InputGroup.Addon>
              <Search aria-hidden="true" />
            </InputGroup.Addon>
            <InputGroup.Input
              name="search"
              type="search"
              value={data.search}
              maxlength={200}
              placeholder={m.skills_library_search_placeholder()}
              aria-label={m.skills_library_search_placeholder()}
            />
          </InputGroup.Root>
          <div class="flex gap-2">
            <Button type="submit" variant="outline">{m.search()}</Button>
            {#if data.search}
              <Button
                href={resolve("/spaces/organization/skills") +
                  (data.removed ? "?removed=true" : "")}
                variant="ghost"
                aria-label={m.organization_skills_clear_search()}
              >
                <X aria-hidden="true" />
                {m.clear()}
              </Button>
            {/if}
          </div>
        </form>
      {/if}

      {#if items.length === 0}
        <div
          class="border-border flex max-w-3xl flex-col items-center gap-4 px-6 py-12 text-center {data.search
            ? 'border-y'
            : 'rounded-xl border border-dashed'}"
        >
          {#if !data.search}
            <div
              class="bg-muted text-muted-foreground flex size-11 items-center justify-center rounded-full"
            >
              <BookOpenCheck class="size-5" aria-hidden="true" />
            </div>
          {/if}
          <div class="max-w-md">
            <h2 class="text-foreground text-base font-medium">
              {data.removed && !data.search
                ? m.organization_skills_removed_empty()
                : data.search
                  ? m.skills_library_no_results()
                  : m.organization_skills_empty_manage_title()}
            </h2>
            {#if !data.search && !data.removed}
              <p class="text-muted-foreground mt-1.5 text-sm leading-6">
                {m.organization_skills_empty_manage_description()}
              </p>
            {/if}
          </div>
          {#if !data.search && !data.removed}
            <Button href={resolve("/spaces/organization/skills/new")}>
              <Plus data-icon="inline-start" aria-hidden="true" />
              {m.skills_library_create_first()}
            </Button>
          {/if}
        </div>
      {:else}
        {#if !data.removed}
          <div class="flex flex-wrap items-center gap-3">
            <p
              class={["text-muted-foreground text-sm", selectedIds.length === 0 && "sr-only"]}
              aria-live="polite"
            >
              {m.organization_skills_selection_count({
                count: String(selectedIds.length),
                limit: String(selectionLimit)
              })}
            </p>
            {#if selectedIds.length > 0}
              <Button
                variant="outline"
                size="sm"
                onclick={() => (removalTargets = [...selectedSkills])}
              >
                <Trash2 aria-hidden="true" />{m.organization_skills_remove_selected()}
              </Button>
              <Button variant="ghost" size="sm" onclick={() => (selectedIds = [])}
                >{m.clear()}</Button
              >
            {/if}
          </div>
        {/if}
        <div class="border-border @container border-y">
          <Table.Root class="w-full table-fixed">
            <Table.Header>
              <Table.Row>
                {#if !data.removed}
                  <Table.Head class="w-12">
                    <Checkbox
                      class="relative before:absolute before:-inset-1.5 before:content-['']"
                      aria-label={m.organization_skills_select_shown({
                        count: String(selectableItems.length)
                      })}
                      checked={selectableItems.length > 0 &&
                        selectableItems.every((skill) => selectedIds.includes(skill.id))}
                      indeterminate={selectedIds.length > 0 &&
                        !selectableItems.every((skill) => selectedIds.includes(skill.id))}
                      onCheckedChange={(checked) =>
                        (selectedIds = checked ? selectableItems.map((skill) => skill.id) : [])}
                    />
                  </Table.Head>
                {/if}
                <Table.Head class="w-auto @4xl:w-[22%]">{m.name()}</Table.Head>
                <Table.Head class="hidden w-[30%] @4xl:table-cell">{m.description()}</Table.Head>
                <Table.Head class="hidden w-32 @md:table-cell">{m.status()}</Table.Head>
                <Table.Head class="hidden w-24 @4xl:table-cell">
                  {m.skills_library_revision_column()}
                </Table.Head>
                <Table.Head class="hidden w-32 @4xl:table-cell">
                  {m.skills_library_updated_column()}
                </Table.Head>
                {#if !data.removed}
                  <Table.Head class="w-16 text-right">
                    <span class="sr-only @4xl:not-sr-only">{m.actions()}</span>
                  </Table.Head>
                {/if}
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {#each items as skill (skill.id)}
                <Table.Row class="[&>td]:align-top">
                  {#if !data.removed}
                    <Table.Cell>
                      <Checkbox
                        class="relative before:absolute before:-inset-1.5 before:content-['']"
                        aria-label={m.organization_skills_select_skill({
                          name: skill.display_name
                        })}
                        checked={selectedIds.includes(skill.id)}
                        disabled={selectedIds.length >= selectionLimit &&
                          !selectedIds.includes(skill.id)}
                        onCheckedChange={(checked) => select(skill.id, checked)}
                      />
                    </Table.Cell>
                  {/if}
                  <Table.Cell class="min-w-0 font-medium @4xl:w-[22%]">
                    <a
                      href={resolve(`/spaces/organization/skills/${skill.id}`)}
                      class="text-foreground hover:text-accent-default focus-visible:ring-ring line-clamp-2 break-words whitespace-normal rounded-sm hover:underline focus-visible:ring-2 focus-visible:outline-none"
                    >
                      {skill.display_name}
                    </a>
                    <p class="text-muted-foreground mt-0.5 break-all whitespace-normal text-xs">
                      {skill.slug}
                    </p>
                    {#if !data.removed}
                      {@const usageText = formatSkillUsage(skill.usage)}
                      {#if usageText === null}
                        <p class="text-muted-foreground mt-2 text-xs font-normal leading-5">
                          {m.organization_skills_usage_none()}
                        </p>
                      {:else}
                        <a
                          href={resolve(
                            `/spaces/organization/skills/${skill.id}#organization-skill-adoption-heading`
                          )}
                          class="text-muted-foreground hover:text-foreground mt-2 block whitespace-normal text-xs font-normal leading-5 tabular-nums underline underline-offset-4"
                        >
                          {usageText}
                          {#if skill.usage.personal_chat_pinned}<span class="block"
                              >{m.organization_skills_usage_personal_chat()}</span
                            >{/if}
                        </a>
                      {/if}
                    {:else if skill.removed_at}
                      <p class="text-muted-foreground mt-2 whitespace-normal text-xs font-normal">
                        {m.organization_skills_removed_at({ time: formatDate(skill.removed_at) })}
                      </p>
                    {/if}
                    <div class="mt-2 @md:hidden">
                      <Badge
                        variant={statusVariant(skill)}
                        class="h-auto min-h-5 max-w-full whitespace-normal text-left"
                      >
                        {#if skill.execution_blocked && !skill.removed_at}
                          <ShieldAlert aria-hidden="true" />
                        {/if}
                        {statusLabel(skill)}
                      </Badge>
                    </div>
                    <p
                      class="text-muted-foreground mt-2 line-clamp-2 min-w-0 break-words whitespace-normal pr-2 text-sm leading-6 @4xl:hidden"
                    >
                      {skill.description}
                    </p>
                    <dl
                      class="text-muted-foreground mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs font-normal"
                    >
                      <div class="flex gap-1 @4xl:hidden">
                        <dt>{m.skills_library_revision_column()}:</dt>
                        <dd>
                          {m.organization_skills_version({
                            version: String(skill.current_revision_number)
                          })}
                        </dd>
                      </div>
                      <div class="flex gap-1 @4xl:hidden">
                        <dt>{m.skills_library_updated_column()}:</dt>
                        <dd class="tabular-nums">{formatDate(skill.updated_at)}</dd>
                      </div>
                    </dl>
                  </Table.Cell>
                  <Table.Cell
                    class="text-muted-foreground hidden w-[30%] max-w-lg whitespace-normal @4xl:table-cell"
                  >
                    <p class="line-clamp-2">{skill.description}</p>
                  </Table.Cell>
                  <Table.Cell class="hidden @md:table-cell">
                    <Badge
                      variant={statusVariant(skill)}
                      class="h-auto min-h-5 max-w-full whitespace-normal text-left"
                    >
                      {#if skill.execution_blocked && !skill.removed_at}
                        <ShieldAlert aria-hidden="true" />
                      {/if}
                      {statusLabel(skill)}
                    </Badge>
                  </Table.Cell>
                  <Table.Cell class="text-muted-foreground hidden text-sm @4xl:table-cell">
                    {m.organization_skills_version({
                      version: String(skill.current_revision_number)
                    })}
                  </Table.Cell>
                  <Table.Cell
                    class="text-muted-foreground hidden text-sm tabular-nums @4xl:table-cell"
                  >
                    {formatDate(skill.updated_at)}
                  </Table.Cell>
                  {#if !data.removed}
                    <Table.Cell class="text-right">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        class="size-11 md:size-7"
                        title={m.remove()}
                        aria-label={m.organization_skills_remove_aria({
                          name: skill.display_name
                        })}
                        onclick={() => (removalTargets = [skill])}
                      >
                        <Trash2 aria-hidden="true" />
                      </Button>
                    </Table.Cell>
                  {/if}
                </Table.Row>
              {/each}
            </Table.Body>
          </Table.Root>
        </div>
        {#if nextCursor !== null || loadError}
          <div class="flex flex-col items-center gap-3">
            {#if loadError}
              <p class="text-destructive text-sm" role="alert">{loadError}</p>
            {/if}
            {#if nextCursor !== null}
              <Button variant="outline" disabled={loadingMore} onclick={loadMore}>
                {#if loadingMore}
                  <LoaderCircle class="animate-spin" aria-hidden="true" />
                  {m.organization_skills_loading_more()}
                {:else}
                  {m.organization_skills_load_more()}
                {/if}
              </Button>
            {/if}
          </div>
        {/if}
      {/if}
    </div>
  </Page.Main>
</Page.Root>

{#if removalTargets.length > 0}
  <SkillRemovalDialog
    skills={removalTargets}
    onRemove={(request) => data.eneo.skills.organization.removeMany(request)}
    onRemoved={removedSkills}
    onClose={() => (removalTargets = [])}
    onExclude={(ids) => {
      removalTargets = removalTargets.filter((skill) => !ids.includes(skill.id));
      selectedIds = selectedIds.filter((id) => !ids.includes(id));
    }}
  />
{/if}
