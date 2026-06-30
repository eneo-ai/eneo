"use client";

import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useTransition } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { toastApiError } from "@/lib/api/toast";
import { setLocale } from "@/lib/i18n/actions";
import { locales } from "@/lib/i18n/locales";

const LOCALE_LABELS: Record<string, string> = { sv: "Svenska", en: "English" };

export function AccountProfile() {
  const t = useTranslations();
  const { user, tenant, versions } = useAppContext();
  const locale = useLocale();
  const router = useRouter();
  const [, startTransition] = useTransition();

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
      <SettingsRow title={t("version")}>
        <p className="text-muted-foreground text-sm">
          web-next {versions.frontend} · backend {versions.backend}
        </p>
      </SettingsRow>
    </SettingsGroup>
  );
}
