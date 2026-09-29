<script lang="ts">
  import type { User } from "@eneo/eneo-js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { Badge } from "$lib/components/ui/badge";
  import UserActions from "./UserActions.svelte";
  import { m } from "$lib/paraglide/messages";

  let { users }: { users: User[] } = $props();
</script>

<div class="border-default bg-primary overflow-hidden rounded-lg border">
  <Table.Root class="[&_td]:px-4 [&_td]:py-3 [&_th]:px-4">
    <Table.Caption class="sr-only">{m.users()}</Table.Caption>
    <Table.Header>
      <Table.Row>
        <Table.Head>{m.email()}</Table.Head>
        <Table.Head>{m.username()}</Table.Head>
        <Table.Head>{m.roles()}</Table.Head>
        <Table.Head>{m.user_groups()}</Table.Head>
        <Table.Head>{m.status()}</Table.Head>
        <Table.Head class="w-16 text-right">{m.actions()}</Table.Head>
      </Table.Row>
    </Table.Header>
    <Table.Body>
      {#each users as user (user.id)}
        <Table.Row>
          <Table.Cell class="font-medium">{user.email}</Table.Cell>
          <Table.Cell>{user.username || "—"}</Table.Cell>
          <Table.Cell>
            <div class="flex flex-wrap gap-1">
              {#each user.roles ?? [] as role (role.id)}
                <Badge variant="outline">{role.name}</Badge>
              {:else}—{/each}
            </div>
          </Table.Cell>
          <Table.Cell>
            <div class="flex flex-wrap gap-1">
              {#each user.user_groups ?? [] as group (group.id)}
                <Badge variant="outline">{group.name}</Badge>
              {:else}—{/each}
            </div>
          </Table.Cell>
          <Table.Cell>
            <Badge variant={user.state === "active" ? "default" : "secondary"}>
              {user.state === "active"
                ? m.active()
                : user.state === "inactive"
                  ? m.inactive()
                  : user.state === "invited"
                    ? m.invited()
                    : user.state}
            </Badge>
          </Table.Cell>
          <Table.Cell><div class="flex justify-end"><UserActions {user} /></div></Table.Cell>
        </Table.Row>
      {:else}
        <Table.Row
          ><Table.Cell colspan={6} class="h-24 text-center">{m.no_results()}</Table.Cell></Table.Row
        >
      {/each}
    </Table.Body>
  </Table.Root>
</div>
