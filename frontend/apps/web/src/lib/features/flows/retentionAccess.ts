import type { Permission } from "@eneo/eneo-js";

/**
 * What the admin area shows a user, from the same role permissions the server
 * checks. The server stays the authority: this only decides what to render
 * and which requests to make.
 */
export type RetentionAccess = {
  admin: boolean;
  retentionManage: boolean;
  retentionHolds: boolean;
};

/** Where a user who may only work with retention lands in the admin area. */
export const RETENTION_ONLY_ADMIN_HREF = "/admin/flow-settings?tab=retention";
const RETENTION_ONLY_ADMIN_PATH = "/admin/flow-settings";

export function retentionAccess(can: (permission: Permission) => boolean): RetentionAccess {
  return {
    admin: can("admin"),
    retentionManage: can("retention_manage"),
    retentionHolds: can("retention_holds")
  };
}

export function hasRetentionPermission(access: RetentionAccess): boolean {
  return access.retentionManage || access.retentionHolds;
}

export function canOpenAdmin(access: RetentionAccess): boolean {
  return access.admin || hasRetentionPermission(access);
}

/**
 * A retention-only user may open the retention tab of Flow settings and nothing
 * else in the admin area; another tab (an old bookmark) has no content for it.
 */
export function retentionOnlyAllows(url: URL, pathname: string): boolean {
  const path = pathname.replace(/\/$/, "");
  const tab = url.searchParams.get("tab");
  return path === RETENTION_ONLY_ADMIN_PATH && (tab === null || tab === "retention");
}

/** Where the main navigation's Admin link points for this user. */
export function adminHomeHref(access: RetentionAccess): string {
  return access.admin ? "/admin" : RETENTION_ONLY_ADMIN_HREF;
}
