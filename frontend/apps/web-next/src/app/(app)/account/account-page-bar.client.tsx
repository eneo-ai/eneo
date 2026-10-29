"use client";

import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { PageBar } from "@/components/shell/page-bar";

/** Konto's pages, by the label of their row on Konto. */
const TITLES: Record<string, string> = {
  "/account/appearance": "account_appearance_language",
  "/account/copy-format": "account_copy_format",
  "/account/password": "change_password",
  "/account/api-keys": "my_api_keys",
  "/account/integrations": "integrations"
};

/**
 * Below 1024 px a page under Konto is a pushed screen (decisions 20, 22): its
 * PageBar goes back to Konto and names the page, and the page's heading is
 * here, for assistive technology (from 1024 px "Mitt konto" and its tabs head
 * every account page). Konto keeps the shell's top bar and its menu.
 */
export function AccountPageBar() {
  const t = useTranslations();
  const key = TITLES[usePathname()];
  if (!key) return null;
  const title = t(key);
  return (
    <>
      <PageBar parent={{ label: t("account"), href: "/account" }} title={title} isTitleShown />
      <h1 className="sr-only lg:hidden">{title}</h1>
    </>
  );
}
