"use client";

import {
  AppWindow,
  BookOpen,
  Cog,
  LayoutDashboard,
  MessageSquare,
  Users,
  Wrench
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { useSpace } from "@/features/spaces/use-space";

function NavItem({
  href,
  active,
  icon: Icon,
  label
}: {
  href: string;
  active: boolean;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "text-muted-foreground hover:bg-muted hover:text-foreground flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium transition-colors",
        active && "bg-muted text-foreground"
      )}
    >
      <Icon className="size-4" />
      {label}
    </Link>
  );
}

/** Sidebar navigation, gated by the space's per-resource permissions. */
export function SpaceNav() {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const pathname = usePathname();
  const section = pathname.split("/")[3];
  const base = `/spaces/${routeId}`;
  const isOrgSpace = space.organization;

  return (
    <nav className="flex flex-col gap-1">
      <p className="text-muted-foreground truncate px-3 py-2 text-xs font-semibold tracking-wide uppercase">
        {space.personal ? t("personal") : space.name}
      </p>
      {!isOrgSpace && space.personal && (
        <>
          <NavItem
            href={`${base}/chat?tab=chat`}
            active={section === "chat"}
            icon={MessageSquare}
            label={t("chat")}
          />
          <Separator className="my-2" />
        </>
      )}
      {!isOrgSpace && (
        <NavItem
          href={`${base}/overview`}
          active={section === "overview"}
          icon={LayoutDashboard}
          label={t("overview")}
        />
      )}
      {!isOrgSpace && can("read", "assistant") && (
        <NavItem
          href={`${base}/assistants`}
          active={section === "assistants"}
          icon={MessageSquare}
          label={t("assistants")}
        />
      )}
      {!isOrgSpace && can("read", "app") && (
        <NavItem
          href={`${base}/apps`}
          active={section === "apps"}
          icon={AppWindow}
          label={t("apps")}
        />
      )}
      {(can("read", "website") || can("read", "collection")) && (
        <NavItem
          href={`${base}/knowledge`}
          active={section === "knowledge"}
          icon={BookOpen}
          label={t("knowledge")}
        />
      )}
      {can("read", "service") && (
        <>
          <Separator className="my-2" />
          <NavItem
            href={`${base}/services`}
            active={section === "services"}
            icon={Wrench}
            label={t("services")}
          />
        </>
      )}
      {!isOrgSpace && can("read", "member") && (
        <>
          <Separator className="my-2" />
          <NavItem
            href={`${base}/members`}
            active={section === "members"}
            icon={Users}
            label={t("members")}
          />
        </>
      )}
      {can("edit", "space") && (
        <NavItem
          href={`${base}/settings`}
          active={section === "settings"}
          icon={Cog}
          label={t("settings")}
        />
      )}
    </nav>
  );
}
