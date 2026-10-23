"use client";

import { Brain } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { PolicySection } from "./policy-section";
import type { PolicyDraft } from "./use-policy-draft";

const DEFAULT = "__default";

export function ReasoningPolicySection({ draft }: { draft: PolicyDraft }) {
  const t = useTranslations();
  const optionLabel = (option: string) => {
    const labels: Record<string, string> = {
      none: t("none"),
      minimal: t("parameter_option_minimal"),
      low: t("parameter_option_low"),
      medium: t("parameter_option_medium"),
      high: t("parameter_option_high"),
      xhigh: t("parameter_option_extra_high"),
      max: t("parameter_option_maximum")
    };
    return labels[option] ?? option.replaceAll("_", " ");
  };

  return (
    <PolicySection
      id="reasoning"
      title={t("governance_reasoning_heading")}
      description={t("governance_reasoning_section_desc")}
      summary={draft.reasoningSummary}
      summaryVariant={draft.reasoningValid ? "outline" : "destructive"}
      icon={<Brain className="size-5" />}
    >
      {!draft.reasoningConfigured ? (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-muted-foreground text-sm">
            {t(
              draft.reasoningOptions.length > 0
                ? "governance_reasoning_activate_help"
                : "governance_reasoning_no_models"
            )}
          </p>
          <Button
            type="button"
            variant="outline"
            disabled={draft.reasoningOptions.length === 0}
            onClick={draft.activateReasoning}
          >
            {t("governance_reasoning_activate")}
          </Button>
        </div>
      ) : draft.reasoningOptions.length > 0 ? (
        <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_16rem] sm:items-center">
          <div>
            <Label htmlFor="reasoning-default">{t("governance_reasoning_default_label")}</Label>
            <p className="text-muted-foreground mt-1 text-sm">
              {t("governance_reasoning_default_help")}
            </p>
          </div>
          <Select
            value={draft.defaultReasoningEffort ?? DEFAULT}
            onValueChange={(value) => draft.setReasoningEffort(value === DEFAULT ? null : value)}
          >
            <SelectTrigger id="reasoning-default" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={DEFAULT}>{t("default_behavior")}</SelectItem>
              {draft.reasoningOptions.map((option) => (
                <SelectItem key={option} value={option}>
                  {optionLabel(option)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : (
        <p className="text-muted-foreground text-sm">{t("governance_reasoning_no_models")}</p>
      )}

      <div className="flex items-start justify-between gap-4 border-t pt-4">
        <div>
          <Label htmlFor="reasoning-user-override">
            {t("governance_reasoning_user_override_label")}
          </Label>
          <p id="reasoning-user-override-help" className="text-muted-foreground mt-1 text-sm">
            {t("governance_reasoning_user_override_help")}
          </p>
        </div>
        <Switch
          id="reasoning-user-override"
          checked={draft.allowUserReasoningEffort}
          onCheckedChange={draft.setReasoningOverride}
          aria-describedby="reasoning-user-override-help"
        />
      </div>
    </PolicySection>
  );
}
