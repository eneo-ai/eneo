"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useSpace } from "@/features/spaces/use-space";
import { PublishDialog } from "@/features/assistants/publish-dialog";
import { appQueryOptions, type App } from "../apps";

/** Publish/unpublish row; apps have no insights toggle (unlike assistants). */
export function PublishingSection({ app }: { app: App }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const queryClient = useQueryClient();
  const [showDialog, setShowDialog] = useState(false);
  const published = app.published;

  const publish = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/apps/{id}/publish/", {
          params: { path: { id: app.id }, query: { published: !published } }
        })
      ),
    onSuccess: (updated) => {
      queryClient.setQueryData(appQueryOptions(browserApi, app.id).queryKey, updated);
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
      setShowDialog(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  if (!(app.permissions ?? []).includes("publish")) return null;

  return (
    <SettingsGroup title={t("publishing")}>
      <SettingsRow title={t("status")} description={t("publishing_description")}>
        <div className="flex items-center gap-3">
          <Badge variant={published ? "default" : "outline"}>
            {published ? t("published") : t("draft")}
          </Badge>
          <Button
            variant={published ? "destructive" : "default"}
            size="sm"
            onClick={() => setShowDialog(true)}
          >
            {published ? t("unpublish") : t("publish")}
          </Button>
        </div>
        <PublishDialog
          open={showDialog}
          onOpenChange={setShowDialog}
          name={app.name}
          published={published}
          pending={publish.isPending}
          onConfirm={() => publish.mutate()}
        />
      </SettingsRow>
    </SettingsGroup>
  );
}
