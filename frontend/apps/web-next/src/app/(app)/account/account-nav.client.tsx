"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

export function AccountNav() {
  const t = useTranslations();
  const pathname = usePathname();

  const items = [
    { href: "/account", label: t("profile") },
    { href: "/account/api-keys", label: t("api_keys") },
    { href: "/account/integrations", label: t("integrations") }
  ];

  return (
    <nav className="flex gap-1 border-b pb-2">
      {items.map((item) => {
        const active = pathname === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "text-muted-foreground hover:bg-muted hover:text-foreground flex h-9 items-center rounded-lg px-3 text-sm font-medium transition-colors",
              active && "bg-muted text-foreground"
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
