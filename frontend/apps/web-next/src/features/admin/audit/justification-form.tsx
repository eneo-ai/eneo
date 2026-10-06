"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Shield } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";

const REASONS = [
  "compliance_review",
  "security_investigation",
  "user_support",
  "gdpr_request",
  "audit_review",
  "troubleshooting",
  "management_review",
  "legal_request",
  "other"
] as const;

const MIN_DESCRIPTION = 10;
const MAX_DESCRIPTION = 500;

/**
 * Access gate for audit logs: the user states a justification, the backend
 * opens a 1-hour HTTP-only access session (cookie, re-scoped by the proxy),
 * then we refetch the logs. Problems show at their fields on submit, and
 * focus moves to the first.
 */
export function JustificationForm() {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [category, setCategory] = useState("");
  const [description, setDescription] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const categoryRef = useRef<HTMLButtonElement>(null);
  const descriptionRef = useRef<HTMLTextAreaElement>(null);

  const create = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/audit/access-session", {
          body: { category, description: description.trim() }
        })
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["audit-logs"] }),
    onError: (error) => toastApiError(error, t)
  });

  const missing = MIN_DESCRIPTION - description.trim().length;
  const categoryProblem = category === "" ? t("required_field") : null;
  const descriptionProblem =
    missing > 0 ? t("audit_access_chars_needed", { count: missing }) : null;
  const shown = (problem: string | null) => (submitted ? problem : null);

  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <div className="border-border bg-card w-full max-w-xl rounded-2xl border p-8 shadow-sm">
        <div className="mb-6 flex items-start gap-4">
          <span className="bg-muted flex size-11 items-center justify-center rounded-lg">
            <Shield className="size-6" />
          </span>
          <div>
            <h2 className="text-lg font-semibold">{t("audit_access_required_title")}</h2>
            <p className="text-muted-foreground text-sm">
              {t("audit_access_required_description")}
            </p>
          </div>
        </div>

        <form
          className="flex flex-col gap-5"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (create.isPending) return;
            const firstProblem = categoryProblem
              ? categoryRef
              : descriptionProblem
                ? descriptionRef
                : null;
            if (firstProblem) {
              // Rendered before focus moves, so the field is read with its error.
              flushSync(() => setSubmitted(true));
              firstProblem.current?.focus();
              return;
            }
            create.mutate();
          }}
        >
          <div className="flex flex-col gap-2">
            <Label>{t("audit_access_reason_label")}</Label>
            <Select value={category} onValueChange={setCategory}>
              <SelectTrigger
                ref={categoryRef}
                className="w-full"
                aria-label={t("audit_access_reason_label")}
                {...fieldProblemProps("audit-reason", shown(categoryProblem))}
              >
                <SelectValue placeholder={t("audit_access_reason_placeholder")} />
              </SelectTrigger>
              <SelectContent>
                {REASONS.map((reason) => (
                  <SelectItem key={reason} value={reason}>
                    {t(`audit_reason_${reason}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FieldProblem id="audit-reason" problem={shown(categoryProblem)} />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="audit-justification">{t("audit_access_description_label")}</Label>
            <Textarea
              ref={descriptionRef}
              id="audit-justification"
              value={description}
              rows={4}
              maxLength={MAX_DESCRIPTION}
              placeholder={t("audit_access_description_placeholder")}
              onChange={(event) => setDescription(event.target.value)}
              {...fieldProblemProps("audit-justification", shown(descriptionProblem))}
            />
            {/* After a submit the count is the field's error; before, a hint. */}
            {shown(descriptionProblem) ? (
              <FieldProblem id="audit-justification" problem={shown(descriptionProblem)} />
            ) : (
              <span className="text-muted-foreground text-xs">
                {descriptionProblem ?? `${description.length}/${MAX_DESCRIPTION}`}
              </span>
            )}
          </div>

          <div className="flex justify-end">
            {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
            <Button type="submit" aria-busy={create.isPending || undefined}>
              {create.isPending ? t("audit_config_saving") : t("audit_access_submit")}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
