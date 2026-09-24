<!--
  Tells a space's members that an organisation administrator joined it
  through oversight: who, when and with which role. The reason is only in the
  data the space's own administrators get, so it shows only for them.
-->
<script lang="ts">
  import type { SpaceMemberOversightJoin, SpaceRoleValue } from "@eneo/eneo-js";
  import { ShieldCheck } from "@lucide/svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { formatDateMedium } from "$lib/core/formatting/dateTime";
  import { m } from "$lib/paraglide/messages";
  import { spaceRoleLabel } from "../roles";

  type Props = {
    members: readonly {
      id: string;
      email: string;
      username?: string | null;
      role: SpaceRoleValue;
      oversight_join?: SpaceMemberOversightJoin | null;
    }[];
  };

  let { members }: Props = $props();

  const uid = $props.id();
  const joined = $derived(
    members.flatMap((member) =>
      member.oversight_join ? [{ ...member, join: member.oversight_join }] : []
    )
  );
</script>

{#if joined.length > 0}
  <!-- A standing notice, not an announcement: `note` instead of the Alert's own `alert` role. -->
  <Alert.Root role="note" aria-labelledby={`${uid}-title`} class="border-default bg-secondary">
    <ShieldCheck aria-hidden="true" />
    <Alert.Title id={`${uid}-title`}>
      {joined.length === 1
        ? m.space_oversight_notice_title()
        : m.space_oversight_notice_title_many()}
    </Alert.Title>
    <Alert.Description class="text-primary">
      <ul class="flex flex-col gap-2">
        {#each joined as { id, email, username, role, join } (id)}
          <li class="flex flex-col gap-0.5">
            <span>
              {m.space_oversight_notice_item({
                name: username || email,
                date: formatDateMedium(join.joined_at),
                role: spaceRoleLabel(role)
              })}
            </span>
            {#if join.reason}
              <span class="text-secondary break-words">
                {m.space_oversight_notice_reason({ reason: join.reason })}
              </span>
            {/if}
          </li>
        {/each}
      </ul>
    </Alert.Description>
  </Alert.Root>
{/if}
