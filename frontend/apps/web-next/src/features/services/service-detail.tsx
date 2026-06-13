"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { PageHeader } from "@/components/composites/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { browserApi } from "@/lib/api/browser";
import { useSpace } from "@/features/spaces/use-space";
import { ServiceEditor } from "./editor/service-editor";
import { serviceQueryOptions } from "./editor/use-service";
import { ServicePlayground } from "./playground";

/** Service playground/settings surface, with the active tab tracked in ?tab=. */
export function ServiceDetail({ serviceId }: { serviceId: string }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const searchParams = useSearchParams();
  const { data: service } = useSuspenseQuery(serviceQueryOptions(browserApi, serviceId));

  const requested = searchParams.get("tab");
  const [tab, setTab] = useState(requested === "settings" ? "settings" : "playground");
  const canEdit = (service.permissions ?? []).includes("edit");

  function selectTab(next: string) {
    setTab(next);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    window.history.replaceState(null, "", url);
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div className="flex flex-col gap-1">
        <Link
          href={`/spaces/${routeId}/services`}
          className="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm"
        >
          <ChevronLeft className="size-4" />
          {t("services")}
        </Link>
        <PageHeader title={service.name} />
      </div>

      <Tabs value={tab} onValueChange={selectTab}>
        <TabsList>
          <TabsTrigger value="playground">{t("playground")}</TabsTrigger>
          {canEdit && <TabsTrigger value="settings">{t("settings")}</TabsTrigger>}
        </TabsList>
        <TabsContent value="playground" className="pt-4">
          <ServicePlayground serviceId={serviceId} />
        </TabsContent>
        {canEdit && (
          <TabsContent value="settings" className="pt-4">
            <ServiceEditor service={service} />
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}
