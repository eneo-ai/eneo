"use client";

import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { MobileNavToggle } from "@astryxdesign/core/MobileNav";
import { Search, SquarePen } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { EneoIcon, EneoWordMark } from "./eneo-logo";
import { NotificationBells } from "./notification-bells";
import { NEW_CONVERSATION_HREF } from "./routes";
import { useShell } from "./shell-context";

/**
 * Phones and iPads held upright: menu, Eneo, search (the ⌘K palette), the
 * notification bells and "Ny konversation", 56 px high with 44 px targets.
 * It gives way to a page's own header (`OWN_MOBILE_HEADER`: the chat's, a
 * PageBar) in CSS, in the frame's `group/shell`.
 */
export function MobileTopBar() {
  const t = useTranslations();
  const { openPalette } = useShell();
  return (
    <header className="bg-ax-surface border-ax-border flex h-14 shrink-0 items-center gap-1 border-b px-1.5 group-has-[[data-own-mobile-header]]/shell:hidden max-md:group-has-[[data-own-phone-header]]/shell:hidden lg:hidden">
      {/* Astryx's toggle only renders once the phone layout is known (after
          hydration); the slot keeps the logo from shifting when it appears. */}
      <span className="flex size-11 shrink-0 items-center justify-center">
        <MobileNavToggle label={t("shell_open_menu")} className="size-11" />
      </span>
      <Link
        href="/"
        aria-label={t("shell_home_link")}
        className="rounded-ax-inner focus-visible:outline-ring flex h-11 items-center px-1 focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        {/* Below 360px the mark alone, so search, both bells and "Ny
            konversation" still fit at 320px. */}
        <EneoIcon className="h-6 w-auto min-[22.5rem]:hidden" />
        <EneoWordMark className="hidden h-5 w-auto min-[22.5rem]:block" />
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
      <div className="flex items-center">
        <NotificationBells />
      </div>
      <Button
        href={NEW_CONVERSATION_HREF}
        variant="ghost"
        size="lg"
        isIconOnly
        icon={<Icon icon={SquarePen} />}
        label={t("new_conversation")}
        className="size-11"
      />
    </header>
  );
}
