"use client";

import { AlertCircle, Info, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";
import { PolicySection } from "./policy-section";
import type { PolicyDraft } from "./use-policy-draft";

export function PromptEnforcementSection({ draft }: { draft: PolicyDraft }) {
  const t = useTranslations();
  const {
    promptEnabled,
    setPromptEnabled,
    selectedPromptId,
    setSelectedPromptId,
    promptOptions,
    promptSummary,
    badgeVariant
  } = draft;

  return (
    <PolicySection
      id="prompt"
      title={t("governance_prompt_heading")}
      description={t("governance_prompt_section_desc")}
      summary={promptSummary}
      summaryVariant={badgeVariant(promptEnabled, selectedPromptId !== null)}
      icon={<Sparkles className="size-5" />}
    >
      <div className="flex items-center justify-between gap-3">
        <Label htmlFor="prompt-enabled" className="text-sm font-medium">
          {t("governance_prompt_toggle_label")}
        </Label>
        <Switch
          id="prompt-enabled"
          checked={promptEnabled}
          onCheckedChange={setPromptEnabled}
          aria-describedby="prompt-help"
        />
      </div>

      {!promptEnabled ? (
        <p id="prompt-help" className="text-muted-foreground text-sm">
          {t("governance_prompt_help_disabled")}
        </p>
      ) : promptOptions.length === 0 ? (
        <Alert>
          <Info className="size-4" />
          <AlertDescription className="text-muted-foreground">
            {t("governance_prompt_library_empty")}
            <Link className="text-primary mt-1 inline-block underline" href="/admin/prompt-library">
              {t("governance_prompt_create_in_library")}
            </Link>
          </AlertDescription>
        </Alert>
      ) : (
        <>
          <p id="prompt-help" className="text-muted-foreground text-sm">
            {t("governance_prompt_help_enabled")}
          </p>
          <RadioGroup
            value={selectedPromptId ?? ""}
            onValueChange={(value) => setSelectedPromptId(value)}
          >
            <div className="space-y-2">
              {promptOptions.map((prompt) => (
                <Label
                  key={prompt.id}
                  htmlFor={`prompt-${prompt.id}`}
                  className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                    selectedPromptId === prompt.id ? "border-primary" : "hover:border-foreground/30"
                  }`}
                >
                  <RadioGroupItem value={prompt.id} id={`prompt-${prompt.id}`} className="mt-0.5" />
                  <div className="flex-1">
                    <div className="text-sm font-medium">{prompt.name}</div>
                    {prompt.description && (
                      <div className="text-muted-foreground mt-0.5 text-xs">
                        {prompt.description}
                      </div>
                    )}
                  </div>
                </Label>
              ))}
            </div>
          </RadioGroup>
          {!selectedPromptId && (
            <p className="text-destructive flex items-center gap-2 text-sm" role="alert">
              <AlertCircle className="size-4 shrink-0" aria-hidden="true" />
              {t("governance_prompt_error_required")}
            </p>
          )}
        </>
      )}
    </PolicySection>
  );
}
