"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAppContext } from "@/components/providers/app-context";
import { cn } from "@/lib/utils";

function NavLink({
  href,
  active,
  children
}: {
  href: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "text-muted-foreground hover:bg-accent hover:text-accent-foreground flex h-8 items-center rounded-md px-3 text-sm font-medium transition-colors",
        active && "bg-secondary text-foreground hover:bg-secondary hover:text-foreground"
      )}
    >
      {children}
    </Link>
  );
}

export function MainNav() {
  const t = useTranslations();
  const { can } = useAppContext();
  const pathname = usePathname();

  const isPersonal = pathname.startsWith("/spaces/personal");
  const isOrganization = pathname.startsWith("/spaces/organization");
  const isSpacesGeneric = pathname.startsWith("/spaces") && !isPersonal && !isOrganization;
  const isAdmin = pathname.startsWith("/admin");

  return (
    <nav className="flex flex-1 items-center gap-1 overflow-x-auto">
      <NavLink href="/spaces/personal/chat" active={isPersonal}>
        {t("personal")}
      </NavLink>
      <NavLink href="/spaces/list" active={isSpacesGeneric}>
        {t("spaces")}
      </NavLink>
      {can("admin") && (
        <NavLink href="/spaces/organization/knowledge" active={isOrganization}>
          {t("organization")}
        </NavLink>
      )}
      <div aria-hidden className="flex-1" />
      {can("admin") && (
        <NavLink href="/admin" active={isAdmin}>
          {t("admin")}
        </NavLink>
      )}
    </nav>
  );
}
