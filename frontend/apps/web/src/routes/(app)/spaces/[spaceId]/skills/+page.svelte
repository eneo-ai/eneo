<script lang="ts">
  import type { ResourcePermission, SkillSparse } from "@eneo/eneo-js";
  import { invalidate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { Page } from "$lib/components/layout";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { SkillCatalogQuery } from "$lib/features/skills/skillCatalogQuery.svelte";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { LoaderCircle, Plus, Search, Trash2 } from "lucide-svelte";
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
      const failure = error as { status?: number; message?: string };
      deleteError =
        failure.status === 409
          ? m.skills_library_delete_bound_error()
          : (failure.message ?? m.skills_library_delete_error());
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
    {#if canCreate && data.skills.length > 0}
      <Button href={resolve(`/spaces/${spaceRouteId}/skills/new`)}>
        <Plus data-icon="inline-start" aria-hidden="true" />
        {m.skills_library_create()}
      </Button>
    {/if}
  </Page.Header>
  <Page.Main>
    <div class="mx-auto w-full max-w-[1100px] px-6 py-6">
      <p class="text-muted-foreground mb-6 max-w-3xl text-sm">
        {m.skills_library_intro()}
      </p>

      {#if skillCatalog.items.length === 0 && !skillCatalog.query && !skillCatalog.loading && !skillCatalog.error}
        <div
          class="border-border bg-muted/25 flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-8 py-16"
        >
          <h2 class="text-foreground mb-2 text-lg font-medium">
            {m.skills_library_empty_title()}
          </h2>
          <p class="text-muted-foreground mb-6 max-w-md text-center text-sm">
            {m.skills_library_empty_description()}
          </p>
          {#if canCreate}
            <Button href={resolve(`/spaces/${spaceRouteId}/skills/new`)}>
              <Plus data-icon="inline-start" aria-hidden="true" />
              {m.skills_library_create_first()}
            </Button>
          {/if}
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
          <p class="text-muted-foreground py-12 text-center text-sm">
            {m.skills_library_no_results()}
          </p>
        {:else}
          <Card.Root>
            <Table.Root>
              <Table.Header>
                <Table.Row>
                  <Table.Head>{m.name()}</Table.Head>
                  <Table.Head>{m.description()}</Table.Head>
                  <Table.Head>{m.status()}</Table.Head>
                  <Table.Head>{m.skills_library_revision_column()}</Table.Head>
                  <Table.Head>{m.skills_library_updated_column()}</Table.Head>
                  {#if canDelete}
                    <Table.Head class="w-16 text-right">{m.actions()}</Table.Head>
                  {/if}
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {#each skillCatalog.items as skill (skill.id)}
                  <Table.Row>
                    <Table.Cell class="font-medium">
                      <a
                        href={resolve(`/spaces/${spaceRouteId}/skills/${skill.id}`)}
                        class="text-foreground hover:text-accent-default focus-visible:ring-ring rounded-sm hover:underline focus-visible:ring-2 focus-visible:outline-none"
                      >
                        {skill.display_name}
                      </a>
                      <p class="text-muted-foreground mt-0.5 text-xs">{skill.slug}</p>
                    </Table.Cell>
                    <Table.Cell class="text-muted-foreground max-w-lg">
                      <p class="line-clamp-2">{skill.description}</p>
                    </Table.Cell>
                    <Table.Cell>
                      <Badge variant={skill.is_active ? "secondary" : "outline"}>
                        {skill.is_active
                          ? m.skills_available_status()
                          : m.skills_unavailable_status()}
                      </Badge>
                    </Table.Cell>
                    <Table.Cell class="text-muted-foreground text-sm">
                      {m.skills_revision_label({
                        revision: String(skill.current_revision_number)
                      })}
                    </Table.Cell>
                    <Table.Cell class="text-muted-foreground text-sm">
                      {formatUpdatedAt(skill.updated_at)}
                    </Table.Cell>
                    {#if canDelete}
                      <Table.Cell class="text-right">
                        <Button
                          variant="ghost"
                          size="icon-sm"
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
          </Card.Root>
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
