"use client";

import { Avatar } from "@astryxdesign/core/Avatar";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxList, CheckboxListItem } from "@astryxdesign/core/CheckboxList";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { TextInput } from "@/components/astryx/text-input";
import { revealProblems } from "@/components/composites/field-problem";
import { LoadMore, QueryStateBoundary } from "@/components/composites/query-state";
import { useReturnFocus } from "@/components/ui/dialog-focus";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { flattenPages } from "@/lib/api/pagination";
import { toastApiError } from "@/lib/api/toast";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { RemovalFocusScope, useRemovalMutation } from "@/features/spaces/removal";
import {
  memberCandidatesQueryOptions,
  refreshUserGroups,
  type GroupMember,
  type UserGroup
} from "./user-groups";

/**
 * Adds users to the group: search by e-mail (sent once typing pauses), tick
 * any number across searches and pages, then add them all at once. Members
 * are listed but cannot be ticked. Each user leaves the selection as soon as
 * they are added, so after a partial failure only the ones still missing
 * stay ticked for a retry (and one removed again meanwhile is not re-added).
 */
function AddMembers({
  group,
  onPendingChange
}: {
  group: UserGroup;
  onPendingChange: (pending: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const headingId = useId();
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [searchInput, setSearchInput] = useState("");
  const [picked, setPicked] = useState<GroupMember[]>([]);
  const [submitted, setSubmitted] = useState(false);

  const email = useDebouncedValue(searchInput.trim());
  const candidates = useInfiniteQuery(memberCandidatesQueryOptions(browserApi, email));
  const users = flattenPages(candidates.data?.pages);
  const total = candidates.data?.pages.at(-1)?.total_count ?? users.length;

  const memberIds = new Set((group.users ?? []).map((user) => user.id));
  const selected = picked.filter((user) => !memberIds.has(user.id));
  const problem = submitted && selected.length === 0 ? t("form_problem_choose_user") : null;

  const add = useMutation({
    // One request per user, as the API takes them; stops at the first refusal.
    mutationFn: async (users: GroupMember[]) => {
      for (const user of users) {
        await unwrap(
          browserApi.POST("/api/v1/user-groups/{id}/users/{user_id}/", {
            params: { path: { id: group.id, user_id: user.id } }
          })
        );
        setPicked((current) => current.filter((other) => other.id !== user.id));
      }
    },
    onMutate: () => onPendingChange(true),
    onSuccess: (_data, users) => {
      setPicked([]);
      setSearchInput("");
      setSubmitted(false);
      announce(t("admin_user_groups_members_added", { count: users.length, name: group.name }));
    },
    onError: (error) => toastApiError(error, t),
    // Also after a partial failure: those that were added show as members.
    onSettled: async () => {
      await refreshUserGroups(queryClient);
      onPendingChange(false);
    }
  });

  function select(ids: string[]) {
    const listed = new Set(users.map((user) => user.id));
    setPicked([
      ...picked.filter((user) => !listed.has(user.id)),
      ...users.filter((user) => ids.includes(user.id))
    ]);
  }

  function submit() {
    if (add.isPending) return;
    if (selected.length === 0) {
      const first = listRef.current?.querySelector<HTMLInputElement>("input:not(:disabled)");
      revealProblems(() => setSubmitted(true), first ?? searchRef.current);
      return;
    }
    add.mutate(selected);
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h3 id={headingId} className="text-sm font-semibold">
        {t("add_user_to_group")}
      </h3>
      <TextInput
        ref={searchRef}
        label={t("admin_users_search")}
        isLabelHidden
        placeholder={t("find_user")}
        startIcon={Search}
        value={searchInput}
        onChange={setSearchInput}
        hasClear
        autoComplete="off"
        // With no list to tick in, the problem shows here, where focus goes.
        status={problem && users.length === 0 ? { type: "error", message: problem } : undefined}
        width="100%"
      />
      {selected.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5" aria-label={t("admin_user_groups_selected")}>
          {selected.map((user) => (
            <li key={user.id} className="flex min-w-0">
              <Token
                label={user.email}
                size="sm"
                onRemove={() => setPicked(picked.filter((other) => other.id !== user.id))}
              />
            </li>
          ))}
        </ul>
      ) : null}
      <QueryStateBoundary query={candidates} rows={3}>
        {() =>
          users.length === 0 ? (
            <Text type="supporting">{t("no_users_found")}</Text>
          ) : (
            <div ref={listRef} className="flex flex-col gap-2">
              <CheckboxList
                label={t("users")}
                isLabelHidden
                value={users
                  .map((user) => user.id)
                  .filter((id) => selected.some((u) => u.id === id))}
                onChange={select}
                density="compact"
                hasDividers
                // The options scroll in their own box; the problem below stays in view.
                className="[&_[role=group]]:border-ax-border [&_[role=group]]:rounded-ax-element [&_[role=group]]:max-h-60 [&_[role=group]]:overflow-y-auto [&_[role=group]]:border [&_[role=group]]:px-3 [&_[role=group]]:py-1"
                status={problem ? { type: "error", message: problem } : undefined}
              >
                {users.map((user) => {
                  const isMember = memberIds.has(user.id);
                  // In words, not only as the dimmed checkbox (WCAG 1.4.1).
                  const details = [isMember ? t("already_added") : null, user.username].filter(
                    Boolean
                  );
                  return (
                    <CheckboxListItem
                      key={user.id}
                      value={user.id}
                      label={user.email}
                      isDisabled={isMember}
                      description={details.length > 0 ? details.join(" · ") : undefined}
                    />
                  );
                })}
              </CheckboxList>
              <LoadMore
                query={candidates}
                label={t("load_more_users", { current: users.length, total })}
              />
            </div>
          )
        }
      </QueryStateBoundary>
      <div className="flex flex-wrap justify-end gap-2">
        {selected.length > 0 ? (
          <Button label={t("clear_selection")} onClick={() => setPicked([])} />
        ) : null}
        <Button
          variant="primary"
          label={t("add_selected", { count: selected.length })}
          // Busy, it keeps focus and a second press is ignored.
          isLoading={add.isPending}
          isInterruptible
          onClick={submit}
        />
      </div>
    </section>
  );
}

/** One member, removed at once (no confirmation, as in the Svelte app). */
function MemberRow({ group, member }: { group: UserGroup; member: GroupMember }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const anchor = useRef<HTMLButtonElement>(null);
  const remove = useRemovalMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/user-groups/{id}/users/{user_id}/", {
          params: { path: { id: group.id, user_id: member.id } }
        })
      ),
    refresh: () => refreshUserGroups(queryClient),
    onRemoved: () =>
      announce(t("admin_user_groups_member_removed", { email: member.email, name: group.name })),
    anchor
  });

  return (
    <li className="flex items-center justify-between gap-3 px-3 py-2">
      <div className="flex min-w-0 items-center gap-3">
        {/* Decorative next to the visible e-mail. */}
        <Avatar name={member.email} size="sm" tooltip={false} aria-hidden="true" />
        <div className="flex min-w-0 flex-col">
          <Text maxLines={1}>{member.email}</Text>
          {member.username ? (
            <Text type="supporting" maxLines={1}>
              {member.username}
            </Text>
          ) : null}
        </div>
      </div>
      <Button
        ref={anchor}
        label={t("admin_user_groups_remove_member", { email: member.email })}
        tooltip={t("admin_user_groups_remove_member", { email: member.email })}
        isIconOnly
        variant="ghost"
        size="sm"
        icon={<Trash2 className="size-4" aria-hidden="true" />}
        isLoading={remove.isPending}
        isInterruptible
        onClick={() => {
          if (!remove.isPending) remove.mutate();
        }}
      />
    </li>
  );
}

/** The members, each with a remove button; focus stays in the list as rows go. */
function CurrentMembers({ group }: { group: UserGroup }) {
  const t = useTranslations();
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const members = group.users ?? [];

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h3
        ref={headingRef}
        id={headingId}
        tabIndex={-1}
        className="focus-visible:outline-ring rounded-ax-inner text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        {t("current_members")} ({members.length})
      </h3>
      <RemovalFocusScope target={headingRef}>
        {members.length === 0 ? (
          <Text type="supporting">{t("no_users_in_group")}</Text>
        ) : (
          <ul className="border-ax-border rounded-ax-element divide-ax-border max-h-64 divide-y overflow-y-auto border">
            {members.map((member) => (
              <MemberRow key={member.id} group={group} member={member} />
            ))}
          </ul>
        )}
      </RemovalFocusScope>
    </section>
  );
}

/**
 * Manage a group's members: add several users at once, remove them one by
 * one. Every change applies at once, as in the Svelte app; `group` is the
 * page's current copy, so the lists follow its refetch.
 */
export function UserGroupMembersDialog({
  group,
  open,
  onOpenChange
}: {
  group: UserGroup | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const [pending, setPending] = useState(false);
  // Opened from a row menu: focus goes back to the menu button.
  const noTrigger = useRef<HTMLElement | null>(null);
  useReturnFocus(open, noTrigger);

  function requestOpenChange(next: boolean) {
    if (!next && pending) return;
    onOpenChange(next);
  }

  return (
    <Dialog
      isOpen={open}
      onOpenChange={requestOpenChange}
      purpose="form"
      width={640}
      maxHeight="90dvh"
    >
      <Layout
        height="auto"
        header={
          <DialogHeader
            title={t("manage_group_members_title", { groupName: group?.name ?? "" })}
            onOpenChange={requestOpenChange}
          />
        }
        content={
          open && group ? (
            <LayoutContent>
              <div className="flex flex-col gap-6">
                <AddMembers group={group} onPendingChange={setPending} />
                <CurrentMembers group={group} />
              </div>
            </LayoutContent>
          ) : null
        }
        footer={
          open ? (
            <LayoutFooter>
              <div className="flex justify-end">
                <Button
                  label={t("close")}
                  isDisabled={pending}
                  onClick={() => requestOpenChange(false)}
                />
              </div>
            </LayoutFooter>
          ) : null
        }
      />
    </Dialog>
  );
}
