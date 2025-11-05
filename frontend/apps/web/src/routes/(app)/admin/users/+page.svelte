<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { setAdminUserCtx } from "./ctx";
  import UserEditor from "./editor/UserEditor.svelte";
  import UserTable from "./UserTable.svelte";
  import { m } from "$lib/paraglide/messages";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";

  // Svelte 5 runes mode: use $props() instead of export let
  let { data } = $props();

  // Get search value from URL params for display
  const searchValue = $derived($page.url.searchParams.get('search') || '');

  setAdminUserCtx({
    customRoles: data.customRoles,
    defaultRoles: data.defaultRoles,
    userGroups: data.userGroups
  });

  // Reference to UserTable component to access filterValue
  let userTableRef: any;

  // Watch built-in table filter and trigger server-side search with debouncing
  let debounceTimer: ReturnType<typeof setTimeout>;

  $effect(() => {
    if (userTableRef?.filterValue) {
      const filterVal = userTableRef.filterValue;

      // Subscribe to filter changes
      const unsubscribe = filterVal.subscribe((value: string) => {
        // Debounce navigation (250ms delay)
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          const trimmed = value.trim();

          // Only trigger search if empty OR >= 3 characters (matches backend validation)
          // Prevents unnecessary network requests and 400 errors for short searches
          if (trimmed === '' || trimmed.length >= 3) {
            const url = trimmed
              ? `/admin/users?search=${encodeURIComponent(trimmed)}`
              : '/admin/users';

            goto(url, { noScroll: true, keepFocus: true, replaceState: true });
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
    <UserEditor mode="create"></UserEditor>
  </Page.Header>
  <Page.Main>
    <UserTable bind:this={userTableRef} users={data.users ?? []} />

    <!-- Pagination display -->
    {#if data.pagination}
      <div class="mt-4 text-sm text-gray-600">
        Showing page {data.pagination.page} of {data.pagination.total_pages}
        ({data.pagination.total_count} total users{searchValue ? ` matching "${searchValue}"` : ''}, {data.users.length} on this page)
      </div>
    {/if}
  </Page.Main>
</Page.Root>
