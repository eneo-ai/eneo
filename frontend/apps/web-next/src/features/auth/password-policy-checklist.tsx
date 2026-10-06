"use client";

import { Check, Circle } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { type PasswordPolicy, policyChecks, policyRuleText } from "./password-policy";

/**
 * What a new password must meet, each rule marked met or not yet as it is
 * typed: SvelteKit's PasswordPolicyChecklist. The password fields name it in
 * their aria-describedby (`describedBy` on ConfirmedSecretInput), so it is
 * read, current, when a field gets focus. Not a live region: announcing each
 * keystroke's change would drown out the typing. The state is also in words
 * (WCAG 1.4.1), not only the icon and colour.
 *
 * @example
 * <PasswordPolicyChecklist id={checklistId} password={next} confirmation={confirm} policy={policy} />
 * <ConfirmedSecretInput describedBy={checklistId} … />
 */
export function PasswordPolicyChecklist({
  id,
  password,
  confirmation,
  policy
}: {
  id: string;
  password: string;
  confirmation: string;
  policy: PasswordPolicy;
}) {
  const t = useTranslations();
  const items = [
    // bcrypt's byte limit is checked on save, as in SvelteKit.
    ...policyChecks(password, policy)
      .filter(({ rule }) => rule !== "max_bytes")
      .map(({ rule, met }) => ({ key: rule, label: policyRuleText(t, rule, policy), met })),
    {
      key: "confirmation",
      label: t("password_policy_confirmation_matches"),
      met: password === confirmation
    }
  ];

  return (
    <div id={id} className="bg-ax-sunken rounded-ax-element flex flex-col gap-2 p-3 text-sm">
      <p className="text-ax-text font-medium">{t("password_policy_intro")}</p>
      <ul className="flex flex-col gap-1.5">
        {items.map(({ key, label, met: rawMet }) => {
          // Nothing typed yet meets nothing.
          const met = password !== "" && rawMet;
          const Icon = met ? Check : Circle;
          return (
            <li
              key={key}
              className={cn(
                "flex items-start gap-2",
                met ? "text-ax-success" : "text-ax-text-secondary"
              )}
            >
              <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <span>
                {label}
                <span className="sr-only">
                  {" – "}
                  {met ? t("password_policy_fulfilled") : t("password_policy_pending")}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
