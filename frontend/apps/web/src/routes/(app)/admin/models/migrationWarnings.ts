/*
 * Copyright (c) 2026 Sundsvalls Kommun
 *
 * Translation of backend migration warning codes to user-facing messages.
 * Used by both `MigrateModelDialog` (when picking a target) and
 * `MigrationHistoryPanel` (when reviewing past migrations).
 *
 * The codes are produced by `models.validateMigration` on the backend; some
 * are simple constants while others embed parameters (`lower_token_limit:`,
 * `different_family:from:to`, `security_classification_insufficient:n:name`).
 * Adding a new code here keeps both surfaces in sync.
 */
import { m } from "$lib/paraglide/messages";

export function translateMigrationWarning(code: string): string {
  if (code === "target_deprecated") return m.migration_warn_target_deprecated();
  if (code.startsWith("lower_token_limit:")) {
    return m.migration_warn_lower_token_limit({ limit: code.split(":")[1] });
  }
  if (code.startsWith("different_family:")) {
    const [, from, to] = code.split(":");
    return m.migration_warn_different_family({ from, to });
  }
  if (code === "lacks_vision") return m.migration_warn_lacks_vision();
  if (code === "lacks_reasoning") return m.migration_warn_lacks_reasoning();
  if (code === "lacks_tool_calling") return m.migration_warn_lacks_tool_calling();
  if (code === "kwargs_reset") return m.migration_warn_kwargs_reset();
  if (code.startsWith("security_classification_insufficient:")) {
    const [, count, classification] = code.split(":");
    return m.migration_blocked_security({ count, classification });
  }
  return code;
}

export function isSecurityBlockerCode(code: string): boolean {
  return code.startsWith("security_classification_insufficient");
}
