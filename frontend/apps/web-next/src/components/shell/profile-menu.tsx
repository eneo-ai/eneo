"use client";

import { Building2, Globe, KeyRound, LogOut, User } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useTransition } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { setLocale } from "@/lib/i18n/actions";
import { locales } from "@/lib/i18n/locales";

const LOCALE_LABELS: Record<string, string> = { sv: "Svenska", en: "English" };

export function ProfileMenu() {
  const t = useTranslations();
  const { user } = useAppContext();
  const locale = useLocale();
  const router = useRouter();
  const [, startTransition] = useTransition();

  const initial = user.email.slice(0, 1).toUpperCase();

  function switchLocale(next: string) {
    startTransition(async () => {
      await setLocale(next);
      router.refresh();
    });
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger aria-label={t("account_and_settings")} className="rounded-full">
        <Avatar>
          <AvatarFallback>{initial}</AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="truncate font-normal">
          <span className="block truncate text-sm font-medium">{user.email}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/account">
            <User /> {t("my_account")}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/account/api-keys">
            <KeyRound /> {t("my_api_keys")}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/account/integrations">
            <Building2 /> {t("integrations")}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuSub>
          <DropdownMenuSubTrigger>
            <Globe className="text-muted-foreground mr-2 size-4" /> {t("language")}
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent>
            <DropdownMenuRadioGroup value={locale} onValueChange={switchLocale}>
              {locales.map((value) => (
                <DropdownMenuRadioItem key={value} value={value}>
                  {LOCALE_LABELS[value] ?? value}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" asChild>
          <a href="/logout">
            <LogOut /> {t("logout")}
          </a>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
