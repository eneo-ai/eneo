import type { AdminSpaceAdmins, AdminSpaceListItem } from "@eneo/eneo-js";
import { formatList } from "$lib/core/formatting/formatList";
import { spaceRoleLabel } from "$lib/features/spaces/roles";
import { m } from "$lib/paraglide/messages";
import type { SortColumn, SpaceListQuery } from "./space-list-query";

/** A sortable column's name, as its header and the caption say it. */
export function sortColumnLabel(column: SortColumn): string {
  switch (column) {
    case "name":
      return m.admin_spaces_col_space();
    case "members":
      return m.members();
    case "activity":
      return m.admin_spaces_col_last_active();
    default:
      return column satisfies never;
  }
}

/** "Sorted by Space, ascending", plus the page when there is more than one. */
export function listOrderLabel(
  query: Pick<SpaceListQuery, "sort" | "dir">,
  page: number,
  pages: number,
  format: (value: number) => string
): string {
  const column = sortColumnLabel(query.sort);
  const direction =
    query.dir === "asc" ? m.admin_spaces_sort_ascending() : m.admin_spaces_sort_descending();
  return pages > 1
    ? m.admin_spaces_order_status_page({
        column,
        direction,
        page: format(page),
        pages: format(pages)
      })
    : m.admin_spaces_order_status({ column, direction });
}

/** "Ada och Bo", or "Ada, Bo och 3 till" past `max` names; null when the space has none. */
export function adminNames(admins: Pick<AdminSpaceAdmins, "principals">, max = 2): string | null {
  const names = admins.principals.map((principal) => principal.name);
  if (names.length === 0) return null;
  if (names.length <= max) return formatList(names);
  return m.admin_spaces_admins_more({
    names: names.slice(0, max).join(", "),
    count: names.length - max
  });
}

/** The viewer's own relation to a space as one short phrase. */
export function listMembershipLabel(membership: AdminSpaceListItem["viewer_membership"]): string {
  if (!membership.role) return m.admin_spaces_not_member();
  const role = spaceRoleLabel(membership.role);
  if (membership.via_group_only) return m.admin_spaces_role_via_group({ role });
  if (membership.oversight_joined_at) return m.admin_spaces_role_via_oversight({ role });
  return role;
}

/** "3 assistenter · 1 app · 2 kunskapskällor", leaving out kinds the space has none of. */
export function resourceSummary(
  resources: AdminSpaceListItem["resources"],
  format: (value: number) => string
): string {
  const parts: string[] = [];
  const { assistants, apps, group_chats, knowledge_sources } = resources;
  if (assistants > 0) {
    parts.push(
      assistants === 1
        ? m.admin_spaces_count_assistants_one()
        : m.admin_spaces_count_assistants({ count: format(assistants) })
    );
  }
  if (apps > 0) {
    parts.push(
      apps === 1
        ? m.admin_spaces_count_apps_one()
        : m.admin_spaces_count_apps({ count: format(apps) })
    );
  }
  if (group_chats > 0) {
    parts.push(
      group_chats === 1
        ? m.admin_spaces_count_group_chats_one()
        : m.admin_spaces_count_group_chats({ count: format(group_chats) })
    );
  }
  if (knowledge_sources > 0) {
    parts.push(
      knowledge_sources === 1
        ? m.admin_spaces_count_knowledge_one()
        : m.admin_spaces_count_knowledge({ count: format(knowledge_sources) })
    );
  }
  // The counts leave out the default assistant, so "none" would be wrong.
  return parts.length > 0 ? parts.join(" · ") : m.admin_spaces_only_default_assistant();
}

/** "{n} grupper" / "1 grupp". */
export function groupCount(value: number, format: (value: number) => string): string {
  return value === 1
    ? m.admin_spaces_count_groups_one()
    : m.admin_spaces_count_groups({ count: format(value) });
}

/** "{n} aktiva webbwidgetar" / "1 aktiv webbwidget". */
export function activeWidgetCount(value: number, format: (value: number) => string): string {
  return value === 1
    ? m.admin_spaces_count_active_widgets_one()
    : m.admin_spaces_count_active_widgets({ count: format(value) });
}

/** "{n} personer" / "1 person". */
export function peopleCount(value: number, format: (value: number) => string): string {
  return value === 1
    ? m.admin_spaces_count_people_one()
    : m.admin_spaces_count_people({ count: format(value) });
}
