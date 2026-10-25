"use client";

import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { Building2, LogOut } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { IndexGroup, IndexRow } from "@/components/composites/index-rows";
import { PageHeader } from "@/components/composites/page-header";
import { useAppContext } from "@/components/providers/app-context";
import { profileDisplayName, profileInitials } from "@/components/shell/profile-menu";
import { THEMES } from "@/components/shell/theme-switcher";
import { useWhatsNew } from "@/features/whats-new/whats-new-provider";
import { useHydrated } from "@/lib/hooks/use-hydrated";
import { MOBILE_QUERY, useMediaMatch } from "@/lib/hooks/use-media-match";
import { LOCALE_LABELS } from "@/lib/i18n/locales";
import { navigateTo } from "@/lib/navigate-to";
import { AccountProfile } from "./account-profile.client";
import { ChangePasswordCard } from "./change-password.client";
import { useCopyFormatLabel } from "./copy-format.client";

/**
 * /account: below 1024 px, where the drawer is, Konto as one page (decision
 * 22); from there the profile and the password form under "Mitt konto" and
 * its tabs. CSS shows one. Konto holds no state and comes and goes with the
 * width; the profile and the password form stay mounted, so what was typed
 * outlives a turn of an iPad across 1024 px.
 */
export function AccountHome() {
  const mobile = useMediaMatch(MOBILE_QUERY);
  return (
    <>
      {mobile !== false ? <Konto /> : null}
      <div className="flex flex-col gap-6 max-lg:hidden">
        <AccountProfile />
        <ChangePasswordCard />
      </div>
    </>
  );
}

/**
 * Who is signed in, the settings in groups (each row a page of its own, with
 * what it holds now), then the organisation switch and Logga ut, last. The
 * drawer's profile row opens it, so no menu opens on the drawer.
 */
function Konto() {
  const t = useTranslations();
  const { user, tenant, federationStatus, links, versions, can } = useAppContext();
  const { enabled: whatsNewEnabled, hasUnseen } = useWhatsNew();
  const locale = useLocale();
  const { theme } = useTheme();
  const hydrated = useHydrated();
  const copyFormat = useCopyFormatLabel();

  const name = profileDisplayName(user);
  const organisation = tenant.display_name?.trim() || tenant.name;
  const roles = user.roles.map((role) => role.name).join(", ");
  const language = LOCALE_LABELS[locale] ?? locale;
  // next-themes knows the theme only in the browser.
  const themeKey = hydrated ? THEMES.find((option) => option.value === theme)?.labelKey : undefined;

  return (
    <div className="flex flex-col gap-6 lg:hidden">
      <div className="flex flex-col gap-4">
        <PageHeader title={t("account")} />
        <div className="flex items-start gap-3">
          <EntityAvatar
            id={user.id}
            name={name}
            icon={profileInitials(name)}
            size="lg"
            className="rounded-full"
          />
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="text-[1.0625rem] leading-tight font-semibold break-words">{name}</span>
            {/* The address wraps rather than being cut. */}
            <span className="text-ax-text-secondary [overflow-wrap:anywhere]">{user.email}</span>
            {/* Plain text: the roles are who the user is, not a status. */}
            <span className="text-ax-text-secondary text-sm">
              {roles ? t("account_identity_line", { organisation, roles }) : organisation}
            </span>
          </div>
        </div>
      </div>

      {/* Edge to edge, out of the page's gutter; the rows' text keeps to it. */}
      <div className="-mx-4 flex flex-col gap-6 sm:-mx-6 sm:[--index-inset:1.5rem]">
        <IndexGroup title={t("settings")}>
          <IndexRow
            href="/account/appearance"
            label={t("account_appearance_language")}
            summary={
              themeKey
                ? t("account_appearance_summary", { theme: t(themeKey), language })
                : language
            }
          />
          <IndexRow
            href="/account/copy-format"
            // What's new's "Visa mig" points here below 1024 px (packages/whats-new).
            data-tour="account-copy-format"
            label={t("account_copy_format")}
            summary={copyFormat}
          />
        </IndexGroup>
        <IndexGroup title={t("account_security_group")}>
          <IndexRow
            href="/account/password"
            data-tour="account-password"
            label={t("change_password")}
          />
          <IndexRow href="/account/api-keys" label={t("my_api_keys")} />
          <IndexRow href="/account/integrations" label={t("integrations")} />
        </IndexGroup>
        <IndexGroup title={t("eneo")}>
          {whatsNewEnabled ? (
            <IndexRow
              href="/whats-new"
              label={t("whats_new")}
              summary={
                hasUnseen ? (
                  // The words say it; the dot only draws the eye. Inline, so the
                  // words end in an ellipsis where the row is narrow.
                  <>
                    <StatusDot
                      variant="accent"
                      label={t("whats_new_unseen")}
                      aria-hidden="true"
                      className="me-1.5"
                    />
                    {t("whats_new_unseen")}
                  </>
                ) : undefined
              }
            />
          ) : null}
          {can("admin") ? <IndexRow href="/admin" label={t("shell_administration")} /> : null}
          {links.accessibilityStatement ? (
            <IndexRow
              href={links.accessibilityStatement}
              label={t("a11y_statement_link")}
              isExternal
            />
          ) : null}
          {links.legacyApp ? (
            <IndexRow href={links.legacyApp} label={t("beta_return_to_legacy")} />
          ) : null}
        </IndexGroup>
      </div>

      {/* Full page loads: each ends the session, which a client navigation or
          a prefetching link would run. */}
      <div className="flex flex-col gap-3">
        {federationStatus.has_multi_tenant_federation ? (
          <Button
            variant="secondary"
            size="lg"
            width="100%"
            label={t("oidc_choose_another_org")}
            icon={<Icon icon={Building2} />}
            onClick={() => navigateTo("/login/switch-organisation")}
          />
        ) : null}
        <Button
          variant="secondary"
          size="lg"
          width="100%"
          label={t("logout")}
          icon={<Icon icon={LogOut} />}
          onClick={() => navigateTo("/logout")}
        />
        <p className="text-ax-text-secondary text-center text-sm">
          {t("shell_versions", { frontend: versions.frontend, backend: versions.backend || "–" })}
        </p>
      </div>
    </div>
  );
}
