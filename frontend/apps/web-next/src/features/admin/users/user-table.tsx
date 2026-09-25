"use client";

import { Avatar } from "@astryxdesign/core/Avatar";
import { Badge } from "@astryxdesign/core/Badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow
} from "@astryxdesign/core/Table";
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
 * Users as a table: initials avatar with username and email, role badges,
 * status dot with its label, and the row menu. Long names and emails truncate
 * with a tooltip; below the min width the table scrolls in its own region.
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

  return (
    <Table aria-label={label} hasHover className="min-w-160 table-fixed">
      <TableHeader>
        <TableRow className="bg-ax-sunken [&>th]:text-xs">
          <TableHeaderCell scope="col">{t("user")}</TableHeaderCell>
          <TableHeaderCell scope="col" className="w-2/5">
            {t("roles")}
          </TableHeaderCell>
          <TableHeaderCell scope="col" className="w-36">
            {t("status")}
          </TableHeaderCell>
          <TableHeaderCell scope="col" className="w-14">
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
                {user.roles.length > 0 ? (
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
                )}
              </TableCell>
              <TableCell>
                <StatusLabel
                  status={STATE_TONE[user.state] ?? "neutral"}
                  label={stateLabel(user.state)}
                />
              </TableCell>
              <TableCell className="text-end">
                <UserActions user={user} onRemoved={onRemoved} />
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
