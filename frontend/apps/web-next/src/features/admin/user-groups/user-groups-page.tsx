"use client";

import { Avatar } from "@astryxdesign/core/Avatar";
import { AvatarGroup, AvatarGroupOverflow } from "@astryxdesign/core/AvatarGroup";
import { Button } from "@astryxdesign/core/Button";
import {
  DropdownMenu,
  DropdownMenuDivider,
  DropdownMenuItem
} from "@astryxdesign/core/DropdownMenu";
import { useCollator } from "@astryxdesign/core/i18n";
import {
  pixel,
  proportional,
  type TableColumn,
  type TableSortComparator,
  useTableSortable,
  useTableSortableState
} from "@astryxdesign/core/Table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Plus, Trash2, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useMemo, useRef, useState } from "react";
import { Table } from "@/components/astryx/table";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { returnTarget } from "@/components/ui/dialog-focus";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { useFocusRescue } from "@/lib/focus-rescue";
import { toast } from "@/lib/toast";
import { useRemovalMutation } from "@/features/spaces/removal";
import { UserGroupDialog } from "./user-group-dialog";
import { UserGroupMembersDialog } from "./user-group-members-dialog";
import { refreshUserGroups, type UserGroup, userGroupsQueryOptions } from "./user-groups";

type SortKey = "name" | "users";

/** Members shown as avatars in a row; the rest are counted. */
const VISIBLE_MEMBERS = 3;

/** What is open: the create or rename dialog, a group's members or a delete confirmation. */
type Flow =
  | { kind: "create" }
  | { kind: "rename"; id: string }
  | { kind: "members"; id: string }
  | { kind: "delete"; id: string }
  | null;

function memberCount(group: UserGroup): number {
  return group.users?.length ?? 0;
}

function comparators(
  compare: (a: string, b: string) => number
): Record<SortKey, TableSortComparator<UserGroup>> {
  return {
    name: (a, b) => compare(a.name, b.name),
    users: (a, b) => memberCount(a) - memberCount(b)
  };
}

/** A group's members: the first few as avatars, and their number in words. */
function MemberStack({ group }: { group: UserGroup }) {
  const t = useTranslations();
  const members = group.users ?? [];
  const hidden = members.length - VISIBLE_MEMBERS;
  return (
    <div className="flex min-w-0 items-center gap-2">
      {members.length > 0 ? (
        // Decorative next to the count.
        <AvatarGroup size={24} aria-hidden="true">
          {members.slice(0, VISIBLE_MEMBERS).map((member) => (
            <Avatar key={member.id} name={member.email} tooltip={false} />
          ))}
          {hidden > 0 ? <AvatarGroupOverflow count={hidden} /> : null}
        </AvatarGroup>
      ) : null}
      <span className="text-ax-text-secondary tabular-nums">
        {t("space_members_count", { count: members.length })}
      </span>
    </div>
  );
}

/** The row menu: manage members, rename, delete. */
function GroupActions({
  group,
  onMembers,
  onRename,
  onDelete
}: {
  group: UserGroup;
  onMembers: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  const t = useTranslations();
  const name = t("ui_more_actions_for", { name: group.name });
  return (
    <DropdownMenu
      button={{
        label: name,
        tooltip: name,
        icon: <MoreHorizontal className="size-4" aria-hidden="true" />,
        isIconOnly: true,
        variant: "ghost",
        size: "sm"
      }}
      hasChevron={false}
      alignment="end"
    >
      <DropdownMenuItem icon={Users} label={t("manage_members")} onClick={onMembers} />
      <DropdownMenuItem icon={Pencil} label={t("rename")} onClick={onRename} />
      <DropdownMenuDivider />
      <DropdownMenuItem
        icon={Trash2}
        label={t("delete_user_group")}
        variant="destructive"
        onClick={onDelete}
      />
    </DropdownMenu>
  );
}

/** The groups as a table sortable by name and member count, with a row menu. */
function UserGroupTable({
  groups,
  labelledBy,
  onAction
}: {
  groups: UserGroup[];
  labelledBy: string;
  onAction: (flow: Exclude<Flow, null | { kind: "create" }>) => void;
}) {
  const t = useTranslations();
  const collator = useCollator();
  const compare = useMemo(() => comparators(collator.compare), [collator]);
  const { sortedData, sortConfig } = useTableSortableState<UserGroup, SortKey>({
    data: groups,
    comparators: compare,
    defaultSort: [{ sortKey: "name", direction: "ascending" }]
  });
  const sortPlugin = useTableSortable<UserGroup, SortKey>(sortConfig);

  const columns: TableColumn<UserGroup>[] = [
    {
      key: "name",
      header: t("name"),
      width: proportional(2),
      sortable: true,
      renderCell: (group) => <span className="font-medium break-words">{group.name}</span>
    },
    {
      key: "users",
      header: t("members"),
      width: proportional(2),
      sortable: true,
      renderCell: (group) => <MemberStack group={group} />
    },
    {
      key: "actions",
      header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
      width: pixel(64),
      align: "end",
      renderCell: (group) => (
        <GroupActions
          group={group}
          onMembers={() => onAction({ kind: "members", id: group.id })}
          onRename={() => onAction({ kind: "rename", id: group.id })}
          onDelete={() => onAction({ kind: "delete", id: group.id })}
        />
      )
    }
  ];

  return (
    <div className="border-ax-border bg-ax-card rounded-ax-container [&_thead_tr]:bg-ax-sunken overflow-hidden border">
      {/* Below its min width the table scrolls inside its own named region. */}
      <Table
        data={sortedData}
        columns={columns}
        idKey="id"
        hasHover
        aria-labelledby={labelledBy}
        plugins={{ sort: sortPlugin }}
        className="min-w-120"
      />
    </div>
  );
}

/**
 * Administration of the organisation's user groups (the Svelte app's
 * admin/legacy/user-groups): create, rename and delete groups and manage
 * their members. A group can be given access to spaces and capability
 * sources, so every change here can widen or narrow what its members reach;
 * the backend requires the admin permission for each one. Changes apply at
 * once. Mounted by the `/admin/user-groups` route under the admin layout,
 * which turns non-admins away.
 */
export function AdminUserGroupsPage() {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const groups = useQuery(userGroupsQueryOptions(browserApi));
  const [flow, setFlow] = useState<Flow>(null);
  // The control that started the flow (a row's menu button or the create
  // button): where focus goes back when a dialog could not return it itself.
  const opener = useRef<HTMLElement | null>(null);
  const rescue = useFocusRescue();

  const flowGroup =
    flow && "id" in flow ? (groups.data?.find((group) => group.id === flow.id) ?? null) : null;

  function start(next: Exclude<Flow, null>) {
    opener.current = returnTarget();
    setFlow(next);
  }

  function end() {
    setFlow(null);
    rescue(opener.current?.isConnected ? opener.current : headingRef.current);
    opener.current = null;
  }

  const remove = useRemovalMutation({
    mutationFn: (group: UserGroup) =>
      unwrap(
        browserApi.DELETE("/api/v1/user-groups/{id}/", { params: { path: { id: group.id } } })
      ),
    refresh: () => refreshUserGroups(queryClient),
    onRemoved: (_data, group) => {
      setFlow(null);
      toast.success(t("admin_user_groups_deleted", { name: group.name }));
    },
    focusTarget: headingRef
  });

  const createButton = (
    <Button
      variant="primary"
      label={t("create_user_group")}
      icon={<Plus className="size-4" aria-hidden="true" />}
      onClick={() => start({ kind: "create" })}
    />
  );

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-5">
      <PageHeader
        title={t("user_groups")}
        description={t("admin_user_groups_description")}
        headingId={headingId}
        headingRef={headingRef}
        breadcrumbs={[
          { label: t("admin_breadcrumb_root"), href: "/admin" },
          { label: t("admin_section_organisation") }
        ]}
        actions={createButton}
      />
      <QueryStateBoundary query={groups} rows={4}>
        {(items) =>
          items.length === 0 ? (
            <EmptyState
              icon={<Users />}
              title={t("no_user_groups_configured")}
              actions={createButton}
            />
          ) : (
            <UserGroupTable groups={items} labelledBy={headingId} onAction={start} />
          )
        }
      </QueryStateBoundary>
      <UserGroupDialog
        group={flow?.kind === "rename" ? flowGroup : null}
        open={flow?.kind === "create" || (flow?.kind === "rename" && flowGroup !== null)}
        onOpenChange={(open) => {
          if (!open) end();
        }}
      />
      <UserGroupMembersDialog
        group={flow?.kind === "members" ? flowGroup : null}
        open={flow?.kind === "members" && flowGroup !== null}
        onOpenChange={(open) => {
          if (!open) end();
        }}
      />
      <ConfirmDialogControlled
        open={flow?.kind === "delete" && flowGroup !== null}
        onOpenChange={(open) => {
          if (!open) end();
        }}
        title={t("delete_user_group")}
        description={t("admin_user_groups_delete_named", { name: flowGroup?.name ?? "" })}
        confirmLabel={remove.isPending ? t("deleting") : t("delete")}
        pending={remove.isPending}
        onConfirm={() => {
          if (flowGroup) remove.mutate(flowGroup);
        }}
      />
    </div>
  );
}
