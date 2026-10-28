"use client";

import { Avatar } from "@astryxdesign/core/Avatar";
import { Badge } from "@astryxdesign/core/Badge";
import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Table } from "@/components/astryx/table";
import { Text } from "@astryxdesign/core/Text";
import { useTranslations } from "next-intl";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import { UserActions } from "./user-actions";
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

/**
 * Users as a table: username and email (with an initials avatar from 768
 * px), role badges, status dot with its label, and the row menu. Every
 * column stays on a phone (decision 9): the table scrolls sideways in its
 * own named region with the name pinned, so a row is always named. Long
 * names and emails truncate with a tooltip.
 */
export function UserTable({
  users,
  label,
  onRemoved
}: {
  users: AdminUser[];
  /** Accessible name of the table (the selected tab). */
  label: string;
  onRemoved?: () => void;
}) {
  const t = useTranslations();
  const stateLabel = useStateLabel();

  const columns: TableColumn<AdminUser>[] = [
    {
      key: "name",
      header: t("user"),
      width: proportional(1, { minWidth: 208 }),
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
      // Shares the room with the name from 768 px, so the badges keep a line.
      width: proportional(1, { minWidth: 224 }),
      renderCell: (user) =>
        user.roles.length > 0 ? (
          <ul className="flex flex-wrap gap-1">
            {user.roles.map((role) => (
              <li key={role.id} className="flex min-w-0">
                <Badge label={role.name} />
              </li>
            ))}
          </ul>
        ) : (
          <>
            <span aria-hidden="true" className="text-ax-text-secondary">
              –
            </span>
            <span className="sr-only">{t("none")}</span>
          </>
        )
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
      renderCell: (user) => <UserActions user={user} onRemoved={onRemoved} />
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
