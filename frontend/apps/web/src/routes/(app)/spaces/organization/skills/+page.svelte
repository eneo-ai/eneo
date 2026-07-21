<script lang="ts">
  import type { OrganizationSkillSummaryPublic, PublishedSkillSummaryPublic } from "@eneo/eneo-js";
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
  import { Info, LoaderCircle, Plus, Search, Trash2, X } from "lucide-svelte";
  import { untrack } from "svelte";

  type CatalogueItem = OrganizationSkillSummaryPublic | PublishedSkillSummaryPublic;

  let { data } = $props();

  let serverPage = $state.raw(untrack(() => data.page));
  let items = $state<CatalogueItem[]>(untrack(() => [...serverPage.items]));
  let nextCursor = $state(untrack(() => serverPage.next_cursor ?? null));
  let loadingMore = $state(false);
  let loadError = $state<string | null>(null);
  let deleteTarget = $state<OrganizationSkillSummaryPublic | null>(null);
  let deleteError = $state<string | null>(null);
  let deleting = $state(false);

  $effect(() => {
    const refreshedPage = data.page;
    if (refreshedPage === serverPage) return;
    serverPage = refreshedPage;
    items = [...refreshedPage.items];
    nextCursor = refreshedPage.next_cursor ?? null;
    loadError = null;
  });

  function isManagedSkill(skill: CatalogueItem): skill is OrganizationSkillSummaryPublic {
    return "current_revision_number" in skill;
  }

  function canDelete(skill: CatalogueItem): skill is OrganizationSkillSummaryPublic {
    return (
      isManagedSkill(skill) &&
      (skill.publication_state === "draft" || skill.publication_state === "unpublished")
    );
  }

  function revisionNumber(skill: CatalogueItem): number {
    return isManagedSkill(skill) ? skill.current_revision_number : skill.revision_number;
  }

  function updatedAt(skill: CatalogueItem): string {
    return isManagedSkill(skill) ? skill.updated_at : skill.first_published_at;
  }

  function formatDate(value: string): string {
    return new Date(value).toLocaleString(getLocale() === "sv" ? "sv-SE" : "en-US", {
      dateStyle: "short",
      timeStyle: "short"
    });
  }

  function publicationLabel(skill: CatalogueItem): string {
    if (!isManagedSkill(skill)) return m.organization_skills_status_published();
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

  function publicationVariant(skill: CatalogueItem): "default" | "secondary" | "outline" {
    if (!isManagedSkill(skill) || skill.publication_state === "published") return "secondary";
    if (skill.publication_state === "update_pending") return "default";
    return "outline";
  }

  async function loadMore() {
    if (nextCursor === null || loadingMore) return;
    loadingMore = true;
    loadError = null;
    try {
      const page =
        data.mode === "manage"
          ? await data.eneo.skills.organization.list({
              cursor: nextCursor,
              search: data.search || undefined
            })
          : await data.eneo.skills.catalogue.list({
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
    try {
      const deletedSkillId = deleteTarget.id;
      await data.eneo.skills.organization.delete({ skillId: deletedSkillId });
      items = items.filter((skill) => skill.id !== deletedSkillId);
      deleteTarget = null;
      await invalidate("organization:skills");
    } catch (error) {
      deleteError = getErrorMessage(error) || m.organization_skills_delete_error();
    } finally {
      deleting = false;
    }
  }
</script>

<svelte:head>
  <title>{m.organization_skills_page_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.skills()}></Page.Title>
    {#if data.canManage && (items.length > 0 || data.search)}
      <Button href={resolve("/spaces/organization/skills/new")}>
        <Plus data-icon="inline-start" aria-hidden="true" />
        {m.skills_library_create()}
      </Button>
    {/if}
  </Page.Header>
  <Page.Main>
    <div class="mx-auto flex w-full max-w-[1100px] flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8">
      <div class="max-w-3xl">
        <h2 class="text-foreground text-lg font-semibold">
          {data.mode === "manage"
            ? m.organization_skills_manage_heading()
            : m.organization_skills_browse_heading()}
        </h2>
        <p class="text-muted-foreground mt-1 max-w-[65ch] text-sm leading-6">
          {data.mode === "manage"
            ? m.organization_skills_manage_intro()
            : m.organization_skills_browse_intro()}
        </p>
      </div>

      {#if data.mode === "manage" && !data.canPublish}
        <Alert.Root>
          <Info aria-hidden="true" />
          <Alert.Title>{m.organization_skills_review_boundary_title()}</Alert.Title>
          <Alert.Description>
            {m.organization_skills_review_boundary_description()}
          </Alert.Description>
        </Alert.Root>
      {/if}

      {#if items.length > 0 || data.search}
        <form
          method="GET"
          action={resolve("/spaces/organization/skills")}
          class="flex max-w-xl flex-col gap-2 sm:flex-row"
          role="search"
        >
          <InputGroup.Root class="flex-1">
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
              : data.mode === "manage"
                ? m.organization_skills_empty_manage_title()
                : m.organization_skills_empty_browse_title()}
          </h2>
          {#if !data.search}
            <p class="text-muted-foreground mt-2 max-w-lg text-center text-sm leading-6">
              {data.mode === "manage"
                ? m.organization_skills_empty_manage_description()
                : m.organization_skills_empty_browse_description()}
            </p>
            {#if data.canManage}
              <Button class="mt-5" href={resolve("/spaces/organization/skills/new")}>
                <Plus data-icon="inline-start" aria-hidden="true" />
                {m.skills_library_create_first()}
              </Button>
            {/if}
          {/if}
        </div>
      {:else}
        <div class="border-border overflow-x-auto border-y">
          <Table.Root class="min-w-[860px]">
            <Table.Header>
              <Table.Row>
                <Table.Head>{m.name()}</Table.Head>
                <Table.Head>{m.description()}</Table.Head>
                <Table.Head>{m.status()}</Table.Head>
                <Table.Head>{m.skills_library_revision_column()}</Table.Head>
                <Table.Head>{m.skills_library_updated_column()}</Table.Head>
                {#if data.canPublish && data.mode === "manage"}
                  <Table.Head class="w-16 text-right">{m.actions()}</Table.Head>
                {/if}
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {#each items as skill (skill.id)}
                <Table.Row class="[&>td]:align-top">
                  <Table.Cell class="w-[24%] font-medium">
                    <a
                      href={resolve(`/spaces/organization/skills/${skill.id}`)}
                      class="text-foreground hover:text-accent-default focus-visible:ring-ring rounded-sm hover:underline focus-visible:ring-2 focus-visible:outline-none"
                    >
                      {skill.display_name}
                    </a>
                    <p class="text-muted-foreground mt-0.5 text-xs">{skill.slug}</p>
                  </Table.Cell>
                  <Table.Cell class="text-muted-foreground w-[40%] max-w-lg whitespace-normal">
                    <p class="line-clamp-2">{skill.description}</p>
                  </Table.Cell>
                  <Table.Cell>
                    <Badge variant={publicationVariant(skill)}>{publicationLabel(skill)}</Badge>
                  </Table.Cell>
                  <Table.Cell class="text-muted-foreground text-sm">
                    {m.organization_skills_version({
                      version: String(revisionNumber(skill))
                    })}
                  </Table.Cell>
                  <Table.Cell class="text-muted-foreground text-sm">
                    {formatDate(updatedAt(skill))}
                  </Table.Cell>
                  {#if data.canPublish && data.mode === "manage"}
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
                  {/if}
                </Table.Row>
              {/each}
            </Table.Body>
          </Table.Root>
          {#if nextCursor !== null || loadError}
            <div class="border-border flex flex-col items-center gap-3 border-t px-6 py-4">
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
        </div>
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
