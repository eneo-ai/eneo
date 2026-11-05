import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { MobileNavToggle } from "@astryxdesign/core/MobileNav";
import { Search, SquarePen } from "lucide-react";
import Link from "@/lib/link";
import { useTranslations } from "use-intl";
import { EneoIcon, EneoWordMark } from "./eneo-logo";
import { NotificationBells } from "./notification-bells";
import { NEW_CONVERSATION_HREF } from "./routes";
import { useShell } from "./shell-context";

/**
 * Phones, held either way (below 768 px, or turned sideways; otherwise the
 * SideNav carries all of it): menu, Eneo, search (the ⌘K palette), the
 * notification bells and "Ny konversation", 56 px high with 44 px targets.
 * The job bell shows here only while a job runs; the drawer always has it.
 * What the bar holds follows its width in rem, so enlarged text counts: below
 * 21 rem the word mark gives way to the mark, and below 18 rem (text at about
 * 150% on most phones) the bells and "Ny konversation" leave it, for their
 * rem-sized buttons no longer fit and pushed the page sideways. Both stay in
 * the drawer.
 * It gives way to a page's own header (`OWN_MOBILE_HEADER`: the chat's, a
 * PageBar) in CSS, in the frame's `group/shell`.
 */
export function MobileTopBar() {
  const t = useTranslations();
  const { openPalette } = useShell();
  return (
    <header className="bg-ax-surface border-ax-border phone:group-has-[[data-own-phone-header]]/shell:hidden wide:hidden @container/topbar flex h-14 shrink-0 items-center gap-1 border-b px-1.5 group-has-[[data-own-mobile-header]]/shell:hidden">
      {/* Astryx measures the layout after mount; reserve the toggle's space
          so the logo stays in place. */}
      <span className="flex size-11 shrink-0 items-center justify-center">
        <MobileNavToggle label={t("shell_open_menu")} className="size-11" />
      </span>
      <Link
        href="/"
        aria-label={t("shell_home_link")}
        className="rounded-ax-inner focus-visible:outline-ring flex h-11 min-w-11 shrink-0 items-center justify-center px-1 focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        {/* The mark alone keeps search, both bells and "Ny konversation" in
            the bar at 320px; it is 24 px wide, so the link is centred in a
            44 px box to stay a full touch target (the word mark is wider, so
            min-w-11 changes nothing beside it). */}
        <EneoIcon className="h-6 w-auto @min-[21rem]/topbar:hidden" />
        <EneoWordMark className="hidden h-5 w-auto @min-[21rem]/topbar:block" />
      </Link>
      <div className="flex-1" />
      <Button
        variant="ghost"
        size="lg"
        isIconOnly
        icon={<Icon icon={Search} />}
        label={t("search")}
        onClick={() => openPalette()}
        className="size-11"
      />
      <div className="flex items-center @max-[18rem]/topbar:hidden">
        <NotificationBells isJobBellHiddenWhenIdle />
      </div>
      <Button
        href={NEW_CONVERSATION_HREF}
        variant="ghost"
        size="lg"
        isIconOnly
        icon={<Icon icon={SquarePen} />}
        label={t("new_conversation")}
        className="size-11 @max-[18rem]/topbar:hidden"
      />
    </header>
  );
}
