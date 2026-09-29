<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { setAdminUserCtx } from "./ctx";
  import UserEditor from "./editor/UserEditor.svelte";
  import UserTable from "./UserTable.svelte";
  import UserFilters from "./UserFilters.svelte";
  import { m } from "$lib/paraglide/messages";
  import { resolve } from "$app/paths";
  import { navigating, page } from "$app/state";
  import { Button } from "$lib/components/ui/button";
  import { userQueryString } from "./user-query";

  let { data } = $props();
  const numberFormatter = new Intl.NumberFormat("sv-SE");
  const isLoading = $derived(navigating.to?.url.pathname === page.url.pathname);
  const rangeStart = $derived(
    data.pagination.total_count === 0
      ? 0
      : (data.pagination.page - 1) * data.pagination.page_size + 1
  );
  const rangeEnd = $derived(
    Math.min(data.pagination.page * data.pagination.page_size, data.pagination.total_count)
  );

  setAdminUserCtx({
    get roles() {
      return data.roles;
    },
    get userGroups() {
      return data.userGroups;
    },
    get passwordCapability() {
      return data.passwordCapability;
    }
  });
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.users()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.users()} tour="admin-users" />
    <nav aria-label={m.status()} class="flex flex-wrap gap-2">
      {#each ["active", "inactive"] as tab (tab)}
        <Button
          variant={data.query.tab === tab ? "secondary" : "ghost"}
          aria-current={data.query.tab === tab ? "page" : undefined}
          href={resolve("/admin/users") +
            userQueryString(data.query, { tab: tab === "inactive" ? "inactive" : "active" })}
        >
          {tab === "active" ? m.active_users() : m.inactive_users()}
          {#if data.counts?.[tab] != null}
            <span class="text-muted-foreground">({numberFormatter.format(data.counts[tab])})</span>
          {/if}
        </Button>
      {/each}
    </nav>
    <UserEditor mode="create" />
  </Page.Header>
  <Page.Main>
    <div class="mx-auto w-full max-w-[1100px] py-6 pr-6">
      {#key page.url.search}
        <UserFilters query={data.query} roles={data.roles} />
      {/key}
      <div aria-busy={isLoading} class:opacity-60={isLoading}>
        <p class="text-muted-foreground mb-3 text-sm" role="status">
          {#if isLoading}
            {m.loading()}
          {:else}
            {m.pagination_showing_range({
              start: rangeStart,
              end: rangeEnd,
              total: data.pagination.total_count
            })}
          {/if}
        </p>
        <UserTable users={data.users} />
        {#if data.pagination.total_count > data.pagination.total_pages * data.pagination.page_size}
          <p class="text-muted-foreground mt-3 text-sm">{m.admin_users_refine_search()}</p>
        {/if}
        {#if data.pagination.total_pages > 1 || data.pagination.has_previous}
          <nav class="mt-4 flex items-center gap-4" aria-label={m.admin_users_pagination()}>
            <Button
              variant="outline"
              disabled={!data.pagination.has_previous || isLoading}
              href={resolve("/admin/users") +
                userQueryString(data.query, { page: data.query.page - 1 })}
              aria-label={m.admin_users_previous_page()}>←</Button
            >
            <span class="text-sm tabular-nums"
              >{data.pagination.page} / {data.pagination.total_pages}</span
            >
            <Button
              variant="outline"
              disabled={!data.pagination.has_next || isLoading}
              href={resolve("/admin/users") +
                userQueryString(data.query, { page: data.query.page + 1 })}
              aria-label={m.admin_users_next_page()}>→</Button
            >
          </nav>
        {/if}
      </div>
    </div>
  </Page.Main>
</Page.Root>
