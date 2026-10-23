"use client";

import { Tab, TabList } from "@astryxdesign/core/TabList";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

/**
 * Account sub-pages as Astryx tabs in their navigation pattern: a named `nav`
 * landmark of links with the current page marked `aria-current`.
 */
export function AccountNav() {
  const t = useTranslations();
  const pathname = usePathname();

  const items = [
    { href: "/account", label: t("profile") },
    { href: "/account/api-keys", label: t("api_keys") },
    { href: "/account/integrations", label: t("integrations") }
  ];
  const current = items.find((item) => item.href === pathname)?.href ?? "";

  return (
    <TabList
      value={current}
      // The tabs are links; navigating to them is what selects them.
      onChange={() => {}}
      hasDivider
      aria-label={t("shell_account_nav_label")}
    >
      {items.map((item) => (
        <Tab key={item.href} value={item.href} label={item.label} href={item.href} />
      ))}
    </TabList>
  );
}
