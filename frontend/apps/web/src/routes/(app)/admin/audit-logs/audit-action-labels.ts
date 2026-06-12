import * as m from "$lib/paraglide/messages";
import type { components } from "@intric/intric-js";

type ActionType = components["schemas"]["ActionType"];
type MessageFn = () => string;

/**
 * Exhaustive action → message map. The `satisfies Record<ActionType, …>` makes the
 * compiler (`bun run check`) reject a new ActionType (added to the union via schema
 * regeneration) until it is registered here with both messages — and referencing
 * a missing `m.*` key fails the same check. en/sv parity is guarded by the
 * audit-i18n unit test. This is the single source of truth for display text.
 */

const ACTION_MESSAGES = {
  user_created: {
    name: m.audit_action_user_created,
    description: m.audit_action_user_created_description
  },
  user_deleted: {
    name: m.audit_action_user_deleted,
    description: m.audit_action_user_deleted_description
  },
  user_updated: {
    name: m.audit_action_user_updated,
    description: m.audit_action_user_updated_description
  },
  role_created: {
    name: m.audit_action_role_created,
    description: m.audit_action_role_created_description
  },
  role_modified: {
    name: m.audit_action_role_modified,
    description: m.audit_action_role_modified_description
  },
  role_deleted: {
    name: m.audit_action_role_deleted,
    description: m.audit_action_role_deleted_description
  },
  permission_changed: {
    name: m.audit_action_permission_changed,
    description: m.audit_action_permission_changed_description
  },
  tenant_settings_updated: {
    name: m.audit_action_tenant_settings_updated,
    description: m.audit_action_tenant_settings_updated_description
  },
  credentials_updated: {
    name: m.audit_action_credentials_updated,
    description: m.audit_action_credentials_updated_description
  },
  federation_updated: {
    name: m.audit_action_federation_updated,
    description: m.audit_action_federation_updated_description
  },
  api_key_generated: {
    name: m.audit_action_api_key_generated,
    description: m.audit_action_api_key_generated_description
  },
  api_key_created: {
    name: m.audit_action_api_key_created,
    description: m.audit_action_api_key_created_description
  },
  api_key_updated: {
    name: m.audit_action_api_key_updated,
    description: m.audit_action_api_key_updated_description
  },
  api_key_revoked: {
    name: m.audit_action_api_key_revoked,
    description: m.audit_action_api_key_revoked_description
  },
  api_key_suspended: {
    name: m.audit_action_api_key_suspended,
    description: m.audit_action_api_key_suspended_description
  },
  api_key_reactivated: {
    name: m.audit_action_api_key_reactivated,
    description: m.audit_action_api_key_reactivated_description
  },
  api_key_rotated: {
    name: m.audit_action_api_key_rotated,
    description: m.audit_action_api_key_rotated_description
  },
  api_key_expiration_extended: {
    name: m.audit_action_api_key_expiration_extended,
    description: m.audit_action_api_key_expiration_extended_description
  },
  api_key_purged: {
    name: m.audit_action_api_key_purged,
    description: m.audit_action_api_key_purged_description
  },
  api_key_expired: {
    name: m.audit_action_api_key_expired,
    description: m.audit_action_api_key_expired_description
  },
  api_key_used: {
    name: m.audit_action_api_key_used,
    description: m.audit_action_api_key_used_description
  },
  api_key_auth_failed: {
    name: m.audit_action_api_key_auth_failed,
    description: m.audit_action_api_key_auth_failed_description
  },
  tenant_policy_updated: {
    name: m.audit_action_tenant_policy_updated,
    description: m.audit_action_tenant_policy_updated_description
  },
  module_added: {
    name: m.audit_action_module_added,
    description: m.audit_action_module_added_description
  },
  module_added_to_tenant: {
    name: m.audit_action_module_added_to_tenant,
    description: m.audit_action_module_added_to_tenant_description
  },
  governance_policy_updated: {
    name: m.audit_action_governance_policy_updated,
    description: m.audit_action_governance_policy_updated_description
  },
  prompt_library_entry_created: {
    name: m.audit_action_prompt_library_entry_created,
    description: m.audit_action_prompt_library_entry_created_description
  },
  prompt_library_entry_updated: {
    name: m.audit_action_prompt_library_entry_updated,
    description: m.audit_action_prompt_library_entry_updated_description
  },
  prompt_library_entry_deleted: {
    name: m.audit_action_prompt_library_entry_deleted,
    description: m.audit_action_prompt_library_entry_deleted_description
  },
  scim_user_provisioned: {
    name: m.audit_action_scim_user_provisioned,
    description: m.audit_action_scim_user_provisioned_description
  },
  scim_user_reconciled: {
    name: m.audit_action_scim_user_reconciled,
    description: m.audit_action_scim_user_reconciled_description
  },
  scim_user_reactivated: {
    name: m.audit_action_scim_user_reactivated,
    description: m.audit_action_scim_user_reactivated_description
  },
  scim_user_deprovisioned: {
    name: m.audit_action_scim_user_deprovisioned,
    description: m.audit_action_scim_user_deprovisioned_description
  },
  scim_user_updated: {
    name: m.audit_action_scim_user_updated,
    description: m.audit_action_scim_user_updated_description
  },
  scim_group_created: {
    name: m.audit_action_scim_group_created,
    description: m.audit_action_scim_group_created_description
  },
  scim_group_reactivated: {
    name: m.audit_action_scim_group_reactivated,
    description: m.audit_action_scim_group_reactivated_description
  },
  scim_group_updated: {
    name: m.audit_action_scim_group_updated,
    description: m.audit_action_scim_group_updated_description
  },
  scim_group_deleted: {
    name: m.audit_action_scim_group_deleted,
    description: m.audit_action_scim_group_deleted_description
  },
  scim_token_created: {
    name: m.audit_action_scim_token_created,
    description: m.audit_action_scim_token_created_description
  },
  scim_token_revoked: {
    name: m.audit_action_scim_token_revoked,
    description: m.audit_action_scim_token_revoked_description
  },
  assistant_created: {
    name: m.audit_action_assistant_created,
    description: m.audit_action_assistant_created_description
  },
  assistant_deleted: {
    name: m.audit_action_assistant_deleted,
    description: m.audit_action_assistant_deleted_description
  },
  assistant_updated: {
    name: m.audit_action_assistant_updated,
    description: m.audit_action_assistant_updated_description
  },
  assistant_transferred: {
    name: m.audit_action_assistant_transferred,
    description: m.audit_action_assistant_transferred_description
  },
  assistant_published: {
    name: m.audit_action_assistant_published,
    description: m.audit_action_assistant_published_description
  },
  space_created: {
    name: m.audit_action_space_created,
    description: m.audit_action_space_created_description
  },
  space_updated: {
    name: m.audit_action_space_updated,
    description: m.audit_action_space_updated_description
  },
  space_deleted: {
    name: m.audit_action_space_deleted,
    description: m.audit_action_space_deleted_description
  },
  space_member_added: {
    name: m.audit_action_space_member_added,
    description: m.audit_action_space_member_added_description
  },
  space_member_removed: {
    name: m.audit_action_space_member_removed,
    description: m.audit_action_space_member_removed_description
  },
  app_created: {
    name: m.audit_action_app_created,
    description: m.audit_action_app_created_description
  },
  app_deleted: {
    name: m.audit_action_app_deleted,
    description: m.audit_action_app_deleted_description
  },
  app_updated: {
    name: m.audit_action_app_updated,
    description: m.audit_action_app_updated_description
  },
  app_executed: {
    name: m.audit_action_app_executed,
    description: m.audit_action_app_executed_description
  },
  app_published: {
    name: m.audit_action_app_published,
    description: m.audit_action_app_published_description
  },
  app_run_deleted: {
    name: m.audit_action_app_run_deleted,
    description: m.audit_action_app_run_deleted_description
  },
  session_started: {
    name: m.audit_action_session_started,
    description: m.audit_action_session_started_description
  },
  session_ended: {
    name: m.audit_action_session_ended,
    description: m.audit_action_session_ended_description
  },
  tool_approval_submitted: {
    name: m.audit_action_tool_approval_submitted,
    description: m.audit_action_tool_approval_submitted_description
  },
  file_uploaded: {
    name: m.audit_action_file_uploaded,
    description: m.audit_action_file_uploaded_description
  },
  file_deleted: {
    name: m.audit_action_file_deleted,
    description: m.audit_action_file_deleted_description
  },
  website_created: {
    name: m.audit_action_website_created,
    description: m.audit_action_website_created_description
  },
  website_updated: {
    name: m.audit_action_website_updated,
    description: m.audit_action_website_updated_description
  },
  website_deleted: {
    name: m.audit_action_website_deleted,
    description: m.audit_action_website_deleted_description
  },
  website_crawled: {
    name: m.audit_action_website_crawled,
    description: m.audit_action_website_crawled_description
  },
  website_transferred: {
    name: m.audit_action_website_transferred,
    description: m.audit_action_website_transferred_description
  },
  group_chat_created: {
    name: m.audit_action_group_chat_created,
    description: m.audit_action_group_chat_created_description
  },
  collection_created: {
    name: m.audit_action_collection_created,
    description: m.audit_action_collection_created_description
  },
  collection_updated: {
    name: m.audit_action_collection_updated,
    description: m.audit_action_collection_updated_description
  },
  collection_deleted: {
    name: m.audit_action_collection_deleted,
    description: m.audit_action_collection_deleted_description
  },
  integration_added: {
    name: m.audit_action_integration_added,
    description: m.audit_action_integration_added_description
  },
  integration_removed: {
    name: m.audit_action_integration_removed,
    description: m.audit_action_integration_removed_description
  },
  integration_connected: {
    name: m.audit_action_integration_connected,
    description: m.audit_action_integration_connected_description
  },
  integration_disconnected: {
    name: m.audit_action_integration_disconnected,
    description: m.audit_action_integration_disconnected_description
  },
  integration_knowledge_created: {
    name: m.audit_action_integration_knowledge_created,
    description: m.audit_action_integration_knowledge_created_description
  },
  integration_knowledge_deleted: {
    name: m.audit_action_integration_knowledge_deleted,
    description: m.audit_action_integration_knowledge_deleted_description
  },
  integration_knowledge_synced: {
    name: m.audit_action_integration_knowledge_synced,
    description: m.audit_action_integration_knowledge_synced_description
  },
  completion_model_created: {
    name: m.audit_action_completion_model_created,
    description: m.audit_action_completion_model_created_description
  },
  completion_model_updated: {
    name: m.audit_action_completion_model_updated,
    description: m.audit_action_completion_model_updated_description
  },
  completion_model_deleted: {
    name: m.audit_action_completion_model_deleted,
    description: m.audit_action_completion_model_deleted_description
  },
  completion_model_migrated: {
    name: m.audit_action_completion_model_migrated,
    description: m.audit_action_completion_model_migrated_description
  },
  embedding_model_created: {
    name: m.audit_action_embedding_model_created,
    description: m.audit_action_embedding_model_created_description
  },
  embedding_model_updated: {
    name: m.audit_action_embedding_model_updated,
    description: m.audit_action_embedding_model_updated_description
  },
  embedding_model_deleted: {
    name: m.audit_action_embedding_model_deleted,
    description: m.audit_action_embedding_model_deleted_description
  },
  transcription_model_created: {
    name: m.audit_action_transcription_model_created,
    description: m.audit_action_transcription_model_created_description
  },
  transcription_model_updated: {
    name: m.audit_action_transcription_model_updated,
    description: m.audit_action_transcription_model_updated_description
  },
  transcription_model_deleted: {
    name: m.audit_action_transcription_model_deleted,
    description: m.audit_action_transcription_model_deleted_description
  },
  transcription_model_migrated: {
    name: m.audit_action_transcription_model_migrated,
    description: m.audit_action_transcription_model_migrated_description
  },
  template_created: {
    name: m.audit_action_template_created,
    description: m.audit_action_template_created_description
  },
  template_updated: {
    name: m.audit_action_template_updated,
    description: m.audit_action_template_updated_description
  },
  template_deleted: {
    name: m.audit_action_template_deleted,
    description: m.audit_action_template_deleted_description
  },
  security_classification_created: {
    name: m.audit_action_security_classification_created,
    description: m.audit_action_security_classification_created_description
  },
  security_classification_updated: {
    name: m.audit_action_security_classification_updated,
    description: m.audit_action_security_classification_updated_description
  },
  security_classification_deleted: {
    name: m.audit_action_security_classification_deleted,
    description: m.audit_action_security_classification_deleted_description
  },
  security_classification_levels_updated: {
    name: m.audit_action_security_classification_levels_updated,
    description: m.audit_action_security_classification_levels_updated_description
  },
  security_classification_enabled: {
    name: m.audit_action_security_classification_enabled,
    description: m.audit_action_security_classification_enabled_description
  },
  security_classification_disabled: {
    name: m.audit_action_security_classification_disabled,
    description: m.audit_action_security_classification_disabled_description
  },
  mcp_server_created: {
    name: m.audit_action_mcp_server_created,
    description: m.audit_action_mcp_server_created_description
  },
  mcp_server_updated: {
    name: m.audit_action_mcp_server_updated,
    description: m.audit_action_mcp_server_updated_description
  },
  mcp_server_deleted: {
    name: m.audit_action_mcp_server_deleted,
    description: m.audit_action_mcp_server_deleted_description
  },
  mcp_server_enabled: {
    name: m.audit_action_mcp_server_enabled,
    description: m.audit_action_mcp_server_enabled_description
  },
  mcp_server_disabled: {
    name: m.audit_action_mcp_server_disabled,
    description: m.audit_action_mcp_server_disabled_description
  },
  mcp_server_tool_enabled: {
    name: m.audit_action_mcp_server_tool_enabled,
    description: m.audit_action_mcp_server_tool_enabled_description
  },
  mcp_server_tool_disabled: {
    name: m.audit_action_mcp_server_tool_disabled,
    description: m.audit_action_mcp_server_tool_disabled_description
  },
  retention_policy_applied: {
    name: m.audit_action_retention_policy_applied,
    description: m.audit_action_retention_policy_applied_description
  },
  encryption_key_rotated: {
    name: m.audit_action_encryption_key_rotated,
    description: m.audit_action_encryption_key_rotated_description
  },
  system_maintenance: {
    name: m.audit_action_system_maintenance,
    description: m.audit_action_system_maintenance_description
  },
  audit_session_created: {
    name: m.audit_action_audit_session_created,
    description: m.audit_action_audit_session_created_description
  },
  audit_log_viewed: {
    name: m.audit_action_audit_log_viewed,
    description: m.audit_action_audit_log_viewed_description
  },
  audit_log_exported: {
    name: m.audit_action_audit_log_exported,
    description: m.audit_action_audit_log_exported_description
  },
  help_assistant_role_assigned: {
    name: m.audit_action_help_assistant_role_assigned,
    description: m.audit_action_help_assistant_role_assigned_description
  },
  help_assistant_role_unassigned: {
    name: m.audit_action_help_assistant_role_unassigned,
    description: m.audit_action_help_assistant_role_unassigned_description
  },
  help_assistant_role_toggled_enabled: {
    name: m.audit_action_help_assistant_role_toggled_enabled,
    description: m.audit_action_help_assistant_role_toggled_enabled_description
  },
  help_assistant_role_toggled_visible: {
    name: m.audit_action_help_assistant_role_toggled_visible,
    description: m.audit_action_help_assistant_role_toggled_visible_description
  },
  help_assistant_installed: {
    name: m.audit_action_help_assistant_installed,
    description: m.audit_action_help_assistant_installed_description
  },
  help_assistant_uninstalled: {
    name: m.audit_action_help_assistant_uninstalled,
    description: m.audit_action_help_assistant_uninstalled_description
  }
} satisfies Record<ActionType, { name: MessageFn; description: MessageFn }>;

export function getActionLabel(action: ActionType | "all"): string {
  if (action === "all") return m.audit_all_actions();
  return ACTION_MESSAGES[action]?.name() ?? action;
}

export function getActionDescription(action: ActionType): string {
  return ACTION_MESSAGES[action]?.description() ?? "";
}

export function getActionOptions(): Array<{ value: ActionType | "all"; label: string }> {
  const options = (Object.keys(ACTION_MESSAGES) as ActionType[]).map((value) => ({
    value,
    label: ACTION_MESSAGES[value].name()
  }));
  options.sort((a, b) => a.label.localeCompare(b.label));
  return [{ value: "all", label: m.audit_all_actions() }, ...options];
}
