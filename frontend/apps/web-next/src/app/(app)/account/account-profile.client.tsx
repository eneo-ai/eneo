"use client";

import { Selector } from "@astryxdesign/core/Selector";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useState, useTransition } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { setLocale } from "@/lib/i18n/actions";
import { locales } from "@/lib/i18n/locales";
import { toast } from "@/lib/toast";
import {
  type AssistantCopyFormat,
  getPreferredAssistantCopyFormat,
  setPreferredAssistantCopyFormat
} from "@/features/chat/copy-assistant-answer";

// Each language in its own name, so every reader finds theirs (not translated).
const LOCALE_LABELS: Record<string, string> = { sv: "Svenska", en: "English" };
const LOCALE_OPTIONS = locales.map((value) => ({ value, label: LOCALE_LABELS[value] ?? value }));
const COPY_FORMAT_OPTIONS: AssistantCopyFormat[] = ["markdown", "richtext"];

function isAssistantCopyFormat(value: string): value is AssistantCopyFormat {
  return value === "markdown" || value === "richtext";
}

export function AccountProfile() {
  const t = useTranslations();
  const { settings, user, tenant, versions } = useAppContext();
  const locale = useLocale();
  const router = useRouter();
  const [, startTransition] = useTransition();
  const serverCopyFormat = getPreferredAssistantCopyFormat(settings);
  const [optimisticCopyFormat, setOptimisticCopyFormat] = useState<AssistantCopyFormat | null>(
    null
  );
  const copyFormat = optimisticCopyFormat ?? serverCopyFormat;
  const [savingCopyFormat, setSavingCopyFormat] = useState(false);

  async function savePreferredCopyFormat(next: string) {
    if (!isAssistantCopyFormat(next) || next === copyFormat || savingCopyFormat) return;

    const previous = optimisticCopyFormat;
    setOptimisticCopyFormat(next);
    setSavingCopyFormat(true);
    try {
      await unwrap(
        browserApi.POST("/api/v1/settings/", {
          body: {
            ...settings,
            chatbot_widget: setPreferredAssistantCopyFormat(settings, next)
          }
        })
      );
      toast.success(t("preferred_copy_format_updated"));
      router.refresh();
    } catch (error) {
      setOptimisticCopyFormat(previous);
      toastApiError(error, t);
    } finally {
      setSavingCopyFormat(false);
    }
  }

  return (
    <SettingsGroup title={t("profile")}>
      <SettingsRow title={t("email")}>
        <p className="text-sm">{user.email}</p>
      </SettingsRow>
      <SettingsRow title={t("organization")}>
        <p className="text-sm">{tenant.display_name ?? tenant.name}</p>
      </SettingsRow>
      <SettingsRow title={t("roles_permissions")}>
        <div className="flex flex-wrap gap-1">
          {user.roles.map((role) => (
            <Badge key={role.id} variant="secondary">
              {role.name}
            </Badge>
          ))}
        </div>
      </SettingsRow>
      {/* The row title is the visible label; the selector's own (hidden) label
          gives the combobox the same name. The current locale (the
          NEXT_LOCALE cookie, read by src/lib/i18n/request.ts) is the value. */}
      <SettingsRow title={t("language")}>
        <Selector
          label={t("language")}
          isLabelHidden
          options={LOCALE_OPTIONS}
          value={locale}
          width={192}
          onChange={(next) =>
            startTransition(async () => {
              try {
                await setLocale(next);
                router.refresh();
              } catch (error) {
                toastApiError(error, t);
              }
            })
          }
        />
      </SettingsRow>
      <SettingsRow
        tour="account-copy-format"
        title={t("preferred_copy_format")}
        description={t("preferred_copy_format_description")}
      >
        <RadioGroup
          value={copyFormat}
          disabled={savingCopyFormat}
          className="grid gap-2 sm:grid-cols-2"
          onValueChange={(next) => {
            void savePreferredCopyFormat(next);
          }}
        >
          {COPY_FORMAT_OPTIONS.map((format) => {
            const id = `account-copy-format-${format}`;
            return (
              <Label
                key={format}
                htmlFor={id}
                className="hover:bg-muted/70 flex cursor-pointer items-center gap-3 rounded-md border p-3 text-sm"
              >
                <RadioGroupItem id={id} value={format} disabled={savingCopyFormat} />
                <span className="font-medium">
                  {format === "markdown" ? t("copy_format_markdown") : t("copy_format_richtext")}
                </span>
              </Label>
            );
          })}
        </RadioGroup>
      </SettingsRow>
      <SettingsRow title={t("version")}>
        <p className="text-muted-foreground text-sm">
          {t("version_frontend")} {versions.frontend}
          {versions.backend ? ` · ${t("version_backend")} ${versions.backend}` : null}
        </p>
      </SettingsRow>
    </SettingsGroup>
  );
}
