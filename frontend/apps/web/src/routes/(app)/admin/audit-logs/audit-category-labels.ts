import * as m from "$lib/paraglide/messages";
import type { components } from "@intric/intric-js";

type CategoryType = components["schemas"]["CategoryType"];
type MessageFn = () => string;

/**
 * Exhaustive category → message map. The `satisfies Record<CategoryType, …>` makes the
 * compiler (`bun run check`) reject a new CategoryType (added to the union via schema
 * regeneration) until it is registered here with both messages — and referencing
 * a missing `m.*` key fails the same check. en/sv parity is guarded by the
 * audit-i18n unit test. This is the single source of truth for display text.
 */

const CATEGORY_MESSAGES = {
  admin_actions: {
    name: m.audit_category_admin_actions,
    description: m.audit_category_admin_actions_description
  },
  user_actions: {
    name: m.audit_category_user_actions,
    description: m.audit_category_user_actions_description
  },
  security_events: {
    name: m.audit_category_security_events,
    description: m.audit_category_security_events_description
  },
  file_operations: {
    name: m.audit_category_file_operations,
    description: m.audit_category_file_operations_description
  },
  integration_events: {
    name: m.audit_category_integration_events,
    description: m.audit_category_integration_events_description
  },
  system_actions: {
    name: m.audit_category_system_actions,
    description: m.audit_category_system_actions_description
  },
  audit_access: {
    name: m.audit_category_audit_access,
    description: m.audit_category_audit_access_description
  }
} satisfies Record<CategoryType, { name: MessageFn; description: MessageFn }>;

export function getCategoryLabel(category: CategoryType): string {
  return CATEGORY_MESSAGES[category]?.name() ?? category;
}

export function getCategoryDescription(category: CategoryType): string {
  return CATEGORY_MESSAGES[category]?.description() ?? "";
}
