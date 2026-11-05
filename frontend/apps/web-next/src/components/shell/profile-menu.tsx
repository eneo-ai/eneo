import {
  DropdownMenu,
  DropdownMenuDivider,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSubMenu
} from "@astryxdesign/core/DropdownMenu";
import { useAppShellMobile } from "@astryxdesign/core/AppShell";
import { useSideNavCollapse } from "@astryxdesign/core/SideNav";
import {
  Accessibility,
  ArrowLeft,
  Building2,
  ChevronRight,
  ChevronsUpDown,
  CircleHelp,
  ExternalLink,
  Globe,
  KeyRound,
  LogOut,
  Plug,
  Sparkles,
  User
} from "lucide-react";
import Link from "@/lib/link";
import { useTranslations } from "use-intl";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { useAppContext } from "@/components/providers/app-context";
import { LOCALE_LABELS, locales } from "@/lib/i18n/locales";
import { useLocaleSwitch } from "@/lib/i18n/use-locale-switch";
import { navigateTo } from "@/lib/navigate-to";
import { useWhatsNew } from "@/features/whats-new/whats-new-provider";
import { ThemeSubMenu } from "./theme-switcher";

/** The name the shell shows for the signed-in user (the API has no display name). */
export function profileDisplayName(user: { username?: string | null; email: string }): string {
  return user.username?.trim() || user.email.split("@")[0] || user.email;
}

/** Up to two initials, splitting on the separators usernames and emails use. */
export function profileInitials(name: string): string {
  const initials = name
    .split(/[\s._@-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => Array.from(part)[0] ?? "")
    .join("")
    .toUpperCase(); // locale-independent: identical on server and client
  return initials || "?";
}

/** Who is signed in, as the profile button and link show and name it. */
function useProfile() {
  const t = useTranslations();
  const { user, tenant } = useAppContext();
  const name = profileDisplayName(user);
  const organisation = tenant.display_name?.trim() || tenant.name;
  return {
    name,
    organisation,
    // Starts with the visible name and organisation (WCAG 2.5.3); the space between their
    // spans keeps them apart for axe, which joins text with no separator.
    label: t("shell_profile_button_label", { name, organisation }),
    avatar: (
      <EntityAvatar
        id={user.id}
        name={name}
        icon={profileInitials(name)}
        size="md"
        className="rounded-full"
      />
    )
  };
}

/**
 * The profile in the drawer (decision 22): a link to Konto, which holds what
 * the menu holds, so no menu opens on the drawer. It closes the drawer as the
 * nav items do, Konto already open too.
 */
export function ProfileLink() {
  const { name, organisation, label, avatar } = useProfile();
  const { closeMobileNav } = useAppShellMobile();
  return (
    <Link
      href="/account"
      aria-label={label}
      onClick={closeMobileNav}
      className="hover:bg-ax-hover active:bg-ax-pressed focus-visible:outline-ring rounded-ax-element flex h-14 w-full items-center gap-2.5 px-2 focus-visible:outline-2 focus-visible:outline-offset-2"
    >
      {avatar}
      <span className="flex min-w-0 flex-1 flex-col leading-tight">
        <span className="truncate font-semibold">{name}</span>{" "}
        <span className="text-ax-text-secondary truncate text-xs">{organisation}</span>
      </span>
      <ChevronRight aria-hidden="true" className="text-ax-text-secondary size-4 shrink-0" />
    </Link>
  );
}

/**
 * The profile button at the foot of the SideNav and its menu: account pages,
 * what's new, language, colour mode, the accessibility statement (when the
 * deployment configures one, WCAG 3.2.6 keeps it here on every page),
 * organisation switch, versions and logout.
 */
export function ProfileMenu({
  inTopBar = false,
  withHelpCenter = false
}: {
  inTopBar?: boolean;
  /** A page without a SideNav: the help centre has no foot (nav-footer.tsx) to sit at. */
  withHelpCenter?: boolean;
}) {
  const t = useTranslations();
  const { user, federationStatus, links, versions } = useAppContext();
  const { enabled: whatsNewEnabled, hasUnseen } = useWhatsNew();
  const { locale, switchLocale } = useLocaleSwitch();
  // In the top bar only the avatar shows, as in the Svelte app, and the menu opens below it.
  const isCollapsed = useSideNavCollapse().isCollapsed || inTopBar;

  const { name, organisation, label: buttonLabel, avatar } = useProfile();

  return (
    <DropdownMenu
      button={{
        label: buttonLabel,
        // The icon rail shows only the avatar: the tooltip names it on hover.
        tooltip: isCollapsed ? buttonLabel : undefined,
        variant: "ghost",
        size: "lg",
        className: isCollapsed
          ? "size-10 p-0 pointer-coarse:size-11"
          : "h-12 w-full justify-between gap-2 px-2 text-left",
        endContent: isCollapsed ? undefined : (
          <ChevronsUpDown aria-hidden="true" className="text-ax-text-secondary size-4" />
        ),
        children: isCollapsed ? (
          avatar
        ) : (
          <span className="flex min-w-0 items-center gap-2.5">
            {avatar}
            <span className="flex min-w-0 flex-col leading-tight">
              <span className="truncate font-semibold">{name}</span>{" "}
              <span className="text-ax-text-secondary truncate text-xs font-normal">
                {organisation}
              </span>
            </span>
          </span>
        )
      }}
      hasChevron={false}
      placement={inTopBar ? "below" : isCollapsed ? "end" : "above"}
      alignment={isCollapsed ? "end" : "start"}
      menuWidth={272}
      // Every row fits, Logga ut and the versions too; Astryx's default 300 px
      // cap scrolls them out of a menu with room to spare. The viewport still bounds it.
      menuMaxHeight={560}
    >
      <div className="flex flex-col px-2 py-1.5 text-sm">
        <span className="truncate font-semibold">{name}</span>
        <span className="text-ax-text-secondary truncate">{user.email}</span>
      </div>
      <DropdownMenuDivider />
      {/* Pages are links: a modified or middle click opens them in a new tab. */}
      <DropdownMenuItem icon={User} label={t("my_account")} href="/account" />
      <DropdownMenuItem icon={KeyRound} label={t("my_api_keys")} href="/account/api-keys" />
      {whatsNewEnabled && (
        <DropdownMenuItem
          icon={Sparkles}
          label={t("whats_new")}
          endContent={
            hasUnseen ? (
              <>
                <span aria-hidden="true" className="bg-ax-success size-2 rounded-full" />
                <span className="sr-only">{t("whats_new_unseen")}</span>
              </>
            ) : undefined
          }
          href="/whats-new"
        />
      )}
      <DropdownMenuItem icon={Plug} label={t("integrations")} href="/account/integrations" />
      <DropdownMenuDivider />
      <DropdownMenuSubMenu icon={Globe} label={t("language")}>
        <DropdownMenuRadioGroup label={t("language")} value={locale} onChange={switchLocale}>
          {locales.map((value) => (
            <DropdownMenuRadioItem
              key={value}
              value={value}
              // Each in its own language, marked with `lang` (WCAG 3.1.2).
              label={<span lang={value}>{LOCALE_LABELS[value] ?? value}</span>}
            />
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuSubMenu>
      <ThemeSubMenu />
      {links.legacyApp && (
        <DropdownMenuItem
          icon={ArrowLeft}
          label={t("beta_return_to_legacy")}
          href={links.legacyApp}
        />
      )}
      {links.accessibilityStatement && (
        <DropdownMenuItem
          icon={Accessibility}
          label={t("a11y_statement_link")}
          href={links.accessibilityStatement}
        />
      )}
      {withHelpCenter && links.helpCenter && (
        <DropdownMenuItem
          icon={CircleHelp}
          label={t("have_a_question")}
          aria-label={`${t("have_a_question")} ${t("chat_opens_in_new_tab")}`}
          href={links.helpCenter}
          target="_blank"
          rel="noopener noreferrer"
          endContent={<ExternalLink aria-hidden="true" className="size-3.5" />}
        />
      )}
      <DropdownMenuDivider />
      {/* Full page loads (navigateTo), not links: a link would preload them on hover. */}
      {federationStatus.has_multi_tenant_federation && (
        <DropdownMenuItem
          icon={Building2}
          label={t("oidc_choose_another_org")}
          onClick={() => navigateTo("/login/switch-organisation")}
        />
      )}
      <DropdownMenuItem
        icon={LogOut}
        label={t("logout")}
        variant="destructive"
        onClick={() => navigateTo("/logout")}
      />
      <div className="text-ax-text-secondary px-2 pt-1.5 pb-1 text-xs">
        {t("shell_versions", { frontend: versions.frontend, backend: versions.backend || "–" })}
      </div>
    </DropdownMenu>
  );
}
