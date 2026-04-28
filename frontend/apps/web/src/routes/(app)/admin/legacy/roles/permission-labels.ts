import { m } from "$lib/paraglide/messages";

// Backend returns stable lower_snake_case permission keys; labels and
// descriptions are translated client-side so the API stays language-
// agnostic.

type Entry = { label: string; description: string };

export function getPermissionCopy(name: string, fallbackDescription: string): Entry {
  // Permission keys are mostly lower_snake_case, but `AI` is uppercase in the
  // backend enum (intric.roles.permissions.Permission.AI == "AI"). Match both
  // cases explicitly rather than lowercasing, so this stays a pure switch.
  switch (name) {
    case "assistants":
      return {
        label: m.permission_assistants(),
        description: m.permission_assistants_description()
      };
    case "group_chats":
      return {
        label: m.permission_group_chats(),
        description: m.permission_group_chats_description()
      };
    case "apps":
      return { label: m.permission_apps(), description: m.permission_apps_description() };
    case "services":
      return {
        label: m.permission_services(),
        description: m.permission_services_description()
      };
    case "collections":
      return {
        label: m.permission_collections(),
        description: m.permission_collections_description()
      };
    case "websites":
      return {
        label: m.permission_websites(),
        description: m.permission_websites_description()
      };
    case "insights":
      return {
        label: m.permission_insights(),
        description: m.permission_insights_description()
      };
    case "integrations":
      return {
        label: m.permission_integrations(),
        description: m.permission_integrations_description()
      };
    case "ai":
    case "AI":
      return { label: m.permission_ai(), description: m.permission_ai_description() };
    case "admin":
      return { label: m.permission_admin(), description: m.permission_admin_description() };
    case "shared_spaces":
      return {
        label: m.permission_shared_spaces(),
        description: m.permission_shared_spaces_description()
      };
    case "api_keys":
      return {
        label: m.permission_api_keys(),
        description: m.permission_api_keys_description()
      };
    default:
      // Unknown permission — degrade gracefully: reformat the key so
      // "unknown_permission" shows as "Unknown permission" rather than raw
      // snake_case, and fall back to the backend-supplied description.
      return {
        label: name.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()),
        description: fallbackDescription
      };
  }
}

export function getPermissionLabel(name: string): string {
  return getPermissionCopy(name, "").label;
}
