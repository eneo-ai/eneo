"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Shield } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
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
 * then we refetch the logs.
 */
export function JustificationForm() {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [category, setCategory] = useState("");
  const [description, setDescription] = useState("");

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

  const valid =
    category !== "" &&
    description.trim().length >= MIN_DESCRIPTION &&
    description.length <= MAX_DESCRIPTION;

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
          onSubmit={(event) => {
            event.preventDefault();
            if (valid) create.mutate();
          }}
        >
          <div className="flex flex-col gap-2">
            <Label>{t("audit_access_reason_label")}</Label>
            <Select value={category} onValueChange={setCategory}>
              <SelectTrigger className="w-full" aria-label={t("audit_access_reason_label")}>
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
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="audit-justification">{t("audit_access_description_label")}</Label>
            <Textarea
              id="audit-justification"
              value={description}
              rows={4}
              maxLength={MAX_DESCRIPTION}
              placeholder={t("audit_access_description_placeholder")}
              onChange={(event) => setDescription(event.target.value)}
            />
            <span className="text-muted-foreground text-xs">
              {description.trim().length < MIN_DESCRIPTION
                ? t("audit_access_chars_needed", {
                    count: MIN_DESCRIPTION - description.trim().length
                  })
                : `${description.length}/${MAX_DESCRIPTION}`}
            </span>
          </div>

          <div className="flex justify-end">
            <Button type="submit" disabled={!valid || create.isPending}>
              {create.isPending ? t("audit_config_saving") : t("audit_access_submit")}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
