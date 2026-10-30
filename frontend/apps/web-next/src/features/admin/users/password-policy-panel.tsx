"use client";

import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Heading";
import { Text } from "@astryxdesign/core/Text";
import { revealProblems } from "@/components/composites/field-problem";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import {
  ADMIN_PASSWORD_POLICY_KEY,
  adminPasswordPolicyQueryOptions,
  type PasswordLifecyclePolicy
} from "./users";

// Mirrors PasswordLifecyclePolicy.max_age_days bounds (backend
// eneo/users/password_lifecycle.py) so the field explains itself before a 422.
const MAX_AGE_DAYS_LIMIT = 3650;

/** Empty means "never"; anything else must be a whole number of days within the bounds. */
function parseMaxAge(value: string): number | null | undefined {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  if (!/^\d+$/.test(trimmed)) return undefined;
  const days = Number(trimmed);
  return days >= 1 && days <= MAX_AGE_DAYS_LIMIT ? days : undefined;
}

function PolicyForm({ policy }: { policy: PasswordLifecyclePolicy }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [maxAgeDays, setMaxAgeDays] = useState(
    policy.max_age_days == null ? "" : String(policy.max_age_days)
  );
  const [submitted, setSubmitted] = useState(false);
  const maxAgeRef = useRef<HTMLInputElement>(null);

  const parsedMaxAge = parseMaxAge(maxAgeDays);
  const maxAgeError = submitted && parsedMaxAge === undefined;
  const hasChanges = parsedMaxAge !== (policy.max_age_days ?? null);

  const save = useMutation({
    mutationFn: (body: { max_age_days: number | null }) =>
      unwrap(browserApi.PATCH("/api/v1/admin/password-policy", { body })),
    onSuccess: (saved) => {
      // The form re-mounts from the saved policy (see the key on PolicyForm).
      queryClient.setQueryData(ADMIN_PASSWORD_POLICY_KEY, saved);
      toast.success(t("admin_password_policy_updated"));
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <form
      className="flex flex-col gap-5"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (save.isPending) return;
        if (parsedMaxAge === undefined) {
          revealProblems(() => setSubmitted(true), maxAgeRef.current);
          return;
        }
        save.mutate({ max_age_days: parsedMaxAge });
      }}
    >
      <TextInput
        ref={maxAgeRef}
        label={t("admin_password_policy_max_age")}
        description={t("admin_password_policy_max_age_desc")}
        value={maxAgeDays}
        onChange={setMaxAgeDays}
        placeholder={t("admin_password_policy_never")}
        autoComplete="off"
        containerClassName="max-w-48"
        status={
          maxAgeError
            ? { type: "error", message: t("admin_password_policy_max_age_invalid") }
            : undefined
        }
      />
      <Button
        type="submit"
        variant="primary"
        label={t("save")}
        className="self-start"
        isDisabled={!hasChanges}
        // Keeps focus while saving; a second press is ignored above.
        isLoading={save.isPending}
        isInterruptible
      />
    </form>
  );
}

/**
 * The organisation's rule for when a local Eneo password must be replaced:
 * after a maximum age. A password an administrator generates is always
 * one-time, which the description says; it is not a setting. Accounts that
 * sign in through an identity provider are never affected. An explicit save,
 * like the SvelteKit panel; a problem shows at the field on submit and focus
 * moves there (WCAG 3.3.1).
 */
export function PasswordPolicyPanel() {
  const t = useTranslations();
  const headingId = useId();
  const policy = useQuery(adminPasswordPolicyQueryOptions(browserApi));

  return (
    <section
      aria-labelledby={headingId}
      data-tour="admin-password-policy"
      className="bg-ax-card border-ax-border rounded-ax-container border"
    >
      <div className="border-ax-border flex flex-col gap-1 border-b px-5 py-4">
        <Heading level={2} id={headingId} className="text-base">
          {t("admin_password_policy_title")}
        </Heading>
        <Text type="supporting">{t("admin_password_policy_description")}</Text>
      </div>
      <div className="px-5 py-4">
        {policy.data ? (
          <PolicyForm key={JSON.stringify(policy.data)} policy={policy.data} />
        ) : policy.isPending ? (
          <LoadingState rows={2} />
        ) : (
          <Text type="supporting">{t("password_policy_unavailable")}</Text>
        )}
      </div>
    </section>
  );
}
