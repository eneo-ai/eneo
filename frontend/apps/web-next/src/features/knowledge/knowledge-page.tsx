"use client";

import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { PageHeader } from "@/components/composites/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useSpace } from "@/features/spaces/use-space";
import { CollectionsTab } from "./collections";
import { IntegrationsTab } from "./integrations";
import { WebsitesTab } from "./websites";

/**
 * The space knowledge hub: collections / websites / integrations tabs, each
 * gated by the corresponding read permission. The active tab lives in ?tab=
 * so links can target one directly.
 */
export function KnowledgePage() {
  const t = useTranslations();
  const { can } = useSpace();
  const searchParams = useSearchParams();

  const tabs = [
    can("read", "collection") ? "collections" : null,
    can("read", "website") ? "websites" : null,
    can("read", "integrationKnowledge") ? "integrations" : null
  ].filter(Boolean) as string[];

  const requested = searchParams.get("tab");
  const [tab, setTab] = useState(
    requested && tabs.includes(requested) ? requested : (tabs[0] ?? "collections")
  );

  function selectTab(next: string) {
    setTab(next);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    window.history.replaceState(null, "", url);
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("knowledge")} />
      <Tabs value={tab} onValueChange={selectTab}>
        <TabsList>
          {can("read", "collection") && (
            <TabsTrigger value="collections">{t("collections")}</TabsTrigger>
          )}
          {can("read", "website") && <TabsTrigger value="websites">{t("websites")}</TabsTrigger>}
          {can("read", "integrationKnowledge") && (
            <TabsTrigger value="integrations">{t("integrations")}</TabsTrigger>
          )}
        </TabsList>
        {can("read", "collection") && (
          <TabsContent value="collections" className="pt-4">
            <CollectionsTab canCreate={can("create", "collection")} />
          </TabsContent>
        )}
        {can("read", "website") && (
          <TabsContent value="websites" className="pt-4">
            <WebsitesTab canCreate={can("create", "website")} />
          </TabsContent>
        )}
        {can("read", "integrationKnowledge") && (
          <TabsContent value="integrations" className="pt-4">
            <IntegrationsTab />
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}
