<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { setAdminUserCtx } from "./ctx";
  import UserEditor from "./editor/UserEditor.svelte";
  import UserTable from "./UserTable.svelte";
  import { m } from "$lib/paraglide/messages";
  import { goto, invalidate } from "$app/navigation";
  import { page } from "$app/stores";
  import ServerPagination from "$lib/components/ServerPagination.svelte";

  // Svelte 5 runes mode: use $props() instead of export let
  let { data } = $props();

  // Get search value and tab from URL params.
  // Support both canonical `search` and legacy `search_email` links.
  const searchValue = $derived(
    $page.url.searchParams.get('search') || $page.url.searchParams.get('search_email') || ''
  );
  const currentTab = $derived($page.url.searchParams.get('tab') || 'active');

  // Swedish number formatting for counts (e.g., 2828 → "2 828", 50000 → "50 000")
  const numberFormatter = new Intl.NumberFormat('sv-SE');

  setAdminUserCtx({
    customRoles: data.customRoles,
    defaultRoles: data.defaultRoles,
    userGroups: data.userGroups
  });

  // Reference to UserTable component to access filterValue
  let userTableRef: any;

  function goToPage(newPage: number) {
    const url = new URL($page.url);
    if (newPage > 1) {
      url.searchParams.set("page", String(newPage));
    } else {
      url.searchParams.delete("page");
    }
    goto(url.toString(), { noScroll: true });
  }

  // Watch built-in table filter and trigger server-side search with debouncing
  let debounceTimer: ReturnType<typeof setTimeout>;

  $effect(() => {
    if (userTableRef?.filterValue) {
      const filterVal = userTableRef.filterValue;

      // Subscribe to filter changes
      let isInitialEmission = true;
      const unsubscribe = filterVal.subscribe((value: string) => {
        if (isInitialEmission) {
          isInitialEmission = false;
          // Prevent initial empty table state from wiping URL-driven searches.
          if (!value.trim() && searchValue.trim()) {
            return;
          }
        }

        // Debounce navigation (250ms delay)
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          const trimmed = value.trim();

          // Skip if search value hasn't changed from current URL (avoids resetting page on mount)
          const currentSearch = $page.url.searchParams.get("search") || "";
          if (trimmed === currentSearch) return;

          // Only trigger search if empty OR >= 3 characters (matches backend validation)
          // Prevents unnecessary network requests and 400 errors for short searches
          if (trimmed === '' || trimmed.length >= 3) {
            // Preserve current tab when searching, reset page to 1
            const params = new URLSearchParams();
            if (currentTab) params.set('tab', currentTab);
            if (trimmed) params.set('search', trimmed);

            const nextUrl = params.toString() ? `/admin/users?${params.toString()}` : '/admin/users';
            const currentUrl = `${$page.url.pathname}${$page.url.search}`;
            if (nextUrl === currentUrl) {
              return;
            }

            goto(nextUrl, { noScroll: true, keepFocus: true, replaceState: true });
          }
          // If 1-2 chars: silently ignore (no request, no error, better UX)
        }, 250);
      });

      return () => {
        clearTimeout(debounceTimer);
        unsubscribe();
      };
    }
  });
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.users()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.users()}></Page.Title>
    <Page.Tabbar>
      <!-- TabTrigger uses goto() for proper SvelteKit navigation -->
      <Page.TabTrigger tab="active">
        <span class="inline-flex items-baseline">
          <span>{m.active_users()}</span>
          {#if data.counts?.active != null}
            <span class="ml-1.5 text-sm text-gray-500">
              ({numberFormatter.format(data.counts.active)})
            </span>
          {/if}
        </span>
      </Page.TabTrigger>
      <Page.TabTrigger tab="inactive">
        <span class="inline-flex items-baseline">
          <span>{m.inactive_users()}</span>
          {#if data.counts?.inactive != null}
            <span class="ml-1.5 text-sm text-gray-500">
              ({numberFormatter.format(data.counts.inactive)})
            </span>
          {/if}
        </span>
      </Page.TabTrigger>
    </Page.Tabbar>
    <UserEditor mode="create"></UserEditor>
  </Page.Header>
  <Page.Main>
    <UserTable bind:this={userTableRef} users={data.users ?? []} initialFilterValue={searchValue} />

    {#if data.pagination}
      <ServerPagination
        page={data.pagination.page}
        totalPages={data.pagination.total_pages}
        totalCount={data.pagination.total_count}
        pageSize={data.pagination.page_size}
        hasNext={data.pagination.has_next}
        hasPrevious={data.pagination.has_previous}
        on:change={(e) => goToPage(e.detail)}
      />
    {/if}
  </Page.Main>
</Page.Root>
