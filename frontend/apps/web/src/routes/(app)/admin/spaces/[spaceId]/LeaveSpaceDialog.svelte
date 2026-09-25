<!--
  An administrator who joined a space leaves it again. Only the direct
  membership goes; a role held through a group stays, and the dialog says so.
-->
<script lang="ts">
  import type { AdminSpaceViewerMembership } from "@eneo/eneo-js";
  import { tick } from "svelte";
  import { invalidateAll } from "$app/navigation";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { toast } from "$lib/components/toast";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { formatList } from "$lib/core/formatting/formatList";
  import { spaceRoleLabel } from "$lib/features/spaces/roles";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    space: { id: string; name: string };
    membership: AdminSpaceViewerMembership;
    /** The id of the visible text that says why leaving is refused. */
    disabledReasonId?: string;
    /** Where focus goes once the button that opened the dialog is gone. */
    focusAfterLeave?: () => HTMLElement | null | undefined;
  };

  let { space, membership, disabledReasonId, focusAfterLeave }: Props = $props();

  const eneo = getEneo();
  let open = $state(false);
  const blocked = $derived(!membership.can_leave);

  // With a role through a group the administrator keeps access, so that case has its own text.
  const description = $derived(
    membership.group_role
      ? m.admin_spaces_leave_body_group({
          role: spaceRoleLabel(membership.group_role),
          groups: formatList(membership.via_groups.map((group) => group.name))
        })
      : m.admin_spaces_leave_body()
  );

  async function leave() {
    await eneo.spaces.admin.leave({ spaceId: space.id });
    await invalidateAll();
    toast.success(m.admin_spaces_left({ space: space.name }));
    await tick();
    focusAfterLeave?.()?.focus();
  }
</script>

<ConfirmDialog
  bind:open={() => open, (value) => (open = value && !blocked)}
  title={m.admin_spaces_leave_title({ space: space.name })}
  {description}
  confirmLabel={m.admin_spaces_leave_confirm()}
  pendingLabel={m.admin_spaces_leave_pending()}
  variant="default"
  errorDisplay="inline"
  onConfirm={leave}
>
  {#snippet trigger({ props })}
    <Button
      {...props}
      variant="outline"
      class={["max-md:min-h-12", blocked && "cursor-not-allowed opacity-60"]}
      aria-disabled={blocked || undefined}
      aria-describedby={blocked ? disabledReasonId : undefined}
    >
      {m.admin_spaces_leave_open()}
    </Button>
  {/snippet}
</ConfirmDialog>
