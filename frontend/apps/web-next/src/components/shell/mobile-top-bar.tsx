"use client";

import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { MobileNavToggle } from "@astryxdesign/core/MobileNav";
import { SquarePen } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { EneoWordMark } from "./eneo-logo";
import { NotificationBells } from "./notification-bells";
import { NEW_CONVERSATION_HREF } from "./routes";

/**
 * Phone layouts outside the chat: menu, Eneo, the notification bells and
 * "Ny konversation", 56 px high with 44 px targets.
 */
export function MobileTopBar() {
  const t = useTranslations();
  return (
    <header className="bg-ax-surface border-ax-border flex h-14 shrink-0 items-center gap-1 border-b px-1.5 md:hidden">
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
        <EneoWordMark decorative className="h-5 w-auto" />
      </Link>
      <div className="flex-1" />
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
