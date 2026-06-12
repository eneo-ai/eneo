"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { AppWindow, MessageSquare } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { EmptyState } from "@/components/composites/empty-state";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger
} from "@/components/ui/accordion";
import { browserApi } from "@/lib/api/browser";
import { dashboardQueryOptions, type SpaceDashboard } from "./queries";

function Tile({
  href,
  icon: Icon,
  name
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  name: string;
}) {
  return (
    <Link
      href={href}
      className="hover:bg-muted/50 flex items-center gap-3 rounded-lg border p-3 transition-colors"
    >
      <Icon className="text-muted-foreground size-5 shrink-0" />
      <span className="truncate text-sm font-medium">{name}</span>
    </Link>
  );
}

function SpaceSection({ space }: { space: SpaceDashboard }) {
  const t = useTranslations();

  // The personal space's default assistant is not part of applications.
  const assistants = [
    ...(space.personal && space.default_assistant ? [space.default_assistant] : []),
    ...(space.applications?.assistants.items ?? [])
  ];
  const apps = space.applications?.apps.items ?? [];

  return (
    <AccordionItem value={space.id}>
      <AccordionTrigger>
        <span className="flex items-baseline gap-3">
          <span className="font-medium">{space.personal ? t("personal") : space.name}</span>
          <span className="text-muted-foreground text-xs">
            {assistants.length} {t("assistants").toLowerCase()} · {apps.length}{" "}
            {t("apps").toLowerCase()}
          </span>
        </span>
      </AccordionTrigger>
      <AccordionContent>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {assistants.map((assistant) => (
            <Tile
              key={assistant.id}
              href={`/dashboard/${assistant.id}?tab=chat`}
              icon={MessageSquare}
              name={assistant.name}
            />
          ))}
          {apps.map((app) => (
            <Tile key={app.id} href={`/dashboard/app/${app.id}`} icon={AppWindow} name={app.name} />
          ))}
        </div>
      </AccordionContent>
    </AccordionItem>
  );
}

export function DashboardList() {
  const t = useTranslations();
  const { data } = useSuspenseQuery(dashboardQueryOptions(browserApi));

  // Only spaces that have something to show: published assistants, the
  // personal default assistant, or apps.
  const spaces = data.spaces.items.filter(
    (space) =>
      (space.applications?.assistants.count ?? 0) > 0 ||
      (space.personal && space.default_assistant != null) ||
      (space.applications?.apps.count ?? 0) > 0
  );

  if (spaces.length === 0) {
    return <EmptyState title={t("dashboard")} description={t("no_results")} />;
  }

  return (
    <Accordion type="multiple" defaultValue={spaces.map((space) => space.id)}>
      {spaces.map((space) => (
        <SpaceSection key={space.id} space={space} />
      ))}
    </Accordion>
  );
}
