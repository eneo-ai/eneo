import { Avatar } from "@astryxdesign/core/Avatar";
import { Badge } from "@astryxdesign/core/Badge";
import { List, ListItem } from "@astryxdesign/core/List";
import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Table } from "@/components/astryx/table";
import { Text } from "@astryxdesign/core/Text";
import { useFormatter, useTranslations } from "use-intl";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import { TableFrame } from "@/components/composites/table-frame";
import { personToneClass } from "@/features/spaces/members/member-avatar";
import { PHONE_QUERY, useMediaMatch } from "@/lib/hooks/use-media-match";
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

type UsersProps = {
  users: AdminUser[];
  /** Accessible name of the list or table (the selected tab). */
  label: string;
  onRemoved?: () => void;
};

/**
 * The users of the selected tab: rows on a phone, like a space's members, so
 * the first screen shows users; a table from 768 px. Their menus' dialogs are
 * in `UserActionScope` above, so a turn across 768 px keeps an open one.
 */
export function UserList(props: UsersProps) {
  const phone = useMediaMatch(PHONE_QUERY);
  return phone ? (
    <UserRows {...props} />
  ) : (
    <TableFrame>
      <UserTable {...props} />
    </TableFrame>
  );
}

/**
 * A user as a phone row: avatar, name, the e-mail under a username, roles and
 * groups in words, a state other than active and a pending password change,
 * and the menu at the end, the row's one control.
 */
function UserRows({ users, label, onRemoved }: UsersProps) {
  const t = useTranslations();
  const format = useFormatter();
  const stateLabel = useStateLabel();
  const names = (items: { name: string }[]) => format.list(items.map((item) => item.name));
  return (
    <List hasDividers edge="outset" aria-label={label}>
      {users.map((user) => {
        const name = user.username || user.email;
        return (
          <ListItem
            key={user.id}
            startContent={
              <Avatar
                name={name}
                size="md"
                tooltip={false}
                aria-hidden="true"
                className={personToneClass(user.id)}
              />
            }
            label={<span className="block font-semibold break-words">{name}</span>}
            description={
              <>
                {user.username ? (
                  <span className="block [overflow-wrap:anywhere]">{user.email}</span>
                ) : null}
                {user.roles.length > 0 ? (
                  <span className="block">
                    {t("admin_users_row_roles", {
                      count: user.roles.length,
                      names: names(user.roles)
                    })}
                  </span>
                ) : null}
                {user.user_groups.length > 0 ? (
                  <span className="block">
                    {t("admin_users_row_groups", {
                      count: user.user_groups.length,
                      names: names(user.user_groups)
                    })}
                  </span>
                ) : null}
                {user.state !== "active" || user.password_change_required ? (
                  <span className="flex flex-wrap items-center gap-1.5 pt-0.5">
                    {user.state !== "active" ? (
                      <StatusLabel status={STATE_TONE[user.state]} label={stateLabel(user.state)} />
                    ) : null}
                    {user.password_change_required ? (
                      <Badge label={t("admin_password_change_required_badge")} />
                    ) : null}
                  </span>
                ) : null}
              </>
            }
            endContent={<UserActions user={user} onRemoved={onRemoved} />}
          />
        );
      })}
    </List>
  );
}

/**
 * Users as a table from 768 px: username and email with an initials avatar,
 * role and user group badges, status dot with its label, and the row menu.
 * Long names and emails truncate with a tooltip.
 */
function UserTable({ users, label, onRemoved }: UsersProps) {
  const t = useTranslations();
  const stateLabel = useStateLabel();

  const columns: TableColumn<AdminUser>[] = [
    {
      key: "name",
      header: t("user"),
      width: proportional(1.5, { minWidth: 176 }),
      renderCell: (user) => {
        const name = user.username || user.email;
        return (
          <div className="flex min-w-0 items-center gap-3">
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
        );
      }
    },
    {
      key: "roles",
      header: t("roles"),
      // Roles and groups share the remaining room, with badges wrapping on tablets.
      width: proportional(1, { minWidth: 120 }),
      renderCell: (user) => <BadgeList items={user.roles} />
    },
    {
      key: "groups",
      header: t("user_groups"),
      width: proportional(1, { minWidth: 120 }),
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
