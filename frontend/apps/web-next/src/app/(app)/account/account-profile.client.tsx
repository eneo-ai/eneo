"use client";

import { Selector } from "@astryxdesign/core/Selector";
import { useTranslations } from "next-intl";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
import { Badge } from "@/components/ui/badge";
import { LOCALE_LABELS, locales } from "@/lib/i18n/locales";
import { useLocaleSwitch } from "@/lib/i18n/use-locale-switch";
import { CopyFormatChoice } from "./copy-format.client";

const LOCALE_OPTIONS = locales.map((value) => ({ value, label: LOCALE_LABELS[value] ?? value }));

export function AccountProfile() {
  const t = useTranslations();
  const { user, tenant, versions } = useAppContext();
  const { locale, switchLocale } = useLocaleSwitch();

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
          onChange={switchLocale}
        />
      </SettingsRow>
      <SettingsRow
        tour="account-copy-format"
        title={t("preferred_copy_format")}
        description={t("preferred_copy_format_description")}
      >
        <CopyFormatChoice />
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
