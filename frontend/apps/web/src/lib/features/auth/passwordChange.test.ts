import { describe, expect, test } from "vitest";
import {
  ENEO_PASSWORD_POLICY,
  firstInvalidPasswordField,
  isCurrentPasswordChangeDialogSubmission,
  validateNewPassword,
  validatePasswordChange,
  type PasswordChangeCapability
} from "./passwordChange";

const eneoCapability: PasswordChangeCapability = {
  source: "eneo",
  policy: ENEO_PASSWORD_POLICY
};

describe("password change validation", () => {
  test("keeps an empty confirmation as required instead of calling it a mismatch", () => {
    const errors = validatePasswordChange(
      {
        currentPassword: "current password",
        newPassword: "a sufficiently long new password",
        confirmPassword: ""
      },
      eneoCapability
    );

    expect(errors.confirmPassword).toBe("required");
  });

  test("rejects a result from a closed or subsequently reopened dialog", () => {
    expect(isCurrentPasswordChangeDialogSubmission(true, 3, 3)).toBe(true);
    expect(isCurrentPasswordChangeDialogSubmission(false, 4, 3)).toBe(false);
    expect(isCurrentPasswordChangeDialogSubmission(true, 4, 3)).toBe(false);
  });

  test("rejects a mistyped confirmation", () => {
    const errors = validatePasswordChange(
      {
        currentPassword: "current password",
        newPassword: "a sufficiently long new password",
        confirmPassword: "a sufficiently long new passwore"
      },
      eneoCapability
    );

    expect(errors.confirmPassword).toBe("confirmation_mismatch");
    expect(firstInvalidPasswordField(errors)).toBe("confirmPassword");
  });

  test("measures the bcrypt boundary in UTF-8 bytes", () => {
    expect(validateNewPassword("å".repeat(36), ENEO_PASSWORD_POLICY)).toBeUndefined();
    expect(validateNewPassword("å".repeat(37), ENEO_PASSWORD_POLICY)).toBe("too_long_bytes");
  });

  test("applies the provider's effective composition policy", () => {
    const zitadelCapability: PasswordChangeCapability = {
      source: "zitadel",
      policy: {
        minLength: 10,
        maxBytes: null,
        requiresUppercase: true,
        requiresLowercase: true,
        requiresNumber: true,
        requiresSymbol: true
      }
    };

    expect(
      validatePasswordChange(
        {
          currentPassword: "old password",
          newPassword: "alllowercase!1",
          confirmPassword: "alllowercase!1"
        },
        zitadelCapability
      ).newPassword
    ).toBe("uppercase_required");
    expect(
      validatePasswordChange(
        {
          currentPassword: "old password",
          newPassword: "ValidPassword!1",
          confirmPassword: "ValidPassword!1"
        },
        zitadelCapability
      )
    ).toEqual({});
  });
});
