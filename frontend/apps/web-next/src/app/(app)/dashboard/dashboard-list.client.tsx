"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { dashboardQueryOptions, type SpaceDashboard } from "./queries";

function spaceCounts(space: SpaceDashboard) {
  return {
    // The personal space's default assistant is not part of applications.
    assistants: (space.applications?.assistants.count ?? 0) + (space.default_assistant ? 1 : 0),
    apps: space.applications?.apps.count ?? 0
  };
}

export function DashboardList() {
  const t = useTranslations();
  const { data, isPending, error } = useQuery(dashboardQueryOptions(browserApi));

  // Hydrated from the server prefetch; pending/error only occur on
  // client-side refetches (e.g. after staleTime expiry).
  if (isPending) return <Skeleton className="h-24 w-full" />;
  if (error) return <p className="text-destructive text-sm">{t("request_failed")}</p>;

  // Deliberate error path proving toast + trace-id plumbing end to end.
  async function triggerError() {
    try {
      await unwrap(
        browserApi.GET("/api/v1/spaces/{id}/", {
          params: { path: { id: crypto.randomUUID() } }
        })
      );
    } catch (error) {
      toastApiError(error, t);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.spaces.items.map((space) => {
          const counts = spaceCounts(space);
          return (
            <li key={space.id}>
              <Card>
                <CardHeader>
                  <CardTitle>{space.name}</CardTitle>
                  <CardDescription>
                    {counts.assistants} {t("assistants").toLowerCase()} · {counts.apps}{" "}
                    {t("apps").toLowerCase()}
                  </CardDescription>
                </CardHeader>
              </Card>
            </li>
          );
        })}
      </ul>
      <div>
        <Button variant="outline" size="sm" onClick={triggerError}>
          {t("trigger_error_demo")}
        </Button>
      </div>
    </div>
  );
}
