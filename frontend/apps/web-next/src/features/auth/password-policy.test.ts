import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";
import sv from "@/lib/i18n/messages/sv.json";
import {
  brokenRule,
  newPasswordErrors,
  passwordCapability,
  type PasswordPolicy,
  policyChecks
} from "./password-policy";

const localPolicy = {
  min_length: 12,
  max_bytes: 72,
  requires_uppercase: false,
  requires_lowercase: false,
  requires_number: false,
  requires_symbol: false
};

const policy: PasswordPolicy = {
  minLength: 12,
  maxBytes: 72,
  requiresUppercase: true,
  requiresLowercase: false,
  requiresNumber: true,
  requiresSymbol: false
};

describe("passwordCapability", () => {
  it("reads the local policy the backend sends", () => {
    expect(passwordCapability({ source: "eneo", policy: localPolicy })).toEqual({
      source: "eneo",
      policy: {
        minLength: 12,
        maxBytes: 72,
        requiresUppercase: false,
        requiresLowercase: false,
        requiresNumber: false,
        requiresSymbol: false
      }
    });
    expect(passwordCapability({ source: "external", policy: null })).toEqual({
      source: "external"
    });
  });

  it("never guesses at a policy that is missing or odd", () => {
    expect(passwordCapability(undefined)).toEqual({ source: "unavailable" });
    expect(passwordCapability({ source: "eneo" })).toEqual({ source: "unavailable" });
    expect(
      passwordCapability({ source: "eneo", policy: { ...localPolicy, min_length: 0 } })
    ).toEqual({ source: "unavailable" });
    // requires_symbol left out.
    const partial = {
      min_length: 12,
      max_bytes: 72,
      requires_uppercase: false,
      requires_lowercase: false,
      requires_number: false
    };
    expect(passwordCapability({ source: "eneo", policy: partial })).toEqual({
      source: "unavailable"
    });
  });
});

describe("policyChecks", () => {
  it("counts characters for the minimum and UTF-8 bytes for the maximum", () => {
    // Twelve characters, one of them four bytes.
    const password = "Lösenord1😀ab";
    expect([...password]).toHaveLength(12);
    expect(brokenRule(password, policy)).toBeUndefined();
    expect(brokenRule("Lösenord1😀a", policy)).toBe("min_length");
    expect(brokenRule(`A1${"😀".repeat(18)}`, policy)).toBe("max_bytes");
  });

  it("asks only for the character classes the policy requires, in the backend's order", () => {
    expect(policyChecks("langtlosenord", policy).map(({ rule, met }) => [rule, met])).toEqual([
      ["min_length", true],
      ["max_bytes", true],
      ["uppercase", false],
      ["number", false]
    ]);
    expect(brokenRule("langtlosenord", policy)).toBe("uppercase");
    expect(brokenRule("Langtlosenord", policy)).toBe("number");
  });
});

// The app's Swedish catalog, looked up by any key as the forms do.
const t = createTranslator({ locale: "sv", messages: sv as Record<string, string> });

describe("the words the forms use", () => {
  it("says what is wrong with a new password and its confirmation", () => {
    const errors = (password: string, confirmation: string, required = true) =>
      newPasswordErrors(t, { password, confirmation, policy, required });

    expect(errors("", "")).toEqual({
      password: "Ange ett nytt lösenord.",
      confirmation: undefined
    });
    expect(errors("Kort1", "")).toEqual({
      password: "Använd minst 12 tecken",
      confirmation: "Skriv det nya lösenordet en gång till."
    });
    expect(errors("Langt-losenord-1", "Langt-losenord-2")).toEqual({
      password: undefined,
      confirmation: "Lösenorden matchar inte. Skriv samma lösenord i båda fälten."
    });
    expect(errors("Langt-losenord-1", "Langt-losenord-1")).toEqual({
      password: undefined,
      confirmation: undefined
    });
    // An admin may leave a user's password as it is.
    expect(errors("", "", false)).toEqual({});
    expect(errors("", "Langt-losenord-1", false).password).toBe("Ange ett nytt lösenord.");
  });
});
