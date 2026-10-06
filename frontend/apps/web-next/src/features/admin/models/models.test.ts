import { describe, expect, it } from "vitest";
import { isMigrationSecurityBlockerCode, migrationWarningLabel } from "./models";

const t = (key: string, values?: Record<string, number | string>) =>
  values ? `${key}:${JSON.stringify(values)}` : key;

describe("model migration warning codes", () => {
  it("labels structured warning codes for display", () => {
    expect(
      migrationWarningLabel(
        t,
        "Target model classification is too low",
        "security_classification_insufficient:3:Confidential"
      )
    ).toBe(
      'migration_warning_security_classification_insufficient:{"count":3,"classification":"Confidential"}'
    );

    expect(migrationWarningLabel(t, "Target model lacks vision support", "lacks_vision")).toBe(
      "migration_warning_lacks_vision"
    );
  });

  it("detects force-override security blockers", () => {
    expect(isMigrationSecurityBlockerCode("security_classification_insufficient:1:none")).toBe(
      true
    );
    expect(isMigrationSecurityBlockerCode("target_deprecated")).toBe(false);
  });
});
