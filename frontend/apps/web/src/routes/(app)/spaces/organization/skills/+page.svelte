<script lang="ts">
  import type { OrganizationSkillSummaryPublic } from "@eneo/eneo-js";
  import { invalidate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { Page } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { getErrorMessage } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { Info, LoaderCircle, Plus, RefreshCw, Search, Trash2, X } from "lucide-svelte";
  import { untrack } from "svelte";

  let { data } = $props();

  let serverPage = $state.raw(untrack(() => data.page));
  let items = $state<OrganizationSkillSummaryPublic[]>(untrack(() => [...serverPage.items]));
  let nextCursor = $state(untrack(() => serverPage.next_cursor ?? null));
  let loadingMore = $state(false);
  let loadError = $state<string | null>(null);
  let deleteTarget = $state<OrganizationSkillSummaryPublic | null>(null);
  let deleteError = $state<string | null>(null);
  let deleting = $state(false);
  let refreshWarning = $state(false);

  $effect(() => {
    const refreshedPage = data.page;
    if (refreshedPage === serverPage) return;
    serverPage = refreshedPage;
    items = [...refreshedPage.items];
    nextCursor = refreshedPage.next_cursor ?? null;
    loadError = null;
  });

  function canDelete(skill: OrganizationSkillSummaryPublic): boolean {
    return skill.publication_state === "draft";
  }

  function formatDate(value: string): string {
    return new Date(value).toLocaleString(getLocale() === "sv" ? "sv-SE" : "en-US", {
      dateStyle: "short",
      timeStyle: "short"
    });
  }

  function publicationLabel(skill: OrganizationSkillSummaryPublic): string {
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

  function publicationVariant(
    skill: OrganizationSkillSummaryPublic
  ): "default" | "secondary" | "outline" {
    if (skill.publication_state === "published") return "secondary";
    if (skill.publication_state === "update_pending") return "default";
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
    try {
      const page = await data.eneo.skills.organization.list({
        cursor: nextCursor,
        search: data.search || undefined
      });
      items = [...items, ...page.items];
      nextCursor = page.next_cursor ?? null;
    } catch (error) {
      loadError = getErrorMessage(error) || m.organization_skills_load_more_error();
    } finally {
      loadingMore = false;
    }
  }

  async function deleteSkill(event: MouseEvent) {
    event.preventDefault();
    if (!deleteTarget || deleting) return;
    deleting = true;
    deleteError = null;
    const deletedSkillId = deleteTarget.id;
    try {
      await data.eneo.skills.organization.delete({ skillId: deletedSkillId });
    } catch (error) {
      deleteError = getErrorMessage(error) || m.organization_skills_delete_error();
      deleting = false;
      return;
    }
    items = items.filter((skill) => skill.id !== deletedSkillId);
    deleteTarget = null;
    deleting = false;
    await refreshOrganizationSkills();
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
      <div class="max-w-3xl">
        <h2 class="text-foreground text-lg font-semibold">
          {m.organization_skills_manage_heading()}
        </h2>
        <p class="text-muted-foreground mt-1 max-w-[65ch] text-sm leading-6">
          {m.organization_skills_manage_intro()}
        </p>
      </div>

      {#if items.length > 0 || data.search}
        <form
          method="GET"
          action={resolve("/spaces/organization/skills")}
          class="grid max-w-xl grid-cols-[minmax(0,1fr)_auto] gap-2"
          role="search"
        >
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
                href={resolve("/spaces/organization/skills")}
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
        <div class="border-border flex max-w-3xl flex-col items-center border-y px-6 py-10">
          <h2 class="text-foreground text-base font-medium">
            {data.search
              ? m.skills_library_no_results()
              : m.organization_skills_empty_manage_title()}
          </h2>
          {#if !data.search}
            <p class="text-muted-foreground mt-2 max-w-lg text-center text-sm leading-6">
              {m.organization_skills_empty_manage_description()}
            </p>
            <Button class="mt-5" href={resolve("/spaces/organization/skills/new")}>
              <Plus data-icon="inline-start" aria-hidden="true" />
              {m.skills_library_create_first()}
            </Button>
          {/if}
        </div>
      {:else}
        <!-- svelte-ignore a11y_no_noninteractive_tabindex (overflow region must be keyboard-scrollable) -->
        <div
          class="border-border focus-visible:ring-ring overflow-x-auto border-y outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
          role="region"
          aria-label={m.organization_skills_table_scroll_region_label({
            count: String(items.length)
          })}
          tabindex="0"
        >
          <Table.Root class="w-full min-w-0 table-fixed md:min-w-[860px]">
            <Table.Header>
              <Table.Row>
                <Table.Head class="w-auto md:w-[24%]">{m.name()}</Table.Head>
                <Table.Head class="hidden md:table-cell">{m.description()}</Table.Head>
                <Table.Head class="hidden md:table-cell">{m.status()}</Table.Head>
                <Table.Head class="hidden md:table-cell">
                  {m.skills_library_revision_column()}
                </Table.Head>
                <Table.Head class="hidden md:table-cell">
                  {m.skills_library_updated_column()}
                </Table.Head>
                <Table.Head class="w-16 text-right">
                  <span class="sr-only md:not-sr-only">{m.actions()}</span>
                </Table.Head>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {#each items as skill (skill.id)}
                <Table.Row class="[&>td]:align-top">
                  <Table.Cell class="min-w-0 font-medium md:w-[24%]">
                    <a
                      href={resolve(`/spaces/organization/skills/${skill.id}`)}
                      class="text-foreground hover:text-accent-default focus-visible:ring-ring line-clamp-2 break-words whitespace-normal rounded-sm hover:underline focus-visible:ring-2 focus-visible:outline-none"
                    >
                      {skill.display_name}
                    </a>
                    <p class="text-muted-foreground mt-0.5 break-all whitespace-normal text-xs">
                      {skill.slug}
                    </p>
                    <div class="mt-2 md:hidden">
                      <Badge variant={publicationVariant(skill)}>{publicationLabel(skill)}</Badge>
                    </div>
                    <p
                      class="text-muted-foreground mt-2 line-clamp-2 min-w-0 break-words whitespace-normal pr-2 text-sm leading-6 md:hidden"
                    >
                      {skill.description}
                    </p>
                    <dl
                      class="text-muted-foreground mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs font-normal md:hidden"
                    >
                      <div class="flex gap-1">
                        <dt>{m.skills_library_revision_column()}:</dt>
                        <dd>
                          {m.organization_skills_version({
                            version: String(skill.current_revision_number)
                          })}
                        </dd>
                      </div>
                      <div class="flex gap-1">
                        <dt>{m.skills_library_updated_column()}:</dt>
                        <dd>{formatDate(skill.updated_at)}</dd>
                      </div>
                    </dl>
                  </Table.Cell>
                  <Table.Cell
                    class="text-muted-foreground hidden w-[40%] max-w-lg whitespace-normal md:table-cell"
                  >
                    <p class="line-clamp-2">{skill.description}</p>
                  </Table.Cell>
                  <Table.Cell class="hidden md:table-cell">
                    <Badge variant={publicationVariant(skill)}>{publicationLabel(skill)}</Badge>
                  </Table.Cell>
                  <Table.Cell class="text-muted-foreground hidden text-sm md:table-cell">
                    {m.organization_skills_version({
                      version: String(skill.current_revision_number)
                    })}
                  </Table.Cell>
                  <Table.Cell class="text-muted-foreground hidden text-sm md:table-cell">
                    {formatDate(skill.updated_at)}
                  </Table.Cell>
                  <Table.Cell class="text-right">
                    {#if canDelete(skill)}
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        class="size-11 md:size-7"
                        title={m.delete()}
                        aria-label={m.skills_library_delete_aria({
                          name: skill.display_name
                        })}
                        onclick={() => (deleteTarget = skill)}
                      >
                        <Trash2 aria-hidden="true" />
                      </Button>
                    {/if}
                  </Table.Cell>
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

<AlertDialog.Root
  open={deleteTarget !== null}
  onOpenChange={(open) => {
    if (!open && !deleting) {
      deleteTarget = null;
      deleteError = null;
    }
  }}
>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.skills_library_delete_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.organization_skills_delete_description({
          name: deleteTarget?.display_name ?? ""
        })}
      </AlertDialog.Description>
    </AlertDialog.Header>
    {#if deleteError}
      <p class="text-destructive text-sm" role="alert">{deleteError}</p>
    {/if}
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={deleting}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" disabled={deleting} onclick={deleteSkill}>
        {deleting ? m.skills_library_deleting() : m.delete()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
