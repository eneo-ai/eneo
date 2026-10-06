// @vitest-environment jsdom
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { PasswordPolicy } from "./password-policy";
import { PasswordPolicyChecklist } from "./password-policy-checklist";

const policy: PasswordPolicy = {
  minLength: 12,
  maxBytes: 72,
  requiresUppercase: true,
  requiresLowercase: false,
  requiresNumber: true,
  requiresSymbol: false
};

function renderChecklist(password: string, confirmation = "") {
  const view = renderInApp(
    <PasswordPolicyChecklist
      id="policy"
      password={password}
      confirmation={confirmation}
      policy={policy}
    />
  );
  const checklist = document.getElementById("policy")!;
  const items = () =>
    within(checklist)
      .getAllByRole("listitem")
      .map((item) => item.textContent);
  return { ...view, checklist, items };
}

describe("PasswordPolicyChecklist", () => {
  it("lists the policy's rules and the confirmation, each marked in words", async () => {
    const { container, checklist, items } = renderChecklist("");

    expect(
      within(checklist).getByText("Det nya lösenordet måste uppfylla följande krav:")
    ).toBeTruthy();
    // bcrypt's byte limit is left to the check on save.
    expect(items()).toEqual([
      "Använd minst 12 tecken – Inte uppfyllt ännu",
      "Inkludera en stor bokstav A–Z – Inte uppfyllt ännu",
      "Inkludera en siffra 0–9 – Inte uppfyllt ännu",
      "Lösenorden matchar – Inte uppfyllt ännu"
    ]);
    await expectNoAxeViolations(container);
  });

  it("marks each rule met as the password is typed", async () => {
    const { container, rerender, items } = renderChecklist("Nytt-lösenord");

    expect(items()).toEqual([
      "Använd minst 12 tecken – Uppfyllt",
      "Inkludera en stor bokstav A–Z – Uppfyllt",
      "Inkludera en siffra 0–9 – Inte uppfyllt ännu",
      "Lösenorden matchar – Inte uppfyllt ännu"
    ]);

    rerender(
      <PasswordPolicyChecklist
        id="policy"
        password="Nytt-lösenord-1"
        confirmation="Nytt-lösenord-1"
        policy={policy}
      />
    );
    expect(items().every((item) => item?.endsWith("– Uppfyllt"))).toBe(true);
    await expectNoAxeViolations(container);
  });

  it("is read with the field, not announced at each keystroke, and takes no focus", () => {
    const { checklist } = renderChecklist("Nytt");

    expect(checklist.closest("[aria-live], [role=status], [role=alert], [role=log]")).toBeNull();
    expect(checklist.querySelector("[aria-live]")).toBeNull();
    // Nothing in it is a tab stop: the fields' own order is kept.
    expect(checklist.querySelectorAll("a, button, input, [tabindex]")).toHaveLength(0);
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
  });
});
