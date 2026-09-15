<script lang="ts">
  import { untrack } from "svelte";
  import { resolve } from "$app/paths";
  import type { Role } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as Select from "$lib/components/ui/select";
  import { m } from "$lib/paraglide/messages";
  import { userQueryString, type UserQuery } from "./user-query";

  let { query, roles }: { query: UserQuery; roles: Role[] } = $props();
  let search = $state(untrack(() => query.search));
  let searchName = $state(untrack(() => query.searchName));
  let roleId = $state(untrack(() => query.roleId || "all"));
  const selectedRole = $derived(roles.find((role) => role.id === roleId));
</script>

<form
  method="GET"
  action={resolve("/admin/users")}
  class="border-default bg-primary mb-6 space-y-4 rounded-lg border p-4 sm:p-5"
  role="search"
  aria-label={m.users()}
>
  <input type="hidden" name="tab" value={query.tab} />
  <input type="hidden" name="role_id" value={roleId === "all" ? "" : roleId} />
  <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
    <div class="min-w-0 space-y-2">
      <Label for="user-email">{m.email()}</Label>
      <Input
        id="user-email"
        name="search"
        type="search"
        bind:value={search}
        minlength={3}
        aria-describedby="user-search-hint"
      />
    </div>
    <div class="min-w-0 space-y-2">
      <Label for="user-name">{m.username()}</Label>
      <Input
        id="user-name"
        name="search_name"
        type="search"
        bind:value={searchName}
        minlength={3}
        aria-describedby="user-search-hint"
      />
    </div>
    <div class="min-w-0 space-y-2">
      <Label for="user-role">{m.roles()}</Label>
      <Select.Root type="single" bind:value={roleId}>
        <Select.Trigger id="user-role" class="w-full">
          <span class="truncate"
            >{roleId === "all"
              ? m.admin_users_all_roles()
              : (selectedRole?.name ?? m.admin_users_unknown_role())}</span
          >
        </Select.Trigger>
        <Select.Content>
          <Select.Item value="all" label={m.admin_users_all_roles()}
            >{m.admin_users_all_roles()}</Select.Item
          >
          {#each roles as role (role.id)}
            <Select.Item value={role.id} label={role.name}>{role.name}</Select.Item>
          {/each}
        </Select.Content>
      </Select.Root>
    </div>
  </div>
  <div class="flex flex-wrap items-center justify-between gap-3">
    <p id="user-search-hint" class="text-muted-foreground max-w-xl text-sm">
      {m.admin_users_search_hint()}
    </p>
    <div class="flex shrink-0 items-center gap-2">
      <Button type="submit">{m.search()}</Button>
      <Button
        variant="outline"
        onclick={() => {
          search = "";
          searchName = "";
          roleId = "all";
        }}
        href={resolve("/admin/users") +
          userQueryString(query, { search: "", searchName: "", roleId: "" })}
      >
        {m.admin_users_clear_filters()}
      </Button>
    </div>
  </div>
</form>
