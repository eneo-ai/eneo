"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { revealProblems } from "@/components/composites/field-problem";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import {
  refreshUserGroups,
  type UserGroup,
  userGroupsQueryOptions
} from "@/features/admin/user-groups/user-groups";
import { useRemovalMutation } from "@/features/spaces/removal";
import type { AdminUser } from "./users";

type GroupRef = AdminUser["user_groups"][number];

/**
 * The user's groups in the edit dialog (the Svelte app's SelectUserGroups):
 * pick a group and assign it, or remove one. Each change is saved at once,
 * apart from the dialog's save, and the hint says so; a group can grant
 * access to spaces and capability sources, so a change takes effect for the
 * user straight away. While one change runs, its refetch included, the
 * others wait.
 */
export function UserGroupField({ user, isDisabled }: { user: AdminUser; isDisabled: boolean }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const groups = useQuery(userGroupsQueryOptions(browserApi));
  const [assigned, setAssigned] = useState<GroupRef[]>(user.user_groups ?? []);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);
  const assignRef = useRef<HTMLButtonElement>(null);
  // The remove button pressed last: focus moves to its neighbour once its row goes.
  const anchor = useRef<HTMLElement | null>(null);

  const available = (groups.data ?? []).filter(
    (group) => !assigned.some((current) => current.id === group.id)
  );
  const selected = available.find((group) => group.id === selectedId) ?? null;
  const problem = submitted && !selected ? t("form_problem_choose_user_group") : null;
  const label = t("user_groups");

  const assign = useMutation({
    mutationFn: (group: UserGroup) =>
      unwrap(
        browserApi.POST("/api/v1/user-groups/{id}/users/{user_id}/", {
          params: { path: { id: group.id, user_id: user.id } }
        })
      ),
    onSuccess: async (_data, group) => {
      setAssigned((current) => [...current, { id: group.id, name: group.name }]);
      setSelectedId(null);
      setSubmitted(false);
      announce(t("admin_user_group_assigned", { name: group.name }));
      // Awaited: the change counts as running until the lists have refetched.
      await refreshUserGroups(queryClient);
    },
    onError: (error) => toastApiError(error, t)
  });

  const unassign = useRemovalMutation({
    mutationFn: (group: GroupRef) =>
      unwrap(
        browserApi.DELETE("/api/v1/user-groups/{id}/users/{user_id}/", {
          params: { path: { id: group.id, user_id: user.id } }
        })
      ),
    refresh: () => refreshUserGroups(queryClient),
    onRemoved: (_data, group) => {
      setAssigned((current) => current.filter((other) => other.id !== group.id));
      announce(t("admin_user_group_unassigned", { name: group.name }));
    },
    focusTarget: assignRef,
    anchor
  });

  const busy = isDisabled || assign.isPending || unassign.isPending;

  function submit() {
    if (busy) return;
    if (!selected) {
      revealProblems(() => setSubmitted(true), pickerRef.current?.querySelector("button"));
      return;
    }
    assign.mutate(selected);
  }

  return (
    <div
      aria-busy={assign.isPending || unassign.isPending || undefined}
      className="border-ax-border flex flex-col gap-3 border-t pt-4"
    >
      <QueryStateBoundary query={groups} rows={1}>
        {(all) => (
          <div className="flex flex-wrap items-end gap-2">
            <div ref={pickerRef} className="min-w-48 flex-1">
              <Selector
                label={label}
                description={t("admin_user_groups_immediate_hint")}
                // With a search field the trigger is named by its label alone.
                aria-label={
                  selected
                    ? t("admin_user_groups_picker_trigger", { label, group: selected.name })
                    : label
                }
                options={available.map((group) => ({ value: group.id, label: group.name }))}
                value={selected?.id}
                onChange={(next) => setSelectedId(next)}
                placeholder={t("select_user_group")}
                hasSearch
                searchPlaceholder={t("select_user_group")}
                emptyText={
                  all.length === 0
                    ? t("no_user_groups_configured")
                    : t("admin_user_groups_all_assigned")
                }
                emptySearchText={t("no_results_found")}
                isDisabled={isDisabled}
                status={problem ? { type: "error", message: problem } : undefined}
                width="100%"
              />
            </div>
            <Button
              ref={assignRef}
              label={t("assign")}
              isDisabled={isDisabled}
              // Busy, it keeps focus and a second press is ignored.
              isLoading={assign.isPending}
              isInterruptible
              onClick={submit}
            />
          </div>
        )}
      </QueryStateBoundary>
      {assigned.length > 0 ? (
        <ul className="border-ax-border rounded-ax-element divide-ax-border divide-y border">
          {assigned.map((group) => (
            <li key={group.id} className="flex items-center justify-between gap-3 px-3 py-1.5">
              <Text className="min-w-0 break-words">{group.name}</Text>
              <Button
                label={t("remove")}
                aria-label={t("admin_remove_user_group", { name: group.name })}
                variant="ghost"
                size="sm"
                isDisabled={isDisabled}
                isLoading={unassign.isPending && unassign.variables?.id === group.id}
                isInterruptible
                onClick={(event) => {
                  if (busy) return;
                  anchor.current = event.currentTarget;
                  unassign.mutate(group);
                }}
              />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
