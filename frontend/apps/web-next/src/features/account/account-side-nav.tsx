import { SideNavHeading, SideNavItem } from "@astryxdesign/core/SideNav";
import { KeyRound, Link2, Sparkles, User } from "lucide-react";
import { useTranslations } from "use-intl";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { useAppContext } from "@/components/providers/app-context";
import { profileDisplayName, profileInitials } from "@/components/shell/profile-menu";
import { usePathname } from "@/lib/navigation";
import { useWhatsNew } from "@/features/whats-new/whats-new-provider";

/** Pages that live under Mitt konto (its profile settings). */
const PROFILE_PAGES = [
  "/account",
  "/account/appearance",
  "/account/copy-format",
  "/account/password"
];

/** The account sidebar's heading, as Svelte's AccountLayout: the user's chip and e-mail. */
export function AccountNavHeading() {
  const { user } = useAppContext();
  const name = profileDisplayName(user);
  return (
    <SideNavHeading
      heading={user.email}
      icon={
        <EntityAvatar
          id={user.id}
          name={name}
          icon={profileInitials(name)}
          size="sm"
          className="size-5 rounded-full"
        />
      }
    />
  );
}

/**
 * Svelte's AccountMenu: Mitt konto, Integrationer, API-nycklar and, when the
 * release notes are on, Nyheter (with its unseen dot). `/whats-new` is
 * Svelte's `/news`, which shows this sidebar too.
 */
export function AccountNavSections() {
  const t = useTranslations();
  const pathname = usePathname();
  const { enabled: whatsNewEnabled, hasUnseen } = useWhatsNew();

  return (
    <div className="flex flex-col gap-0.5">
      <SideNavItem
        label={t("my_account")}
        icon={User}
        href="/account"
        isSelected={PROFILE_PAGES.includes(pathname)}
      />
      <SideNavItem
        label={t("integrations")}
        icon={Link2}
        href="/account/integrations"
        isSelected={pathname.startsWith("/account/integrations")}
      />
      <SideNavItem
        label={t("api_keys")}
        icon={KeyRound}
        href="/account/api-keys"
        isSelected={pathname.startsWith("/account/api-keys")}
      />
      {whatsNewEnabled && (
        <SideNavItem
          label={t("whats_new")}
          icon={Sparkles}
          href="/whats-new"
          isSelected={pathname === "/whats-new"}
          endContent={
            hasUnseen ? (
              <>
                <span aria-hidden="true" className="bg-ax-success size-2 rounded-full" />
                <span className="sr-only">{t("whats_new_unseen")}</span>
              </>
            ) : undefined
          }
        />
      )}
    </div>
  );
}
