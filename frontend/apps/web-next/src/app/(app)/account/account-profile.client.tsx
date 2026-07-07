"use client";

import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { setLocale } from "@/lib/i18n/actions";
import { locales } from "@/lib/i18n/locales";
import {
  type AssistantCopyFormat,
  getPreferredAssistantCopyFormat,
  setPreferredAssistantCopyFormat
} from "@/features/chat/copy-assistant-answer";

const LOCALE_LABELS: Record<string, string> = { sv: "Svenska", en: "English" };
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
      <SettingsRow title={t("language")}>
        <Select
          value={locale}
          onValueChange={(next) =>
            startTransition(async () => {
              try {
                await setLocale(next);
                router.refresh();
              } catch (error) {
                toastApiError(error, t);
              }
            })
          }
        >
          <SelectTrigger className="w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {locales.map((value) => (
              <SelectItem key={value} value={value}>
                {LOCALE_LABELS[value] ?? value}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </SettingsRow>
      <SettingsRow
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
          web-next {versions.frontend} · backend {versions.backend}
        </p>
      </SettingsRow>
    </SettingsGroup>
  );
}
