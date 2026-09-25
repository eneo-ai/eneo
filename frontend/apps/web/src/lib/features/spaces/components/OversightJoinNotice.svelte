<!--
  Tells a space's members that organisation administrators joined it to see
  its content: who, when, with which role and when they left. A visit stays
  listed for 90 days after it ends. The reason is only in the data readers of
  the member list get, so it shows only for them.
-->
<script lang="ts">
  import type { SpaceOversightVisit } from "@eneo/eneo-js";
  import { ShieldCheck } from "@lucide/svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { formatDateMedium } from "$lib/core/formatting/dateTime";
  import { m } from "$lib/paraglide/messages";
  import { spaceRoleLabel } from "../roles";

  type Props = {
    /** Open visits and those that ended in the last 90 days, newest first. */
    visits: readonly SpaceOversightVisit[];
  };

  let { visits }: Props = $props();

  const uid = $props.id();
  // A deleted user has no id left; each such visit counts as its own person.
  const people = $derived(
    new Set(visits.map((visit, index) => visit.person?.id ?? `deleted-${index}`)).size
  );

  function describe(visit: SpaceOversightVisit): string {
    const name = visit.person?.name ?? m.space_oversight_visit_deleted_person();
    const role = spaceRoleLabel(visit.role);
    return visit.left_at
      ? m.space_oversight_visit_left({
          name,
          joined: formatDateMedium(visit.joined_at),
          role,
          left: formatDateMedium(visit.left_at)
        })
      : m.space_oversight_visit_open({ name, date: formatDateMedium(visit.joined_at), role });
  }
</script>

{#if visits.length > 0}
  <!-- A standing notice, not an announcement: `note` instead of the Alert's own `alert` role. -->
  <Alert.Root role="note" aria-labelledby={`${uid}-title`} class="border-default bg-secondary">
    <ShieldCheck aria-hidden="true" />
    <Alert.Title id={`${uid}-title`}>
      {people === 1 ? m.space_oversight_notice_title() : m.space_oversight_notice_title_many()}
    </Alert.Title>
    <Alert.Description class="text-primary flex flex-col gap-2">
      <p class="text-secondary">{m.space_oversight_notice_help()}</p>
      <ul class="flex flex-col gap-2">
        {#each visits as visit, index (`${visit.person?.id ?? index}-${visit.joined_at}`)}
          <li class="flex flex-col gap-0.5">
            <span>{describe(visit)}</span>
            {#if visit.reason}
              <span class="text-secondary break-words">
                {m.space_oversight_notice_reason({ reason: visit.reason })}
              </span>
            {/if}
          </li>
        {/each}
      </ul>
    </Alert.Description>
  </Alert.Root>
{/if}
