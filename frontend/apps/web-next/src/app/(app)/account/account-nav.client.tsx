"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

/** Account sub-pages as pills; a second `nav` on the page, so it is named. */
export function AccountNav() {
  const t = useTranslations();
  const pathname = usePathname();

  const items = [
    { href: "/account", label: t("profile") },
    { href: "/account/api-keys", label: t("api_keys") },
    { href: "/account/integrations", label: t("integrations") }
  ];

  return (
    <nav aria-label={t("shell_account_nav_label")}>
      <ul className="flex flex-wrap gap-1">
        {items.map((item) => {
          const active = pathname === item.href;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "text-ax-text-secondary hover:bg-ax-hover hover:text-ax-text focus-visible:outline-ring rounded-ax-element flex h-9 items-center px-3 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:h-11",
                  active && "bg-ax-selected text-ax-text hover:bg-ax-selected font-semibold"
                )}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
