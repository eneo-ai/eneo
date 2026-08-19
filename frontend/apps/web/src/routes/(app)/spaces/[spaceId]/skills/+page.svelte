<script lang="ts">
  import type { ResourcePermission, SkillSparse } from "@eneo/eneo-js";
  import { invalidate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { Page } from "$lib/components/layout";
  import { getErrorMessage } from "$lib/core/errors";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { SkillCatalogQuery } from "$lib/features/skills/skillCatalogQuery.svelte";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import LoaderCircle from "lucide-svelte/icons/loader-circle";
  import Plus from "lucide-svelte/icons/plus";
  import Search from "lucide-svelte/icons/search";
  import Trash2 from "lucide-svelte/icons/trash-2";
  import { onDestroy, untrack } from "svelte";

  const CREATE_SKILL_PERMISSION: ResourcePermission = "create";
  const DELETE_SKILL_PERMISSION: ResourcePermission = "delete";

  let { data } = $props();

  let deleteTarget = $state<SkillSparse | null>(null);
  let deleteError = $state<string | null>(null);
  let isDeleting = $state(false);
  let loadedInitialPage = untrack(() => data.skills);
  const skillCatalog = new SkillCatalogQuery(loadedInitialPage, (params) =>
    data.eneo.skills.list({ spaceId: data.currentSpace.id, ...params })
  );
  onDestroy(() => skillCatalog.dispose());

  $effect(() => {
    if (data.skills === loadedInitialPage) return;
    loadedInitialPage = data.skills;
    skillCatalog.reset(data.skills);
  });

  const spaceRouteId = $derived(
    data.currentSpace.personal
      ? "personal"
      : data.currentSpace.organization
        ? "organization"
        : data.currentSpace.id
  );
  const canCreate = $derived(data.currentSpace.skill_permissions.includes(CREATE_SKILL_PERMISSION));
  const canDelete = $derived(data.currentSpace.skill_permissions.includes(DELETE_SKILL_PERMISSION));

  function formatUpdatedAt(value: string): string {
    return new Date(value).toLocaleString(getLocale() === "sv" ? "sv-SE" : "en-US", {
      dateStyle: "short",
      timeStyle: "short"
    });
  }

  async function deleteSkill(event: MouseEvent) {
    event.preventDefault();
    if (!deleteTarget) return;
    isDeleting = true;
    deleteError = null;
    try {
      await data.eneo.skills.delete({
        spaceId: data.currentSpace.id,
        skillId: deleteTarget.id
      });
      deleteTarget = null;
      await invalidate("space:skills");
    } catch (error) {
      // Each delete conflict carries its own reason code, so the localized
      // recovery instruction names the actual blocker.
      deleteError = getErrorMessage(error);
    } finally {
      isDeleting = false;
    }
  }
</script>

<svelte:head>
  <title>{m.skills_library_page_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.skills()}></Page.Title>
    {#if canCreate && data.skills.items.length > 0}
      <Button href={resolve(`/spaces/${spaceRouteId}/skills/new`)}>
        <Plus data-icon="inline-start" aria-hidden="true" />
        {m.skills_library_create()}
      </Button>
    {/if}
  </Page.Header>
  <Page.Main>
    <div class="mx-auto w-full max-w-[1100px] px-4 py-6 sm:px-6 sm:py-8">
      <p class="text-muted-foreground mb-6 max-w-[65ch] text-sm leading-6">
        {m.skills_library_intro()}
      </p>

      {#if skillCatalog.items.length === 0 && !skillCatalog.query && !skillCatalog.loading && !skillCatalog.error}
        <div class="border-border max-w-3xl border-y py-8">
          <div class="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
            <div class="max-w-lg">
              <h2 class="text-foreground text-base font-medium">
                {m.skills_library_empty_title()}
              </h2>
              <p class="text-muted-foreground mt-1.5 text-sm leading-6">
                {m.skills_library_empty_description()}
              </p>
            </div>
            {#if canCreate}
              <Button
                class="shrink-0 sm:mt-0.5"
                href={resolve(`/spaces/${spaceRouteId}/skills/new`)}
              >
                <Plus data-icon="inline-start" aria-hidden="true" />
                {m.skills_library_create_first()}
              </Button>
            {/if}
          </div>
        </div>
      {:else}
        <InputGroup.Root class="mb-3 max-w-sm">
          <InputGroup.Addon>
            <Search aria-hidden="true" />
          </InputGroup.Addon>
          <InputGroup.Input
            value={skillCatalog.query}
            type="search"
            placeholder={m.skills_library_search_placeholder()}
            aria-label={m.skills_library_search_placeholder()}
            oninput={(event) => skillCatalog.setQuery(event.currentTarget.value)}
          />
        </InputGroup.Root>

        {#if skillCatalog.error}
          <div class="flex flex-col items-center gap-3 py-12 text-center">
            <p class="text-destructive text-sm" role="alert">{skillCatalog.error}</p>
            <Button variant="outline" size="sm" onclick={() => skillCatalog.retry()}>
              {m.retry()}
            </Button>
          </div>
        {:else if skillCatalog.loading && skillCatalog.items.length === 0}
          <p
            class="text-muted-foreground flex items-center justify-center gap-2 py-12 text-sm"
            role="status"
          >
            <LoaderCircle class="size-4 animate-spin" aria-hidden="true" />
            {m.loading()}
          </p>
        {:else if skillCatalog.items.length === 0}
          <div class="border-border max-w-3xl border-y py-10 text-center">
            <p class="text-foreground text-sm font-medium">{m.skills_library_no_results()}</p>
            <Button
              class="mt-3"
              type="button"
              variant="ghost"
              onclick={() => skillCatalog.setQuery("")}
            >
              {m.clear()}
            </Button>
          </div>
        {:else}
          <div class="border-border @container border-y">
            <Table.Root class="w-full table-fixed">
              <Table.Header>
                <Table.Row>
                  <Table.Head class="w-auto @4xl:w-[22%]">{m.name()}</Table.Head>
                  <Table.Head class="hidden w-[30%] @4xl:table-cell">
                    {m.description()}
                  </Table.Head>
                  <Table.Head class="hidden w-32 @md:table-cell">{m.status()}</Table.Head>
                  <Table.Head class="hidden w-24 @4xl:table-cell">
                    {m.skills_library_revision_column()}
                  </Table.Head>
                  <Table.Head class="hidden w-32 @4xl:table-cell">
                    {m.skills_library_updated_column()}
                  </Table.Head>
                  {#if canDelete}
                    <Table.Head class="w-16 text-right">{m.actions()}</Table.Head>
                  {/if}
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {#each skillCatalog.items as skill (skill.id)}
                  <Table.Row class="[&>td]:align-top">
                    <Table.Cell class="min-w-0 font-medium @4xl:w-[22%]">
                      <a
                        href={resolve(`/spaces/${spaceRouteId}/skills/${skill.id}`)}
                        class="text-foreground hover:text-accent-default focus-visible:ring-ring line-clamp-2 break-words whitespace-normal rounded-sm hover:underline focus-visible:ring-2 focus-visible:outline-none"
                      >
                        {skill.display_name}
                      </a>
                      <p class="text-muted-foreground mt-0.5 break-all whitespace-normal text-xs">
                        {skill.slug}
                      </p>
                      <div class="mt-2 @md:hidden">
                        <Badge variant={skill.is_active ? "secondary" : "outline"}>
                          {skill.is_active
                            ? m.skills_available_status()
                            : m.skills_unavailable_status()}
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
                            {m.skills_revision_label({
                              revision: String(skill.current_revision_number)
                            })}
                          </dd>
                        </div>
                        <div class="flex gap-1 @4xl:hidden">
                          <dt>{m.skills_library_updated_column()}:</dt>
                          <dd>{formatUpdatedAt(skill.updated_at)}</dd>
                        </div>
                      </dl>
                    </Table.Cell>
                    <Table.Cell
                      class="text-muted-foreground hidden w-[30%] max-w-lg whitespace-normal @4xl:table-cell"
                    >
                      <p class="line-clamp-2">{skill.description}</p>
                    </Table.Cell>
                    <Table.Cell class="hidden @md:table-cell">
                      <Badge variant={skill.is_active ? "secondary" : "outline"}>
                        {skill.is_active
                          ? m.skills_available_status()
                          : m.skills_unavailable_status()}
                      </Badge>
                    </Table.Cell>
                    <Table.Cell class="text-muted-foreground hidden text-sm @4xl:table-cell">
                      {m.skills_revision_label({
                        revision: String(skill.current_revision_number)
                      })}
                    </Table.Cell>
                    <Table.Cell class="text-muted-foreground hidden text-sm @4xl:table-cell">
                      {formatUpdatedAt(skill.updated_at)}
                    </Table.Cell>
                    {#if canDelete}
                      <Table.Cell class="text-right">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          class="size-11 md:size-7"
                          title={m.delete()}
                          aria-label={m.skills_library_delete_aria({ name: skill.display_name })}
                          onclick={() => (deleteTarget = skill)}
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
          {#if skillCatalog.loading}
            <p class="text-muted-foreground mt-3 text-center text-sm" role="status">
              {m.loading()}
            </p>
          {/if}
          {#if skillCatalog.hasMore && !skillCatalog.loading}
            <div class="mt-4 flex justify-center">
              <Button
                variant="outline"
                disabled={skillCatalog.loadingMore}
                onclick={() => skillCatalog.loadMore()}
              >
                {skillCatalog.loadingMore ? m.loading() : m.load_more()}
              </Button>
            </div>
          {/if}
        {/if}
      {/if}
    </div>
  </Page.Main>
</Page.Root>

<AlertDialog.Root
  open={deleteTarget !== null}
  onOpenChange={(open) => {
    if (!open && !isDeleting) {
      deleteTarget = null;
      deleteError = null;
    }
  }}
>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.skills_library_delete_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.skills_library_delete_description({ name: deleteTarget?.display_name ?? "" })}
      </AlertDialog.Description>
    </AlertDialog.Header>
    {#if deleteError}
      <p class="text-destructive text-sm" role="alert">{deleteError}</p>
    {/if}
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={isDeleting}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" disabled={isDeleting} onclick={deleteSkill}>
        {isDeleting ? m.skills_library_deleting() : m.delete()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
