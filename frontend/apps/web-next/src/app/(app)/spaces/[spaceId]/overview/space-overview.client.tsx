"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useSpace } from "@/features/spaces/use-space";

function OverviewTile({ title, count, href }: { title: string; count: number; href: string }) {
  return (
    <Link href={href}>
      <Card className="hover:bg-muted/50 transition-colors">
        <CardHeader>
          <CardTitle className="text-3xl">{count}</CardTitle>
          <CardDescription>{title}</CardDescription>
        </CardHeader>
      </Card>
    </Link>
  );
}

export function SpaceOverview() {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const base = `/spaces/${routeId}`;

  const chatCount =
    (space.applications?.assistants.count ?? 0) + (space.applications?.group_chats.count ?? 0);
  const knowledgeCount =
    space.knowledge.groups.count +
    space.knowledge.websites.count +
    space.knowledge.integration_knowledge_list.count;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-extrabold">{space.personal ? t("personal") : space.name}</h1>
        <p className="text-muted-foreground max-w-prose">
          {space.personal ? t("personal_space_description") : (space.description ?? "")}
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {can("read", "assistant") && (
          <OverviewTile title={t("assistants")} count={chatCount} href={`${base}/assistants`} />
        )}
        {can("read", "app") && (
          <OverviewTile
            title={t("apps")}
            count={space.applications?.apps.count ?? 0}
            href={`${base}/apps`}
          />
        )}
        {(can("read", "collection") || can("read", "website")) && (
          <OverviewTile title={t("knowledge")} count={knowledgeCount} href={`${base}/knowledge`} />
        )}
        {can("read", "member") && (
          <OverviewTile title={t("members")} count={space.members.count} href={`${base}/members`} />
        )}
      </div>
    </div>
  );
}
