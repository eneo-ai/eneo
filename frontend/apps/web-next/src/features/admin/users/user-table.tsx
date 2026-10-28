"use client";

import { Avatar } from "@astryxdesign/core/Avatar";
import { Badge } from "@astryxdesign/core/Badge";
import {
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow
} from "@astryxdesign/core/Table";
import { Table } from "@/components/astryx/table";
import { Text } from "@astryxdesign/core/Text";
import { useTranslations } from "next-intl";
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
 * Users as a table: initials avatar with username and email, role and user
 * group badges, status dot with its label, and the row menu. Long names and
 * emails truncate with a tooltip; below the min width the table scrolls in
 * its own region.
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

  // Each set width is also a min width (AGENTS.md → Tables).
  return (
    <Table aria-label={label} hasHover className="min-w-200 table-fixed">
      <TableHeader>
        <TableRow className="bg-ax-sunken [&>th]:text-xs">
          <TableHeaderCell scope="col">{t("user")}</TableHeaderCell>
          <TableHeaderCell scope="col" className="w-1/4">
            {t("roles")}
          </TableHeaderCell>
          <TableHeaderCell scope="col" className="w-1/4">
            {t("user_groups")}
          </TableHeaderCell>
          <TableHeaderCell scope="col" className="w-36 min-w-36">
            {t("status")}
          </TableHeaderCell>
          <TableHeaderCell scope="col" className="w-14 min-w-14">
            <span className="sr-only">{t("actions")}</span>
          </TableHeaderCell>
        </TableRow>
      </TableHeader>
      <TableBody>
        {users.map((user) => {
          const name = user.username || user.email;
          return (
            <TableRow key={user.id}>
              <TableCell>
                <div className="flex min-w-0 items-center gap-3">
                  {/* Decorative next to the visible name. */}
                  <Avatar name={name} size="md" tooltip={false} aria-hidden="true" />
                  <div className="flex min-w-0 flex-col">
                    <Text weight="semibold" maxLines={1}>
                      {name}
                    </Text>
                    {user.username && (
                      <Text type="supporting" maxLines={1}>
                        {user.email}
                      </Text>
                    )}
                  </div>
                </div>
              </TableCell>
              <TableCell>
                <BadgeList items={user.roles} />
              </TableCell>
              <TableCell>
                <BadgeList items={user.user_groups} />
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap items-center gap-1.5">
                  <StatusLabel
                    status={STATE_TONE[user.state] ?? "neutral"}
                    label={stateLabel(user.state)}
                  />
                  {user.password_change_required && (
                    <Badge label={t("admin_password_change_required_badge")} />
                  )}
                </div>
              </TableCell>
              <TableCell className="text-end">
                <UserActions user={user} onRemoved={onRemoved} onIssued={onIssued} />
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
