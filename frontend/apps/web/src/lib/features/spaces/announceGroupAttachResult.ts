// Copyright (c) 2026 Sundsvalls Kommun
// Licensed under the MIT License.

import { m } from "$lib/paraglide/messages";
import { toast } from "$lib/components/toast";

/**
 * Outcome of attaching a user group. The success toast confirms the audit
 * action fired. The inert-member count is surfaced by a separate persistent
 * in-page notice (see `InertMembersNotice.svelte`) rather than a second
 * toast, so screen reader users and slower readers don't lose the warning
 * to the toast auto-dismiss timeout.
 */
export type GroupAttachOutcome = {
  groupName: string;
};

export function announceGroupAttachResult({ groupName }: GroupAttachOutcome): void {
  toast.success(m.group_added_to_space({ groupName }));
}
