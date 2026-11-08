import { SideNavItem, useSideNavRenderMode } from "@astryxdesign/core/SideNav";
import { CircleHelp, ExternalLink, Shield } from "lucide-react";
import { useTranslations } from "use-intl";
import type { ComponentProps } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { cn } from "@/lib/utils";
import { NAV_ITEM_CLASSES, SECONDARY_LINK_CLASSES } from "./nav-styles";
import { useTouchTablet } from "@/lib/hooks/use-media-match";
import { ProfileLink, ProfileMenu } from "./profile-menu";
import type { NavVariant } from "./routes";

/** A plain anchor to another site, in a new tab (SideNavItem's own link uses the app router). */
function ExternalNavLink({ children, ...props }: ComponentProps<"a">) {
  return (
    <a {...props} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

/**
 * "Har du en fråga?" → the deployment's help centre (HELP_CENTER_URL, shown
 * when SHOW_HELP_CENTER is on). It opens in a new tab, which the accessible
 * name says, in the rail and the drawer too, where the row's own text is gone.
 */
function HelpCenterItem({ href }: { href: string }) {
  const t = useTranslations();
  return (
    <SideNavItem
      as={ExternalNavLink}
      label={t("have_a_question")}
      aria-label={`${t("have_a_question")} ${t("chat_opens_in_new_tab")}`}
      icon={CircleHelp}
      href={href}
      endContent={<ExternalLink aria-hidden="true" className="size-3.5" />}
    />
  );
}

/**
 * The help centre, as at the foot of Svelte's sidebar. In the phone's drawer
 * also "Administration" (admins) and a link to Konto (decision 22); in a
 * tablet's SideNav those and the profile's menu. With a mouse the top bar
 * carries them; Organisation sits with the areas (main-nav.tsx).
 */
export function NavFooter({ variant }: { variant: NavVariant }) {
  const t = useTranslations();
  const { can, links } = useAppContext();
  const isAdmin = can("admin");
  const isInDrawer = useSideNavRenderMode() === "drawer-content";
  // A tablet has no top bar: its SideNav carries them, and the profile's menu.
  const tablet = useTouchTablet();

  return (
    <div className={cn("flex flex-col gap-0.5", NAV_ITEM_CLASSES, SECONDARY_LINK_CLASSES)}>
      {(isInDrawer || tablet) && variant === "main" && isAdmin ? (
        <SideNavItem label={t("shell_administration")} icon={Shield} href="/admin" />
      ) : null}
      {links.helpCenter ? <HelpCenterItem href={links.helpCenter} /> : null}
      {isInDrawer || tablet ? (
        <div className="mt-1.5">{isInDrawer ? <ProfileLink /> : <ProfileMenu />}</div>
      ) : null}
    </div>
  );
}
