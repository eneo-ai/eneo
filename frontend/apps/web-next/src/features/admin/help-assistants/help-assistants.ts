import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type RoleAssignment = Schema<"RoleAssignmentPublic">;
export type HelperTemplate = Schema<"HelperTemplatePublic">;
export type HelperKind = Schema<"HelperKind">;

export const ROLES_KEY = ["admin-help-roles"];
export const TEMPLATES_KEY = ["admin-help-templates"];

export function helpRolesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ROLES_KEY,
    queryFn: async (): Promise<RoleAssignment[]> => {
      const page = await unwrap(api.GET("/api/v1/admin/help-assistants/roles/"));
      return page.items;
    }
  });
}
export function helpTemplatesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: TEMPLATES_KEY,
    queryFn: async (): Promise<HelperTemplate[]> => {
      const page = await unwrap(api.GET("/api/v1/admin/help-assistants/templates/"));
      return page.items;
    }
  });
}
