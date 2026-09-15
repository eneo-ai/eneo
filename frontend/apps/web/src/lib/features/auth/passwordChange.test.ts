import { describe, expect, test } from "vitest";
import {
  ENEO_PASSWORD_POLICY,
  firstInvalidPasswordField,
  isCurrentPasswordChangeDialogSubmission,
  validateNewPassword,
  validateNewPasswordPair,
  validatePasswordChange,
  type PasswordChangeCapability
} from "./passwordChange";

const eneoCapability: PasswordChangeCapability = {
  source: "eneo",
  policy: ENEO_PASSWORD_POLICY
};

describe("administrator password entry", () => {
  const newPassword = "a sufficiently long new password";

  test.each(["a", "å", "🔑"])("accepts 12 characters and rejects 11 for %s", (character) => {
    const accepted = character.repeat(12);
    const rejected = character.repeat(11);
    expect(
      validateNewPasswordPair(
        { newPassword: accepted, confirmPassword: accepted },
        eneoCapability,
        false
      )
    ).toEqual({});
    expect(
      validateNewPasswordPair(
        { newPassword: rejected, confirmPassword: rejected },
        eneoCapability,
        false
      )
    ).toEqual({ newPassword: "too_short" });
  });

  test("allows updating account details without changing the password", () => {
    expect(
      validateNewPasswordPair({ newPassword: "", confirmPassword: "" }, eneoCapability, false)
    ).toEqual({});
  });

  test("requires a password and confirmation when creating an account", () => {
    expect(
      validateNewPasswordPair({ newPassword: "", confirmPassword: "" }, eneoCapability)
    ).toEqual({ newPassword: "required", confirmPassword: "required" });
  });

  test("sets a new password without requiring the current password", () => {
    expect(
      validateNewPasswordPair({ newPassword, confirmPassword: newPassword }, eneoCapability, false)
    ).toEqual({});
  });

  test.each([
    [{ newPassword, confirmPassword: "" }, { confirmPassword: "required" }],
    [{ newPassword: "", confirmPassword: newPassword }, { newPassword: "required" }],
    [
      { newPassword, confirmPassword: `${newPassword}!` },
      { confirmPassword: "confirmation_mismatch" }
    ],
    [{ newPassword: "short", confirmPassword: "short" }, { newPassword: "too_short" }],
    [
      { newPassword: "å".repeat(37), confirmPassword: "å".repeat(37) },
      { newPassword: "too_long_bytes" }
    ]
  ])("rejects invalid password pairs: %j", (values, errors) => {
    expect(validateNewPasswordPair(values, eneoCapability, false)).toEqual(errors);
  });
});

describe("password change validation", () => {
  test("self-service still requires the current password", () => {
    expect(
      validatePasswordChange(
        {
          currentPassword: "",
          newPassword: "a sufficiently long password",
          confirmPassword: "a sufficiently long password"
        },
        eneoCapability
      )
    ).toEqual({ currentPassword: "required" });
  });

  test("self-service still rejects reusing the current password", () => {
    const password = "a sufficiently long password";
    expect(
      validatePasswordChange(
        { currentPassword: password, newPassword: password, confirmPassword: password },
        eneoCapability
      )
    ).toEqual({ newPassword: "password_unchanged" });
  });
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
    expect(validateNewPassword("å".repeat(36), eneoCapability)).toBeUndefined();
    expect(validateNewPassword("å".repeat(37), eneoCapability)).toBe("too_long_bytes");
    expect(validateNewPassword("å".repeat(11), eneoCapability)).toBe("too_short");
    expect(validateNewPassword("å".repeat(12), eneoCapability)).toBeUndefined();
  });

  test.each([
    ["å".repeat(8), undefined],
    ["å".repeat(7), "too_short_bytes"]
  ])("measures Zitadel's minimum in UTF-8 bytes for %s", (password, expected) => {
    expect(
      validateNewPassword(password, {
        source: "zitadel",
        policy: { ...ENEO_PASSWORD_POLICY, minLength: 15, maxBytes: null }
      })
    ).toBe(expected);
  });

  test.each([
    ["Valid Password1", undefined],
    ["ValidPassword1å", undefined],
    ["Åbcdefghijklmn1!", "uppercase_required"],
    ["ABCDEFGHIJKLMå1!", "lowercase_required"],
    ["ValidPassword١!", "number_required"],
    ["ValidPassword12", "symbol_required"]
  ])("matches Zitadel's ASCII composition rules for %s", (password, expected) => {
    expect(
      validateNewPassword(password, {
        source: "zitadel",
        policy: {
          minLength: 15,
          maxBytes: null,
          requiresUppercase: true,
          requiresLowercase: true,
          requiresNumber: true,
          requiresSymbol: true
        }
      })
    ).toBe(expected);
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
