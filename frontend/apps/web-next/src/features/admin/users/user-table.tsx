"use client";

import { Avatar } from "@astryxdesign/core/Avatar";
import { Badge } from "@astryxdesign/core/Badge";
import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Table } from "@/components/astryx/table";
import { Text } from "@astryxdesign/core/Text";
import { useTranslations } from "use-intl";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import { UserActions } from "./user-actions";
import type { IssuedPassword } from "./user-editor";
import type { AdminUser, UserState } from "./users";

const STATE_TONE: Record<UserState, StatusTone> = {
  active: "success",
  invited: "accent",
  inactive: "neutral",
  deleted: "error"
};

function useStateLabel() {
  const t = useTranslations();
  return (state: UserState) =>
    state === "active"
      ? t("active")
      : state === "inactive"
        ? t("inactive")
        : state === "invited"
          ? t("invited")
          : t("admin_users_state_deleted");
}

/** Badges for a user's roles or groups, or a dash (read out as "none") without any. */
function BadgeList({ items }: { items: { id: string; name: string }[] }) {
  const t = useTranslations();
  if (items.length === 0) {
    return (
      <>
        <span aria-hidden="true" className="text-ax-text-secondary">
          –
        </span>
        <span className="sr-only">{t("none")}</span>
      </>
    );
  }
  return (
    <ul className="flex flex-wrap gap-1">
      {items.map((item) => (
        <li key={item.id} className="flex min-w-0">
          <Badge label={item.name} />
        </li>
      ))}
    </ul>
  );
}

/**
 * Users as a table: username and email (with an initials avatar from 768
 * px), role and user group badges, status dot with its label, and the row menu. Every
 * column stays on a phone (decision 9): the table scrolls sideways in its
 * own named region with the name pinned, so a row is always named. Long
 * names and emails truncate with a tooltip.
 */
export function UserTable({
  users,
  label,
  onRemoved,
  onIssued
}: {
  users: AdminUser[];
  /** Accessible name of the table (the selected tab). */
  label: string;
  onRemoved?: () => void;
  /** A password a row's editor set, for the page's one-time view. */
  onIssued: (issued: IssuedPassword) => void;
}) {
  const t = useTranslations();
  const stateLabel = useStateLabel();

  const columns: TableColumn<AdminUser>[] = [
    {
      key: "name",
      header: t("user"),
      width: proportional(1.5, { minWidth: 208 }),
      renderCell: (user) => {
        const name = user.username || user.email;
        return (
          <div className="flex min-w-0 items-center gap-3">
            {/* Decorative next to the visible name; a phone keeps the room. */}
            <span className="hidden md:contents">
              <Avatar name={name} size="md" tooltip={false} aria-hidden="true" />
            </span>
            <div className="flex min-w-0 flex-col">
              <Text weight="semibold" maxLines={1}>
                {name}
              </Text>
              {user.username && (
                <Text type="supporting" maxLines={1}>
                  {user.email}
                </Text>
              )}
              {/* On a phone the exceptions are in view with the name, so no
                  account's state waits on a sideways scroll. */}
              {user.state !== "active" || user.password_change_required ? (
                <div className="flex flex-wrap items-center gap-1.5 pt-0.5 md:hidden">
                  {user.state !== "active" ? (
                    <StatusLabel status={STATE_TONE[user.state]} label={stateLabel(user.state)} />
                  ) : null}
                  {user.password_change_required ? (
                    <Badge label={t("admin_password_change_required_badge")} />
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
        );
      }
    },
    {
      key: "roles",
      header: t("roles"),
      // Roles and groups share the remaining room, with badges wrapping on tablets.
      width: proportional(1, { minWidth: 144 }),
      renderCell: (user) => <BadgeList items={user.roles} />
    },
    {
      key: "groups",
      header: t("user_groups"),
      width: proportional(1, { minWidth: 144 }),
      renderCell: (user) => <BadgeList items={user.user_groups} />
    },
    {
      key: "status",
      header: t("status"),
      width: pixel(156),
      renderCell: (user) => (
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusLabel
            status={STATE_TONE[user.state] ?? "neutral"}
            label={stateLabel(user.state)}
          />
          {user.password_change_required && (
            <Badge label={t("admin_password_change_required_badge")} />
          )}
        </div>
      )
    },
    {
      key: "actions",
      header: <span className="sr-only">{t("actions")}</span>,
      width: pixel(72),
      align: "end",
      renderCell: (user) => <UserActions user={user} onRemoved={onRemoved} onIssued={onIssued} />
    }
  ];

  return (
    <Table
      data={users}
      columns={columns}
      idKey="id"
      aria-label={label}
      pinnedColumn="name"
      hasHover
    />
  );
}
